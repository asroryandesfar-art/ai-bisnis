"""Lightweight, dependency-free HTML → Markdown converter."""
from __future__ import annotations

from urllib.parse import urljoin

from .html import clean_html, make_soup
from ..security.sanitizer import sanitize_text, is_dangerous_link

_HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}


def html_to_markdown(html: str, *, base_url: str = "") -> str:
    """Convert HTML into readable Markdown (headings, lists, links, emphasis,
    code, blockquotes, tables). Boilerplate is stripped first."""
    soup = make_soup(clean_html(html))
    body = soup.body or soup
    parts: list[str] = []
    for el in body.children:
        _render(el, parts, base_url)
    md = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return sanitize_text(md)


def _inline(node, base_url: str) -> str:
    from bs4 import NavigableString, Tag
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    name = node.name
    inner = "".join(_inline(c, base_url) for c in node.children)
    if name in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else ""
    if name in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else ""
    if name == "code":
        return f"`{inner.strip()}`"
    if name == "br":
        return "\n"
    if name == "a":
        href = (node.get("href") or "").strip()
        if not href or is_dangerous_link(href):
            return inner
        absolute = urljoin(base_url, href) if base_url else href
        return f"[{inner.strip()}]({absolute})" if inner.strip() else ""
    return inner


def _render(node, parts: list[str], base_url: str) -> None:
    from bs4 import NavigableString, Tag
    if isinstance(node, NavigableString):
        txt = str(node).strip()
        if txt:
            parts.append(txt)
        return
    if not isinstance(node, Tag):
        return
    name = node.name
    if name in _HEADINGS:
        parts.append(_HEADINGS[name] + _inline(node, base_url).strip())
    elif name == "p":
        parts.append(_inline(node, base_url).strip())
    elif name == "blockquote":
        text = _inline(node, base_url).strip()
        parts.append("\n".join("> " + ln for ln in text.split("\n")))
    elif name == "pre":
        parts.append("```\n" + node.get_text().strip() + "\n```")
    elif name in ("ul", "ol"):
        ordered = name == "ol"
        lines = []
        for i, li in enumerate(node.find_all("li", recursive=False), 1):
            bullet = f"{i}. " if ordered else "- "
            lines.append(bullet + _inline(li, base_url).strip())
        parts.append("\n".join(lines))
    elif name == "table":
        from .tables import extract_tables
        tbls = extract_tables(str(node), max_tables=1)
        if tbls:
            parts.append(tbls[0]["markdown"])
    elif name in ("div", "section", "article", "main"):
        for child in node.children:
            _render(child, parts, base_url)
    else:
        txt = _inline(node, base_url).strip()
        if txt:
            parts.append(txt)
