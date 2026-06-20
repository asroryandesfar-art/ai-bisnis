# BotNesia — Referensi Database

> Konsolidasi semua tabel di 3 file schema. Setiap tabel hanya disebutkan
> **sekali** di sini (cek migrasi nyata dengan `grep -n "CREATE TABLE" <file>`
> jika butuh detail kolom — dokumen ini sengaja ringkas per tabel, bukan DDL
> lengkap). Total: 3 file schema, dijalankan idempoten & berurutan oleh
> `migrate_database.sh` (lihat [DEPLOYMENT.md](DEPLOYMENT.md)).

**Prinsip kunci:** semua tabel tenant diberi kolom `org_id UUID REFERENCES
organizations(id)` dan setiap query di seluruh codebase memfilter
`WHERE org_id = $1` — `organizations.id` berperan sebagai `tenant_id` (tidak
ada tabel `tenants` terpisah, hanya VIEW kompatibilitas `tenants`).

## 1. `schema.sql` (root) — Core

| Tabel | Fungsi |
|---|---|
| `organizations` | Tenant. `plan`, `bot_limit`, `conv_limit`, `doc_limit`, `billing_status` |
| `users` | User per organisasi. `role` lama (free-text) dimigrasi lazy ke RBAC |
| `bots` | AI agent/persona yang di-deploy tenant (nama, system prompt, channel) |
| `documents`, `doc_chunks` | Dokumen knowledge base + chunk untuk embedding |
| `conversations`, `messages` | Riwayat chat pelanggan↔bot |
| `api_keys` | API key per organisasi (scoped, bukan dienkripsi — lihat SECURITY.md §3) |
| `usage_snapshots` | Snapshot pemakaian harian per tenant (untuk billing/limit) |
| `webhook_configs` | Konfigurasi webhook channel dasar |
| `ai_traces`, `agent_executions` | Observability: jejak eksekusi agent |
| `cost_records`, `tenant_cost_budgets` | Cost Intelligence — biaya token per request, budget per tenant |
| `human_queue` | Antrian eskalasi AI→manusia (status, priority, SLA, assigned_agent) |
| `marketplace_templates`, `tenant_template_installs` | Katalog template agent + riwayat instal |
| `agent_categories`, `agents`, `agent_versions`, `agent_installs`, `agent_ratings`, `agent_knowledge_sources` | Agent Marketplace (versi awal, generik) |
| `feedback_records`, `feedback_learning_queue` | Rating pelanggan (helpful/not helpful) + antrian perbaikan |
| `kb_generated_faqs`, `kb_generated_sops`, `kb_quality_reports` | Knowledge Builder — FAQ/SOP/skor kualitas hasil AI dari dokumen |
| `workflows`, `workflow_executions`, `workflow_execution_steps` | Workflow Builder (ala n8n/Zapier) |
| `sessions` | Sesi login (IP, user agent, revoke) |
| `ai_improvement_recommendations` | Rekomendasi perbaikan self-evaluasi (knowledge_gap/prompt/workflow/agent) |
| `knowledge_sources`, `knowledge_chunks` | Sumber pengetahuan tambahan (URL crawl, dst) |
| `image_generations`, `generated_documents` | Multimedia Studio — gambar & dokumen hasil generate AI |

> Catatan: beberapa tabel di atas (`human_queue`, `marketplace_templates`,
> `tenant_template_installs`, `feedback_records`, `feedback_learning_queue`,
> `kb_generated_*`, `workflows*`, `sessions`, `ai_improvement_recommendations`)
> juga muncul sebagai `CREATE TABLE IF NOT EXISTS` di `bn_platform/schema_platform.sql`
> — ini idempotent guard, bukan duplikat tabel; definisi kanonik ada di
> `schema.sql` (dibuat lebih dulu), `schema_platform.sql` hanya memastikan
> tabel ada jika migrasi dijalankan terpisah.

## 2. `intelligence/schema_intelligence.sql` — Phase 1 (Conversation Intelligence)

| Tabel | Fungsi |
|---|---|
| `conversation_analysis` | Intent, sentiment, topics, `lead_status`, `purchase_status`, `escalation_status`, `quality_score` per percakapan |
| `conversation_embeddings` | Embedding 384-dim (hashing-trick lokal) untuk semantic search, pakai pgvector |
| `faq_entries`, `faq_source_messages` | Cluster pertanyaan berulang + skor frekuensi/sukses/konversi |
| `sales_patterns`, `sales_signals` | Pola trigger→objection→solution + sinyal individual |
| `kg_nodes`, `kg_edges` | Knowledge graph: User↔Produk↔Pertanyaan↔Masalah↔Solusi↔Penjualan |
| `customer_profiles`, `customer_facts` | Profil pelanggan lintas-percakapan: lead_score, churn_risk, fakta terkumpul |
| `learning_reports` | Snapshot harian: top FAQ, top complaint, sales trigger, percakapan gagal |

## 3. `bn_platform/schema_platform.sql` — Phase 2 (Business Platform) + AI Workforce

### 3.1 RBAC & multi-tenancy
`permissions`, `roles`, `role_permissions`, `user_roles` — 5 role sistem
(owner/admin/manager/agent/viewer), permission granular per domain
(`bots.*`, `finance.*`, `learning.*`, dst — lihat [SECURITY.md](SECURITY.md) §2).

### 3.2 Billing & subscription
`plans`, `subscriptions`, `invoices`, `payment_history` — 5 SKU
(free/starter/pro/business/enterprise), provider Midtrans/Xendit.

### 3.3 Omnichannel
`channels`, `channel_connections`, `channel_accounts`, `channel_messages`,
`channel_events`, `channel_logs`, `meta_asset_routes` — WhatsApp/Telegram/
Instagram/Facebook/Website/Email, plus VIEW `unified_inbox`.

### 3.4 Security & audit
`audit_logs` (login/role_change/payment/security_scan/dll, indexed by
org+actor+action), `lead_scores`, `revenue_snapshots`.

### 3.5 AI Workforce — per domain (Phase 1-8 AI Workforce, lihat ARCHITECTURE.md §2)

| Domain | Tabel |
|---|---|
| Finance (Phase 1) | `finance_invoices`, `finance_payments`, `finance_expenses`, `finance_transactions`, `finance_reports` |
| Marketing (Phase 2) | `marketing_campaigns`, `marketing_content`, `marketing_engagement` |
| HR (Phase 3) | `hr_candidates`, `hr_employees`, `hr_evaluations`, `hr_training_records` |
| Operations + Security (Phase 4-5) | `ops_alerts`, `ops_reports` — kolom `source` (`operations`/`security`/`executive`) membedakan asal |
| Workforce Orchestration (Phase 7) | `workforce_tasks` — `domain` CHECK IN (finance/marketing/hr/operations/security/executive), `requires_approval`/`approved_by`/`approved_at`, `has_conflict` |
| Self Learning Company (Phase 8) | `organizational_memory` — `category` CHECK IN (sales_pattern/complaint_resolution/successful_approach), `status` CHECK IN (candidate/approved/rejected/archived), `UNIQUE(org_id, dedup_key)` |

### 3.6 Marketplace, AI quality, lainnya
`ai_answer_quality` (skor akurasi/helpfulness/conversion per jawaban),
plus tabel `feedback_records`/`workflows`/`kb_generated_*`/`sessions`/
`ai_improvement_recommendations`/`marketplace_templates`/`tenant_template_installs`
(idempotent guard, lihat catatan §1).

## 4. Pola desain skema yang konsisten di seluruh proyek

1. **UUID PK** (`uuid_generate_v4()`) di semua tabel tenant.
2. **`ON DELETE CASCADE`** dari child ke `organizations`/parent entity utama
   — menghapus tenant otomatis membersihkan semua datanya.
3. **`UNIQUE(org_id, dedup_key)` + upsert idempoten** untuk tabel hasil scan
   otomatis (`ai_improvement_recommendations`, `organizational_memory`) —
   scan ulang me-refresh data, tapi **tidak pernah menimpa kolom `status`**
   yang sudah diputuskan manusia.
4. **Index `(org_id, status, ...)`** di setiap tabel yang sering difilter per
   status dashboard, supaya query dashboard tetap cepat dengan banyak tenant.
5. **Gotcha asyncpg yang sudah pernah dikoreksi** (lihat memory teknis
   proyek): interval native (`INTERVAL '1 day' * $N`, bukan string concat),
   `FILTER` menempel langsung ke aggregate bukan ke `ROUND()` pembungkus,
   kolom `TIMESTAMPTZ` di request body harus tipe `datetime` bukan `str`.
