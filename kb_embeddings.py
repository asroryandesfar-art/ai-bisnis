"""kb_embeddings.py — provider embedding semantik sungguhan untuk Knowledge Base.

Sebelumnya KB hybrid search (main.py::_text_to_embedding) cuma memakai feature
hashing lokal (SHA1 token -> bucket) -- cukup untuk pengelompokan kasar tapi
tidak menangkap kemiripan makna ("kasir" vs "petugas pembayaran").

Modul ini menambah provider OpenAI text-embedding-3-small (pakai
OPENAI_API_KEY yang sama dengan image_providers.py) sebagai opsional, otomatis
aktif begitu key terisi -- mengikuti pola graceful-degradation yang sama
dengan image_providers.py/web_search_agent.py. Tanpa key, KB tetap jalan
seperti sebelumnya (fallback ke hash lokal, dipanggil oleh main.py).

PENTING: kalau OPENAI_API_KEY baru ditambahkan ke env yang sudah punya chunk
ter-index, embedding lama (hash) dan baru (OpenAI) ada di vector space yang
berbeda walau dimensinya sama -- main.py membandingkan `model` tag tiap chunk
supaya tidak menghitung cosine similarity lintas-provider yang tidak valid,
tapi chunk lama tetap perlu di-reindex (scripts/reindex_kb_embeddings.py)
supaya skor embedding-nya ikut aktif lagi (bukan cuma keyword-only).
"""
from __future__ import annotations

import httpx

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDING_TAG = f"openai:{OPENAI_EMBEDDING_MODEL}"


async def generate_openai_embedding(text: str, api_key: str, dim: int) -> list[float] | None:
    """Panggil OpenAI Embeddings API. None kalau key kosong/teks kosong/gagal --
    caller fallback ke hash embedding lokal."""
    api_key = (api_key or "").strip()
    text = (text or "").strip()
    if not api_key or not text:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": OPENAI_EMBEDDING_MODEL, "input": text, "dimensions": dim},
            )
            resp.raise_for_status()
            data = resp.json()
        return list(data["data"][0]["embedding"])
    except Exception:
        return None
