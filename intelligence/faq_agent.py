"""
intelligence/faq_agent.py — FAQ ENGINE

Dua jalur kerja:

1. REAL-TIME (`FAQAgent`, didaftarkan ke SupervisorAgent, jalan paralel dengan
   CS/Analytics): cocokkan pertanyaan masuk dengan FAQ yang sudah ada lewat
   semantic search (pgvector ANN). Hasilnya bisa dipakai CS Agent sebagai
   jawaban cepat berkonfidensi tinggi, dan dipakai untuk menambah
   `frequency_score` FAQ yang cocok.

2. BATCH / NIGHTLY (`cluster_new_questions`, `recompute_scores`, dipanggil dari
   `nightly_jobs.py`): kumpulkan pertanyaan yang belum cocok dengan FAQ manapun
   ("kandidat"), kelompokkan yang mirip secara semantik (clustering), dan
   gabungkan jadi entri FAQ baru — lengkap dengan frequency / success /
   conversion score.

    FAQ
    ├── Pertanyaan      (question, hasil pemilihan representatif cluster)
    ├── Jawaban         (answer, dipilih dari kandidat ber-skor tertinggi)
    ├── Frekuensi       (frequency_score)
    ├── Tingkat keberhasilan (success_score = rasio outcome 'resolved'/'purchased')
    ├── Conversion      (conversion_score = rasio outcome 'purchased')
    └── Terakhir diperbarui (last_seen_at / updated_at)
"""
from __future__ import annotations

from base import AgentResult, BaseAgent

from .config import cfg
from .db import get_pool
from .embeddings import cosine_similarity, generate_embedding
from .llm import call_llm

_OUTCOME_SUCCESS = {"resolved", "purchased"}
_OUTCOME_CONVERTED = {"purchased"}


# ════════════════════════════════════════════════════════════════
# 1. REAL-TIME — pencocokan FAQ saat percakapan berlangsung
# ════════════════════════════════════════════════════════════════

class FAQAgent(BaseAgent):
    """
    Agent ringan: HANYA membaca (semantic search), tidak menulis ke DB di jalur
    realtime — supaya latensi `/process` tetap rendah. Penulisan (counter,
    kandidat baru) dilakukan async setelah jawaban dikirim, lewat
    `record_question_signal()` yang dipanggil dari agent_api bersama
    `conversation_memory.persist_conversation`.
    """
    name = "faq_agent"
    skills = ["faq_matching", "semantic_question_search"]
    tools: list[str] = []
    goals = [
        "Mengenali apakah pertanyaan pengguna sudah pernah terjawab (FAQ) dan menyumbangkan jawaban siap pakai bila cocok.",
    ]
    system_prompt = (
        "Kamu adalah FAQ Agent dalam sistem multi-agent BotNesia. "
        "Tugasmu: mengenali apakah pertanyaan pengguna sudah pernah terjawab "
        "sebelumnya (FAQ) dan menyumbangkan jawaban siap pakai bila cocok."
    )

    async def run(self, context: dict) -> AgentResult:
        bot_id = context.get("bot_id")
        user_message = (context.get("user_message") or "").strip()
        if not bot_id or not user_message:
            return AgentResult(agent=self.name, success=True, output={"matched": False}, latency_ms=0)

        try:
            match = await match_existing_faq(bot_id, user_message)
        except Exception as e:
            return AgentResult(agent=self.name, success=False, output={"matched": False}, latency_ms=0, error=str(e))

        if match:
            return AgentResult(
                agent=self.name,
                success=True,
                output={
                    "matched": True,
                    "faq_id": match["id"],
                    "question": match["question"],
                    "suggested_answer": match["answer"],
                    "similarity": match["similarity"],
                    "frequency_score": match["frequency_score"],
                    "success_score": match["success_score"],
                },
                latency_ms=0,
            )

        return AgentResult(agent=self.name, success=True, output={"matched": False}, latency_ms=0)


async def match_existing_faq(bot_id: str, question_text: str, min_similarity: float | None = None) -> dict | None:
    """Cari FAQ paling mirip secara semantik. None bila tak ada di atas ambang batas."""
    threshold = cfg.faq_similarity_threshold if min_similarity is None else min_similarity
    vec = await generate_embedding(question_text)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, question, answer, frequency_score, success_score, conversion_score,
               1 - (embedding <=> $2::vector) AS similarity
        FROM faq_entries
        WHERE bot_id = $1 AND embedding IS NOT NULL AND status != 'archived'
        ORDER BY embedding <=> $2::vector
        LIMIT 1
        """,
        bot_id, vec,
    )
    if row and row["similarity"] is not None and row["similarity"] >= threshold:
        return dict(row)
    return None


async def record_question_signal(
    *,
    bot_id: str,
    org_id: str,
    conversation_id: str,
    question_text: str,
    answer_text: str,
    outcome: str,
    quality_score: float,
) -> None:
    """
    Dipanggil setelah jawaban dikirim (fire-and-forget, bersamaan dengan
    conversation_memory.persist_conversation). Dua kemungkinan:
      a) Cocok dengan FAQ existing  -> increment frequency_score + catat asal (audit trail)
      b) Tidak cocok                -> simpan sebagai kandidat (faq_id NULL) untuk di-cluster nanti
    """
    question_text = (question_text or "").strip()
    if not question_text:
        return

    vec = await generate_embedding(question_text)
    pool = await get_pool()

    match = await match_existing_faq(bot_id, question_text)
    async with pool.acquire() as conn:
        async with conn.transaction():
            if match:
                await conn.execute(
                    """UPDATE faq_entries
                       SET frequency_score = frequency_score + 1,
                           last_seen_at = NOW(),
                           updated_at = NOW()
                       WHERE id = $1""",
                    match["id"],
                )
                faq_id = match["id"]
            else:
                faq_id = None

            await conn.execute(
                """INSERT INTO faq_source_messages
                       (faq_id, bot_id, org_id, conversation_id, message_text,
                        answer_text, embedding, similarity, outcome, quality_score)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                faq_id, bot_id, org_id, conversation_id, question_text,
                answer_text, vec, (match or {}).get("similarity"), outcome, float(quality_score or 0.0),
            )


# ════════════════════════════════════════════════════════════════
# 2. BATCH — clustering kandidat baru jadi FAQ (dipanggil nightly_jobs)
# ════════════════════════════════════════════════════════════════

_CANONICAL_PROMPT = (
    "Kamu menerima beberapa variasi pertanyaan pelanggan yang bermakna sama. "
    "Tulis SATU pertanyaan kanonik yang ringkas dan mewakili semuanya, "
    "dalam Bahasa Indonesia, gaya tanya formal singkat. Jawab hanya dengan "
    "kalimat pertanyaannya, tanpa penjelasan tambahan."
)


async def _canonical_question(samples: list[str]) -> str:
    """Pilih/susun representasi pertanyaan kanonik dari satu cluster."""
    uniq = list(dict.fromkeys(s.strip() for s in samples if s.strip()))
    if not uniq:
        return ""
    if cfg.groq_api_key and len(uniq) > 1:
        try:
            joined = "\n".join(f"- {s}" for s in uniq[:12])
            out = await call_llm(
                messages=[
                    {"role": "system", "content": _CANONICAL_PROMPT},
                    {"role": "user", "content": joined},
                ],
                temperature=0.1,
                max_tokens=80,
            )
            if out.strip():
                return out.strip().strip('"')
        except Exception:
            pass
    # Fallback heuristik: ambil yang paling representatif (panjang median)
    uniq.sort(key=len)
    return uniq[len(uniq) // 2]


def _greedy_cluster(items: list[dict], threshold: float) -> list[list[dict]]:
    """
    Single-link greedy clustering berbasis cosine similarity terhadap centroid.
    items: [{"embedding": [...], ...}, ...]   — urut tidak masalah (deterministik by id).
    """
    clusters: list[dict] = []   # tiap elemen: {"centroid": [...], "members": [...]}
    for item in items:
        emb = item["embedding"]
        best_idx, best_sim = -1, 0.0
        for idx, cl in enumerate(clusters):
            sim = cosine_similarity(emb, cl["centroid"])
            if sim > best_sim:
                best_sim, best_idx = sim, idx
        if best_idx >= 0 and best_sim >= threshold:
            cl = clusters[best_idx]
            cl["members"].append(item)
            n = len(cl["members"])
            cl["centroid"] = [
                (c * (n - 1) + e) / n for c, e in zip(cl["centroid"], emb)
            ]
        else:
            clusters.append({"centroid": list(emb), "members": [item]})
    return [cl["members"] for cl in clusters]


async def cluster_new_questions(bot_id: str, org_id: str, *, limit: int = 1000) -> dict:
    """
    Ambil kandidat (faq_id IS NULL) untuk satu bot, kelompokkan, dan buat
    entri FAQ baru untuk cluster yang cukup besar (>= faq_min_cluster_size).
    Dipanggil oleh nightly_jobs.run_daily_learning().
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, conversation_id, message_text, answer_text, embedding, outcome, quality_score
           FROM faq_source_messages
           WHERE bot_id = $1 AND faq_id IS NULL AND embedding IS NOT NULL
           ORDER BY created_at ASC
           LIMIT $2""",
        bot_id, limit,
    )
    candidates = [dict(r) for r in rows]
    if not candidates:
        return {"clusters_formed": 0, "faq_created": 0, "candidates_seen": 0}

    clusters = _greedy_cluster(candidates, cfg.faq_similarity_threshold)
    faq_created = 0

    for members in clusters:
        if len(members) < cfg.faq_min_cluster_size:
            continue

        questions = [m["message_text"] for m in members]
        canonical_q = await _canonical_question(questions)
        if not canonical_q:
            continue

        # Jawaban kanonik = jawaban dari kandidat ber-skor kualitas tertinggi
        best = max(members, key=lambda m: (m.get("quality_score") or 0.0))
        canonical_a = (best.get("answer_text") or "").strip()
        if not canonical_a:
            continue

        total = len(members)
        success = sum(1 for m in members if (m.get("outcome") or "") in _OUTCOME_SUCCESS)
        converted = sum(1 for m in members if (m.get("outcome") or "") in _OUTCOME_CONVERTED)

        emb = await generate_embedding(canonical_q)

        async with pool.acquire() as conn:
            async with conn.transaction():
                faq_id = await conn.fetchval(
                    """INSERT INTO faq_entries
                           (bot_id, org_id, question, answer, embedding,
                            frequency_score, success_score, conversion_score, status)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'auto')
                       RETURNING id""",
                    bot_id, org_id, canonical_q, canonical_a, emb,
                    total, success / total, converted / total,
                )
                member_ids = [m["id"] for m in members]
                await conn.execute(
                    "UPDATE faq_source_messages SET faq_id = $1 WHERE id = ANY($2::uuid[])",
                    faq_id, member_ids,
                )
        faq_created += 1

    return {"clusters_formed": len(clusters), "faq_created": faq_created, "candidates_seen": len(candidates)}


async def recompute_scores(bot_id: str) -> int:
    """
    Refresh success_score & conversion_score semua FAQ existing berdasarkan
    seluruh `faq_source_messages` yang sudah tertaut (termasuk yang baru
    bergabung sejak terakhir dihitung). Dipanggil tiap malam.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT faq_id,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE outcome = ANY($2::text[])) AS success,
               COUNT(*) FILTER (WHERE outcome = ANY($3::text[])) AS converted
        FROM faq_source_messages
        WHERE bot_id = $1 AND faq_id IS NOT NULL
        GROUP BY faq_id
        """,
        bot_id, list(_OUTCOME_SUCCESS), list(_OUTCOME_CONVERTED),
    )
    updated = 0
    async with pool.acquire() as conn:
        for r in rows:
            total = r["total"] or 1
            await conn.execute(
                """UPDATE faq_entries
                   SET success_score = $2, conversion_score = $3,
                       frequency_score = $4, updated_at = NOW()
                   WHERE id = $1""",
                r["faq_id"], r["success"] / total, r["converted"] / total, r["total"],
            )
            updated += 1
    return updated
