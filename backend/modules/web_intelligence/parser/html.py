"""HTML cleaning: strip scripts/styles/nav/boilerplate → clean HTML + plain text.

Uses BeautifulSoup (lxml parser when available). No external services."""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..security.sanitizer import sanitize_text

# Tags that are never content and are always removed.
_DROP_TAGS = [
    "script", "style", "noscript", "template", "iframe", "svg", "canvas",
    "form", "button", "input", "select", "textarea", "nav", "aside",
    "footer", "header", "video", "audio", "object", "embed", "map",
]
# Attribute-value hints that mark boilerplate containers (ads/nav/cookie/social).
_BOILERPLATE_HINTS = (
    "advert", "adsense", "sponsor", "cookie", "consent", "newsletter",
    "sidebar", "breadcrumb", "social", "share", "related", "comment",
    "popup", "modal", "subscribe", "banner", "menu", "navigation",
)


def _parser_name() -> str:
    try:
        import lxml  # noqa: F401
        return "lxml"
    except Exception:
        return "html.parser"


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", _parser_name())


def clean_html(html: str) -> str:
    """Return cleaned HTML with scripts/boilerplate removed (structure kept)."""
    soup = make_soup(html)
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        blob = " ".join(filter(None, [
            " ".join(tag.get("class", []) if isinstance(tag.get("class"), list) else [tag.get("class") or ""]),
            tag.get("id") or "", tag.get("role") or "",
        ])).lower()
        if blob and any(h in blob for h in _BOILERPLATE_HINTS):
            tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, type(soup.comment)) if hasattr(soup, "comment") else False):
        comment.extract()
    return str(soup)


def html_to_text(html: str, *, max_len: int | None = None) -> str:
    """Extract readable plain text from HTML (boilerplate stripped)."""
    soup = make_soup(clean_html(html))
    # Block-level newlines so text doesn't run together.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
        block.append("\n")
    text = soup.get_text(separator=" ")
    return sanitize_text(text, max_len=max_len)
