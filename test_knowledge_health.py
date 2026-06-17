"""
Tests untuk knowledge_health_report() (bn_platform/knowledge_builder.py) dan
SSRF guard di knowledge_seeder.is_valid_url() — bagian "Knowledge Quality
Check" dari Production Readiness Phase.

knowledge_health_report() pakai query agregat lintas beberapa tabel nyata
(documents, doc_chunks, kb_quality_reports) — diuji langsung terhadap
Postgres asli (bukan FakePool) karena lebih sederhana & lebih dipercaya
untuk query agregat seperti ini, konsisten dengan tema "stop testing
offline" di seluruh pekerjaan stabilization ini.

Catatan teknis: setiap test membuat & menutup pool asyncpg-nya sendiri di
dalam SATU panggilan asyncio.run() — asyncpg connection terikat ke event
loop tempat ia dibuat, jadi berbagi pool lintas asyncio.run() yang berbeda
(loop berbeda) akan gagal dengan "attached to a different loop".
"""
import asyncio
import uuid

import asyncpg
import pytest

import main
from bn_platform.knowledge_builder import knowledge_health_report


async def _setup_org_and_bot(pool) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    bot_id = str(uuid.uuid4())
    slug = f"e2e-kb-health-{uuid.uuid4().hex[:8]}"
    await pool.execute(
        """INSERT INTO organizations (id, name, slug, plan, billing_status)
           VALUES ($1,$2,$3,'starter','trialing')""",
        org_id, "KB Health Test Org", slug,
    )
    await pool.execute(
        """INSERT INTO bots (id, org_id, name, status, primary_color, greeting, language, system_prompt)
           VALUES ($1,$2,'KB Health Test Bot','active','#0066FF','Halo','id','Kamu adalah asisten.')""",
        bot_id, org_id,
    )
    return org_id, bot_id


async def _insert_document(pool, *, org_id, bot_id, status, source_type="url", source_url=None,
                            filename="doc.txt", error_msg=None) -> str:
    doc_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO documents (id, org_id, bot_id, filename, file_size, mime_type,
                                  status, source_type, source_url, error_msg)
           VALUES ($1,$2,$3,$4,10,'text/plain',$5,$6,$7,$8)""",
        doc_id, org_id, bot_id, filename, status, source_type, source_url, error_msg,
    )
    return doc_id


async def _insert_chunk(pool, *, document_id, org_id, content, token_count) -> str:
    chunk_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO doc_chunks (id, document_id, org_id, chunk_index, content, token_count)
           VALUES ($1,$2,$3,0,$4,$5)""",
        chunk_id, document_id, org_id, content, token_count,
    )
    return chunk_id


def _run(coro_fn):
    """Run an async test body inside a single fresh event loop + pool."""
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


def test_health_report_counts_urls_and_documents():
    async def body(pool):
        org_id, bot_id = await _setup_org_and_bot(pool)
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready",
                                source_type="url", source_url="https://example.com/a")
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="failed",
                                source_type="url", source_url="https://example.com/b",
                                error_msg="Timeout saat fetch")
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready",
                                source_type="file", filename="upload.txt")

        report = await knowledge_health_report(pool, org_id=org_id, bot_id=bot_id)

        assert report["total_urls"] == 2
        assert report["indexed_urls"] == 1
        assert report["failed_urls"] == 1
        assert report["total_documents"] == 3
        assert report["indexed_documents"] == 2
        assert report["failed_documents"] == 1
        assert len(report["failed_documents_detail"]) == 1
        assert report["failed_documents_detail"][0]["error_msg"] == "Timeout saat fetch"

    _run(body)


def test_health_report_detects_duplicate_urls():
    async def body(pool):
        org_id, bot_id = await _setup_org_and_bot(pool)
        dup_url = "https://example.com/duplicate-page"
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready",
                                source_type="url", source_url=dup_url)
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready",
                                source_type="url", source_url=dup_url)
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready",
                                source_type="url", source_url="https://example.com/unique-page")

        report = await knowledge_health_report(pool, org_id=org_id, bot_id=bot_id)

        assert report["duplicate_url_count"] == 1
        assert report["duplicate_urls"][0]["source_url"] == dup_url
        assert report["duplicate_urls"][0]["count"] == 2

    _run(body)


def test_health_report_detects_empty_chunks():
    async def body(pool):
        org_id, bot_id = await _setup_org_and_bot(pool)
        doc_id = await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready", source_type="file")
        await _insert_chunk(pool, document_id=doc_id, org_id=org_id,
                             content="Konten valid yang cukup panjang.", token_count=6)
        await _insert_chunk(pool, document_id=doc_id, org_id=org_id, content="   ", token_count=0)

        report = await knowledge_health_report(pool, org_id=org_id, bot_id=bot_id)

        assert report["empty_chunks"] == 1

    _run(body)


def test_health_report_org_wide_when_bot_id_omitted():
    async def body(pool):
        org_id, bot_id = await _setup_org_and_bot(pool)
        await _insert_document(pool, org_id=org_id, bot_id=bot_id, status="ready",
                                source_type="url", source_url="https://example.com/org-wide")

        scoped = await knowledge_health_report(pool, org_id=org_id, bot_id=bot_id)
        org_wide = await knowledge_health_report(pool, org_id=org_id, bot_id=None)

        assert org_wide["total_documents"] >= scoped["total_documents"]
        assert org_wide["bot_id"] is None

    _run(body)


# ── SSRF guard regression for the real URL-ingestion fetch point ──────────
#
# main.py::_fetch_website_text() is the single function every knowledge URL
# ingestion path (single-URL endpoint, bulk endpoint, background crawler)
# funnels through via _process_document_sync(). It used to fetch ANY
# tenant-submitted URL with zero validation (and follow_redirects=True with
# no re-check on the redirect target) — a real SSRF hole: an authenticated
# tenant could make the server fetch http://169.254.169.254/... or an
# internal service and store the response into their bot's knowledge base.

import asyncio as _asyncio

import main as _main


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1/admin",
    "http://localhost:8000/secret",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router-config",
    "ftp://example.com/file",
])
def test_fetch_website_text_rejects_private_and_unsupported_urls(url):
    result = _asyncio.run(_main._fetch_website_text(url))
    assert result == ""
