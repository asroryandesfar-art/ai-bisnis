"""Document knowledge-base routes for a bot (URL upload, FAQ CSV import, list,
delete, reindex), extracted from main.py.

The large file-upload handler (POST /bots/{id}/documents) stays in main for now
(it is entangled with the knowledge-builder pipeline). Shared main helpers
(_title_from_url, _process_document_sync, _store_chunk_embeddings) are injected;
the platform hooks (_platform_check_limit, _platform_write_audit) are injected as
getters (late binding). No direct-caller tests, so no re-export needed.
"""
import csv
import io
import uuid
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel


class RagReindexReq(BaseModel):
    include_shared: bool = True
    limit_chunks: int = 2000


def build_documents_router(
    *,
    get_current_user: Callable[..., Awaitable[dict]],
    get_pool: Callable[..., Awaitable],
    get_check_limit: Callable[[], object],
    get_write_audit: Callable[[], object],
    title_from_url: Callable[[str], str],
    process_document_sync: Callable[..., Awaitable],
    store_chunk_embeddings: Callable[..., Awaitable],
    KnowledgeBaseUrlReq,
) -> APIRouter:
    router = APIRouter()

    @router.post("/bots/{bot_id}/documents/url", status_code=201)
    async def upload_document_url(
        bot_id: str,
        body: KnowledgeBaseUrlReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Upload sumber URL ke knowledge base bot."""
        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
        )
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan")

        url = (body.url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "URL harus diawali http:// atau https://")

        check_limit = get_check_limit()
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "knowledge")
            if not ok:
                raise HTTPException(
                    402,
                    f"Limit jumlah dokumen knowledge base paket '{detail['plan']}' tercapai "
                    f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
                )
        else:
            doc_count = await pool.fetchval(
                "SELECT COUNT(*) FROM documents WHERE org_id=$1", user["org_id"]
            )
            doc_limit = await pool.fetchval(
                "SELECT doc_limit FROM organizations WHERE id=$1", user["org_id"]
            )
            if doc_count >= doc_limit:
                raise HTTPException(402, f"Batas dokumen ({doc_limit}) tercapai. Upgrade plan untuk upload lebih.")

        title = (body.title or title_from_url(url)).strip() or title_from_url(url)
        doc_id = str(uuid.uuid4())
        await pool.execute(
            """INSERT INTO documents (id, org_id, bot_id, filename, file_size, mime_type, status, source_type, source_url)
               VALUES ($1,$2,$3,$4,$5,$6,'pending','url',$7)""",
            doc_id, user["org_id"], bot_id,
            title, 0, "text/html", url,
        )

        await process_document_sync(pool, doc_id, source_type="url", source_url=url)
        row = await pool.fetchrow("SELECT status, error_msg FROM documents WHERE id=$1", doc_id)
        return {"doc_id": doc_id, "status": row["status"], "error_msg": row["error_msg"]}

    @router.post("/bots/{bot_id}/documents/faq-import", status_code=201)
    async def import_faq_csv(
        bot_id: str,
        file: UploadFile = File(...),
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Import FAQ langsung dari CSV (kolom question/pertanyaan & answer/jawaban,
        opsional category/kategori). Setiap baris otomatis di-approve dan langsung
        masuk knowledge base (doc_chunks + embeddings) tanpa melalui AI generation."""
        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"]
        )
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan")

        check_limit = get_check_limit()
        if check_limit:
            ok, detail = await check_limit(pool, user["org_id"], "knowledge")
            if not ok:
                raise HTTPException(
                    402,
                    f"Limit jumlah dokumen knowledge base paket '{detail['plan']}' tercapai "
                    f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
                )

        contents = await file.read()
        try:
            reader = csv.reader(io.StringIO(contents.decode("utf-8-sig", errors="ignore")))
            rows = [r for r in reader if any((c or "").strip() for c in r)]
        except Exception as e:
            raise HTTPException(400, f"Gagal membaca CSV: {e}")

        if len(rows) < 2:
            raise HTTPException(400, "CSV harus memiliki header dan minimal 1 baris data.")

        header = [(c or "").strip().lower() for c in rows[0]]
        q_idx = next((i for i, h in enumerate(header) if h in ("question", "pertanyaan", "q")), None)
        a_idx = next((i for i, h in enumerate(header) if h in ("answer", "jawaban", "a")), None)
        c_idx = next((i for i, h in enumerate(header) if h in ("category", "kategori")), None)
        if q_idx is None or a_idx is None:
            raise HTTPException(400, "CSV harus memiliki kolom 'question'/'pertanyaan' dan 'answer'/'jawaban'.")

        pairs: list[tuple[str, str, str | None]] = []
        for r in rows[1:]:
            if len(r) <= max(q_idx, a_idx):
                continue
            q = (r[q_idx] or "").strip()
            a = (r[a_idx] or "").strip()
            if not q or not a:
                continue
            category = (r[c_idx] or "").strip() if c_idx is not None and len(r) > c_idx else ""
            pairs.append((q, a, category or None))

        if not pairs:
            raise HTTPException(400, "Tidak ada pasangan pertanyaan/jawaban valid di CSV.")

        doc_id = str(uuid.uuid4())
        org_id = user["org_id"]
        await pool.execute(
            """INSERT INTO documents
               (id, org_id, bot_id, filename, file_size, mime_type, status, source_type, source_url,
                kb_status, chunk_count, processed_at)
               VALUES ($1,$2,$3,$4,$5,'text/csv','ready','faq_import',NULL,'ready',$6,NOW())""",
            doc_id, org_id, bot_id, file.filename or "faq-import.csv", len(contents), len(pairs),
        )

        async with pool.acquire() as conn:
            async with conn.transaction():
                chunk_rows: list[tuple[str, str]] = []
                for i, (q, a, category) in enumerate(pairs):
                    chunk_id = str(uuid.uuid4())
                    chunk_text = f"Q: {q}\nA: {a}"
                    await conn.execute(
                        """INSERT INTO doc_chunks (id, document_id, org_id, chunk_index, content, token_count)
                           VALUES ($1,$2,$3,$4,$5,$6)""",
                        chunk_id, doc_id, org_id, i, chunk_text, len(chunk_text.split()),
                    )
                    chunk_rows.append((chunk_id, chunk_text))
                    await conn.execute(
                        """INSERT INTO kb_generated_faqs
                           (id, org_id, bot_id, document_id, question, answer, category, source, status, chunk_id)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,'import','approved',$8)""",
                        str(uuid.uuid4()), org_id, bot_id, doc_id, q, a, category, chunk_id,
                    )
                await store_chunk_embeddings(conn, str(org_id), chunk_rows)

        return {"doc_id": doc_id, "imported": len(pairs), "status": "ready"}

    @router.get("/bots/{bot_id}/documents")
    async def list_documents(
        bot_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        rows = await pool.fetch(
            """SELECT id, filename, file_size, status, chunk_count, error_msg, created_at, processed_at,
                      source_type, source_url
               FROM documents WHERE bot_id=$1 AND org_id=$2 ORDER BY created_at DESC""",
            bot_id, user["org_id"],
        )
        return [dict(r) for r in rows]

    @router.delete("/bots/{bot_id}/documents/{doc_id}")
    async def delete_document(
        bot_id: str,
        doc_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        # Pastikan dokumen milik org + bot yang sama
        doc = await pool.fetchrow(
            """SELECT id FROM documents
               WHERE id=$1 AND bot_id=$2 AND org_id=$3""",
            doc_id, bot_id, user["org_id"],
        )
        if not doc:
            raise HTTPException(404, "Dokumen tidak ditemukan")

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM doc_chunks WHERE document_id=$1", doc_id)
                await conn.execute("DELETE FROM documents WHERE id=$1", doc_id)

        write_audit = get_write_audit()
        if write_audit:
            try:
                await write_audit(
                    pool, org_id=user["org_id"], actor_user_id=user["id"], actor_email=user.get("email"),
                    action="delete", resource_type="document", resource_id=doc_id,
                    metadata={"bot_id": bot_id},
                )
            except Exception:
                pass

        return {"message": "Dokumen dihapus"}

    @router.post("/bots/{bot_id}/documents/reindex")
    async def rag_reindex_embeddings(
        bot_id: str,
        body: RagReindexReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        raise HTTPException(410, "Reindex embedding sudah dihapus. Sistem sekarang memakai pencarian keyword internal.")

    return router
