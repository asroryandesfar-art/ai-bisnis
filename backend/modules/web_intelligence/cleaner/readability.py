"""Main-content extraction via readability-lxml, with a dependency-free fallback.

If `readability-lxml` is installed it is used; otherwise a BeautifulSoup
heuristic (largest <article>/<main>/content block) is used. Either way this
returns real extracted content — the `method` field says which was used."""
from __future__ import annotations

from ..parser.html import clean_html, make_soup, html_to_text
from ..security.sanitizer import sanitize_text


def readability_available() -> bool:
    try:
        import readability  # noqa: F401
        return True
    except Exception:
        return False


def _fallback_main_html(html: str) -> str:
    """Heuristic: pick <article>/<main>/<[role=main]> or the densest text block."""
    soup = make_soup(clean_html(html))
    for sel in ("article", "main", "[role=main]"):
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 200:
            return str(node)
    # densest <div>/<section> by text length
    best, best_len = None, 0
    for node in soup.find_all(["div", "section"]):
        length = len(node.get_text(strip=True))
        if length > best_len:
            best, best_len = node, length
    if best is not None and best_len > 200:
        return str(best)
    return str(soup.body or soup)


def extract_main_content(html: str, *, url: str = "") -> dict:
    """Return {method, title, content_html, text}."""
    if readability_available():
        try:
            from readability import Document
            doc = Document(html)
            content_html = doc.summary(html_partial=True)
            return {
                "method": "readability-lxml",
                "title": sanitize_text(doc.short_title() or "", max_len=500) or None,
                "content_html": content_html,
                "text": html_to_text(content_html),
            }
        except Exception:
            pass  # fall through to heuristic
    content_html = _fallback_main_html(html)
    return {
        "method": "bs4-heuristic",
        "title": None,
        "content_html": content_html,
        "text": html_to_text(content_html),
    }
