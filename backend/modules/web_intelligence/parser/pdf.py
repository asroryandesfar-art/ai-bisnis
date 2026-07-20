"""PDF text extraction from bytes.

Uses pypdf / PyPDF2 if installed. Honest degradation (Truthfulness Policy):
if no PDF library is available, returns available=False with a clear reason
instead of raising or faking output."""
from __future__ import annotations

from ..security.sanitizer import sanitize_text


def _load_reader():
    for modname in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(modname)
            return getattr(mod, "PdfReader")
        except Exception:
            continue
    return None


def pdf_available() -> bool:
    return _load_reader() is not None


def extract_pdf_text(data: bytes, *, max_pages: int = 100, max_chars: int = 200_000) -> dict:
    """Return {available, text, pages, truncated, reason?}."""
    reader_cls = _load_reader()
    if reader_cls is None:
        return {"available": False, "text": "", "pages": 0,
                "reason": "PDF extraction butuh library 'pypdf' (belum terpasang)."}
    import io
    try:
        reader = reader_cls(io.BytesIO(data))
    except Exception as exc:
        return {"available": True, "text": "", "pages": 0,
                "reason": f"PDF tidak dapat dibaca: {exc!s}"}
    chunks: list[str] = []
    total = 0
    n = min(len(reader.pages), max_pages)
    for page in reader.pages[:n]:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        chunks.append(t)
        total += len(t)
        if total >= max_chars:
            break
    text = sanitize_text("\n\n".join(chunks), max_len=max_chars)
    return {"available": True, "text": text, "pages": len(reader.pages),
            "truncated": total >= max_chars}
