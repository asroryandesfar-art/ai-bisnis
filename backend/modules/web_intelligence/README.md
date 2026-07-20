# Web Intelligence

Read, crawl, and extract **public websites** into clean, cited, Knowledge-Base-ready
content — for BotNesia agents (Supervisor / Research / Memory) and the dashboard.

Self-contained module at `backend/modules/web_intelligence/`. **Backward compatible**:
imports nothing from `main`/`bn_platform` at module top-level, adds no runtime
dependency to existing code, and **reuses the platform's SSRF-safe fetch primitives**
(`tool_registry`) instead of reinventing security. No paid external APIs.

## Pipeline

```
User / Agent
   │
   ▼
Supervisor Agent ──► Web Intelligence
                         │
                         ├─ 1. Validate URL           (security/validator — reuses SSRF)
                         ├─ 2. robots.txt check        (crawler/robots)
                         ├─ 3. Fetch (rate-limit/retry/timeout/cache, IP-pinned) (crawler/crawl)
                         ├─ 4. Render JS if needed     (browser/playwright)
                         ├─ 5. Clean HTML              (parser/html)
                         ├─ 6. Extract main content    (cleaner/trafilatura → readability → bs4)
                         ├─ 7. Metadata / tables / links / images (parser/*)
                         ├─ 8. Convert Markdown/JSON/Text (parser/markdown)
                         ├─ 9. Verify + cite + score   (verifier/citation, verifier/confidence)
                         ├─ 10. Chunk + save to KB      (knowledge/chunker, knowledge/vector)
                         └─ 11. Return to requesting agent
```

## Architecture

```
backend/modules/web_intelligence/
├── crawler/     crawl.py (fetch+rate-limit+retry+cache) · recursive.py (BFS) · robots.py
├── browser/     playwright.py (JS render) · screenshot.py
├── parser/      html.py · markdown.py · metadata.py · tables.py · pdf.py
├── cleaner/     trafilatura.py · readability.py   (main-content extraction, w/ fallback)
├── cache/       cache.py (TTL+LRU)
├── security/    validator.py (SSRF reuse + scheme block) · sanitizer.py
├── verifier/    citation.py · confidence.py
├── knowledge/   chunker.py · embedding.py · vector.py (KB persistence)
├── services/    reader.py (single-URL pipeline) · pipeline.py (crawl+ingest+agent facade)
├── api/         routes.py (factory-DI FastAPI router)
├── schemas/     models.py (pydantic)
└── tests/       test_web_intelligence.py (44 tests)
```

## Features

Single URL Reader · Website Crawl · Recursive Crawl · HTML Cleaner · Markdown Converter ·
Metadata Extractor · Table Extractor · PDF Extractor · Image Metadata · robots.txt checker ·
Rate Limiter · Retry · Timeout · Cache · JS rendering (Playwright) · Screenshot ·
Source Verification (citation + confidence) · Knowledge-Base ingestion.

**Outputs:** JSON · Markdown · Plain Text.

## Dependencies

Required (present): `httpx`, `beautifulsoup4`, `lxml`, `playwright`.
Optional (honest graceful degradation if absent — see `/status`):
`trafilatura`, `readability-lxml` (better main-content extraction; falls back to a
bs4 heuristic), `pypdf` (PDF text), and Playwright browser binaries
(`playwright install chromium`) for JS render/screenshot.

```
pip install trafilatura readability-lxml pypdf
playwright install chromium
```

## Usage — Python

```python
from backend.modules.web_intelligence import read_url, crawl_and_extract, ingest_to_kb, agent_read

# Single URL → markdown + citation + confidence
res = await read_url("https://example.com/article", output="markdown", include_tables=True)
print(res["markdown"], res["citation"], res["confidence"])

# Recursive crawl (same-site, robots-respecting)
out = await crawl_and_extract("https://example.com", max_depth=1, max_pages=10)

# Crawl + save into the tenant Knowledge Base (needs asyncpg pool + org/bot)
await ingest_to_kb(pool, org_id=org, bot_id=bot, seed_url="https://example.com")

# Agent-facing (Supervisor / Research / Memory)
doc = await agent_read("https://example.com")   # read-only, cited, no persistence
```

## API

Mounted at `/api/web-intelligence` (see `main.py` wiring, RBAC via `knowledge.read/write`).

| Method | Path | Auth | Description |
|---|---|---|---|
| GET  | `/status` | read | Capabilities + which optional deps are available + cache stats |
| POST | `/read` | read | Read one URL → `{markdown,text,metadata,tables,links,images,citation,confidence,monitoring}` |
| POST | `/crawl` | read | Recursive crawl → extracted documents + stats |
| POST | `/screenshot` | read | Full-page PNG (Playwright) |
| POST | `/ingest?bot_id=…` | write | Crawl → chunk → save to Knowledge Base |
| POST | `/cache/clear` | write | Clear the page cache |

`POST /read` body: `{"url": "...", "render_js": false, "output": "markdown|json|text",
"include_tables": true, "include_links": false, "include_images": false, "use_cache": true}`

## Security

- **URL validation** reuses `tool_registry._validate_url` + `resolve_public_ips`
  (blocks localhost, private/reserved IPs, DNS-rebinding via IP pinning).
- Blocks `file://`, `ftp://`, `javascript:`, `data:`, `vbscript:`, `ws(s)://`, … —
  only `http`/`https` allowed.
- Input sanitized (control chars stripped, length capped); dangerous links dropped
  from extracted output; response size capped (5 MB/page); redirects re-validated.

## Monitoring

Every read/crawl returns a `monitoring` block: status, duration_ms, bytes,
pages_crawled, errors, from_cache, content_chars. Crawl exposes `on_progress`.

## Testing

```
python3 -m pytest backend/modules/web_intelligence/tests/ -q   # 44 tests
```
Covers: URL security (block localhost/private/file/ftp/javascript/data), sanitizer,
TTL+LRU cache, HTML clean, markdown, metadata, links/images, tables, PDF degrade,
main-content extraction + fallback, citation, confidence tiers, chunker, rate-limiter,
retry, KB adapter, the full single-URL pipeline (network mocked), recursive BFS crawl
(same-site scoping), and the API router (status/read/RBAC). Network + Playwright are
mocked so tests are deterministic and offline.
