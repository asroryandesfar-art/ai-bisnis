# BotNesia — Referensi API

> Semua endpoint di bawah ini diverifikasi langsung dari
> `grep -n "@router\.(get|post|patch|put|delete)" bn_platform/*.py` dan dari
> `app.include_router(...)` di `main.py` — bukan ditebak dari nama file.
> Semua router di-mount dengan `prefix="/api"` di `main.py`; setiap path di
> tabel di bawah adalah path **setelah** `/api`. Autentikasi: JWT Bearer
> (lihat [SECURITY.md](SECURITY.md) §1) kecuali disebut publik.

## 1. Core (`main.py`, tidak lewat router file)

- `POST /chat` — pipeline chat utama pelanggan→bot (Supervisor + agent + intelligence context)
- `POST /upload` — upload dokumen ke knowledge base
- Auth: `POST /auth/register`, `POST /auth/login`, dan endpoint org/bot/api-key CRUD lain — lihat `main.py` langsung untuk daftar lengkap (file ini >100rb baris campuran logic, bukan satu blok rapi).

## 2. RBAC & Tim (`bn_platform/rbac.py`, prefix `/rbac`)
`GET /permissions` · `GET /roles` · `GET /me` · `GET /team` · `POST /invite` · `POST /assign` · `POST /revoke`

## 3. Billing (`bn_platform/billing.py`, prefix `/billing`)
`GET /plans` · `GET /subscription` · `GET /usage` · `POST /checkout` · `POST /cancel` · `GET /invoices` · `GET /payments` · `POST /webhooks/midtrans` (publik, signature-verified) · `POST /webhooks/xendit` (publik, signature-verified)

## 4. Human Handoff (`bn_platform/handoff.py`, prefix `/handoff`)
`GET /queue` · `GET /stats` · `GET /mine` · `POST /{queue_id}/claim` · `POST /{queue_id}/assign` · `POST /{queue_id}/resolve` · `POST /{queue_id}/reply`

## 5. Omnichannel (`bn_platform/omnichannel.py`, tanpa prefix tambahan — path literal)
`GET /channels` · `POST /channels/connect` · `POST /channels/disconnect` · `DELETE /channels/{connection_id}` · `GET /channels/status` · `GET /channels/analytics` · `POST /channels/send` · `POST /channels/broadcast` · `GET /inbox` · `GET /inbox/summary` · `GET|POST /webhooks/channels/{channel}/{connection_id}` (publik, dipakai provider channel) · `POST /channels/webchat/{connection_id}/messages`

## 6. Meta OAuth (`bn_platform/meta_oauth.py`, prefix `/integrations/meta/oauth`)
`POST /start` · `GET /callback` (publik, redirect dari Meta) · `GET /status` · `POST /select` · `POST /refresh` · `POST /disconnect`

## 7. Lead Generation (`bn_platform/lead_engine.py`, prefix `/leads`)
`GET /` · `GET /summary` · `POST /recompute`

## 8. Marketplace (`bn_platform/marketplace.py`, prefix `/marketplace`)
`GET /templates` · `GET /templates/{key}` · `POST /install` · `GET /installs` · `POST /installs/{install_id}/update` · `POST /installs/{install_id}/uninstall` · `GET /categories` · `GET /analytics` · `GET /recommended` · `POST /supervisor/route` · `GET /health`

## 9. Revenue Intelligence (`bn_platform/revenue_intel.py`, prefix `/revenue`) — gated `PLATFORM_ADMIN_EMAILS`, bukan RBAC tenant
`GET /overview` · `GET /trend` · `POST /snapshot/run`

## 10. Founder OS (`bn_platform/founder_os.py`, prefix `/founder`) — sama, khusus operator platform
`GET /access` · `GET /overview`

## 11. Security & Audit (`bn_platform/security.py`, prefix `/security`) — owner/admin only
`GET /audit-logs` · `POST /scan` · `GET /api-keys` · `POST /api-keys/{key_id}/rotate` · `PATCH /api-keys/{key_id}/scopes` · `DELETE /api-keys/{key_id}` · `GET /sessions` · `POST /sessions/{session_id}/revoke` · `GET /dashboard` · `POST /scan-and-alert` · `GET /risk-alerts` · `PATCH /risk-alerts/{alert_id}` · `GET /reports` · `POST /reports/generate` · `GET /reports/{report_id}`

## 12. AI Observability (`bn_platform/ai_observability.py`, prefix `/observability`)
`GET /summary` · `GET /traces/{trace_id}`

## 13. Cost Intelligence (`bn_platform/cost_intelligence.py`, prefix `/cost-intelligence`)
`GET /summary` · `PUT /budget`

## 14. Feedback Learning (`bn_platform/feedback_learning.py`, prefix `/feedback-learning`)
`POST /feedback` · `POST /public/{bot_id}` (publik) · `GET /summary` · `GET /queue` · `PATCH /queue/{item_id}`

## 15. Knowledge Builder (`bn_platform/knowledge_builder.py`, prefix `/knowledge-builder`)
`GET /bots/{bot_id}/overview` · `POST /bots/{bot_id}/documents/{doc_id}/generate` · `GET /bots/{bot_id}/faqs` · `PATCH /faqs/{faq_id}` · `GET /bots/{bot_id}/sops` · `PATCH /sops/{sop_id}` · `GET /bots/{bot_id}/quality` · `GET /health`

## 16. Workflow Builder (`bn_platform/workflow_builder.py`, prefix `/workflow-builder`)
`GET /node-catalog` · `GET|POST /bots/{bot_id}/workflows` · `GET|PATCH /workflows/{workflow_id}` · `POST /workflows/{workflow_id}/publish` · `POST /workflows/{workflow_id}/unpublish` · `DELETE /workflows/{workflow_id}` · `POST /workflows/{workflow_id}/test` · `GET /workflows/{workflow_id}/executions` · `GET /executions/{execution_id}`

## 17. AI Improvement (`bn_platform/improvement_engine.py`, prefix `/improvement`)
`GET /dashboard` · `GET /recommendations` · `PATCH /recommendations/{rec_id}` · `POST /scan`

## 18. System Health (`bn_platform/system_health.py`, tanpa prefix)
`GET /system-health` (publik, dipakai monitoring/uptime check)

---

## AI Workforce (Phase 1-8) — semua RBAC-gated per domain, semua `org_id`-scoped

## 19. Finance Agent (`bn_platform/finance.py`, prefix `/finance`)
`GET /dashboard` · `GET /reports/revenue` · `GET /reports/profit` · `GET /reports/cashflow` · `GET /reports/forecast` · `GET /reminders` · `GET|POST /invoices` · `GET /invoices/{invoice_id}` · `PATCH /invoices/{invoice_id}/status` · `DELETE /invoices/{invoice_id}` · `GET|POST /payments` · `GET|POST /expenses` · `PATCH /expenses/{expense_id}/approval` · `POST /parse`

## 20. Marketing Agent (`bn_platform/marketing.py`, prefix `/marketing`)
`GET /dashboard` · `GET /calendar` · `GET /due` · `GET|POST /campaigns` · `GET /campaigns/{campaign_id}` · `PATCH /campaigns/{campaign_id}/status` · `GET /campaigns/{campaign_id}/analytics` · `DELETE /campaigns/{campaign_id}` · `GET|POST /content` · `POST /content/generate` · `GET /content/{content_id}` · `PATCH /content/{content_id}/schedule` · `PATCH /content/{content_id}/approve` · `PATCH /content/{content_id}/publish` · `DELETE /content/{content_id}` · `GET|POST /content/{content_id}/engagement`

## 21. HR Agent (`bn_platform/hr.py`, prefix `/hr`)
`GET /dashboard` · `GET|POST /candidates` · `POST /candidates/{candidate_id}/cv` · `GET /candidates/{candidate_id}` · `PATCH /candidates/{candidate_id}/status` · `POST /candidates/{candidate_id}/score` · `POST /candidates/{candidate_id}/interview-questions` · `DELETE /candidates/{candidate_id}` · `GET|POST /employees` · `GET /employees/{employee_id}` · `PATCH /employees/{employee_id}/status` · `DELETE /employees/{employee_id}` · `GET /employees/{employee_id}/evaluations` · `POST /employees/{employee_id}/evaluations/generate` · `PATCH /evaluations/{evaluation_id}/finalize` · `GET /employees/{employee_id}/performance` · `GET|POST /employees/{employee_id}/training` · `POST /employees/{employee_id}/training/recommend` · `PATCH /training/{training_id}/status`

## 22. Operations Agent (`bn_platform/operations.py`, prefix `/operations`)
`GET /dashboard` · `GET /alerts` · `PATCH /alerts/{alert_id}` · `POST /scan` · `GET /reports` · `POST /reports/generate` · `GET /reports/{report_id}`

## 23. Executive Agent (`bn_platform/executive.py`, prefix `/executive`) — hanya 4 endpoint, by design
`GET /dashboard` (no LLM) · `GET /reports` · `POST /reports/generate` (satu-satunya LLM call lintas-domain) · `GET /reports/{report_id}`

## 24. Workforce Orchestration (`bn_platform/workforce.py`, prefix `/workforce`)
`GET /dashboard` · `GET|POST /tasks` · `PATCH /tasks/{task_id}/status` · `PATCH /tasks/{task_id}/assign` · `POST /tasks/{task_id}/approve` · `POST /scan-conflicts`

## 25. Self Learning Company (`bn_platform/self_learning.py`, prefix `/learning`)
`GET /dashboard` · `GET /insights` · `POST /scan` · `PATCH /insights/{insight_id}`

---

## 26. Intelligence Platform (`intelligence/routes_intelligence.py`, di-mount via `agent_api.py`, prefix `/intel`)
Dashboard, FAQ, sales intelligence, knowledge graph, learning reports — lihat [`intelligence/ARCHITECTURE.md`](../intelligence/ARCHITECTURE.md) untuk daftar lengkap (router ini di-mount ke `agent_api.py`, bukan `main.py`, jadi terpisah dari 25 router di atas).
