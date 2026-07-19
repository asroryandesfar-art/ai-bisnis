"""Dynamic DeepSeek model discovery + capability ranking.

Kebijakan: DeepSeek = otak utama BotNesia; SELALU pakai model DeepSeek paling
cerdas yang tersedia. JANGAN hardcode nama model — deteksi dinamis dari
/models, ranking berdasarkan kapabilitas, pilih otomatis. Model flagship baru
(mis. deepseek-v5-*) otomatis dipilih tanpa ubah kode.

Prioritas: Reasoning Quality > Accuracy > Reliability > Speed > Cost.

Ranking heuristik (API tidak memberi skor kecerdasan):
  skor = versi*100 (+ versi-reasoner*10) + bonus keyword kapabilitas.
Model "fast/flash/lite" → tier cepat (simple); "pro/reasoner/max" → tier cerdas
(complex). Karena semua diskor by versi, model versi lebih tinggi menang.
"""
import logging
import os
import re
import time
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_MODELS_URL = os.getenv("DEEPSEEK_MODELS_URL", "https://api.deepseek.com/models")
_TTL = int(os.getenv("DEEPSEEK_DISCOVERY_TTL", "3600"))

# Keyword → bonus kapabilitas. Reasoning/pro tinggi; fast/lite rendah.
_CAPABILITY_KW: dict[str, int] = {
    "reasoner": 55, "reasoning": 55, "thinking": 52, "think": 50,
    "pro": 50, "ultra": 50, "max": 46, "advanced": 44, "plus": 36,
    "chat": 26, "flash": 16, "fast": 12, "turbo": 12, "lite": 6, "mini": 5, "nano": 3,
}
# Sinyal model CEPAT (kandidat tier 'simple').
_FAST_KW = ("flash", "fast", "lite", "mini", "nano", "turbo", "instant", "8b", "small")

# Fallback aman bila discovery gagal & tak ada env override.
FALLBACK_SIMPLE = "deepseek-chat"
FALLBACK_COMPLEX = "deepseek-reasoner"

_cache: dict = {"models": [], "ts": 0.0}


def _version_score(name: str) -> float:
    score = 0.0
    m = re.search(r"v(\d+(?:\.\d+)?)", name)          # deepseek-v4-pro → 4
    if m:
        score += float(m.group(1)) * 100
    r = re.search(r"\br(\d+)\b", name)                # reasoner r1/r2 → +versi
    if r:
        score += int(r.group(1)) * 10
    return score


def capability_score(name: str) -> float:
    """Skor kapabilitas relatif. Makin tinggi = makin cerdas/canggih."""
    n = (name or "").lower()
    score = _version_score(n)
    for kw, pts in _CAPABILITY_KW.items():
        if kw in n:
            score += pts
    return score


def is_fast_model(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _FAST_KW)


def rank_models(models: list[str]) -> list[str]:
    """Urut model paling CERDAS → paling ringan."""
    return sorted([m for m in models if m], key=capability_score, reverse=True)


def select_tiers(models: list[str]) -> dict:
    """Petakan model tersedia ke {simple, medium, complex}.

    complex = paling cerdas; simple = paling cepat; medium = penyeimbang
    (mengutamakan kualitas — Reasoning Quality > Cost)."""
    ranked = rank_models(models)
    if not ranked:
        return {}
    complex_m = ranked[0]
    fast = [m for m in models if is_fast_model(m)]
    simple_m = rank_models(fast)[-1] if fast else ranked[-1]   # tercepat yg tersedia
    if len(ranked) >= 3:
        medium_m = ranked[1]
    else:
        medium_m = complex_m                                   # prioritas kualitas
    return {"simple": simple_m, "medium": medium_m, "complex": complex_m}


async def discover_models(api_key: str, *, force: bool = False,
                          fetch: Callable[[str], Awaitable[list[str]]] | None = None) -> list[str]:
    """Ambil daftar model DeepSeek yang tersedia (di-cache TTL). `fetch` bisa
    diinjeksi untuk test. Gagal → kembalikan cache lama (atau [])."""
    now = time.time()
    if not force and _cache["models"] and (now - _cache["ts"]) < _TTL:
        return _cache["models"]
    if not api_key:
        return _cache["models"]
    try:
        if fetch is not None:
            models = await fetch(api_key)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(DEEPSEEK_MODELS_URL,
                                        headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                models = [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
        if models:
            _cache["models"] = models
            _cache["ts"] = now
            logger.info("deepseek discovery: %s", models)
            return models
    except Exception as exc:
        logger.warning("deepseek discovery gagal (pakai cache/fallback): %s", exc)
    return _cache["models"]


def cached_models() -> list[str]:
    return list(_cache["models"])


def reset_cache() -> None:
    _cache["models"] = []
    _cache["ts"] = 0.0
