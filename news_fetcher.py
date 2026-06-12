from __future__ import annotations

import asyncio
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str | None = None
    summary: str | None = None
    source_url: str | None = None


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _source_from_url(u: str) -> str:
    try:
        host = urllib.parse.urlparse(u).netloc.strip().lower()
    except Exception:
        host = ""
    return f"Source ({host})" if host else "Source"


def _extract_html_title(html: str) -> str:
    h = html or ""
    patterns = [
        r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'(?is)<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\'](.*?)["\']',
        r"(?is)<title[^>]*>(.*?)</title>",
        r"(?is)<h1[^>]*>(.*?)</h1>",
    ]
    for pat in patterns:
        m = re.search(pat, h)
        if m:
            title = _clean_text(_strip_html(m.group(1)))
            if title:
                return title[:300]
    return ""


def _parse_rss(xml_text: str, source: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    root = ET.fromstring(xml_text)
    for it in root.findall(".//item"):
        title = _strip_html((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip() or None
        desc = _strip_html((it.findtext("description") or "").strip()) or None
        source_el = it.find("source")
        publisher = _strip_html(((source_el.text if source_el is not None else "") or "").strip()) or source
        publisher_url = ((source_el.get("url") if source_el is not None else "") or "").strip() or None
        if title and link:
            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    source=publisher,
                    published=pub,
                    summary=desc,
                    source_url=publisher_url,
                )
            )
    if items:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns) or root.findall(".//entry"):
        title = _strip_html((entry.findtext("atom:title", namespaces=ns) or entry.findtext("title") or "").strip())
        pub = (
            (entry.findtext("atom:updated", namespaces=ns) or entry.findtext("updated") or "").strip()
            or (entry.findtext("atom:published", namespaces=ns) or entry.findtext("published") or "").strip()
            or None
        )
        desc = (
            _strip_html(
                (
                    entry.findtext("atom:summary", namespaces=ns)
                    or entry.findtext("summary")
                    or entry.findtext("atom:content", namespaces=ns)
                    or entry.findtext("content")
                    or ""
                ).strip()
            )
            or None
        )
        link = ""
        link_el = entry.find("atom:link[@rel='alternate']", ns) or entry.find("atom:link", ns) or entry.find("link")
        if link_el is not None:
            link = (link_el.get("href") or (link_el.text or "")).strip()
        if title and link:
            items.append(NewsItem(title=title, link=link, source=source, published=pub, summary=desc))
    return items


async def fetch_rss(url: str, source: str, timeout_s: float = 8.0) -> list[NewsItem]:
    async with httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": "BotNesia/1.0"}) as client:
        r = await client.get(url)
        r.raise_for_status()
        return _parse_rss(r.text, source)


async def fetch_source_url(url: str, timeout_s: float = 8.0) -> list[NewsItem]:
    source = _source_from_url(url)
    headers = {"User-Agent": "BotNesia/1.0"}
    async with httpx.AsyncClient(timeout=timeout_s, headers=headers, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        final_url = str(r.url)
        content_type = (r.headers.get("content-type") or "").lower()
        body = r.text or ""

    if any(k in content_type for k in ("xml", "rss", "atom")):
        return _parse_rss(body, source)

    stripped = body.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<rss") or "<feed" in stripped[:500]:
        try:
            items = _parse_rss(body, source)
            if items:
                return items
        except Exception:
            pass

    title = _extract_html_title(body)
    summary = _extract_readable_text(body, max_chars=600)
    if title:
        return [
            NewsItem(
                title=title,
                link=final_url,
                source=source,
                published=None,
                summary=summary or None,
            )
        ]
    return []


_QUERY_FILLER = {
    "berita", "news", "terbaru", "terkini", "hari", "ini", "update",
    "headline", "artikel", "ringkas", "rangkum", "ringkasan", "summary",
    "tolong", "kasih", "berikan", "cari", "carikan", "tentang", "mengenai",
    "dan", "yang", "untuk", "dengan", "solusi", "solusinya", "saya", "aku",
}


def _is_query_term(word: str) -> bool:
    return (len(word) >= 3 or word in {"ai"}) and word not in _QUERY_FILLER


def _tok(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
    return {w for w in words if _is_query_term(w)}


def _search_phrase(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
    useful = [w for w in words if _is_query_term(w)]
    return " ".join(useful) or (text or "").strip()


def _pub_dt(pub: str | None) -> datetime | None:
    if not pub:
        return None
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def search_news(query: str, limit: int = 6, *, rss_urls: list[str] | None = None) -> list[NewsItem]:
    """
    Lightweight news search using public RSS feeds (Google News RSS).
    No API key required. Results depend on network access.
    """
    q_raw = (query or "").strip()
    q = _tok(q_raw)
    search_phrase = _search_phrase(q_raw)
    q_enc = urllib.parse.quote_plus(search_phrase) if search_phrase else ""

    feeds: list[tuple[str, str]] = [
        (
            "Google News (ID) Search",
            f"https://news.google.com/rss/search?q={q_enc}&hl=id&gl=ID&ceid=ID:id"
            if q_enc
            else "https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id",
        ),
        ("Google News (ID) Top", "https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id"),
        (
            "Google News (ID) Business",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=id&gl=ID&ceid=ID:id",
        ),
        (
            "Google News (ID) Tech",
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=id&gl=ID&ceid=ID:id",
        ),
        (
            "Google News (World) Search",
            f"https://news.google.com/rss/search?q={q_enc}&hl=en-US&gl=US&ceid=US:en"
            if q_enc
            else "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        ),
        ("Google News (World) Top", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
    ]

    # Custom RSS feeds (publisher-direct). If provided, we prioritize them in ranking.
    # Note: We still keep Google News feeds as fallback in case custom feeds return 0 items.
    # This keeps the system resilient under network blocks or feed downtime.
    custom_urls: list[str] = []

    async def _fetch(src: str, url: str) -> list[NewsItem]:
        try:
            return await fetch_rss(url, src)
        except Exception:
            return []

    async def _fetch_custom(url: str) -> list[NewsItem]:
        try:
            return await fetch_source_url(url)
        except Exception:
            return []

    if rss_urls:
        seen: set[str] = set()
        for u in rss_urls:
            uu = (u or "").strip()
            if not uu or uu in seen:
                continue
            seen.add(uu)
            custom_urls.append(uu)

    # Fetch custom feeds first (so later ranking can prefer them).
    results = await asyncio.gather(
        *([_fetch_custom(url) for url in custom_urls] + [_fetch(src, url) for src, url in feeds])
    )

    has_url_in_query = ("http://" in q_raw) or ("https://" in q_raw)
    custom_links = {it.link for group in results[: len(custom_urls)] for it in group}

    ranked: list[tuple[int, datetime | None, NewsItem]] = []
    for items in results:
        for it in items:
            title_tokens = _tok(it.title)
            summary_tokens = _tok(it.summary or "")
            matched_tokens = title_tokens | summary_tokens
            score = len(title_tokens & q) * 3 + len(summary_tokens & q)
            is_custom = it.link in custom_links
            # Istilah inti pendek seperti "AI" wajib benar-benar muncul; tanpa ini
            # artikel bisnis umum mudah lolos hanya karena cocok pada kata "bisnis".
            if "ai" in q and "ai" not in matched_tokens and not has_url_in_query:
                continue
            if q and score <= 0 and not has_url_in_query:
                continue
            # Prefer custom publisher URLs/feeds if scores are tied.
            custom_boost = 2 if is_custom else (1 if it.source.startswith("Source") and not it.source.startswith("Google News") else 0)
            ranked.append((score * 10 + custom_boost, _pub_dt(it.published), it))

    ranked.sort(
        key=lambda t: (
            t[0],
            t[1] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    deduped: list[NewsItem] = []
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    for _, _, it in ranked:
        key_link = (it.link or "").strip()
        key_title = (it.title or "").strip().lower()
        if key_link and key_link in seen_links:
            continue
        if key_title and key_title in seen_titles:
            continue
        if key_link:
            seen_links.add(key_link)
        if key_title:
            seen_titles.add(key_title)
        deduped.append(it)
        if len(deduped) >= limit:
            break
    return deduped


def _clean_text(text: str) -> str:
    t = (text or "").replace("\u00a0", " ")
    t = _WS_RE.sub(" ", t).strip()
    return t


def _extract_readable_text(html: str, max_chars: int = 4000) -> str:
    """
    Tiny HTML-to-text extractor (best-effort).
    """
    if not html:
        return ""
    h = html
    h = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", h)
    h = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", h)
    h = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", h)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", h)
    if m:
        h = m.group(1)
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)
    texts: list[str] = []
    for p in paras:
        t = _clean_text(_strip_html(p))
        if len(t) >= 60:
            texts.append(t)
    if not texts:
        t = _clean_text(_strip_html(h))
        # Heuristic boilerplate trimming (common on news sites / reader proxies).
        low = t.lower()
        for marker in [
            "what to know:",
            "key points:",
            "key takeaways:",
            "highlights:",
            "summary:",
        ]:
            idx = low.find(marker)
            if idx >= 0:
                t = t[idx:].strip()
                break
        # If we still have obvious nav junk at the start, drop the first chunk.
        if t.startswith(("Search/", "Search ", "Home ", "Menu ")):
            t = t[200:].strip() if len(t) > 260 else t
        return t[:max_chars].strip()
    out = "\n".join(texts)
    # Apply the same boilerplate trimming to paragraph-extracted text.
    low_out = out.lower()
    for marker in [
        "what to know:",
        "key points:",
        "key takeaways:",
        "highlights:",
        "summary:",
    ]:
        idx = low_out.find(marker)
        if idx >= 0:
            out = out[idx:].strip()
            break
    if out.startswith(("Search/", "Search ", "Home ", "Menu ")):
        out = out[200:].strip() if len(out) > 260 else out
    return out[:max_chars].strip()


def _split_sentences(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    # Split by newline or punctuation boundaries (very rough, but ok for extractive).
    parts = re.split(r"(?:\n+|(?<=[.!?])\s+)", t)
    out: list[str] = []
    for p in parts:
        s = (p or "").strip(" \t\r-•")
        if len(s) >= 40:
            out.append(s)
    return out


def extract_key_quotes(article_text: str, query: str, max_quotes: int = 5) -> list[str]:
    q = _tok(query)
    sents = _split_sentences(article_text)
    if not sents or not q:
        out = sents[: max(1, min(max_quotes, 3))]
        return [s[:280].rstrip() for s in out]

    scored: list[tuple[int, int, str]] = []
    for s in sents:
        sl = s.lower()
        if "share this article" in sl or sl.startswith(("search/", "search ")):
            continue
        st = _tok(s)
        score = len(st & q)
        scored.append((score, len(s), s))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    quotes = [s[:280].rstrip() for score, _, s in scored if score > 0][: max(1, max_quotes)]
    if quotes:
        return quotes
    out = sents[: max(1, min(max_quotes, 3))]
    return [s[:280].rstrip() for s in out]


async def fetch_article_text(url: str, timeout_s: float = 8.0, max_chars: int = 2000) -> tuple[str, str]:
    """
    Returns (final_url, extracted_text). Best-effort: may return empty text.
    """
    u = (url or "").strip()
    if not u:
        return "", ""
    headers = {"User-Agent": "Mozilla/5.0 (BotNesia/1.0)"}
    def _is_google_news(link: str) -> bool:
        return "news.google.com/" in (link or "")

    def _pick_original_from_google_news_html(html: str) -> str:
        # Heuristic: find first non-google absolute URL in the page
        urls = re.findall(r"https?://[^\\s\"'<>]+", html or "")
        for cand in urls:
            c = cand.strip()
            if not c:
                continue
            if "news.google.com" in c:
                continue
            if "google.com" in c:
                continue
            # skip obvious googleusercontent proxy too
            if "gstatic.com" in c or "googleapis.com" in c:
                continue
            return c
        return ""

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True, headers=headers) as client:
        r = await client.get(u)
        r.raise_for_status()
        final_url = str(r.url)
        html = r.text

        # If this is a Google News wrapper URL, attempt to resolve original publisher URL first.
        if _is_google_news(final_url):
            try:
                # r.jina.ai often exposes the original links more clearly
                proxy_url = "https://r.jina.ai/" + final_url
                r_g = await client.get(proxy_url)
                r_g.raise_for_status()
                orig = _pick_original_from_google_news_html(r_g.text)
                if orig:
                    r_o = await client.get(orig)
                    r_o.raise_for_status()
                    final_url = str(r_o.url)
                    html = r_o.text
            except Exception:
                pass

        text = _extract_readable_text(html, max_chars=max_chars)

        # Fallback: some sites block bots / heavy JS. Try jina.ai reader proxy on final_url.
        if len(text) < 200 and final_url.startswith(("http://", "https://")):
            try:
                proxy_url = "https://r.jina.ai/" + final_url
                r2 = await client.get(proxy_url)
                r2.raise_for_status()
                text2 = _extract_readable_text(r2.text, max_chars=max_chars)
                if len(text2) > len(text):
                    text = text2
            except Exception:
                pass

        return final_url, text


async def build_news_context(
    query: str,
    limit: int = 6,
    *,
    include_bodies: bool = True,
    fetch_timeout_s: float = 8.0,
    max_body_chars: int = 1400,
    max_concurrency: int = 3,
    rss_urls: list[str] | None = None,
) -> str:
    items = await search_news(query, limit=limit, rss_urls=rss_urls)
    if not items:
        return ""
    now = datetime.now(timezone.utc).isoformat()
    lines = [f"Waktu server (UTC): {now}", "Hasil berita (ringkas):"]

    if not include_bodies:
        for idx, it in enumerate(items, 1):
            pub = f" | Terbit: {it.published}" if it.published else ""
            lines.append(f"- Berita {idx}: {it.title}")
            lines.append(f"  Media/feed: {it.source}{pub}")
            lines.append(f"  URL sumber: {it.source_url or it.link}")
            if it.summary:
                lines.append(f"  Ringkasan RSS: {it.summary}")
        return "\n".join(lines).strip()

    sem = asyncio.Semaphore(max(1, int(max_concurrency or 3)))

    async def _one(it: NewsItem) -> tuple[NewsItem, str, str]:
        async with sem:
            try:
                final_url, body = await fetch_article_text(
                    it.link,
                    timeout_s=fetch_timeout_s,
                    max_chars=max_body_chars,
                )
                return it, final_url, body
            except Exception:
                return it, "", ""

    fetched = await asyncio.gather(*[_one(it) for it in items])
    for idx, (it, final_url, body) in enumerate(fetched, 1):
        pub = f" | Terbit: {it.published}" if it.published else ""
        resolved_url = final_url or it.link
        source_url = it.source_url if "news.google.com/" in resolved_url and it.source_url else resolved_url
        lines.append(f"- Berita {idx}: {it.title}")
        lines.append(f"  Media/feed: {it.source}{pub}")
        lines.append(f"  URL sumber: {source_url}")
        if body:
            lines.append(f"  Teks artikel (ringkas): {body}")
            quotes = extract_key_quotes(body, query, max_quotes=5)
            if quotes:
                lines.append("  Kutipan relevan (wajib jadi dasar jawaban):")
                for q in quotes:
                    lines.append(f"  - \"{q}\"")
        else:
            if it.summary:
                lines.append(f"  Ringkasan dari RSS: {it.summary}")
            lines.append("  Teks artikel: (tidak berhasil diambil — kemungkinan diblokir / butuh JS).")
    return "\n".join(lines).strip()
