"""
intelligence/sales_agent.py — SALES INTELLIGENCE

Mendeteksi otomatis sinyal-sinyal yang berhubungan dengan keputusan beli:
    • Pertanyaan sebelum membeli   (pre_purchase_question)
    • Alasan membeli               (reason_buy)
    • Alasan batal membeli         (reason_cancel)
    • Keberatan harga              (objection_price)
    • Keberatan produk             (objection_product)
    • Keberatan layanan            (objection_service)

Dua jalur kerja (sama seperti FAQ Engine):

1. REAL-TIME (`SalesAgent`) — deteksi sinyal di pesan yang sedang berlangsung,
   dipakai Supervisor untuk mewarnai jawaban (mis. siap-siap menjawab keberatan
   harga) dan untuk analytics langsung.

2. BATCH (`mine_patterns`, dipanggil nightly_jobs) — agregasi `sales_signals`
   mentah menjadi `sales_patterns` (Trigger → Objection → Solution) lengkap
   dengan conversion_rate & confidence_score:

    Sales Patterns
    ├── Trigger           (apa yang memicu sinyal ini)
    ├── Objection         (keberatan yang muncul, bila ada)
    ├── Solution          (respons bot yang terbukti meredakan & lanjut closing)
    ├── Conversion Rate   (porsi kemunculan pola ini yang berakhir purchase)
    └── Confidence Score  (naik seiring jumlah data — Wilson lower bound sederhana)
"""
from __future__ import annotations

import math

from base import AgentResult, BaseAgent

from .config import cfg
from .db import get_pool
from .embeddings import cosine_similarity, generate_embedding

# ── Kamus kata kunci heuristik per jenis sinyal (Bahasa Indonesia) ──

_SIGNAL_KEYWORDS: dict[str, list[str]] = {
    "pre_purchase_question": [
        "berapa harga", "harganya berapa", "ada garansi", "bagaimana cara order",
        "cara belinya", "metode pembayaran", "bisa cod", "stok ada", "ready stock",
        "kapan dikirim", "ongkir berapa", "ada testimoni",
    ],
    "reason_buy": [
        "saya beli karena", "tertarik karena", "alasan saya pilih", "milih ini karena",
        "soalnya butuh", "karena direkomendasikan", "karena promo", "karena lihat review",
    ],
    "reason_cancel": [
        "gak jadi beli karena", "batal beli karena", "saya batalkan karena",
        "gak jadi order soalnya", "akhirnya gak jadi karena",
    ],
    "objection_price": [
        "kemahalan", "mahal banget", "harganya kemahalan", "kompetitor lebih murah",
        "ada yang lebih murah", "kurang worth it", "diskon dong", "boleh nego",
        "diluar budget", "gak sesuai budget",
    ],
    "objection_product": [
        "kualitasnya kurang", "fiturnya kurang", "gak sesuai ekspektasi",
        "barangnya jelek", "kurang lengkap fiturnya", "kurang bagus produknya",
        "spek nya kurang",
    ],
    "objection_service": [
        "pelayanannya lambat", "respon lama", "cs nya kurang ramah", "susah dihubungi",
        "lama banget balesnya", "kurang responsif", "pelayanan kurang memuaskan",
    ],
}

_OBJECTION_TYPES = {"objection_price", "objection_product", "objection_service"}


def detect_sales_signals(text: str) -> list[dict]:
    """Pindai teks untuk semua jenis sinyal penjualan. Return list {signal_type, snippet}."""
    t = (text or "").lower()
    found: list[dict] = []
    for signal_type, keywords in _SIGNAL_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                # ambil cuplikan di sekitar keyword untuk konteks
                idx = t.find(kw)
                start = max(0, idx - 40)
                end = min(len(t), idx + len(kw) + 40)
                snippet = text[start:end].strip()
                found.append({"signal_type": signal_type, "snippet": snippet})
                break  # satu sinyal per tipe per pesan sudah cukup
    return found


# ════════════════════════════════════════════════════════════════
# 1. REAL-TIME — deteksi sinyal selama percakapan berlangsung
# ════════════════════════════════════════════════════════════════

class SalesAgent(BaseAgent):
    """
    Agent ringan: deteksi heuristik (regex/keyword) di jalur realtime — tanpa
    panggilan LLM tambahan supaya latensi tetap rendah. Hasil deteksi disimpan
    permanen lewat `record_sales_signals()` (dipanggil bersamaan dengan
    conversation_memory.persist_conversation, setelah jawaban terkirim).
    """
    name = "sales_agent"
    skills = ["sales_signal_detection", "objection_detection", "purchase_intent_tracking"]
    tools: list[str] = []
    goals = [
        "Mengenali sinyal niat beli, alasan membeli/batal, dan keberatan pelanggan secara real-time.",
        "Memberi rekomendasi angle respons strategis tanpa menambah latensi jawaban chat.",
    ]
    system_prompt = (
        "Kamu adalah Sales Intelligence Agent dalam sistem multi-agent BotNesia. "
        "Tugasmu: kenali sinyal niat beli, alasan membeli/batal, dan keberatan "
        "(harga/produk/layanan) dari pesan pelanggan, agar bot bisa merespons "
        "secara strategis dan tim sales mendapat insight."
    )

    async def run(self, context: dict) -> AgentResult:
        user_message = context.get("user_message") or ""
        bot_response = context.get("bot_response") or ""
        signals = detect_sales_signals(user_message)

        has_objection = any(s["signal_type"] in _OBJECTION_TYPES for s in signals)
        recommended_angle = None
        if has_objection:
            recommended_angle = (
                "Pelanggan menunjukkan keberatan — pertimbangkan menonjolkan "
                "value/garansi/testimoni alih-alih menurunkan harga langsung."
            )
        elif any(s["signal_type"] == "pre_purchase_question" for s in signals):
            recommended_angle = (
                "Pelanggan dalam fase riset sebelum beli — beri info lengkap & "
                "ajakan bertindak (CTA) yang jelas."
            )

        return AgentResult(
            agent=self.name,
            success=True,
            output={
                "signals": signals,
                "has_objection": has_objection,
                "recommended_angle": recommended_angle,
                "bot_response_excerpt": bot_response[:200],
            },
            latency_ms=0,
        )


async def record_sales_signals(
    *,
    bot_id: str,
    org_id: str,
    conversation_id: str,
    signals: list[dict],
    resulted_in_purchase: bool | None,
) -> int:
    """Simpan sinyal mentah hasil deteksi realtime. Dipanggil setelah jawaban terkirim."""
    if not signals:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for s in signals:
                await conn.execute(
                    """INSERT INTO sales_signals
                           (conversation_id, bot_id, org_id, signal_type, text_snippet, resulted_in_purchase)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    conversation_id, bot_id, org_id, s["signal_type"], s["snippet"], resulted_in_purchase,
                )
    return len(signals)


# ════════════════════════════════════════════════════════════════
# 2. BATCH — tambang pola Trigger → Objection → Solution (nightly)
# ════════════════════════════════════════════════════════════════

def _wilson_confidence(successes: int, total: int, z: float = 1.96) -> float:
    """
    Wilson score lower bound — confidence_score yang naik dengan jumlah data
    DAN proporsi sukses (mencegah pola dengan 1 contoh "sukses" mendapat skor 1.0).
    """
    if total <= 0:
        return 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom)


def _cluster_by_text_similarity(items: list[dict], embeddings: list[list[float]], threshold: float) -> list[list[int]]:
    """Greedy clustering by cosine similarity terhadap centroid — return list of index-groups."""
    clusters: list[dict] = []
    for i, emb in enumerate(embeddings):
        best_idx, best_sim = -1, 0.0
        for ci, cl in enumerate(clusters):
            sim = cosine_similarity(emb, cl["centroid"])
            if sim > best_sim:
                best_sim, best_idx = sim, ci
        if best_idx >= 0 and best_sim >= threshold:
            cl = clusters[best_idx]
            cl["members"].append(i)
            n = len(cl["members"])
            cl["centroid"] = [(c * (n - 1) + e) / n for c, e in zip(cl["centroid"], emb)]
        else:
            clusters.append({"centroid": list(emb), "members": [i]})
    return [cl["members"] for cl in clusters]


async def mine_patterns(bot_id: str, org_id: str, *, limit: int = 2000) -> dict:
    """
    Ambil semua sales_signals yang belum tertaut ke pattern, kelompokkan
    berdasarkan kemiripan teks (per signal_type), upsert sales_patterns dengan
    conversion_rate & confidence_score (Wilson lower bound).
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, signal_type, text_snippet, resulted_in_purchase
           FROM sales_signals
           WHERE bot_id = $1 AND pattern_id IS NULL
           ORDER BY created_at ASC
           LIMIT $2""",
        bot_id, limit,
    )
    signals = [dict(r) for r in rows]
    if not signals:
        return {"patterns_upserted": 0, "signals_processed": 0}

    threshold = cfg.sales_pattern_similarity_threshold
    patterns_upserted = 0

    # Cluster per signal_type supaya trigger/objection sejenis tidak tercampur
    by_type: dict[str, list[dict]] = {}
    for s in signals:
        by_type.setdefault(s["signal_type"], []).append(s)

    for signal_type, group in by_type.items():
        embeddings = [await generate_embedding(s["text_snippet"]) for s in group]
        clusters = _cluster_by_text_similarity(group, embeddings, threshold)

        for member_idxs in clusters:
            members = [group[i] for i in member_idxs]
            if len(members) < 2:
                continue

            total = len(members)
            conversions = sum(1 for m in members if m.get("resulted_in_purchase") is True)
            conversion_rate = conversions / total
            confidence = _wilson_confidence(conversions, total)

            # representative text = median length snippet (heuristik ringan, konsisten dgn FAQ)
            texts = sorted((m["text_snippet"] for m in members), key=len)
            representative = texts[len(texts) // 2]
            emb = await generate_embedding(representative)

            is_objection = signal_type in _OBJECTION_TYPES
            trigger_text = representative if not is_objection else None
            objection_text = representative if is_objection else None

            async with pool.acquire() as conn:
                async with conn.transaction():
                    pattern_id = await conn.fetchval(
                        """
                        INSERT INTO sales_patterns
                            (bot_id, org_id, pattern_type, trigger_text, objection_text,
                             solution_text, occurrences, conversions, conversion_rate,
                             confidence_score, embedding, last_seen_at)
                        VALUES ($1,$2,$3,$4,$5, NULL, $6,$7,$8, $9,$10, NOW())
                        RETURNING id
                        """,
                        bot_id, org_id, signal_type, trigger_text, objection_text,
                        total, conversions, conversion_rate, confidence, emb,
                    )
                    member_ids = [m["id"] for m in members]
                    await conn.execute(
                        "UPDATE sales_signals SET pattern_id = $1 WHERE id = ANY($2::uuid[])",
                        pattern_id, member_ids,
                    )
            patterns_upserted += 1

    return {"patterns_upserted": patterns_upserted, "signals_processed": len(signals)}


async def attach_solutions(bot_id: str) -> int:
    """
    Untuk pola objection dengan conversion_rate tinggi, cari ringkasan
    percakapan (conversation_analysis.summary) dari sumber sinyalnya yang
    berakhir 'purchased' — jadikan itu sebagai `solution_text` (apa yang
    "berhasil" meredakan objection tsb). Heuristik sederhana, dijalankan nightly.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT sp.id AS pattern_id, ca.summary
        FROM sales_patterns sp
        JOIN sales_signals ss   ON ss.pattern_id = sp.id AND ss.resulted_in_purchase = TRUE
        JOIN conversation_analysis ca ON ca.conversation_id = ss.conversation_id
        WHERE sp.bot_id = $1 AND sp.pattern_type = ANY($2::text[])
              AND sp.solution_text IS NULL AND sp.conversion_rate > 0
        ORDER BY sp.id, ca.analyzed_at DESC
        """,
        bot_id, list(_OBJECTION_TYPES),
    )
    seen: set[str] = set()
    updated = 0
    async with pool.acquire() as conn:
        for r in rows:
            pid = str(r["pattern_id"])
            if pid in seen:
                continue
            seen.add(pid)
            await conn.execute(
                "UPDATE sales_patterns SET solution_text = $2, updated_at = NOW() WHERE id = $1",
                r["pattern_id"], r["summary"],
            )
            updated += 1
    return updated
