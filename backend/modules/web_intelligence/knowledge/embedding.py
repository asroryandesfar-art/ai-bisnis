"""Embedding adapter — REUSES the platform embedding pipeline, does not add a
second one. This keeps Web Intelligence modular while sharing one embedding
strategy/table (`doc_chunk_embeddings`) with the rest of BotNesia.

Honest degradation: if no platform embedder is wired, `embedder_available()` is
False and ingestion still stores chunks as searchable text (keyword search),
just without vector search — instead of failing."""
from __future__ import annotations


def embedder_available() -> bool:
    """True if the platform exposes an embedding function we can reuse."""
    try:
        import embeddings as _e  # platform module, if present
        return any(hasattr(_e, fn) for fn in ("embed_text", "embed", "get_embedding"))
    except Exception:
        return False


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Delegate to the platform embedder. Returns None if unavailable (caller
    falls back to keyword-only indexing)."""
    if not embedder_available():
        return None
    try:
        import embeddings as _e
        fn = getattr(_e, "embed_text", None) or getattr(_e, "embed", None) or getattr(_e, "get_embedding", None)
        out = []
        for t in texts:
            r = fn(t)
            out.append(await r if hasattr(r, "__await__") else r)
        return out
    except Exception:
        return None
