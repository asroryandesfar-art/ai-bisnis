# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Start development server
python run_server.py                      # auto-selects port 8000/8001/8002/8010
uvicorn main:app --reload --port 8000     # hot-reload dev mode

# Database (first-time setup)
./setup_db.sh                             # create PostgreSQL 16 + pgvector + botnesia DB
./migrate_database.sh                     # run schema migrations

# Tests
pytest                                    # all tests (911+)
pytest test_<name>.py                     # single file
pytest test_<name>.py::test_function      # single test
pytest -x                                 # stop on first failure
pytest -k "gemini"                        # filter by keyword
```

No linter is configured. Follow existing code style (no trailing utility comments, no `from __future__ import annotations`).

## Architecture

### Entry Points
- **`main.py`** (6400 lines) — FastAPI app, `Settings` (pydantic-settings reads `.env`) as module-level `cfg`, all REST endpoints, DB pool lifecycle in `lifespan()`.
- **`run_server.py`** — starts uvicorn, handles port conflicts.
- **`agent_api.py`** — separate FastAPI app for multi-agent demo routes.

### Chat Pipeline
`POST /chat/{bot_id}` → `SupervisorAgent._process()` → `IntentClassifier` (standard vs pro path) → parallel `asyncio.gather` of specialist agents → CS Agent synthesizes reply → `EscalationAgent` gates human handoff.

`MemoryAgent` injects per-customer profile. `VerificationAgent` critiques output. `SelfLearningAgent` (read-only, pre-approved insights) adds organizational context.

### AI Provider Layer (`ai_providers/`)
Provider abstraction built on top of the agent base class:
- **`types.py`** — `LLMRequest`, `LLMResponse`, `ProviderType`, `TaskType`
- **`base.py`** — `AIProvider` ABC
- **`gemini.py`** — `GeminiProvider`: full Gemini Content API client (retries, streaming, JSON mode, images, PDFs, tool calling, safety handling)
- **`groq_provider.py`** — `GroqProvider`: wraps OpenAI-compatible Groq API
- **`router.py`** — `SmartModelRouter`: STANDARD → Flash, PRO/complex → Pro; Groq fallback when Gemini fails

**Model routing:** STANDARD tier and simple task types (chat/cs/faq/sales/marketing/hr/knowledge) → `gemini-2.5-flash`. PRO tier and complex task types (document/reasoning/planning/coding/workflow) → `gemini-2.5-pro`.

### Agent Base Class (`base.py`)
All agents extend `BaseAgent`. When `gemini_api_key` is set, `_call_llm()` routes to Gemini first (Flash for standard, Pro for complex), falling back to Groq on failure. Key methods:
- `_call_llm()` — primary text completion (Gemini-first if key set, else Groq)
- `_call_gemini()` — direct Gemini call (also used by router)
- `_call_llm_json()` — returns parsed dict, never raises
- `_call_llm_with_tools()` — OpenAI-compatible tool-calling loop (Groq only, Gemini tool format differs)
- `safe_run()` — wraps `run()` with timing + observability, never propagates exceptions

### Database
PostgreSQL 16 + pgvector, accessed via `asyncpg` raw SQL (no ORM). Three schema layers:
- `schema.sql` — core: organizations, users, bots, conversations, messages, knowledge
- `intelligence/schema_intelligence.sql` — conversation memory, FAQ, sales patterns
- `bn_platform/schema_platform.sql` — RBAC, billing, omnichannel, AI Workforce tables

Pool created in `lifespan()`, injected as `pool` into route handlers. **JSONB columns require `json.dumps()` — pass `json.dumps(my_dict)` for JSONB parameters, not a raw `dict`.**

Every query is scoped by `org_id`. Never write cross-org queries.

### Business Platform (`bn_platform/`)
FastAPI routers mounted in `main.py`. Pattern: `<domain>.py` router + `<domain>_agent.py` AI logic + tables in `schema_platform.sql`.

**AI Workforce agents (Finance/Marketing/HR/Operations/Security/Executive/Workforce) are never called from the customer chat pipeline** — only from authenticated `/api/*` REST endpoints. This is an intentional security boundary.

`SelfLearningAgent` is the only AI Workforce module that injects context into chat (read-only, SQL query, pre-approved organizational insights).

### Cost & Observability
- `cost_intelligence.py` — pricing registry (Groq + Gemini), `routed_model()` for A/B routing, `estimate_cost_usd()`
- `agent_observability.py` — `add_token_usage()` logs per-model token counts + cost to every LLM call; `observe_agent()` wraps agent execution with tracing
- `bn_platform/observability.py` — Prometheus metrics + DB persistence for dashboard

### Frontend
`frontend/` — vanilla JS SPA (no build step, no framework). Served as static files. `app.js` + `components.js`.

## Critical Conventions

- `from __future__ import annotations` is **not used** anywhere in this codebase.
- `CREATE INDEX` must use `CREATE INDEX IF NOT EXISTS` — plain `CREATE UNIQUE INDEX` fails if index already exists.
- Tests mock `httpx.AsyncClient` at the transport level (not method-level), so the actual HTTP request shape is verified.
- `safe_run()` contract: agent `run()` overrides must not propagate exceptions — errors surface in `AgentResult.error`.
- Agents are constructed with explicit keys in `main.py`'s `get_supervisor()` / `get_knowledge_builder_agent()`. When adding new config, add to `Settings` in `main.py` and pass through these factory functions.
- **Gemini key env var**: `GEMINI_API_KEY` (preferred) or legacy `GOOGLE_API_KEY`. Both read by `Settings.effective_gemini_api_key`.
