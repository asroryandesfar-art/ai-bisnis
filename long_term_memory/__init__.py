"""long_term_memory — memori jangka-panjang yang di-RETRIEVE saat reasoning (P1-B).

Menutup temuan audit "memory write-only": memori semantik/episodik/task disimpan
dengan embedding (pgvector) & diambil berdasar kemiripan makna untuk memperkaya
konteks reasoning.

    from long_term_memory import SemanticMemory
    mem = SemanticMemory()
    await mem.store(pool, org_id=org, content="pelanggan suka warna biru", subject=user_id)
    hits = await mem.retrieve(pool, org_id=org, query="preferensi warna", subject=user_id, k=3)

Embedding via `kb_embeddings.generate_local_embedding` (lokal/gratis, 384-dim) atau
`embed_fn` injeksi. Graceful degrade tanpa pgvector/model. Additive; konsumen
mengadopsi di belakang flag `is_enabled("long_term_memory")`. Lihat ADR-0006.
"""
from long_term_memory.schema import ensure_memory_schema, MEMORY_SCHEMA_SQL, EMBED_DIM
from long_term_memory.store import SemanticMemory

__all__ = ["ensure_memory_schema", "MEMORY_SCHEMA_SQL", "EMBED_DIM", "SemanticMemory"]
