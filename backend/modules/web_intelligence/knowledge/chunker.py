"""Split extracted text into overlapping chunks suitable for a Knowledge Base."""
from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Paragraph-aware chunking with character overlap. Returns non-empty chunks."""
    text = (text or "").strip()
    if not text:
        return []
    max_chars = max(200, int(max_chars))
    overlap = max(0, min(int(overlap), max_chars // 2))

    paras = [p.strip() for p in _PARA.split(text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > max_chars:                    # hard-split an oversized paragraph
            if buf:
                chunks.append(buf); buf = ""
            for i in range(0, len(para), max_chars - overlap):
                chunks.append(para[i:i + max_chars])
            continue
        if buf and len(buf) + len(para) + 2 > max_chars:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = (tail + "\n\n" + para).strip()
        else:
            buf = (buf + "\n\n" + para).strip() if buf else para
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]
