"""
intelligence/embeddings.py — Generator embedding & util pgvector.

BotNesia sebelumnya menonaktifkan embedding berbasis API (lihat komentar
"Reindex embedding sudah dihapus" di main.py) karena Groq tidak menyediakan
endpoint embedding dan provider eksternal menambah biaya/latensi.

Modul ini menyediakan **embedding lokal** — deterministik, gratis, jalan
di CPU dengan numpy (sudah ter-vendor) — memakai teknik *feature hashing*
(hashing trick, mirip Vowpal Wabbit / scikit-learn HashingVectorizer):
setiap token (termasuk bigram karakter untuk menangkap typo & morfologi
Bahasa Indonesia) di-hash ke salah satu dari N bucket dengan tanda ±,
lalu divektor dijumlahkan dan dinormalisasi (L2) sehingga cosine similarity
pgvector (`<=>`) bekerja dengan baik.

Kualitasnya tentu di bawah model embedding neural, tapi cukup untuk:
  - mengelompokkan pertanyaan yang mirip (FAQ Engine),
  - mencari percakapan serupa (semantic search Conversation Memory),
  - mengelompokkan pola sales (trigger/objection).

Provider bisa diganti tanpa mengubah pemanggil: set `EMBEDDING_PROVIDER=external`
dan isi `EMBEDDING_API_URL`/`EMBEDDING_API_KEY` (format request/response mengikuti
konvensi OpenAI-compatible `{"input": [...]}`  → `{"data": [{"embedding": [...]}]}`).
Saat berganti provider, dimensi & semantik vektor berubah — buat ulang index
(`schema_intelligence.sql`) dan reproses data lama lewat nightly job.
"""
from __future__ import annotations

import hashlib
import re

import httpx
import numpy as np

from .config import cfg

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+", re.UNICODE)

_STOPWORDS_ID = {
    "yang", "dan", "atau", "di", "ke", "dari", "pada", "untuk", "dengan", "tanpa",
    "ini", "itu", "saya", "kamu", "anda", "dia", "mereka", "kami",
    "apa", "kenapa", "mengapa", "bagaimana", "kapan", "dimana",
    "tolong", "mohon", "please", "ya", "iya", "jadi", "karena", "kalau", "jika",
    "bisa", "dapat", "mau", "ingin", "akan", "sudah", "belum", "lagi", "saja",
}


def _tokens(text: str) -> list[str]:
    words = [w.lower() for w in _TOKEN_RE.findall(text or "")]
    out: list[str] = []
    for w in words:
        if len(w) < 2 or w in _STOPWORDS_ID:
            continue
        out.append(w)
        # char-trigram menangkap kemiripan morfologis ("membeli" ~ "pembelian")
        if len(w) >= 5:
            for i in range(len(w) - 2):
                out.append("#" + w[i:i + 3])
    return out


def _hash_token(token: str, dim: int) -> tuple[int, float]:
    """Hash deterministik -> (index 0..dim-1, sign +1/-1)."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    h = int.from_bytes(digest[:4], "big")
    sign_bit = digest[4] & 1
    return h % dim, (1.0 if sign_bit == 0 else -1.0)


def embed_local(text: str, dim: int | None = None) -> list[float]:
    """
    Embedding lokal deterministik via feature hashing (TF dengan sign hashing),
    dinormalisasi L2 ke unit vector. Teks kosong -> vektor nol.
    """
    dim = dim or cfg.embedding_dim
    vec = np.zeros(dim, dtype=np.float64)
    for tok in _tokens(text):
        idx, sign = _hash_token(tok, dim)
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 1e-12:
        vec = vec / norm
    return vec.tolist()


async def embed_external(text: str) -> list[float]:
    """Panggil provider embedding eksternal OpenAI-compatible (opsional)."""
    if not cfg.embedding_api_url:
        raise RuntimeError("EMBEDDING_API_URL belum diisi untuk provider 'external'.")
    headers = {"Content-Type": "application/json"}
    if cfg.embedding_api_key:
        headers["Authorization"] = f"Bearer {cfg.embedding_api_key}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            cfg.embedding_api_url,
            json={"model": cfg.embedding_model, "input": [text]},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
    return list(data["data"][0]["embedding"])


async def generate_embedding(text: str) -> list[float]:
    """
    Titik masuk tunggal yang dipakai semua agent — pilih provider sesuai
    konfigurasi tanpa mengubah pemanggil.
    """
    text = (text or "").strip()
    if not text:
        return [0.0] * cfg.embedding_dim
    if cfg.embedding_provider == "external":
        return await embed_external(text)
    return embed_local(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity dua vektor (dipakai untuk clustering in-process)."""
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
