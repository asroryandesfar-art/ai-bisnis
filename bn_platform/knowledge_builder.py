"""Auto Knowledge Builder — dashboard untuk hasil AI generation per bot:
ringkasan/kategori/tag/intent dokumen, FAQ & SOP hasil AI (review/approve),
dan Knowledge Quality Score (completeness, redundancy, coverage, missing topics)."""
import asyncio
import json
import uuid
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .security import write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]
RunPipeline = Callable[[str], Awaitable[None]]
StoreChunkEmbeddings = Callable[[asyncpg.Connection, str, list[tuple[str, str]]], Awaitable[None]]

FAQ_STATUSES = {"suggested", "approved", "rejected"}
SOP_STATUSES = {"suggested", "approved", "rejected"}


class FaqUpdateRequest(BaseModel):
    status: str | None = None
    question: str | None = None
    answer: str | None = None
    category: str | None = None


class SopUpdateRequest(BaseModel):
    status: str | None = None
    title: str | None = None
    steps: list[str] | None = None
    category: str | None = None


def _jsonb(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else []
    if value is None:
        return default if default is not None else []
    return value


def _row_with_jsonb(row: dict, fields: list[str]) -> dict:
    out = dict(row)
    for field in fields:
        if field in out:
            out[field] = _jsonb(out[field])
    return out


async def _publish_to_kb(
    conn: asyncpg.Connection,
    *,
    org_id: str,
    document_id: str,
    content: str,
    store_chunk_embeddings: StoreChunkEmbeddings,
) -> str:
    """Tambahkan satu chunk baru (FAQ/SOP yang di-approve) ke knowledge base."""
    chunk_id = str(uuid.uuid4())
    await conn.execute(
        """INSERT INTO doc_chunks (id, document_id, org_id, chunk_index, content, token_count)
           VALUES ($1,$2,$3,
               (SELECT COALESCE(MAX(chunk_index)+1, 0) FROM doc_chunks WHERE document_id=$2),
               $4,$5)""",
        chunk_id, document_id, org_id, content, len(content.split()),
    )
    await store_chunk_embeddings(conn, org_id, [(chunk_id, content)])
    return chunk_id


async def _unpublish_from_kb(conn: asyncpg.Connection, *, org_id: str, chunk_id: str | None) -> None:
    if chunk_id:
        await conn.execute("DELETE FROM doc_chunks WHERE id=$1 AND org_id=$2", chunk_id, org_id)


async def knowledge_health_report(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None = None) -> dict:
    """Audit kesehatan knowledge base dari sisi ingestion: total/indexed/failed
    URL, URL duplikat, chunk kosong, dan quality score (rata-rata
    kb_quality_reports.overall_score yang sudah dihitung knowledge_builder_agent).
    Berbeda dari overview() di atas (yang fokus per-dokumen untuk satu bot) —
    fungsi ini bisa lintas-bot (bot_id=None) untuk audit org-wide."""
    bot_filter = "AND bot_id=$2" if bot_id else ""
    params: list = [org_id] + ([bot_id] if bot_id else [])

    totals = await pool.fetchrow(
        f"""SELECT
              COUNT(*) FILTER (WHERE source_type='url')::int               AS total_urls,
              COUNT(*) FILTER (WHERE source_type='url' AND status='ready')::int  AS indexed_urls,
              COUNT(*) FILTER (WHERE source_type='url' AND status='failed')::int AS failed_urls,
              COUNT(*)::int                                                 AS total_documents,
              COUNT(*) FILTER (WHERE status='ready')::int                  AS indexed_documents,
              COUNT(*) FILTER (WHERE status='failed')::int                 AS failed_documents
            FROM documents WHERE org_id=$1 {bot_filter}""",
        *params,
    )

    dup_rows = await pool.fetch(
        f"""SELECT source_url, COUNT(*)::int AS count
              FROM documents
             WHERE org_id=$1 {bot_filter} AND source_type='url' AND source_url IS NOT NULL
             GROUP BY source_url HAVING COUNT(*) > 1
             ORDER BY COUNT(*) DESC""",
        *params,
    )

    empty_chunks = await pool.fetchval(
        f"""SELECT COUNT(*)::int FROM doc_chunks c
              JOIN documents d ON d.id = c.document_id
             WHERE d.org_id=$1 {bot_filter}
               AND (TRIM(c.content) = '' OR c.token_count = 0)""",
        *params,
    )

    failed_detail = await pool.fetch(
        f"""SELECT id, filename, source_url, kb_error, error_msg
              FROM documents
             WHERE org_id=$1 {bot_filter} AND status='failed'
             ORDER BY created_at DESC LIMIT 50""",
        *params,
    )

    quality_row = await pool.fetchrow(
        f"""SELECT ROUND(AVG(overall_score)::numeric, 1) AS overall_score,
                   COUNT(DISTINCT document_id)::int AS documents_scored
              FROM kb_quality_reports WHERE org_id=$1 {bot_filter}""",
        *params,
    )

    totals_dict = dict(totals)
    quality_score = (
        float(quality_row["overall_score"]) if quality_row["overall_score"] is not None else None
    )

    return {
        "org_id": org_id,
        "bot_id": bot_id,
        "total_urls": totals_dict["total_urls"],
        "indexed_urls": totals_dict["indexed_urls"],
        "failed_urls": totals_dict["failed_urls"],
        "total_documents": totals_dict["total_documents"],
        "indexed_documents": totals_dict["indexed_documents"],
        "failed_documents": totals_dict["failed_documents"],
        "duplicate_urls": [dict(r) for r in dup_rows],
        "duplicate_url_count": len(dup_rows),
        "empty_chunks": empty_chunks,
        "failed_documents_detail": [dict(r) for r in failed_detail],
        "quality_score": quality_score,
        "quality_documents_scored": quality_row["documents_scored"],
    }


def build_knowledge_builder_router(
    *,
    get_pool: GetPool,
    get_current_user: GetCurrentUser,
    run_pipeline: RunPipeline,
    store_chunk_embeddings: StoreChunkEmbeddings,
) -> APIRouter:
    router = APIRouter(prefix="/knowledge-builder", tags=["knowledge-builder"])

    async def _get_bot(pool: asyncpg.Pool, bot_id: str, org_id: str) -> dict:
        bot = await pool.fetchrow(
            "SELECT id, name FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id
        )
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan")
        return dict(bot)

    @router.get("/bots/{bot_id}/overview")
    async def overview(
        bot_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)

        documents = await pool.fetch(
            """SELECT id, filename, status, kb_status, kb_error, chunk_count,
                      source_type, source_url, summary, categories, tags,
                      suggested_intents, created_at, processed_at
               FROM documents WHERE bot_id=$1 AND org_id=$2
               ORDER BY created_at DESC""",
            bot_id, org_id,
        )

        faq_counts = await pool.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE status='suggested')::int AS suggested,
                      COUNT(*) FILTER (WHERE status='approved')::int AS approved,
                      COUNT(*) FILTER (WHERE status='rejected')::int AS rejected
               FROM kb_generated_faqs WHERE bot_id=$1 AND org_id=$2""",
            bot_id, org_id,
        )
        sop_counts = await pool.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE status='suggested')::int AS suggested,
                      COUNT(*) FILTER (WHERE status='approved')::int AS approved,
                      COUNT(*) FILTER (WHERE status='rejected')::int AS rejected
               FROM kb_generated_sops WHERE bot_id=$1 AND org_id=$2""",
            bot_id, org_id,
        )

        quality_rows = await pool.fetch(
            """SELECT DISTINCT ON (document_id) document_id, completeness_score,
                      redundancy_score, coverage_score, overall_score,
                      missing_topics, duplicate_groups, created_at
               FROM kb_quality_reports WHERE bot_id=$1 AND org_id=$2
               ORDER BY document_id, created_at DESC""",
            bot_id, org_id,
        )

        missing_topics: dict[str, int] = {}
        overall_scores = []
        completeness_scores = []
        redundancy_scores = []
        coverage_scores = []
        for row in quality_rows:
            overall_scores.append(row["overall_score"])
            completeness_scores.append(row["completeness_score"])
            redundancy_scores.append(row["redundancy_score"])
            coverage_scores.append(row["coverage_score"])
            for topic in _jsonb(row["missing_topics"]):
                topic = str(topic).strip()
                if topic:
                    missing_topics[topic] = missing_topics.get(topic, 0) + 1

        def _avg(values: list[int]) -> int:
            return round(sum(values) / len(values)) if values else 0

        documents_out = []
        for row in documents:
            documents_out.append(_row_with_jsonb(
                dict(row), ["categories", "tags", "suggested_intents"]
            ))

        return {
            "bot_id": bot_id,
            "documents": documents_out,
            "documents_total": len(documents_out),
            "faqs": dict(faq_counts),
            "sops": dict(sop_counts),
            "quality": {
                "overall_score": _avg(overall_scores),
                "completeness_score": _avg(completeness_scores),
                "redundancy_score": _avg(redundancy_scores),
                "coverage_score": _avg(coverage_scores),
                "documents_scored": len(quality_rows),
            },
            "missing_topics": [
                {"topic": topic, "document_count": count}
                for topic, count in sorted(missing_topics.items(), key=lambda kv: kv[1], reverse=True)
            ][:20],
        }

    @router.post("/bots/{bot_id}/documents/{doc_id}/generate")
    async def regenerate(
        bot_id: str,
        doc_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)

        doc = await pool.fetchrow(
            "SELECT id, status FROM documents WHERE id=$1 AND bot_id=$2 AND org_id=$3",
            doc_id, bot_id, org_id,
        )
        if not doc:
            raise HTTPException(404, "Dokumen tidak ditemukan")
        if doc["status"] != "ready":
            raise HTTPException(409, "Dokumen belum siap (status bukan 'ready')")

        await pool.execute(
            "UPDATE documents SET kb_status='pending', kb_error=NULL WHERE id=$1", doc_id
        )
        asyncio.create_task(run_pipeline(doc_id))
        return {"message": "Knowledge Builder dijadwalkan ulang untuk dokumen ini", "doc_id": doc_id}

    @router.get("/bots/{bot_id}/faqs")
    async def list_faqs(
        bot_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)

        conditions = ["bot_id=$1", "org_id=$2"]
        args: list = [bot_id, org_id]
        if status:
            if status not in FAQ_STATUSES:
                raise HTTPException(422, "Status FAQ tidak valid")
            args.append(status)
            conditions.append(f"status=${len(args)}")

        rows = await pool.fetch(
            f"""SELECT id, document_id, question, answer, category, source, status,
                       chunk_id, created_at, updated_at
                FROM kb_generated_faqs WHERE {' AND '.join(conditions)}
                ORDER BY CASE status WHEN 'suggested' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                         created_at DESC""",
            *args,
        )
        return {"faqs": [dict(row) for row in rows]}

    @router.patch("/faqs/{faq_id}")
    async def update_faq(
        faq_id: str,
        body: FaqUpdateRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        faq = await pool.fetchrow(
            "SELECT * FROM kb_generated_faqs WHERE id=$1 AND org_id=$2", faq_id, org_id
        )
        if not faq:
            raise HTTPException(404, "FAQ tidak ditemukan")

        new_status = body.status if body.status is not None else faq["status"]
        if new_status not in FAQ_STATUSES:
            raise HTTPException(422, "Status FAQ tidak valid")
        question = body.question if body.question is not None else faq["question"]
        answer = body.answer if body.answer is not None else faq["answer"]
        category = body.category if body.category is not None else faq["category"]

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE kb_generated_faqs
                       SET question=$1, answer=$2, category=$3, status=$4, updated_at=NOW()
                       WHERE id=$5 AND org_id=$6 RETURNING *""",
                    question, answer, category, new_status, faq_id, org_id,
                )
                row = dict(row)
                if new_status == "approved" and not row["chunk_id"]:
                    chunk_id = await _publish_to_kb(
                        conn, org_id=org_id, document_id=row["document_id"],
                        content=f"Q: {question}\nA: {answer}",
                        store_chunk_embeddings=store_chunk_embeddings,
                    )
                    await conn.execute(
                        "UPDATE kb_generated_faqs SET chunk_id=$1 WHERE id=$2 AND org_id=$3", chunk_id, faq_id, org_id,
                    )
                    row["chunk_id"] = chunk_id
                elif new_status != "approved" and row["chunk_id"]:
                    await _unpublish_from_kb(conn, org_id=org_id, chunk_id=row["chunk_id"])
                    await conn.execute(
                        "UPDATE kb_generated_faqs SET chunk_id=NULL WHERE id=$1 AND org_id=$2", faq_id, org_id,
                    )
                    row["chunk_id"] = None

        if new_status != faq["status"]:
            await write_audit_log(
                pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
                action="update", resource_type="knowledge_faq", resource_id=faq_id,
                metadata={"old_status": faq["status"], "new_status": new_status},
            )

        return {"faq": row}

    @router.get("/bots/{bot_id}/sops")
    async def list_sops(
        bot_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        status: str | None = None,
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)

        conditions = ["bot_id=$1", "org_id=$2"]
        args: list = [bot_id, org_id]
        if status:
            if status not in SOP_STATUSES:
                raise HTTPException(422, "Status SOP tidak valid")
            args.append(status)
            conditions.append(f"status=${len(args)}")

        rows = await pool.fetch(
            f"""SELECT id, document_id, title, steps, category, status,
                       chunk_id, created_at, updated_at
                FROM kb_generated_sops WHERE {' AND '.join(conditions)}
                ORDER BY CASE status WHEN 'suggested' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                         created_at DESC""",
            *args,
        )
        return {"sops": [_row_with_jsonb(dict(row), ["steps"]) for row in rows]}

    @router.patch("/sops/{sop_id}")
    async def update_sop(
        sop_id: str,
        body: SopUpdateRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        sop = await pool.fetchrow(
            "SELECT * FROM kb_generated_sops WHERE id=$1 AND org_id=$2", sop_id, org_id
        )
        if not sop:
            raise HTTPException(404, "SOP tidak ditemukan")

        new_status = body.status if body.status is not None else sop["status"]
        if new_status not in SOP_STATUSES:
            raise HTTPException(422, "Status SOP tidak valid")
        title = body.title if body.title is not None else sop["title"]
        steps = body.steps if body.steps is not None else _jsonb(sop["steps"])
        steps = [str(s).strip() for s in steps if str(s).strip()]
        if not steps:
            raise HTTPException(422, "SOP harus memiliki minimal 1 langkah")
        category = body.category if body.category is not None else sop["category"]

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE kb_generated_sops
                       SET title=$1, steps=$2::jsonb, category=$3, status=$4, updated_at=NOW()
                       WHERE id=$5 AND org_id=$6 RETURNING *""",
                    title, json.dumps(steps), category, new_status, sop_id, org_id,
                )
                row = _row_with_jsonb(dict(row), ["steps"])
                if new_status == "approved" and not row["chunk_id"]:
                    steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
                    chunk_id = await _publish_to_kb(
                        conn, org_id=org_id, document_id=row["document_id"],
                        content=f"SOP: {title}\n{steps_text}",
                        store_chunk_embeddings=store_chunk_embeddings,
                    )
                    await conn.execute(
                        "UPDATE kb_generated_sops SET chunk_id=$1 WHERE id=$2 AND org_id=$3", chunk_id, sop_id, org_id,
                    )
                    row["chunk_id"] = chunk_id
                elif new_status != "approved" and row["chunk_id"]:
                    await _unpublish_from_kb(conn, org_id=org_id, chunk_id=row["chunk_id"])
                    await conn.execute(
                        "UPDATE kb_generated_sops SET chunk_id=NULL WHERE id=$1 AND org_id=$2", sop_id, org_id,
                    )
                    row["chunk_id"] = None

        if new_status != sop["status"]:
            await write_audit_log(
                pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
                action="update", resource_type="knowledge_sop", resource_id=sop_id,
                metadata={"old_status": sop["status"], "new_status": new_status},
            )

        return {"sop": row}

    @router.get("/bots/{bot_id}/quality")
    async def quality(
        bot_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)

        rows = await pool.fetch(
            """SELECT q.id, q.document_id, d.filename, q.completeness_score,
                      q.redundancy_score, q.coverage_score, q.overall_score,
                      q.missing_topics, q.duplicate_groups, q.created_at
               FROM kb_quality_reports q
               JOIN documents d ON d.id = q.document_id
               WHERE q.bot_id=$1 AND q.org_id=$2
               ORDER BY q.document_id, q.created_at DESC""",
            bot_id, org_id,
        )
        seen: set[str] = set()
        reports = []
        for row in rows:
            doc_id = str(row["document_id"])
            if doc_id in seen:
                continue
            seen.add(doc_id)
            reports.append(_row_with_jsonb(dict(row), ["missing_topics", "duplicate_groups"]))
        return {"reports": reports}

    @router.get("/health")
    async def health(
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        bot_id: str | None = None,
    ):
        if bot_id:
            await _get_bot(pool, bot_id, user["org_id"])
        return await knowledge_health_report(pool, org_id=user["org_id"], bot_id=bot_id)

    return router
