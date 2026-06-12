"""
intelligence/conversation_memory.py — CONVERSATION MEMORY

Mengubah setiap percakapan menjadi baris data terstruktur + ringkasan +
embedding, disimpan permanen di PostgreSQL/pgvector. Ini fondasi semua
subsistem lain (FAQ Engine, Sales Intelligence, Knowledge Graph membaca
dari sini).

Dipanggil dari `agent_api.py` setelah `SupervisorAgent.process()` selesai
(fire-and-forget — kegagalan modul ini TIDAK boleh mengganggu jawaban ke user).

Yang disimpan per percakapan (tabel `conversation_analysis`):
    user_id, timestamp, channel, intent, sentiment, topic,
    conversation_outcome, lead_status, purchase_status, escalation_status
+ ringkasan otomatis (LLM, fallback heuristik)
+ embedding (disimpan di `conversation_embeddings`, tabel pgvector)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import cfg
from .db import get_pool
from .embeddings import generate_embedding
from .llm import call_llm

# ── Kata kunci heuristik (Bahasa Indonesia, sejalan dengan text_insights.py) ──

_PURCHASE_DONE = [
    "sudah saya beli", "sudah order", "sudah checkout", "sudah bayar",
    "barusan beli", "berhasil beli", "transaksi berhasil", "pesanan saya",
]
_PURCHASE_CONSIDERING = [
    "mau beli", "mau order", "mau pesan", "tertarik beli", "boleh saya beli",
    "gimana cara beli", "cara order", "cara checkout", "minat sama",
]
_PURCHASE_CANCELLED = [
    "batal beli", "gak jadi beli", "tidak jadi beli", "batalkan pesanan",
    "cancel order", "batal order",
]
_PURCHASE_REFUNDED = ["refund", "uang kembali", "pengembalian dana", "minta retur"]

_LEAD_HOT = ["mau beli", "mau order", "siap bayar", "gimana cara bayar", "kirim invoice"]
_LEAD_WARM = ["harga", "promo", "diskon", "paket", "biaya", "berapa harga", "pricing"]
_LEAD_LOST = ["gak jadi", "batal", "kemahalan", "kompetitor lebih murah", "pikir-pikir dulu"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _joined_text(context: dict, bot_response: str = "") -> str:
    history = context.get("messages") or []
    lines = [f"{(m.get('role') or '').upper()}: {m.get('content', '')}" for m in history[-12:]]
    user_msg = context.get("user_message", "")
    return "\n".join([*lines, f"USER: {user_msg}", f"ASSISTANT: {bot_response}"]).strip()


def _any_kw(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


# ── Derivasi field terstruktur dari hasil analisis + heuristik kata kunci ──

def derive_purchase_status(joined_text: str) -> str:
    t = joined_text.lower()
    if _any_kw(t, _PURCHASE_REFUNDED):
        return "refunded"
    if _any_kw(t, _PURCHASE_CANCELLED):
        return "cancelled"
    if _any_kw(t, _PURCHASE_DONE):
        return "purchased"
    if _any_kw(t, _PURCHASE_CONSIDERING):
        return "considering"
    return "none"


def derive_lead_status(joined_text: str, purchase_status: str, sentiment_score: float) -> str:
    if purchase_status == "purchased":
        return "converted"
    if purchase_status in ("cancelled", "refunded"):
        return "lost"
    t = joined_text.lower()
    if _any_kw(t, _LEAD_LOST):
        return "lost"
    if _any_kw(t, _LEAD_HOT) or purchase_status == "considering":
        return "hot"
    if _any_kw(t, _LEAD_WARM):
        return "warm"
    if sentiment_score < -0.3:
        return "cold"
    return "none"


def derive_escalation_status(should_escalate: bool, friction_points: list[str]) -> str:
    if should_escalate:
        return "escalated"
    if friction_points:
        return "flagged"
    return "none"


def derive_outcome(resolved: bool, should_escalate: bool, msg_count: int) -> str:
    if should_escalate:
        return "escalated"
    if resolved:
        return "resolved"
    if msg_count <= 1:
        return "abandoned"
    return "unresolved"


def derive_channel(context: dict) -> str:
    meta = context.get("metadata") or {}
    return str(meta.get("channel") or context.get("channel") or "widget")


def derive_end_user_id(context: dict) -> str | None:
    meta = context.get("metadata") or {}
    for key in ("end_user_id", "user_id", "userId"):
        v = meta.get(key)
        if v:
            return str(v)
    return None


# ── Ringkasan otomatis (LLM, fallback heuristik bila LLM tak tersedia) ──

_SUMMARY_SYSTEM_PROMPT = (
    "Kamu adalah asisten yang merangkum percakapan layanan pelanggan dalam "
    "Bahasa Indonesia. Tulis ringkasan 1-3 kalimat: apa yang ditanyakan/diinginkan "
    "pelanggan, bagaimana bot merespons, dan hasil akhirnya (terselesaikan/belum/"
    "berpotensi closing/dieskalasi). Jangan mengulang teks mentah, sintesiskan."
)


def _heuristic_summary(context: dict, bot_response: str, outcome: str) -> str:
    user_msg = (context.get("user_message") or "").strip().replace("\n", " ")
    if len(user_msg) > 160:
        user_msg = user_msg[:160] + "..."
    label = {
        "resolved": "Pertanyaan terjawab.",
        "unresolved": "Belum sepenuhnya terjawab.",
        "abandoned": "Percakapan ditinggalkan pengguna.",
        "escalated": "Dieskalasi ke tim manusia.",
    }.get(outcome, "")
    return f"User menanyakan: {user_msg}. {label}".strip()


async def summarize_conversation(context: dict, bot_response: str, outcome: str) -> str:
    """Ringkasan via LLM; fallback ke heuristik bila API key kosong / request gagal."""
    if not cfg.groq_api_key:
        return _heuristic_summary(context, bot_response, outcome)
    try:
        text = _joined_text(context, bot_response)
        out = await call_llm(
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Transkrip percakapan:\n{text}\n\nRingkasan:"},
            ],
            temperature=0.2,
            max_tokens=180,
        )
        return out.strip() or _heuristic_summary(context, bot_response, outcome)
    except Exception:
        return _heuristic_summary(context, bot_response, outcome)


# ── Persistensi ──

async def persist_conversation(
    context: dict,
    *,
    bot_response: str,
    sentiment: dict,
    intent: str,
    topics: list[str],
    resolved: bool,
    should_escalate: bool,
    friction_points: list[str],
    quality_score: float,
    extra_metrics: dict | None = None,
) -> dict:
    """
    Titik masuk utama — dipanggil setelah Supervisor selesai memproses satu pesan.
    Upsert 1 baris di `conversation_analysis` (per conversation_id, kolom
    di-refresh tiap pesan supaya selalu mencerminkan state percakapan terkini)
    + simpan/replace embedding-nya.

    Return dict ringkas untuk logging/observability — bukan untuk dikirim ke end-user.
    """
    bot_id          = context.get("bot_id")
    org_id          = context.get("org_id")
    conversation_id = context.get("conversation_id")
    if not (bot_id and org_id and conversation_id):
        raise ValueError("context wajib berisi bot_id, org_id, conversation_id")

    joined = _joined_text(context, bot_response)
    msg_count = len(context.get("messages") or [])

    purchase_status   = derive_purchase_status(joined)
    sentiment_score   = float((sentiment or {}).get("score", 0.0) or 0.0)
    lead_status       = derive_lead_status(joined, purchase_status, sentiment_score)
    escalation_status = derive_escalation_status(should_escalate, friction_points)
    outcome           = derive_outcome(resolved, should_escalate, msg_count)
    channel           = derive_channel(context)
    end_user_id       = derive_end_user_id(context)

    summary = await summarize_conversation(context, bot_response, outcome)
    embedding = await generate_embedding(summary or context.get("user_message", ""))

    raw_metrics = {
        "friction_points": friction_points,
        "msg_count": msg_count,
        **(extra_metrics or {}),
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO conversation_analysis (
                    conversation_id, bot_id, org_id, end_user_id, channel,
                    intent, sentiment_label, sentiment_score, topics, outcome,
                    lead_status, purchase_status, escalation_status,
                    summary, quality_score, raw_metrics, analyzed_at
                ) VALUES ($1,$2,$3,$4,$5, $6,$7,$8,$9,$10, $11,$12,$13, $14,$15,$16, NOW())
                ON CONFLICT (conversation_id) DO UPDATE SET
                    end_user_id       = EXCLUDED.end_user_id,
                    channel           = EXCLUDED.channel,
                    intent            = EXCLUDED.intent,
                    sentiment_label   = EXCLUDED.sentiment_label,
                    sentiment_score   = EXCLUDED.sentiment_score,
                    topics            = EXCLUDED.topics,
                    outcome           = EXCLUDED.outcome,
                    lead_status       = EXCLUDED.lead_status,
                    purchase_status   = EXCLUDED.purchase_status,
                    escalation_status = EXCLUDED.escalation_status,
                    summary           = EXCLUDED.summary,
                    quality_score     = EXCLUDED.quality_score,
                    raw_metrics       = EXCLUDED.raw_metrics,
                    analyzed_at       = NOW()
                """,
                conversation_id, bot_id, org_id, end_user_id, channel,
                intent, (sentiment or {}).get("label", "neutral"), sentiment_score,
                topics or [], outcome,
                lead_status, purchase_status, escalation_status,
                summary, float(quality_score or 0.0), json.dumps(raw_metrics),
            )

            await conn.execute(
                """
                INSERT INTO conversation_embeddings (conversation_id, org_id, bot_id, embedding, model, source_text)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (conversation_id) DO UPDATE SET
                    embedding   = EXCLUDED.embedding,
                    model       = EXCLUDED.model,
                    source_text = EXCLUDED.source_text,
                    created_at  = NOW()
                """,
                conversation_id, org_id, bot_id, embedding, cfg.embedding_model, summary,
            )

    return {
        "conversation_id": conversation_id,
        "intent": intent,
        "sentiment": sentiment,
        "topics": topics,
        "outcome": outcome,
        "lead_status": lead_status,
        "purchase_status": purchase_status,
        "escalation_status": escalation_status,
        "summary": summary,
        "persisted_at": _now_iso(),
    }


# ── Customer Intelligence — akumulasi profil lintas percakapan ──

def _lead_score_from_status(lead_status: str) -> float:
    return {"hot": 0.9, "warm": 0.6, "converted": 1.0, "cold": 0.2, "lost": 0.0, "none": 0.4}.get(lead_status, 0.4)


def _churn_risk_from(sentiment_score: float, escalation_status: str) -> float:
    risk = max(0.0, -sentiment_score)             # makin negatif sentimen, makin tinggi risiko
    if escalation_status == "escalated":
        risk = min(1.0, risk + 0.3)
    elif escalation_status == "flagged":
        risk = min(1.0, risk + 0.15)
    return round(min(1.0, risk), 3)


async def upsert_customer_profile(
    context: dict,
    *,
    end_user_id: str | None,
    topics: list[str],
    lead_status: str,
    purchase_status: str,
    escalation_status: str,
    sentiment_score: float,
) -> str | None:
    """
    Akumulasi profil pelanggan (Customer Intelligence System) — dipanggil
    bersamaan dengan persist_conversation. Tanpa end_user_id (pengunjung
    anonim) kita tidak membuat profil permanen (tidak ada kunci yang stabil
    lintas sesi).
    """
    if not end_user_id:
        return None

    bot_id = context.get("bot_id")
    org_id = context.get("org_id")
    meta = context.get("metadata") or {}
    display_name = meta.get("end_user_name") or meta.get("name")
    email = meta.get("end_user_email") or meta.get("email")

    lead_score = _lead_score_from_status(lead_status)
    churn_risk = _churn_risk_from(sentiment_score, escalation_status)
    purchase_inc = 1 if purchase_status == "purchased" else 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO customer_profiles (
                    bot_id, org_id, end_user_id, display_name, email,
                    total_conversations, total_purchases, lead_score, churn_risk,
                    preferred_topics, last_interaction_at
                ) VALUES ($1,$2,$3,$4,$5, 1,$6,$7,$8, $9, NOW())
                ON CONFLICT (bot_id, end_user_id) DO UPDATE SET
                    display_name        = COALESCE(EXCLUDED.display_name, customer_profiles.display_name),
                    email               = COALESCE(EXCLUDED.email, customer_profiles.email),
                    total_conversations = customer_profiles.total_conversations + 1,
                    total_purchases     = customer_profiles.total_purchases + $6,
                    -- exponential moving average supaya skor tidak melompat-lompat per pesan
                    lead_score          = ROUND((customer_profiles.lead_score * 0.7 + $7 * 0.3)::numeric, 3),
                    churn_risk          = ROUND((customer_profiles.churn_risk * 0.7 + $8 * 0.3)::numeric, 3),
                    preferred_topics    = (
                        SELECT ARRAY(SELECT DISTINCT unnest(customer_profiles.preferred_topics || $9) LIMIT 15)
                    ),
                    last_interaction_at = NOW(),
                    updated_at          = NOW()
                RETURNING id
                """,
                bot_id, org_id, end_user_id, display_name, email,
                purchase_inc, lead_score, churn_risk, topics or [],
            )
    return str(row["id"]) if row else None


async def record_customer_fact(profile_id: str, fact_key: str, fact_value, *,
                                confidence: float = 1.0, source: str = "extracted") -> None:
    """Simpan/refresh satu fakta granular (LongTermFact yang dipersist permanen)."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO customer_facts (profile_id, fact_key, fact_value, confidence, source, times_used)
        VALUES ($1,$2,$3,$4,$5,1)
        ON CONFLICT (profile_id, fact_key) DO UPDATE SET
            fact_value = EXCLUDED.fact_value,
            confidence = EXCLUDED.confidence,
            source     = EXCLUDED.source,
            times_used = customer_facts.times_used + 1,
            updated_at = NOW()
        """,
        profile_id, fact_key, json.dumps(fact_value), confidence, source,
    )


# ── Semantic search — percakapan serupa via pgvector ANN ──

async def search_similar_conversations(bot_id: str, query_text: str, limit: int = 5) -> list[dict]:
    """
    Cari percakapan yang ringkasannya paling mirip secara semantik dengan `query_text`.
    Memakai cosine distance pgvector (`<=>`) + index ivfflat — tetap cepat di skala jutaan baris.
    """
    query_vec = await generate_embedding(query_text)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT
            ca.conversation_id, ca.intent, ca.sentiment_label, ca.topics,
            ca.outcome, ca.lead_status, ca.purchase_status, ca.summary,
            1 - (ce.embedding <=> $2::vector) AS similarity
        FROM conversation_embeddings ce
        JOIN conversation_analysis ca ON ca.conversation_id = ce.conversation_id
        WHERE ce.bot_id = $1
        ORDER BY ce.embedding <=> $2::vector
        LIMIT $3
        """,
        bot_id, query_vec, limit,
    )
    return [dict(r) for r in rows]
