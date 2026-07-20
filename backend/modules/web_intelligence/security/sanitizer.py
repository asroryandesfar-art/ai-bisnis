"""Input/content sanitization for Web Intelligence."""
from __future__ import annotations

import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_WS = re.compile(r"[ \t ]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")
_DANGEROUS_LINK = re.compile(r"^\s*(javascript|data|vbscript|file|ftp):", re.I)


def sanitize_url_input(raw: str, *, max_len: int = 2048) -> str:
    """Trim, strip control chars, and cap a user-supplied URL string. Does NOT
    validate safety — call `validator.validate_url` for that."""
    if not raw or not isinstance(raw, str):
        return ""
    cleaned = _CONTROL_CHARS.sub("", raw.strip())
    return cleaned[:max_len]


def sanitize_text(text: str, *, max_len: int | None = None) -> str:
    """Normalize extracted text: NFC, drop control chars, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    text = _CONTROL_CHARS.sub("", text)
    text = _MULTI_WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    if max_len is not None and len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def is_dangerous_link(href: str) -> bool:
    """True for links using a dangerous scheme (javascript:, data:, file:, …)."""
    return bool(href and _DANGEROUS_LINK.match(href))
