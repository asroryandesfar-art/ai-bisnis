# ADR-0006 — Long-Term Memory (semantic, pgvector)

- **Status:** Accepted — P1-B.1 (semantic store) selesai; episodic/task + retrieval-wiring menyusul
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 2 (Cognitive Core), item **P1-B** — gap audit "memory write-only"
- **Terkait:** ADR-0005 (cognitive loop — konsumen retrieval), memory_agent (conversation/facts existing)

## Konteks
Audit: memori semantik/episodik "hanya ditulis, tak di-retrieve saat reasoning".
Yang ada baru conversation-summary + user-facts (key-value) di `memory_agent`;
lapisan **semantik vektor** cuma komentar TODO Pinecone. Reasoning tak bisa
mengambil memori relevan berdasar MAKNA.

## Keputusan
Modul mandiri `long_term_memory` + tabel `agent_memories` dengan kolom **pgvector**
(`vector(384)`, cocok model lokal all-MiniLM). `SemanticMemory.store/retrieve/
summarize`: `store` meng-embed konten & simpan; `retrieve` meng-embed query &
ambil top-k via kemiripan cosine (`embedding <=> $q`). Embedding via `embed_fn`
yang DISUNTIKKAN — default lazy `kb_embeddings.generate_local_embedding` (lokal,
gratis, tanpa API); test menyuntik fake deterministik. Scope: semantic/episodic/
task/reasoning; `subject` (user/conversation/agent) sebagai partisi.

## Alternatif
1. **Pinecone / vector-DB eksternal.** Ditolak: biaya/SaaS/lock-in; pgvector sudah tersedia di Postgres (terverifikasi).
2. **Embedding disimpan JSONB + cosine di Python.** Dipertahankan sebagai FALLBACK degrade; pgvector jadi jalur utama (indeks ANN, skalabel).
3. **pgvector + embed_fn injeksi (DIPILIH).** Reuse infra & embedder lokal; test cepat; degrade jujur.

## Konsekuensi
**Positif:** reasoning bisa mengambil memori relevan-makna lintas-sesi; interface seragam; skalabel (ANN index HNSW/IVFFlat).
**Batasan/mitigasi:** butuh extension `vector` (di-`CREATE EXTENSION IF NOT EXISTS`, wrap try — bila tak ada, degrade non-vektor); model embedding lokal ~470MB diunduh sekali saat pertama (lazy) — test pakai fake; dimensi terkunci 384 (embedder lokal).

## Rencana
- **P1-B.1 (selesai):** schema `agent_memories` (pgvector) + `SemanticMemory` (store/retrieve/summarize) + degrade + 5 test vs Postgres nyata. Wired ke `ensure_optional_schema` (try). Zero konsumen.
- **P1-B.2:** episodic/task memory (rekam event TaskFinished/aksi → retrieve pengalaman relevan).
- **P1-B.3:** wire retrieval ke reasoning — `enrich_context` (chat) & cognitive loop, gate `is_enabled("long_term_memory", org_id)` (default OFF).
- **P1-B.4:** fasad `AgentMemory` menyatukan conversation+working+semantic+episodic+task+reasoning.

## Rollback
Konsumen di belakang flag → OFF = tak ada retrieval baru. Tabel additive; bila pgvector absen, ensure di-skip (log warning), SemanticMemory degrade aman.
