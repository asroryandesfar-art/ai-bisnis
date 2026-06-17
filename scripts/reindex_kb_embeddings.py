"""
Regenerate embeddings for every doc_chunks row through whichever provider
main.py::_generate_kb_embedding currently selects (OpenAI text-embedding-3-small
if OPENAI_API_KEY is set, otherwise the local hash fallback).

Run this once right after adding/rotating OPENAI_API_KEY so all chunks share
the same model tag -- main.py::_score_kb_candidate skips the embedding score
for any chunk whose stored `model` tag doesn't match the current query's
provider, so mixed old/new chunks silently fall back to keyword-only scoring
until they're reindexed. Also backfills any doc_chunks row that's missing an
embedding row entirely (e.g. from before doc_chunk_embeddings existed).

Idempotent -- ON CONFLICT (chunk_id) DO UPDATE, safe to run multiple times.

Usage: python3 scripts/reindex_kb_embeddings.py
"""
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402
import kb_embeddings  # noqa: E402

BATCH_SIZE = 200


async def reindex(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch(
        """SELECT c.id, c.content, c.org_id
           FROM doc_chunks c"""
    )
    total = len(rows)
    provider = kb_embeddings.OPENAI_EMBEDDING_TAG if main.cfg.openai_api_key else "local hash"
    print(f"Reindexing {total} chunks (provider: {provider})...")

    done = 0
    for row in rows:
        embedding, model_tag = await main._generate_kb_embedding(row["content"] or "")
        await pool.execute(
            """INSERT INTO doc_chunk_embeddings (chunk_id, org_id, embedding, model)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (chunk_id) DO UPDATE
               SET org_id=EXCLUDED.org_id,
                   embedding=EXCLUDED.embedding,
                   model=EXCLUDED.model""",
            row["id"], row["org_id"], json.dumps(embedding), model_tag,
        )
        done += 1
        if done % BATCH_SIZE == 0 or done == total:
            print(f"  {done}/{total}")

    print(f"Done. {done} chunks reindexed with model tag(s) seen above.")


async def _run() -> None:
    pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
    try:
        await reindex(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
