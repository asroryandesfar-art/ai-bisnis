"""Main-content extraction via trafilatura (best-in-class, no paid API).

Honest degradation: if `trafilatura` is not installed, `trafilatura_available()`
is False and callers fall back to `cleaner.readability.extract_main_content`."""
from __future__ import annotations

from ..security.sanitizer import sanitize_text


def trafilatura_available() -> bool:
    try:
        import trafilatura  # noqa: F401
        return True
    except Exception:
        return False


def extract_with_trafilatura(html: str, *, url: str = "", output: str = "markdown") -> dict | None:
    """Return {method, text, markdown?} or None if trafilatura is unavailable/failed."""
    if not trafilatura_available():
        return None
    try:
        import trafilatura
        fmt = "markdown" if output == "markdown" else "txt"
        extracted = trafilatura.extract(
            html, url=url or None, output_format=fmt,
            include_tables=True, include_links=(output == "markdown"),
            favor_precision=True,
        )
        if not extracted:
            return None
        text = sanitize_text(extracted)
        result = {"method": "trafilatura", "text": text}
        if output == "markdown":
            result["markdown"] = text
        return result
    except Exception:
        return None
