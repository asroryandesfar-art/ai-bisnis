"""Extract HTML <table> elements into structured rows and Markdown."""
from __future__ import annotations

from .html import make_soup
from ..security.sanitizer import sanitize_text


def extract_tables(html: str, *, max_tables: int = 25, max_rows: int = 500) -> list[dict]:
    """Return [{"headers": [...], "rows": [[...]], "markdown": "..."}]."""
    soup = make_soup(html)
    out: list[dict] = []
    for table in soup.find_all("table")[:max_tables]:
        rows: list[list[str]] = []
        for tr in table.find_all("tr")[:max_rows]:
            cells = [sanitize_text(td.get_text(" "), max_len=500)
                     for td in tr.find_all(["th", "td"])]
            if any(c for c in cells):
                rows.append(cells)
        if not rows:
            continue
        header_cells = table.find_all("th")
        headers = ([sanitize_text(th.get_text(" "), max_len=500) for th in header_cells]
                   if header_cells else rows[0])
        body = rows[1:] if not header_cells and len(rows) > 1 else rows if header_cells else rows[1:]
        out.append({
            "headers": headers,
            "rows": body,
            "markdown": _table_markdown(headers, body),
        })
    return out


def _table_markdown(headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return ""
    def esc(c: str) -> str:
        return (c or "").replace("|", "\\|").replace("\n", " ")
    width = len(headers)
    lines = ["| " + " | ".join(esc(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        r = (r + [""] * width)[:width]
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)
