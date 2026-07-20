"""Heuristic source-confidence score (0..1) for extracted web content.

Deterministic, no LLM/paid API. Signals: HTTPS, content length, metadata
completeness, extraction method quality, and domain-shape hints. Meant as a
transparent quality flag, not a truth oracle."""
from __future__ import annotations

from urllib.parse import urlparse

_LOW_TRUST_TLDS = (".xyz", ".top", ".click", ".gq", ".tk", ".ml", ".ga", ".cf")
_METHOD_WEIGHT = {"trafilatura": 1.0, "readability-lxml": 0.9, "bs4-heuristic": 0.6}


def score_source(*, url: str, text: str, metadata: dict | None = None,
                 method: str = "bs4-heuristic") -> dict:
    """Return {score, level, signals}. Never raises."""
    metadata = metadata or {}
    signals: dict[str, float] = {}

    parsed = urlparse(url)
    signals["https"] = 0.15 if parsed.scheme == "https" else 0.0

    n = len(text or "")
    signals["content_length"] = 0.25 if n >= 1500 else 0.15 if n >= 400 else 0.05 if n >= 80 else 0.0

    meta_fields = ("title", "description", "author", "published_at", "canonical_url")
    filled = sum(1 for f in meta_fields if metadata.get(f))
    signals["metadata_completeness"] = round(0.25 * (filled / len(meta_fields)), 3)

    signals["extraction_method"] = round(0.25 * _METHOD_WEIGHT.get(method, 0.6), 3)

    host = (parsed.hostname or "").lower()
    penalty = 0.0
    if any(host.endswith(t) for t in _LOW_TRUST_TLDS):
        penalty += 0.1
    if host.count(".") >= 4:            # very deep sub-domains → mild penalty
        penalty += 0.05
    signals["domain_penalty"] = -round(min(penalty, 0.15), 3)

    score = max(0.0, min(1.0, round(sum(signals.values()) + 0.1, 3)))  # +0.1 base
    level = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
    return {"score": score, "level": level, "signals": signals}
