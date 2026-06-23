"""
web_search_agent.py — WebSearchAgent (Real-Time Knowledge Layer).

Pencarian web umum (general web search) untuk pertanyaan yang butuh informasi
terbaru di luar berita/finansial (yang sudah ditangani `news_fetcher.py` /
`finance_fetcher.py`). Sebelumnya `tool_registry.general_web_search` ditandai
`available: False` karena belum ada API key search engine — modul ini
mengimplementasikan tool tersebut secara pluggable dan TETAP jujur (Truthfulness
Policy): jika tidak ada provider yang terkonfigurasi sama sekali, `search()`
langsung mengembalikan `{"success": False, "skipped": True, ...}` tanpa
panggilan network, supaya pipeline tetap berjalan tanpa fitur ini.

Provider utama: SearXNG (self-hosted/instance pihak ketiga, gratis, tanpa API
key) via `SEARXNG_URL`. Tavily (https://tavily.com, berbayar/free-tier
terbatas) jadi CADANGAN — dipanggil otomatis hanya kalau SearXNG tidak
dikonfigurasi atau panggilannya gagal (network error/HTTP error/JSON kosong).
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

_TIMEOUT = 10.0


async def search(
    query: str,
    *,
    searxng_url: str = "",
    tavily_api_key: str = "",
    max_results: int = 5,
) -> dict:
    """Cari di web. Urutan provider: SearXNG dulu, Tavily sebagai cadangan.

    Returns dict:
      - tidak ada provider terkonfigurasi: {"success": False, "skipped": True, "reason": "..."}
      - semua provider yang terkonfigurasi gagal: {"success": False, "error": "..."}
      - sukses: {"success": True, "provider": "searxng"|"tavily", "query": ..., "results": [...]}
        tiap item: {"title", "url", "snippet", "score", "published_date"?}
        Kalau SearXNG gagal lalu Tavily berhasil, hasil sukses juga membawa
        "fallback_from": "searxng" supaya pemanggil tahu itu bukan jalur utama.
    """
    searxng_url = (searxng_url or "").strip()
    tavily_api_key = (tavily_api_key or "").strip()

    if not searxng_url and not tavily_api_key:
        return {
            "success": False,
            "skipped": True,
            "reason": "SEARXNG_URL/SEARCH_API_KEY belum dikonfigurasi — general web search tidak aktif.",
        }

    last_error = None
    tried_searxng = False

    if searxng_url:
        result = await _search_searxng(query, searxng_url, max_results)
        if result.get("success"):
            return result
        last_error = result.get("error") or result.get("reason")
        tried_searxng = True

    if tavily_api_key:
        result = await _search_tavily(query, tavily_api_key, max_results)
        if result.get("success"):
            if tried_searxng:
                result["fallback_from"] = "searxng"
            return result
        last_error = result.get("error") or last_error

    return {"success": False, "error": last_error or "Semua provider web search gagal."}


async def _search_searxng(query: str, base_url: str, max_results: int) -> dict:
    base_url = base_url.rstrip("/")
    params = {"q": query, "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{base_url}/search", params=params)
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}

    if r.status_code >= 400:
        return {"success": False, "error": (r.text or "")[:300]}

    try:
        data = r.json()
    except Exception:
        return {
            "success": False,
            "error": "SearXNG tidak mengembalikan JSON — pastikan format 'json' "
            "diaktifkan di settings.yml instance ini.",
        }

    raw_results = data.get("results") or []
    results = []
    for item in raw_results[: max(1, min(10, max_results))]:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": str(item.get("content") or "").strip(),
            "score": item.get("score"),
            "published_date": item.get("publishedDate"),
        })

    return {
        "success": True,
        "provider": "searxng",
        "query": query,
        "results": results,
    }


async def _search_tavily(query: str, api_key: str, max_results: int) -> dict:
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max(1, min(10, max_results)),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}

    if r.status_code >= 400:
        return {"success": False, "error": r.text[:300]}

    data = r.json()
    raw_results = data.get("results") or []
    results = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": str(item.get("content") or "").strip(),
            "score": item.get("score"),
            "published_date": item.get("published_date"),
        })

    return {
        "success": True,
        "provider": "tavily",
        "query": query,
        "results": results,
    }


def rank_sources(results: list) -> list:
    """Source Ranking: urutkan berdasarkan score (desc), dedupe per domain."""
    if not results:
        return []

    def _score(item: dict) -> float:
        value = item.get("score")
        return float(value) if isinstance(value, (int, float)) else 0.0

    ordered = sorted(results, key=_score, reverse=True)

    seen_domains: set[str] = set()
    ranked: list[dict] = []
    for item in ordered:
        domain = urlparse(item.get("url") or "").netloc.lower()
        if domain and domain in seen_domains:
            continue
        if domain:
            seen_domains.add(domain)
        ranked.append(item)
    return ranked


WEB_SEARCH_BLOCK = """## Web Search (sumber pihak ketiga)
Hasil pencarian web di atas berasal dari mesin pencari pihak ketiga, BUKAN data
BotNesia sendiri. Terapkan Source Verification:
- Sebutkan sumbernya (judul/URL) saat memakai informasi ini.
- Jika ada tanggal publikasi, sebutkan freshness-nya.
- Jika beberapa sumber saling bertentangan, jangan diam-diam memilih salah
  satu — jelaskan perbedaannya secara jujur.
- Jangan mengarang detail yang tidak ada di hasil pencarian."""


def format_web_search_context(result: dict, query: str) -> str:
    """Format hasil `search()` (setelah `rank_sources`) menjadi blok konteks."""
    if not result or not result.get("success"):
        return ""

    ranked = rank_sources(result.get("results") or [])
    if not ranked:
        return ""

    lines = [f"## Hasil pencarian web untuk: \"{query}\""]
    for item in ranked:
        title = item.get("title") or item.get("url") or "(tanpa judul)"
        url = item.get("url") or ""
        snippet = (item.get("snippet") or "").strip()
        published = item.get("published_date")
        line = f"- {title} ({url})"
        if published:
            line += f" — dipublikasikan: {published}"
        if snippet:
            line += f"\n  {snippet[:400]}"
        lines.append(line)
    return "\n".join(lines)
