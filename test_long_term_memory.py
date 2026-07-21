"""P1-B.1 — SemanticMemory (pgvector) vs Postgres nyata.

embed_fn di-fake (384-dim deterministik) → cepat & tanpa unduh model. Menguji
store+retrieve by-similarity, filter scope/subject, degrade tanpa embedding.
"""
import asyncio
import uuid

import asyncpg

import main
from long_term_memory import SemanticMemory, ensure_memory_schema


async def fake_embed(text):
    """384-dim: dominan dim-0 utk 'apel', dim-1 'mobil', dim-2 lainnya."""
    v = [0.0] * 384
    t = (text or "").lower()
    if "apel" in t:
        v[0] = 1.0
    elif "mobil" in t:
        v[1] = 1.0
    else:
        v[2] = 1.0
    return v


mem = SemanticMemory(embed_fn=fake_embed)
mem_degraded = SemanticMemory(embed_fn=lambda _t: _none())


async def _none():
    return None


def _run(body):
    async def wrap():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await ensure_memory_schema(pool)
            org = str(uuid.uuid4())
            await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                               org, "MemTest", f"mem-{org[:8]}")
            try:
                await body(pool, org)
            finally:
                await pool.execute("DELETE FROM organizations WHERE id=$1", org)
        finally:
            await pool.close()
    asyncio.run(wrap())


def test_store_returns_id_and_retrieve_by_similarity():
    async def body(pool, org):
        assert await mem.store(pool, org_id=org, content="apel manis dari kebun") is not None
        await mem.store(pool, org_id=org, content="apel merah segar")
        await mem.store(pool, org_id=org, content="mobil balap cepat")
        top2 = await mem.retrieve(pool, org_id=org, query="apel hijau", k=2)
        assert len(top2) == 2 and all("apel" in it["content"] for it in top2)
        assert top2[0]["score"] == 1.0                     # cosine identik (dim-0)
        top3 = await mem.retrieve(pool, org_id=org, query="apel", k=3)
        assert "mobil" in top3[2]["content"]               # paling tak relevan di akhir
    _run(body)


def test_filter_scope_and_subject():
    async def body(pool, org):
        await mem.store(pool, org_id=org, content="fakta apel A", scope="semantic", subject="user-1")
        await mem.store(pool, org_id=org, content="fakta apel B", scope="episodic", subject="user-2")
        s = await mem.retrieve(pool, org_id=org, query="apel", scope="semantic")
        assert len(s) == 1 and s[0]["subject"] == "user-1"
        u2 = await mem.retrieve(pool, org_id=org, query="apel", subject="user-2")
        assert len(u2) == 1 and u2[0]["scope"] == "episodic"
    _run(body)


def test_degrade_without_embedding_uses_recency():
    async def body(pool, org):
        # tanpa embedding: tersimpan tanpa vektor, retrieve fallback recency/importance
        assert await mem_degraded.store(pool, org_id=org, content="catatan tanpa vektor",
                                        importance=0.9) is not None
        hits = await mem_degraded.retrieve(pool, org_id=org, query="apa saja")
        assert len(hits) == 1 and hits[0]["score"] is None
    _run(body)


def test_summarize_builds_prompt_text():
    async def body(pool, org):
        await mem.store(pool, org_id=org, content="pelanggan suka apel")
        text = await mem.summarize(pool, org_id=org, query="apel", k=3)
        assert "Memori relevan" in text and "apel" in text
        assert await mem.summarize(pool, org_id=org, query="") == ""     # query kosong → ""
    _run(body)


def test_access_count_incremented():
    async def body(pool, org):
        mid = await mem.store(pool, org_id=org, content="apel untuk akses")
        await mem.retrieve(pool, org_id=org, query="apel")
        n = await pool.fetchval("SELECT access_count FROM agent_memories WHERE id=$1", uuid.UUID(mid))
        assert n >= 1
    _run(body)
