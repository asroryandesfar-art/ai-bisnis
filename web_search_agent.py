"""
web_search_agent.py — WebSearchAgent (Real-Time Knowledge Layer).

Pencarian web umum (general web search) untuk pertanyaan yang butuh informasi
terbaru di luar berita/finansial (yang sudah ditangani `news_fetcher.py` /
`finance_fetcher.py`). Sebelumnya `tool_registry.general_web_search` ditandai
`available: False` karena belum ada API key search engine — modul ini
mengimplementasikan tool tersebut secara pluggable dan TETAP jujur (Truthfulness
Policy): jika `SEARCH_API_KEY` belum diisi di `.env`, `search()` langsung
mengembalikan `{"success": False, "skipped": True, ...}` tanpa panggilan
network, supaya pipeline tetap berjalan tanpa fitur ini sampai key ditambahkan.

Provider default: Tavily (https://tavily.com) — REST API sederhana, free tier.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

_TIMEOUT = 10.0


async def search(query: str, api_key: str, provider: str = "tavily", max_results: int = 5) -> dict:
    """Cari di web menggunakan provider yang dikonfigurasi.

    Returns dict:
      - tidak terkonfigurasi: {"success": False, "skipped": True, "reason": "..."}
      - error HTTP/koneksi:   {"success": False, "error": "..."}
      - sukses: {"success": True, "provider": ..., "query": ..., "results": [...]}
        tiap item: {"title", "url", "snippet", "score", "published_date"?}
    """
    if not (api_key or "").strip():
        return {
            "success": False,
            "skipped": True,
            "reason": "SEARCH_API_KEY belum dikonfigurasi — general web search tidak aktif.",
        }

    provider = (provider or "tavily").strip().lower()
    if provider == "tavily":
        return await _search_tavily(query, api_key, max_results)

    return {
        "success": False,
        "skipped": True,
        "reason": f"Provider web search '{provider}' belum didukung.",
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
