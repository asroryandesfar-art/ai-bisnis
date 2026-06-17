# Phase 4 - BotNesia Agent Marketplace Ecosystem

## Goal
BotNesia upgrades the existing multi-agent SaaS into a Shopify + ChatGPT + Agent Marketplace model without rebuilding or removing existing features.

## Marketplace Architecture
- `marketplace_templates` remains the canonical template catalog.
- `tenant_template_installs` remains the existing install table for backward compatibility.
- New compatibility tables support the expanded ecosystem: `agents`, `agent_versions`, `agent_installs`, `agent_ratings`, `agent_categories`, `agent_knowledge_sources`.
- `bn_platform.agent_marketplace_catalog` seeds 160 professional templates across 22 categories.

## Agent Architecture
Each template includes:
- `agent_id` / `key`
- name, description, category
- prompt / system prompt
- tools
- knowledge source metadata
- icon and color
- starter questions
- visibility flags: public, featured, recommended
- rating, popularity score, install counter, version

## Supervisor Architecture
The Supervisor Agent is exposed through `/api/marketplace/supervisor/route` for routing preview.
Runtime policy:
1. Solve
2. Explain
3. Recommend
4. Clarify
5. Escalate only when the user explicitly asks for human help

If no specialist fits, fallback is `General AI Agent`.

## Knowledge Isolation
Knowledge remains tenant and bot isolated. Template metadata defines recommended knowledge categories and URL seeds; installed agents create their own bot record and use that bot's knowledge sources and FAQ entries.

## API
Existing APIs preserved:
- `GET /api/marketplace/templates`
- `GET /api/marketplace/templates/{key}`
- `POST /api/marketplace/install`
- `GET /api/marketplace/installs`
- `POST /api/marketplace/installs/{install_id}/update`
- `POST /api/marketplace/installs/{install_id}/uninstall`

New APIs:
- `GET /api/marketplace/categories`
- `GET /api/marketplace/analytics`
- `GET /api/marketplace/recommended?q=&limit=12`
- `POST /api/marketplace/supervisor/route`

## Database Migration
Startup migration adds metadata columns to `marketplace_templates`, creates Phase 4 tables, and rebuilds `agent_templates` view safely with `DROP VIEW IF EXISTS` + `CREATE VIEW`.

For production, run the SQL in `schema.sql` or `bn_platform/schema_platform.sql` during deployment, then restart the API so startup seeding upserts the professional catalog.

## Deployment Guide
1. Backup PostgreSQL.
2. Deploy code.
3. Apply `schema.sql` or allow startup migration to run.
4. Restart FastAPI.
5. Open Agent Marketplace and confirm template count is 100+.
6. Install a featured template and confirm a new active bot appears.
7. Add knowledge to that bot from Knowledge Base.
8. Test Supervisor route with a broad user question and confirm fallback to General AI when needed.

## Verification
Run:

```bash
python3 -m pytest test_marketplace.py
node --check frontend/app.js
node --check frontend/api-client.js
```
