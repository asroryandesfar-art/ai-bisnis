"""kb_embeddings.py — provider embedding semantik sungguhan untuk Knowledge Base.

Sebelumnya KB hybrid search (main.py::_text_to_embedding) cuma memakai feature
hashing lokal (SHA1 token -> bucket) -- cukup untuk pengelompokan kasar tapi
tidak menangkap kemiripan makna ("kasir" vs "petugas pembayaran").

Dua provider embedding semantik sungguhan, keduanya opsional dan graceful-
degradation seperti image_providers.py/web_search_agent.py:

1. **Lokal** (`generate_local_embedding`, default/prioritas utama) -- pakai
   `sentence-transformers` (model multilingual, jalan di CPU, GRATIS, tanpa
   API key, tanpa data keluar server). Model di-load sekali (lazy singleton)
   lalu dipakai berkali-kali; inference dijalankan di thread executor supaya
   tidak blocking event loop asyncio.
2. **OpenAI** text-embedding-3-small (pakai OPENAI_API_KEY yang sama dengan
   image_providers.py) -- cadangan kalau provider lokal gagal di-import/load
   (mis. dependency belum terinstall) DAN key OpenAI tersedia.

PENTING: tiap provider punya vector space berbeda (juga dimensi berbeda --
lokal 384, OpenAI sesuai `dim` yang diminta) walau sama-sama "embedding
semantik". main.py membandingkan `model` tag tiap chunk supaya tidak
menghitung cosine similarity lintas-provider yang tidak valid; chunk lama
(hash atau provider lain) perlu di-reindex (scripts/reindex_kb_embeddings.py)
supaya skor embedding-nya ikut aktif lagi (bukan cuma keyword-only).
"""
from __future__ import annotations

import asyncio

import httpx

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDING_TAG = f"openai:{OPENAI_EMBEDDING_MODEL}"

# Model multilingual ringan (~470MB), paham Bahasa Indonesia + 50+ bahasa lain,
# output 384 dimensi. Di-load sekali secara lazy (bukan saat import modul ini)
# supaya start-up server tidak ikut nunggu download/load model.
LOCAL_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_EMBEDDING_TAG = f"local:{LOCAL_EMBEDDING_MODEL}"

_local_model = None  # lazy singleton, diisi oleh _load_local_model()
_local_model_load_failed = False


def _load_local_model():
    """Load (sekali) lalu cache instance SentenceTransformer. None kalau
    dependency belum terinstall atau gagal load -- caller fallback ke
    provider lain."""
    global _local_model, _local_model_load_failed
    if _local_model is not None or _local_model_load_failed:
        return _local_model
    try:
        from sentence_transformers import SentenceTransformer
        _local_model = SentenceTransformer(LOCAL_EMBEDDING_MODEL)
    except Exception:
        _local_model_load_failed = True
        return None
    return _local_model


def _encode_local_sync(text: str) -> list[float] | None:
    model = _load_local_model()
    if model is None:
        return None
    vec = model.encode(text, normalize_embeddings=True)
    return [float(x) for x in vec]


async def generate_local_embedding(text: str) -> list[float] | None:
    """Embedding semantik lokal (sentence-transformers, CPU, gratis). None
    kalau dependency belum terinstall/gagal load/teks kosong -- caller
    fallback ke provider lain (OpenAI) atau hash."""
    text = (text or "").strip()
    if not text:
        return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _encode_local_sync, text)


async def generate_openai_embedding(text: str, api_key: str, dim: int) -> list[float] | None:
    """Panggil OpenAI Embeddings API. None kalau key kosong/teks kosong/gagal --
    caller fallback ke provider lain."""
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
