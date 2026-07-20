"""Web Intelligence — read/crawl/extract public websites into clean, cited,
Knowledge-Base-ready content.

Fully modular: imports nothing from `main`/`bn_platform` at module top-level and
adds no runtime dependency to existing modules (backward compatible). Reuses the
platform's SSRF-safe fetch primitives (`tool_registry`) rather than reinventing
security. Heavy optional deps (Playwright, trafilatura, readability, pypdf)
degrade honestly when absent.

Public API:
    from backend.modules.web_intelligence import read_url, crawl_and_extract, ingest_to_kb
    from backend.modules.web_intelligence import agent_read, agent_crawl
    from backend.modules.web_intelligence.api.routes import build_web_intelligence_router
"""
from .services.reader import read_url
from .services.pipeline import crawl_and_extract, ingest_to_kb, agent_read, agent_crawl
from .security.validator import validate_url, is_valid_url

__all__ = [
    "read_url", "crawl_and_extract", "ingest_to_kb",
    "agent_read", "agent_crawl", "validate_url", "is_valid_url",
]
__version__ = "1.0.0"
