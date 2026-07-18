# Project Structure

A map of the repository. BotNesia is a Python (FastAPI + asyncpg + PostgreSQL)
backend that serves a vanilla-JS single-page dashboard, with a companion Expo
mobile app. The AI layer is a Supervisor-orchestrated team of specialist agents.

> **On the flat root:** the application modules (`main.py`, `base.py`,
> `agent_registry.py`, the specialist `*_agent.py` files, and the `test_*.py`
> suite) live at the repository root and are imported flatly (`import main`,
> `from base import ...`). This is an intentional, load-bearing convention: the
> whole import graph and the ~1,470-test suite depend on it. It is **not**
> reorganized into `src/` because doing so on a live, continuously-deployed
> service would be a high-risk, low-reward change. New shared/platform code is
> instead added under `bn_platform/` (the strangler target).

## Top-level layout

```
.
├── main.py                     # FastAPI application entrypoint + app wiring
├── base.py                     # Agent base class + LLM call plumbing
├── agent_registry.py           # Agent discovery / orchestration registry
├── *_agent.py                  # Specialist agents (cs, sales, executive, …)
├── *.py                        # Domain services (cost_intelligence, escalation, …)
├── test_*.py                   # Test suite (pytest, root-level)
│
├── bn_platform/                # Extracted routers + platform layer (strangler target)
│   ├── auth.py  billing.py  sso.py  marketplace.py  rbac.py  pages.py
│   ├── config.py               # Settings (pydantic-settings)
│   ├── schema_platform.sql     # Platform DB schema (idempotent)
│   └── ARCHITECTURE.md
│
├── ai_providers/               # LLM provider routing (SmartModelRouter, streaming)
├── intelligence/               # Intelligence platform modules
├── casper/                     # Casper blockchain proof anchoring
│
├── frontend/                   # Vanilla-JS SPA dashboard
│   ├── app.js  api-client.js  i18n.js  styles.css  index.html
│   └── public/                 # Static assets (brand, widget)
│
├── mobile/                     # Expo SDK 54 React Native app (feature-parity)
│
├── migrations/                 # Database migrations
├── seeds/  backend/seeds/      # Seed data (agent/marketplace URL corpora)
├── scripts/                    # Operational & seeding scripts
├── deploy/                     # Deployment configuration
│
├── docs/                       # Documentation
│   ├── ARCHITECTURE.md  AI_AGENT_ARCHITECTURE.md
│   ├── hackathon/              # Pitch, demo script, diagrams, roadmap
│   ├── marketing/              # Company profile, pitch deck, screenshots
│   └── submission/             # Submission materials
│
├── reports/                    # Generated audit/report artifacts
├── archive/                    # Verified-unused files kept for reference (see archive/README.md)
│
├── Dockerfile  docker-compose.yml
├── requirements.txt            # Python dependencies
├── pytest.ini                  # Test configuration
├── .env.example                # Documented environment variables (no secrets)
├── README.md  CHANGELOG.md  ARCHITECTURE (docs/)  SECURITY.md
└── CONTRIBUTING.md  CODE_OF_CONDUCT.md  LICENSE
```

## Where to make changes

| You want to… | Edit |
|--------------|------|
| Add/modify an HTTP API | a router in `bn_platform/` (or `main.py` for legacy endpoints) |
| Add/change an AI agent | a `*_agent.py` at root + register in `agent_registry.py` |
| Change the dashboard UI | `frontend/app.js`, `frontend/i18n.js`, `frontend/styles.css` |
| Change the mobile app | `mobile/src/…` |
| Change DB schema | `bn_platform/schema_platform.sql` + `ensure_optional_schema()` in `main.py` |
| Add env config | `bn_platform/config.py` + document in `.env.example` |
| Add tests | `test_<area>.py` at root (unit/integration) or `tests/e2e/` |
