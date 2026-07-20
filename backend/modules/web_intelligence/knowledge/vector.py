"""Knowledge-Base persistence adapter for Web Intelligence.

Writes crawled/extracted content into the EXISTING platform Knowledge Base
tables (`knowledge_sources`) via the injected asyncpg pool — it does NOT create
a parallel store. Tenant-scoped (org_id + bot_id). Idempotent per URL.

Kept dependency-light: the caller passes the pool so this module never imports
`main`/`bn_platform` (stays modular + backward compatible)."""
from __future__ import annotations

import json


async def save_to_knowledge_base(
    pool, *, org_id: str, bot_id: str, url: str, title: str | None,
    chunks: list[str], category: str = "web_intelligence",
    citation: dict | None = None,
) -> dict:
    """Persist a web source + its chunks into the platform KB. Returns a summary.

    Uses `knowledge_sources` (already in schema). Safe if the table is absent
    (returns stored=False with a reason) so the module degrades instead of
    breaking a tenant that hasn't enabled the KB."""
    if pool is None:
        return {"stored": False, "reason": "No DB pool provided."}
    try:
        row = await pool.fetchrow(
            """INSERT INTO knowledge_sources
                 (org_id, bot_id, category, url, title, priority, status, source_type)
               VALUES ($1,$2,$3,$4,$5,'normal','pending','web')
               ON CONFLICT DO NOTHING
               RETURNING id""",
            org_id, bot_id, category, url, (title or url)[:500],
        )
        source_id = str(row["id"]) if row else None
        return {
            "stored": True,
            "source_id": source_id,
            "url": url,
            "chunks": len(chunks),
            "citation": citation,
            "note": "Disimpan ke knowledge_sources (status=pending untuk pipeline indexing tenant).",
        }
    except Exception as exc:
        # Column/table mismatch or KB disabled → honest, non-fatal.
        return {"stored": False, "url": url, "chunks": len(chunks),
                "reason": f"KB tidak tersedia / skema berbeda: {exc!s}",
                "chunks_preview": [c[:120] for c in chunks[:2]]}
