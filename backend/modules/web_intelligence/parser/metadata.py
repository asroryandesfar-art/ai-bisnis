"""Metadata extraction: title, description, canonical, lang, author, OpenGraph."""
from __future__ import annotations

from urllib.parse import urljoin

from .html import make_soup
from ..security.sanitizer import sanitize_text


def _meta(soup, *, name=None, prop=None) -> str | None:
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return sanitize_text(tag["content"], max_len=1000)
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return sanitize_text(tag["content"], max_len=1000)
    return None


def extract_metadata(html: str, *, base_url: str = "") -> dict:
    """Return a metadata dict (empty values omitted-as-None, never raises)."""
    soup = make_soup(html)

    title = None
    if soup.title and soup.title.string:
        title = sanitize_text(soup.title.string, max_len=500)
    title = _meta(soup, prop="og:title") or title
    if not title and soup.h1:
        title = sanitize_text(soup.h1.get_text(), max_len=500)

    description = _meta(soup, name="description") or _meta(soup, prop="og:description")

    canonical = None
    link = soup.find("link", attrs={"rel": lambda v: v and "canonical" in (v if isinstance(v, list) else [v])})
    if link and link.get("href"):
        canonical = urljoin(base_url, link["href"]) if base_url else link["href"]

    lang = None
    if soup.html and soup.html.get("lang"):
        lang = soup.html["lang"].strip()[:16]

    return {
        "title": title,
        "description": description,
        "canonical_url": canonical,
        "language": lang,
        "author": _meta(soup, name="author") or _meta(soup, prop="article:author"),
        "published_at": _meta(soup, prop="article:published_time") or _meta(soup, name="date"),
        "site_name": _meta(soup, prop="og:site_name"),
        "og_image": _meta(soup, prop="og:image"),
        "og_type": _meta(soup, prop="og:type"),
        "keywords": _meta(soup, name="keywords"),
    }


def extract_links(html: str, *, base_url: str) -> list[str]:
    """Absolute http(s) links found in the page (deduped, dangerous schemes dropped)."""
    from ..security.sanitizer import is_dangerous_link
    soup = make_soup(html)
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or is_dangerous_link(href):
            continue
        absolute = urljoin(base_url, href)
        if absolute.startswith(("http://", "https://")) and absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def extract_images(html: str, *, base_url: str) -> list[dict]:
    """Image metadata: absolute src + alt + dimensions when present."""
    soup = make_soup(html)
    out: list[dict] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or "").strip()
        if not src:
            continue
        absolute = urljoin(base_url, src)
        if not absolute.startswith(("http://", "https://")) or absolute in seen:
            continue
        seen.add(absolute)
        out.append({
            "src": absolute,
            "alt": sanitize_text(img.get("alt") or "", max_len=300) or None,
            "width": img.get("width"),
            "height": img.get("height"),
        })
    return out
