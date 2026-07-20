"""Build a structured, verifiable citation for extracted content."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse


def build_citation(url: str, metadata: dict | None = None, *, final_url: str | None = None) -> dict:
    """Return a citation dict: source URL, domain, title, author, dates, accessed_at."""
    metadata = metadata or {}
    cite_url = final_url or url
    domain = urlparse(cite_url).hostname or ""
    return {
        "source_url": cite_url,
        "original_url": url,
        "domain": domain,
        "title": metadata.get("title"),
        "author": metadata.get("author"),
        "site_name": metadata.get("site_name"),
        "published_at": metadata.get("published_at"),
        "accessed_at": datetime.now(timezone.utc).isoformat(),
    }


def format_citation(citation: dict) -> str:
    """Human-readable one-line citation (APA-ish)."""
    parts = []
    if citation.get("author"):
        parts.append(str(citation["author"]))
    if citation.get("title"):
        parts.append(f"\"{citation['title']}\"")
    if citation.get("site_name") or citation.get("domain"):
        parts.append(str(citation.get("site_name") or citation["domain"]))
    if citation.get("published_at"):
        parts.append(str(citation["published_at"])[:10])
    parts.append(str(citation.get("source_url", "")))
    return ". ".join(p for p in parts if p)
