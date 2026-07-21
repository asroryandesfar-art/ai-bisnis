"""long_term_memory.store — SemanticMemory (P1-B.1).

Simpan & RETRIEVE memori berdasar kemiripan makna (pgvector). Interface seragam:
`store` / `retrieve` (+ `summarize` sederhana). Embedding via `embed_fn` yang
DISUNTIKKAN (default lazy `kb_embeddings.generate_local_embedding`, 384-dim lokal)
→ test cepat/deterministik & produksi gratis-tanpa-API.

Graceful degrade: bila embedding None (model tak ada) → simpan tanpa vektor &
retrieve fallback ke recency; bila tabel/pgvector tak ada → operasi aman (no-op/
kosong), tak me-crash pemanggil. Modul mandiri (tak impor main/bn_platform).
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

import asyncpg


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


class SemanticMemory:
    def __init__(self, *, embed_fn: Callable[[str], Awaitable[list | None]] | None = None):
        self._embed_fn = embed_fn

    async def _embed(self, text: str) -> list | None:
        fn = self._embed_fn
        if fn is None:
            try:
                from kb_embeddings import generate_local_embedding
                fn = generate_local_embedding
            except Exception:
                return None
        try:
            return await fn(text)
        except Exception:
            return None

    async def store(self, pool: asyncpg.Pool, *, org_id: str, content: str,
                    scope: str = "semantic", subject: str | None = None,
                    metadata: dict | None = None, importance: float = 0.5,
                    bot_id: str | None = None) -> str | None:
        """Simpan satu memori (embed otomatis). Return id, atau None bila gagal/degrade."""
        content = (content or "").strip()
        if not content:
            return None
        vec = await self._embed(content)
        try:
            row = await pool.fetchrow(
                """INSERT INTO agent_memories
                   (org_id, bot_id, scope, subject, content, metadata, embedding, importance)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::vector,$8)
                   RETURNING id""",
                org_id, bot_id, scope, subject, content, json.dumps(metadata or {}),
                _vec_literal(vec) if vec else None, float(importance))
            return str(row["id"])
        except Exception:
            return None

    async def retrieve(self, pool: asyncpg.Pool, *, org_id: str, query: str,
                       scope: str | None = None, subject: str | None = None,
                       k: int = 5) -> list[dict]:
        """Ambil <=k memori paling relevan (kemiripan vektor; fallback recency).
        Setiap item: {id, content, metadata, scope, subject, importance, score}."""
        query = (query or "").strip()
        if not query:
            return []
        vec = await self._embed(query)
        params: list = [org_id]
        where = ["org_id = $1"]
        if scope:
            params.append(scope); where.append(f"scope = ${len(params)}")
        if subject:
            params.append(subject); where.append(f"subject = ${len(params)}")
        wsql = " AND ".join(where)
        try:
            if vec:
                params.append(_vec_literal(vec))
                vp = f"${len(params)}::vector"
                rows = await pool.fetch(
                    f"""SELECT id, content, metadata, scope, subject, importance,
                               (embedding <=> {vp}) AS distance
                        FROM agent_memories
                        WHERE {wsql} AND embedding IS NOT NULL
                        ORDER BY embedding <=> {vp} LIMIT {int(max(1, k))}""", *params)
            else:
                rows = await pool.fetch(
                    f"""SELECT id, content, metadata, scope, subject, importance,
                               NULL::float8 AS distance
                        FROM agent_memories WHERE {wsql}
                        ORDER BY importance DESC, created_at DESC LIMIT {int(max(1, k))}""", *params)
        except Exception:
            return []
        out = []
        ids = []
        for r in rows:
            dist = r["distance"]
            out.append({
                "id": str(r["id"]), "content": r["content"],
                "metadata": r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"] or "{}"),
                "scope": r["scope"], "subject": r["subject"], "importance": r["importance"],
                "score": round(1.0 - float(dist), 4) if dist is not None else None,
            })
            ids.append(r["id"])
        if ids:                                             # catat akses (best-effort)
            try:
                await pool.execute(
                    "UPDATE agent_memories SET access_count = access_count + 1, "
                    "last_accessed_at = NOW() WHERE id = ANY($1::uuid[])", ids)
            except Exception:
                pass
        return out

    async def summarize(self, pool: asyncpg.Pool, *, org_id: str, query: str,
                        scope: str | None = None, subject: str | None = None,
                        k: int = 5, max_chars: int = 1500) -> str:
        """Ringkas memori relevan jadi teks siap-inject ke prompt (retrieve → gabung)."""
        items = await self.retrieve(pool, org_id=org_id, query=query, scope=scope, subject=subject, k=k)
        if not items:
            return ""
        lines = ["## Memori relevan:"]
        for it in items:
            lines.append(f"- {it['content'].strip()}")
        return "\n".join(lines)[:max_chars]
