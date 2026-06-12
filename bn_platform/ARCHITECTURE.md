# BotNesia Business Platform (Phase 2) — Arsitektur

> Status: implementasi production-ready, siap diintegrasikan. Modul ini
> **memperluas** BotNesia (`main.py`) menjadi SaaS multi-tenant siap jual ke
> ribuan bisnis — TANPA rebuild. Lihat juga [`intelligence/ARCHITECTURE.md`](../intelligence/ARCHITECTURE.md)
> untuk Phase 1 (Conversation Memory, FAQ, Sales Intelligence, Knowledge Graph).

Prinsip desain: **SCALABLE · SECURE · MODULAR · MULTI-TENANT · SAAS-READY · ENTERPRISE-READY**

---

## 0. Keputusan Arsitektur Kunci

| Keputusan | Alasan |
|---|---|
| **Tidak membuat tabel `tenants` baru** — `organizations.id` BERPERAN sebagai `tenant_id`, ditambah VIEW kompatibilitas `tenants` | `organizations` sudah jadi unit penyewa (punya `plan`, `bot_limit`, `billing_status`, FK dari `users`/`bots`/dst). Tabel baru akan memecah graph FK & memaksa migrasi data besar — bertentangan dengan instruksi "jangan rebuild". |
| **Package `bn_platform`, bukan `platform`** | `platform` adalah modul stdlib Python (`/usr/lib/python3.12/platform.py`) — penamaan itu akan menimpa import stdlib di seluruh proses. |
| **Pola Factory Function untuk router** (`build_xxx_router(*, get_pool, get_current_user, require_permission, ...)`) | `main.py` (107 KB) sudah mendefinisikan `get_pool`, `get_current_user`, `hash_password`, `dispatch_webhook`, `cfg` di tengah file. Modul `bn_platform.*` TIDAK BOLEH `from main import ...` di top-level (circular import). Sebaliknya, `main.py` memanggil factory ini di **paling bawah file**, setelah semua dependency tsb terdefinisi, lalu `app.include_router(...)`. Pola ini identik dgn cara `routes_intelligence.py` di-include ke `agent_api.py`. |
| **Migrasi RBAC "lazy" (on-the-fly), bukan skrip migrasi data massal** | `users.role` lama (TEXT bebas: owner/admin/member/...) dipetakan ke role RBAC baru saat pertama kali `get_user_permissions()` dipanggil, lalu dipersist ke `user_roles`. Tidak perlu downtime/migrasi big-bang utk 100rb+ user. |
| **Revenue Intelligence di-gate `PLATFORM_ADMIN_EMAILS`, bukan RBAC tenant** | MRR/ARR/Churn adalah milik OPERATOR PLATFORM (BotNesia), bukan data tenant. Pragmatis utk tahap ini — gantikan dgn role `superadmin`/SSO internal sebelum scale besar (lihat §10). |
| **Enkripsi kredensial channel pakai Fernet (simetris), bukan KMS eksternal** | Cukup utk skala awal, tidak menambah dependency infrastruktur (Vault/KMS). `CHANNEL_ENCRYPTION_KEY` di `.env`/secret K8s — upgrade ke KMS terkelola saat audit enterprise menuntutnya. |

---

## 1. Struktur Folder

```
ai bisnis/
├── main.py                       # BotNesia core API (existing) — app FastAPI utama
│                                 #   + WIRING Phase 2 di paling bawah file (lihat §9)
├── agent_api.py                  # Multi-agent FastAPI app terpisah (existing, tidak disentuh)
├── schema.sql                    # Skema inti existing (organizations/users/bots/conversations/...)
├── requirements.txt              # + cryptography, prometheus-client (lihat §0 deps baru)
├── docker-compose.yml            # + service api, postgres exporter, prometheus, grafana (lihat §8)
├── Dockerfile                    # existing, dipakai bersama oleh semua service Python
│
├── intelligence/                 # ══ PHASE 1 — Intelligence Platform (existing) ══
│   └── ...                       #   (Conversation Memory, FAQ, Sales, Knowledge Graph, Auto-Learning)
│
└── bn_platform/                  # ══ PHASE 2 — BUSINESS PLATFORM (BARU) ══
    ├── __init__.py               # PLATFORM_VERSION, dokumentasi pola factory
    ├── ARCHITECTURE.md           # dokumen ini
    ├── config.py                 # PlatformSettings (Midtrans/Xendit/Telegram/enkripsi/SLA/.env)
    ├── schema_platform.sql       # Skema baru: RBAC, billing, handoff, omnichannel, dst (lihat §2)
    │
    ├── rbac.py                   # 1. MULTI-TENANT & RBAC — roles/permissions/middleware
    ├── billing.py                # 2. SUBSCRIPTION & BILLING — plans, Midtrans, Xendit, invoice
    ├── handoff.py                # 3. HUMAN HANDOFF — antrian eskalasi AI→manusia + SLA
    ├── omnichannel.py            # 4. OMNICHANNEL — WhatsApp/Telegram/Website → Unified Inbox
    │                             #    (Admin Dashboard §5 & Customer 360 §6 memakai endpoint
    │                             #     gabungan dari modul² ini + intelligence/customer_profiles —
    │                             #     lihat §5/§6 utk daftar endpoint yg relevan, tanpa modul terpisah)
    ├── security.py               # 7. SECURITY — encrypt/decrypt, audit log, API key, security scan
    ├── observability.py          # 8. OBSERVABILITY — Prometheus middleware + /metrics + helper token usage
    ├── observability_dashboard.json  #    contoh dashboard Grafana (import langsung)
    ├── prometheus.yml.example    #    contoh scrape config Prometheus
    ├── lead_engine.py            # 10. LEAD GENERATION ENGINE — scoring cold/warm/hot + rekomendasi
    ├── marketplace.py            # 11. MARKETPLACE — katalog 6 template + instal 1-klik
    └── revenue_intel.py          # 12. REVENUE INTELLIGENCE — MRR/ARR/Churn/LTV/CAC + proyeksi
```

> Catatan subsistem #5 (Admin Dashboard) & #6 (Customer 360): **tidak dibuat sebagai modul
> terpisah** karena datanya adalah agregasi lintas modul yang sudah ada (conversation
> analytics existing di `main.py`/`analytics.py`, `intelligence.customer_profiles`,
> `bn_platform.lead_engine`, `bn_platform.omnichannel.inbox_summary`,
> `bn_platform.revenue_intel`). Endpoint untuk kedua dashboard ini didaftarkan
> langsung dari `main.py` sebagai query gabungan ringan (lihat §9.4) — menghindari
> duplikasi logic & menjaga "satu sumber kebenaran" per data.

### 1.1 Subsistem #9 — AI Quality System

Subsistem ini **dibangun di atas** tabel `ai_answer_quality` (lihat §2, dideklarasikan
di `schema_platform.sql`) dan terintegrasi langsung ke loop self-improvement
**Phase 1** yang sudah berjalan di `intelligence/nightly_jobs.py`
(Auto-Learning — re-skor `faq_entries.success_score`/`conversion_score`). Skor
kualitas per jawaban (`accuracy`/`helpfulness`/`conversion_impact`/`overall_score`)
ditulis oleh `EscalationAgent`/`SalesAgent` existing (lewat helper `record_answer_quality()`
yang akan ditambahkan di `intelligence/conversation_memory.py` saat wiring §9.2 — pola
identik dgn `record_sales_signal()` yang sudah ada) lalu dibaca kembali oleh nightly
job untuk menyesuaikan bobot FAQ. Tidak perlu modul `bn_platform` terpisah — ini
murni perluasan loop yang sudah ada, sesuai instruksi "gunakan codebase existing".

---

## 2. Skema Database (ERD) — `schema_platform.sql`

```
organizations (= TENANT, existing) ─────────────────────────────────────────────┐
   id, name, slug, plan, billing_status, bot_limit, conv_limit, doc_limit       │
   │                                                                             │
   ├─ VIEW tenants              ── alias kompatibilitas (tenant_id = o.id)      │
   │                                                                             │
   ├──< roles (org_id NULL = role sistem: owner/admin/manager/agent/viewer)     │
   │       │                                                                     │
   │       ├──< role_permissions >── permissions (17 entri: bots.*, billing.*, │
   │       │                                       conversations.*, rbac.*, …)  │
   │       │                                                                     │
   │       └──< user_roles >── users (existing; users.role lama dimigrasi lazy) │
   │                                                                             │
   ├──< subscriptions ──> plans (Free/Starter/Pro/Business/Enterprise;          │
   │       │                     max_conversations/agents/users/knowledge/      │
   │       │                     channels, features JSONB, -1 = unlimited)      │
   │       │                                                                     │
   │       ├──< invoices ──< payment_history                                    │
   │       │      (provider: midtrans|xendit, status, due_date,                │
   │       │       provider_invoice_id/payment_url, raw_payload)               │
   │       │                                                                     │
   ├──< channel_accounts (whatsapp|telegram|website|instagram|email|gmail;     │
   │       │               kredensial terenkripsi Fernet via security.py)       │
   │       │                                                                     │
   ├──< bots ─┬──< conversations ─┬──< messages                  (existing)    │
   │          │   (+ channel_account_id, assigned_agent_id,                    │
   │          │      unread_count, closed_at — kolom baru via ALTER TABLE)     │
   │          │         │                                                       │
   │          │         ├──< human_queue (reason, priority low→urgent,         │
   │          │         │      status waiting/claimed/assigned/resolved,       │
   │          │         │      assigned_agent_id, sla_due_at)                  │
   │          │         │                                                       │
   │          │         └──< ai_answer_quality (per message_id; accuracy/      │
   │          │                helpfulness/conversion_impact/overall_score)    │
   │          │                                                                 │
   │          └─ VIEW unified_inbox  (gabung conversation+human_queue+channel; │
   │                inbox_state ∈ escalation|closed|assigned|unread)           │
   │                                                                             │
   ├──< lead_scores (snapshot riwayat: score 0-100, category cold/warm/hot,    │
   │       signals JSONB, recommended_action) — lihat lead_engine.py            │
   │                                                                             │
   ├──< tenant_template_installs >── marketplace_templates                     │
   │       (6 template: Toko Online/Travel/Klinik/Pesantren/Properti/UMKM;     │
   │        system_prompt, greeting, primary_color, sample_faqs JSONB)         │
   │                                                                             │
   ├──< audit_logs (actor_user_id/email, action, resource_type/id,             │
   │       ip_address, user_agent, metadata JSONB)                              │
   │                                                                             │
   └──< revenue_snapshots (org_id NULL = agregat platform-wide;                │
          mrr/arr/churn_rate/ltv/cac/projected_mrr per snapshot_date)          │
                                                                                 │
api_keys (existing) ── + kolom scopes TEXT[] (ALTER TABLE, lihat security.py) ──┘
```

### 2.1 Tipe ENUM baru
`permission_scope_t`, `handoff_priority_t` (low<medium<high<urgent — terurut utk `GREATEST()`),
`handoff_status_t`, `channel_type_t`, `subscription_status_t`, `invoice_status_t`,
`payment_provider_t`, `lead_category_t`, `audit_action_t`.

### 2.2 Seed data (otomatis ter-load saat `schema_platform.sql` dieksekusi)
- **5 paket langganan**: Free, Starter, Pro, Business, Enterprise — lengkap dengan limit
  `max_conversations_per_month`, `max_agents`, `max_users`, `max_knowledge_docs`, `max_channels`
- **17 permission** dalam katalog (`bots.create`, `bots.delete`, `billing.manage`,
  `conversations.read`, `rbac.manage`, `apikeys.manage`, `marketplace.install`, dst)
- **5 role sistem** (org_id NULL — dipakai lintas tenant): Owner (semua izin),
  Admin (semua kecuali `billing.manage`/`bots.delete`), Manager, Agent, Viewer
  — masing² dengan `role_permissions` terisi sesuai matriks tanggung jawab
- **6 template marketplace** lengkap dengan konten Bahasa Indonesia siap pakai

### 2.3 Migration — cara menjalankan

```bash
# Skema baru bersifat ADDITIVE (CREATE TABLE IF NOT EXISTS / ALTER TABLE ... ADD COLUMN IF NOT EXISTS)
# — aman dijalankan di database existing tanpa downtime.
psql "$DATABASE_URL" -f schema.sql                       # baseline (no-op jika sudah ada)
psql "$DATABASE_URL" -f intelligence/schema_intelligence.sql
psql "$DATABASE_URL" -f bn_platform/schema_platform.sql  # ⭐ migrasi Phase 2

# atau via Docker Compose (volume init-db, lihat docker-compose.yml §8):
docker compose exec postgres psql -U botnesia -d botnesia -f /docker-entrypoint-initdb.d/03_schema_platform.sql
```

Tidak ada *data migration* terpisah untuk RBAC — pemetaan `users.role` lama →
role baru terjadi **lazy** di `rbac.get_user_permissions()` saat user login pertama
kali setelah deploy (lihat `_legacy_role_key()` di `rbac.py`).

---

## 3. API Endpoints (lengkap)

Semua endpoint di-mount dengan prefix `/api` mengikuti konvensi `main.py` existing
(lihat §9 untuk detail `include_router(prefix="/api")`), KECUALI webhook (top-level,
karena URL-nya didaftarkan ke provider eksternal Midtrans/Xendit/Telegram).

### 3.1 RBAC & Multi-Tenant — `bn_platform.rbac` (`/api/rbac`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/rbac/permissions` | (login) | Katalog 17 permission |
| GET | `/rbac/roles` | (login) | Role tenant ini + role sistem |
| GET | `/rbac/me` | (login) | Role & permission user saat ini (memicu lazy-migration) |
| GET | `/rbac/team` | `rbac.manage` | Daftar anggota tim + role masing² |
| POST | `/rbac/assign` | `rbac.manage` | Berikan role ke user (+ audit log `role_change`) |
| POST | `/rbac/revoke` | `rbac.manage` | Cabut role dari user (+ audit log) |

### 3.2 Subscription & Billing — `bn_platform.billing` (`/api/billing`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/billing/plans` | (login) | Daftar 5 paket + limit & harga |
| GET | `/billing/subscription` | (login) | Langganan aktif tenant (auto-provision Free+trial) |
| GET | `/billing/usage` | (login) | Pemakaian vs limit (`check_limit`) per kategori |
| POST | `/billing/checkout` | `billing.manage` | Buat invoice + transaksi Midtrans/Xendit |
| POST | `/billing/cancel` | `billing.manage` | Batalkan langganan (`cancel_at_period_end`) |
| GET | `/billing/invoices` | `billing.manage` | Riwayat invoice |
| GET | `/billing/payments` | `billing.manage` | Riwayat pembayaran (`payment_history`) |
| POST | `/billing/webhooks/midtrans` | *(public, verifikasi SHA512)* | Callback notifikasi status Midtrans |
| POST | `/billing/webhooks/xendit` | *(public, verifikasi `x-callback-token`)* | Callback notifikasi Xendit |

### 3.3 Human Handoff — `bn_platform.handoff` (`/api/handoff`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/handoff/queue` | `conversations.read` | Antrian eskalasi (filter status/priority) |
| GET | `/handoff/stats` | `conversations.read` | Statistik antrian (waiting/claimed/SLA breach) |
| GET | `/handoff/mine` | (login) | Item yang ditugaskan ke saya |
| POST | `/handoff/{id}/claim` | `conversations.assign` | Klaim item antrian |
| POST | `/handoff/{id}/assign` | `conversations.assign` | Tugaskan ke agent tertentu |
| POST | `/handoff/{id}/resolve` | `conversations.assign` | Tandai selesai ditangani |

### 3.4 Omnichannel & Unified Inbox — `bn_platform.omnichannel` (`/api`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/channels` | `settings.manage` | Daftar channel terhubung |
| POST | `/channels/connect` | `settings.manage` | Hubungkan WA/Telegram/Website (+setup webhook Telegram otomatis) |
| DELETE | `/channels/{id}` | `settings.manage` | Putuskan channel |
| GET | `/inbox` | `conversations.read` | Unified Inbox (filter state/channel) |
| GET | `/inbox/summary` | `conversations.read` | Ringkasan unread/assigned/closed/escalation per channel |
| POST | `/webhooks/telegram/{org_id}` | *(public, verifikasi secret token)* | Inbound message Telegram → routing ke AI/agent |

### 3.5 Lead Generation Engine — `bn_platform.lead_engine` (`/api/leads`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/leads` | `analytics.read` | Daftar leads + skor & rekomendasi (filter cold/warm/hot) |
| GET | `/leads/summary` | `analytics.read` | Ringkasan funnel (jumlah per kategori) |
| POST | `/leads/recompute` | `analytics.read` | Hitung ulang skor (on-demand / dipicu nightly job) |

### 3.6 Marketplace Template — `bn_platform.marketplace` (`/api/marketplace`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/marketplace/templates` | (login) | Katalog 6 template |
| GET | `/marketplace/templates/{key}` | (login) | Detail 1 template |
| POST | `/marketplace/install` | `marketplace.install` | Instal 1-klik (cek limit `max_agents`) |
| GET | `/marketplace/installs` | (login) | Riwayat instalasi tenant ini |

### 3.7 Security Enterprise — `bn_platform.security` (`/api/security`)
| Method | Path | Permission | Keterangan |
|---|---|---|---|
| GET | `/security/audit-logs` | `audit.read` | Jejak audit (filter action/resource_type) |
| POST | `/security/scan` | `audit.read` | Jalankan automated security scan (skor 0-100) |
| GET | `/security/api-keys` | `apikeys.manage` | Daftar API key (tanpa expose hash) |
| PATCH | `/security/api-keys/{id}/scopes` | `apikeys.manage` | Atur scope granular API key |
| DELETE | `/security/api-keys/{id}` | `apikeys.manage` | Cabut (revoke, soft-delete `is_active=FALSE`) |

> Pembuatan API key tetap memakai `POST /api-keys` existing di `main.py` (sudah
> menangani plan-gating & hashing `bn_live_...`) — endpoint di atas MELENGKAPI,
> bukan menggantikan.

### 3.8 Revenue Intelligence — `bn_platform.revenue_intel` (`/api/revenue`)
*(khusus operator platform — gate `PLATFORM_ADMIN_EMAILS`, lihat §0)*

| Method | Path | Keterangan |
|---|---|---|
| GET | `/revenue/overview` | MRR/ARR/Churn/LTV/CAC + rasio LTV:CAC + proyeksi |
| GET | `/revenue/trend` | Tren historis dari `revenue_snapshots` (default 90 hari) |
| POST | `/revenue/snapshot/run` | Generate snapshot harian (idealnya dipicu Celery beat) |

### 3.9 Observability — `bn_platform.observability`
| Method | Path | Keterangan |
|---|---|---|
| GET | `/metrics` | Format teks Prometheus (opsional `Authorization: Bearer <METRICS_AUTH_TOKEN>`) |

---

## 4. Arsitektur Keamanan (Security Architecture)

```
┌──────────────────────────────────────────────────────────────────────┐
│ LAPISAN 1 — TRANSPORT & EDGE                                         │
│   • HTTPS wajib (TLS terminasi di reverse proxy/Ingress)            │
│   • Rate limiting per-org (rate_limiter.py existing, PlanTier enum) │
│   • Webhook signature verification:                                  │
│       - Midtrans: SHA512(order_id+status_code+gross_amount+key)     │
│       - Xendit:   x-callback-token header == XENDIT_CALLBACK_TOKEN  │
│       - Telegram: x-telegram-bot-api-secret-token header            │
│       - Outbound (dispatch_webhook existing): HMAC-SHA256 payload   │
├──────────────────────────────────────────────────────────────────────┤
│ LAPISAN 2 — AUTENTIKASI & OTORISASI                                  │
│   • JWT (python-jose, HS256) — create_token/get_current_user existing│
│   • API Key (bn_live_..., hash via passlib) — bn_platform.security  │
│   • RBAC granular: 17 permission × 5 role sistem + role custom org  │
│     → require_permission("xxx.yyy") sbg FastAPI dependency (403)    │
│   • Isolasi data ketat: SETIAP query difilter `WHERE org_id = $1`   │
│     dari `user["org_id"]` (JWT) — Company A tidak bisa lihat data B │
├──────────────────────────────────────────────────────────────────────┤
│ LAPISAN 3 — DATA AT REST                                            │
│   • Password: passlib (bcrypt/sha256_crypt — existing)              │
│   • Kredensial channel (token WA/Telegram): Fernet AES-128-CBC+HMAC │
│     prefix "enc:" — kunci CHANNEL_ENCRYPTION_KEY (32-byte b64url)   │
│   • API key: hanya hash (bcrypt) + prefix tersimpan, raw key sekali │
│     tampil saat dibuat                                              │
├──────────────────────────────────────────────────────────────────────┤
│ LAPISAN 4 — AUDIT & DETEKSI                                         │
│   • audit_logs: actor, action, resource, IP, user-agent, metadata   │
│     — ditulis utk role_change, billing/payment, security_scan,      │
│       create/update/delete resource sensitif                        │
│   • run_security_scan(): 5 pemeriksaan otomatis →                   │
│       1) API key kedaluwarsa/tidak terpakai >90 hari (medium)       │
│       2) User non-aktif yg masih punya role Owner/Admin (high)      │
│       3) Webhook tanpa HTTPS (high)                                  │
│       4) Kredensial channel tersimpan tanpa enkripsi (critical)     │
│       5) Trial akan berakhir tanpa metode pembayaran (low)          │
│     → skor 0-100 (kurangi: critical 30 / high 15 / medium 7 / low 2)│
│   • Dijadwalkan via Celery beat (nightly) ATAU dipicu manual Owner  │
├──────────────────────────────────────────────────────────────────────┤
│ LAPISAN 5 — OBSERVABILITY & RESPON                                   │
│   • Prometheus metrics (request rate/latency/error/token usage)     │
│   • Audit log + security scan → early warning sebelum insiden       │
│   • SLA Human Handoff (15/60/240/1440 menit per prioritas) →        │
│     mencegah keluhan pelanggan dibiarkan tanpa respon manusia       │
└──────────────────────────────────────────────────────────────────────┘
```

**Checklist hardening sebelum go-live (di luar scope kode, operasional):**
1. Generate & set `CHANNEL_ENCRYPTION_KEY`, `SECRET_KEY`, `METRICS_AUTH_TOKEN` unik per environment (jangan pakai default).
2. Set `PLATFORM_ADMIN_EMAILS` — tanpa ini endpoint Revenue Intelligence terbuka untuk semua user terotentikasi (ada warning log).
3. Aktifkan TLS di Ingress/reverse proxy; jangan expose port DB/Redis/Prometheus ke publik.
4. Jadwalkan `POST /security/scan` & `POST /revenue/snapshot/run` via Celery beat (lihat `celery_app.py` existing — tambahkan entry baru, pola sama dgn `NIGHTLY_JOB_HOUR`).
5. Audit `PERMISSIONS`/`SYSTEM_ROLE_PERMISSIONS` di `rbac.py` tetap sinkron dgn seed di `schema_platform.sql` saat menambah fitur baru.

---

## 5. Observability — Prometheus + Grafana

```
                ┌─────────────┐   scrape /metrics   ┌────────────┐   query   ┌─────────┐
  uvicorn main:app middleware │  ◄──────────────────│ Prometheus │ ◄─────────│ Grafana │
  (instrument_app)            │   (15s interval)    │            │  (dash)   │         │
                ┌─────────────┘                     └────────────┘           └─────────┘
```

- `instrument_app(app)` memasang **ASGI middleware** yang mencatat tiap request
  (route TEMPLATE — bukan raw URL — supaya cardinality terkendali) ke:
  `bn_http_requests_total`, `bn_http_request_duration_seconds` (histogram p50/p95/p99),
  `bn_http_requests_in_progress`, `bn_http_errors_total`.
- Helper `record_token_usage(org_id, model, prompt_tokens, completion_tokens)` —
  panggil dari `intelligence/llm.py` (`call_llm`) setelah tiap respons LLM untuk
  metrik `bn_ai_tokens_total{org_id, model, kind}` (dashboard biaya per tenant).
- Helper `record_ai_request(agent, success, duration_seconds)` — opsional,
  panggil dari `supervisor.py` setelah tiap pemanggilan agent.
- `/metrics` mengekspos juga metrik proses bawaan (`bn_process_cpu_seconds_total`,
  `bn_process_resident_memory_bytes`) dari `ProcessCollector` prometheus_client.
- Import `bn_platform/observability_dashboard.json` langsung ke Grafana
  (Dashboards → Import → Upload JSON) — berisi 9 panel siap pakai (request rate,
  error rate, latency percentile, AI agent throughput/latency, token usage per
  tenant, CPU/RAM, DB pool).
- Contoh scrape config: `bn_platform/prometheus.yml.example`.

---

## 6. Deployment — Docker & Kubernetes

### 6.1 Docker Compose (tambahan ke `docker-compose.yml` existing)

`docker-compose.yml` saat ini sudah punya `postgres`, `redis`, `agent_api`,
`celery-worker`, `celery-beat`. **Tambahkan** service berikut (gunakan image
`build: .` yang sama — `Dockerfile` existing sudah meng-install semua dependency
termasuk `prometheus-client`/`cryptography` setelah `requirements.txt` di-update):

```yaml
  api:                      # ⭐ BotNesia core API (main.py) — customer-facing, multi-tenant
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-botnesia}:${POSTGRES_PASSWORD:-botnesia}@postgres:5432/botnesia
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    ports: ["8000:8000"]
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

  prometheus:
    image: prom/prometheus:v2.55.0
    restart: unless-stopped
    volumes:
      - ./bn_platform/prometheus.yml.example:/etc/prometheus/prometheus.yml:ro
      - promdata:/prometheus
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:11.2.0
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
    volumes:
      - grafanadata:/var/lib/grafana
    ports: ["3000:3000"]
    depends_on: [prometheus]

# tambahkan ke `volumes:` existing:
#   promdata:
#   grafanadata:
```

Juga tambahkan baris init-db di service `postgres` (volumes), urut setelah
`02_schema_intelligence.sql` (Postgres mengeksekusi file `*.sql` di
`/docker-entrypoint-initdb.d/` secara alfabetis):

```yaml
      - ./bn_platform/schema_platform.sql:/docker-entrypoint-initdb.d/03_schema_platform.sql:ro
```

> Catatan: file init-db HANYA dieksekusi saat volume `pgdata` PERTAMA KALI dibuat
> (`docker-entrypoint-initdb.d` adalah mekanisme bootstrap, bukan migrator). Untuk
> database yang SUDAH berjalan, jalankan migrasi manual seperti di §2.3.

### 6.2 Kubernetes (manifest siap pakai)

Struktur direktori yang disarankan (buat `k8s/` di root project):

```
k8s/
├── namespace.yaml
├── configmap.yaml          # env non-rahasia (APP_URL, GROQ_MODEL, dst)
├── secret.yaml             # DATABASE_URL, SECRET_KEY, CHANNEL_ENCRYPTION_KEY,
│                           # MIDTRANS_SERVER_KEY, XENDIT_SECRET_KEY, dst
│                           # → buat via: kubectl create secret generic botnesia-secrets --from-env-file=.env
├── deployment-api.yaml     # main:app — Deployment + HPA (horizontal pod autoscaler)
├── deployment-agent-api.yaml
├── deployment-celery-worker.yaml
├── deployment-celery-beat.yaml
├── service.yaml            # ClusterIP utk api & agent-api
├── ingress.yaml            # TLS termination + routing /api → api, /intel → agent-api
└── servicemonitor.yaml     # Prometheus Operator: scrape /metrics otomatis
```

Contoh `deployment-api.yaml` (pola yang sama berlaku utk `agent-api`/`celery-*`,
ganti `command`/`image`/`ports` sesuai service):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: botnesia-api
  namespace: botnesia
spec:
  replicas: 3
  selector:
    matchLabels: { app: botnesia-api }
  template:
    metadata:
      labels: { app: botnesia-api }
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8000"
    spec:
      containers:
        - name: api
          image: ghcr.io/yourorg/botnesia:latest
          command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
          ports: [{ containerPort: 8000 }]
          envFrom:
            - configMapRef: { name: botnesia-config }
            - secretRef:    { name: botnesia-secrets }
          readinessProbe:
            httpGet: { path: /health, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /health, port: 8000 }
            initialDelaySeconds: 20
            periodSeconds: 30
          resources:
            requests: { cpu: "250m", memory: "512Mi" }
            limits:   { cpu: "1",    memory: "1Gi" }
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: botnesia-api-hpa
  namespace: botnesia
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: botnesia-api }
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } }
```

`servicemonitor.yaml` (jika memakai Prometheus Operator/kube-prometheus-stack):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: botnesia-api
  namespace: botnesia
spec:
  selector: { matchLabels: { app: botnesia-api } }
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      bearerTokenSecret: { name: botnesia-secrets, key: METRICS_AUTH_TOKEN }
```

**Skalabilitas**: app layer stateless (semua state di Postgres/Redis) — replika
`botnesia-api` bisa ditambah horizontal di belakang Ingress/load balancer tanpa
sticky session. Untuk >100rb pelanggan/jutaan percakapan: pertimbangkan
read-replica Postgres untuk query analitik berat (`/revenue/*`, `/leads`,
`unified_inbox`), serta partitioning tabel `messages`/`audit_logs`/`lead_scores`
per bulan (lihat catatan skala di `intelligence/ARCHITECTURE.md`).

---

## 7. Skrip Migrasi

Karena seluruh skema Phase 2 bersifat **aditif** (`CREATE TABLE IF NOT EXISTS`,
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE OR REPLACE VIEW`, `ON CONFLICT
DO NOTHING` untuk seed), tidak diperlukan tooling migrasi (Alembic dkk) — cukup:

```bash
#!/usr/bin/env bash
# bn_platform/migrate.sh — jalankan migrasi Phase 2 ke database existing
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL env var dulu, mis. postgresql://user:pass@host/db}"

echo "→ Menjalankan schema_platform.sql ..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$(dirname "$0")/schema_platform.sql"

echo "→ Memverifikasi tabel kunci ..."
psql "$DATABASE_URL" -tAc "
  SELECT string_agg(table_name, ', ') FROM information_schema.tables
  WHERE table_schema='public' AND table_name IN
    ('roles','permissions','subscriptions','plans','human_queue',
     'channel_accounts','audit_logs','lead_scores','marketplace_templates',
     'revenue_snapshots','ai_answer_quality')"

echo "✓ Migrasi Phase 2 selesai."
```

Simpan sebagai `bn_platform/migrate.sh` (`chmod +x`), jalankan dengan
`DATABASE_URL=postgresql://... ./bn_platform/migrate.sh`. Skrip ini **idempotent**
— aman dijalankan ulang (mis. di setiap deploy CI/CD) tanpa efek samping.

Untuk rollback: karena bersifat aditif, rollback cukup berarti "berhenti memakai"
tabel/kolom baru — TIDAK disarankan `DROP TABLE` di produksi (lihat checklist
keamanan §4). Jika benar² perlu, audit dulu FK dependency (`role_permissions`,
`user_roles`, `subscriptions`, dst mereferensikan `organizations`/`users`/`bots`).

---

## 8. Panduan Integrasi Step-by-Step ke `main.py`

> **PENTING**: jangan modifikasi `agent_api.py` — itu adalah app FastAPI terpisah
> untuk pipeline AI agent. Semua router Phase 2 (kecuali yang memang butuh akses
> ke pipeline AI, lihat §8.3) didaftarkan ke `main.py` (107 KB, app customer-facing
> yang sudah punya auth/orgs/users/bots/webhooks).

### 8.1 Update dependency

```bash
pip install -r requirements.txt   # sudah ditambah: cryptography, prometheus-client
```

Generate kunci enkripsi & tambahkan ke `.env`:
```bash
python -c "from cryptography.fernet import Fernet; print('CHANNEL_ENCRYPTION_KEY=' + Fernet.generate_key().decode())" >> .env
```

Tambahkan variabel `.env` lain sesuai kebutuhan (lihat `bn_platform/config.py`
untuk daftar lengkap & nilai default): `MIDTRANS_SERVER_KEY`, `MIDTRANS_CLIENT_KEY`,
`XENDIT_SECRET_KEY`, `XENDIT_CALLBACK_TOKEN`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_WEBHOOK_SECRET`, `PLATFORM_ADMIN_EMAILS`, `METRICS_AUTH_TOKEN`,
`MONTHLY_MARKETING_SPEND_IDR`.

### 8.2 Jalankan migrasi skema

```bash
DATABASE_URL=postgresql://... ./bn_platform/migrate.sh
# atau langsung: psql "$DATABASE_URL" -f bn_platform/schema_platform.sql
```

### 8.3 Tambahkan blok wiring di `main.py` (PALING BAWAH FILE)

Tempatkan blok ini **setelah** definisi `dispatch_webhook` (≈ baris 2885) dan
endpoint `create_api_key`/`health` (≈ baris 2912-2962) — yaitu di akhir file,
karena factory butuh `get_pool`, `get_current_user`, `hash_password`, `cfg`,
`dispatch_webhook` yang semuanya sudah terdefinisi pada titik ini:

```python
# ═══════════════════════════════════════════════════════════════
# PHASE 2 — BUSINESS PLATFORM (bn_platform) — wiring
# ═══════════════════════════════════════════════════════════════
from bn_platform.rbac import make_permission_checker, build_rbac_router
from bn_platform.billing import build_billing_router, check_limit
from bn_platform.handoff import build_handoff_router
from bn_platform.omnichannel import build_omnichannel_router
from bn_platform.lead_engine import build_lead_router
from bn_platform.marketplace import build_marketplace_router
from bn_platform.revenue_intel import build_revenue_router
from bn_platform.security import build_security_router, write_audit_log
from bn_platform.observability import instrument_app

# 1) Instrumentasi Prometheus (middleware + GET /metrics)
instrument_app(app)

# 2) Dependency RBAC `require_permission("xxx.yyy")` — dipakai semua router di bawah
require_permission = make_permission_checker(get_current_user=get_current_user, get_pool=get_pool)

# 3) Adapter routing pesan masuk Telegram → pipeline AI existing.
#    Pola IDENTIK dengan `_meta_route_and_reply_whatsapp` (≈ baris 2021) — PAKAI ULANG
#    fungsi tsb / SupervisorAgent yang sama, jangan duplikasi logic pemrosesan AI.
async def _route_inbound_platform_message(*, org_id, bot_id, channel, external_user_id, text, display_name):
    # TODO saat wiring: panggil persist+SupervisorAgent yang sama dgn jalur WhatsApp Meta,
    # lalu kembalikan teks balasan (string) — lihat _handle_meta_whatsapp_inbound (≈ baris 1964)
    # untuk pola persist conversation/message + pemanggilan supervisor.handle_message(...).
    raise NotImplementedError("Hubungkan ke SupervisorAgent — lihat _meta_route_and_reply_whatsapp")

# 4) Daftarkan semua router Phase 2 dengan prefix /api (konsisten dgn endpoint existing)
app.include_router(build_rbac_router(get_pool=get_pool, get_current_user=get_current_user), prefix="/api")
app.include_router(build_billing_router(get_pool=get_pool, get_current_user=get_current_user,
                                         require_permission=require_permission,
                                         dispatch_webhook=dispatch_webhook), prefix="/api")
app.include_router(build_handoff_router(get_pool=get_pool, get_current_user=get_current_user,
                                         require_permission=require_permission,
                                         dispatch_webhook=dispatch_webhook), prefix="/api")
app.include_router(build_omnichannel_router(get_pool=get_pool, get_current_user=get_current_user,
                                             require_permission=require_permission,
                                             app_url=cfg.app_url,
                                             route_inbound_message=_route_inbound_platform_message), prefix="/api")
app.include_router(build_lead_router(get_pool=get_pool, get_current_user=get_current_user,
                                      require_permission=require_permission), prefix="/api")
app.include_router(build_marketplace_router(get_pool=get_pool, get_current_user=get_current_user,
                                             require_permission=require_permission,
                                             check_limit=check_limit), prefix="/api")
app.include_router(build_revenue_router(get_pool=get_pool, get_current_user=get_current_user), prefix="/api")
app.include_router(build_security_router(get_pool=get_pool, get_current_user=get_current_user,
                                          require_permission=require_permission), prefix="/api")
```

> **Mengapa router omnichannel & billing tidak pakai prefix tambahan untuk webhook**:
> `build_omnichannel_router`/`build_billing_router` sudah mendefinisikan path lengkap
> `/webhooks/telegram/{org_id}` & `/billing/webhooks/midtrans|xendit` di dalam
> router-nya sendiri — `include_router(prefix="/api")` akan membuatnya menjadi
> `/api/webhooks/telegram/{org_id}` dst. **Sesuaikan `app_url`/URL yang didaftarkan
> ke provider eksternal (Telegram setWebhook, Midtrans/Xendit dashboard) agar
> menyertakan prefix `/api`** — atau hapus `prefix="/api"` khusus untuk
> `build_omnichannel_router`/`build_billing_router` jika ingin webhook tetap di
> top-level (tanpa `/api`). Pilih salah satu pendekatan & jaga konsistensi dengan
> `cfg.app_url` yang dipakai `omnichannel.py` saat membentuk `webhook_url`.

### 8.4 Daftarkan endpoint Admin Dashboard & Customer 360 (agregasi ringan)

Tambahkan langsung di `main.py` (dekat endpoint `/health` existing) — query
gabungan tipis di atas data yang SUDAH ADA, tanpa modul baru:

```python
@app.get("/api/dashboard/overview")
async def dashboard_overview(user=Depends(get_current_user), pool=Depends(get_pool)):
    # gabungkan: total chat (conversations), active users (DISTINCT end_user_id 30 hari),
    # conversion rate (sales_signals.resulted_in_purchase), faq growth (faq_entries created_at),
    # sales growth (sales_signals per minggu), lead score distribution (lead_engine.lead_funnel_summary)
    ...

@app.get("/api/customers/{end_user_id}/360")
async def customer_360(end_user_id: str, user=Depends(get_current_user), pool=Depends(get_pool)):
    # gabungkan: customer_profiles (Phase 1), riwayat conversations/messages,
    # sales_signals (riwayat pembelian/komplain), lead_scores terbaru + recommended_action
    ...
```

(Kerangka query SQL untuk kedua endpoint tinggal menggabungkan SELECT yang sudah
ada di `analytics.py`/`intelligence/reports.py`/`lead_engine.list_leads` — JOIN
melalui `bot_id`+`end_user_id`, semua sudah terindeks.)

### 8.5 (Opsional) Hubungkan AI Quality System ke Auto-Learning

Di `intelligence/conversation_memory.py`, tambahkan helper `record_answer_quality()`
(pola sama dgn `record_sales_signal()` existing) yang menulis ke `ai_answer_quality`
setiap kali `EscalationAgent`/`SalesAgent` selesai mengevaluasi sebuah respons.
`intelligence/nightly_jobs.py` lalu membaca rata-rata `overall_score` per `faq_id`/
`bot_id` untuk menyesuaikan `faq_entries.success_score` — menutup loop
self-improvement tanpa menambah Celery task baru (cukup extend task existing).

### 8.6 Verifikasi

```bash
uvicorn main:app --reload --port 8000
curl -s localhost:8000/health | jq
curl -s localhost:8000/api/billing/plans | jq         # publik (login required)
curl -s localhost:8000/metrics | head -30             # Prometheus text format
```

Login sebagai user existing → `GET /api/rbac/me` harus mengembalikan role hasil
migrasi lazy dari `users.role` lama. Buat org baru → `GET /api/billing/subscription`
harus auto-provision paket Free + trial 14 hari.

---

## 9. Ringkasan Pemetaan Spesifikasi → Implementasi

| # | Subsistem diminta | Implementasi |
|---|---|---|
| 1 | Multi-tenant + RBAC | `organizations`(=tenant) + VIEW `tenants`, `roles`/`permissions`/`role_permissions`/`user_roles`, `rbac.py` |
| 2 | Subscription + Payment | `plans`/`subscriptions`/`invoices`/`payment_history`, `billing.py` (Midtrans+Xendit) |
| 3 | Human Handoff | `human_queue`, `handoff.py` (`evaluate_handoff_trigger`, SLA per prioritas) |
| 4 | Omnichannel + Unified Inbox | `channel_accounts`, VIEW `unified_inbox`, `omnichannel.py` (WA existing + Telegram baru + Website existing) |
| 5 | Admin Dashboard | Endpoint agregasi di `main.py` §8.4 (di atas data existing + lead/inbox/revenue) |
| 6 | Customer 360 | Endpoint agregasi di `main.py` §8.4 (`customer_profiles` Phase 1 + sales_signals + lead_scores) |
| 7 | Security Enterprise | `security.py` (encrypt/decrypt, audit log, API key mgmt, automated scan); JWT/RBAC dari §1/§3.1 |
| 8 | Observability | `observability.py` (Prometheus middleware + `/metrics`), `observability_dashboard.json`, `prometheus.yml.example` |
| 9 | AI Quality System | `ai_answer_quality` table + perluasan loop Auto-Learning Phase 1 (lihat §1.1, §8.5) |
| 10 | Lead Generation Engine | `lead_scores`, `lead_engine.py` (skor komposit 0-100, kategori cold/warm/hot, rekomendasi) |
| 11 | Marketplace | `marketplace_templates`/`tenant_template_installs`, `marketplace.py` (6 template, instal 1-klik) |
| 12 | Revenue Intelligence | `revenue_snapshots`, `revenue_intel.py` (MRR/ARR/Churn/LTV/CAC + proyeksi regresi linear) |

---

## 10. Catatan Pengembangan Lanjutan (Post-Launch)

1. **Superadmin role** — ganti `PLATFORM_ADMIN_EMAILS` allowlist dengan role
   `superadmin` resmi (mis. tabel `platform_admins` + SSO internal) sebelum
   tim operasional bertambah besar.
2. **KMS terkelola** — migrasikan `CHANNEL_ENCRYPTION_KEY` dari `.env`/K8s Secret
   ke layanan KMS (AWS KMS/GCP KMS/HashiCorp Vault) untuk audit enterprise/SOC2.
3. **Read replica & partitioning** — saat volume >jutaan percakapan, tambahkan
   Postgres read-replica untuk endpoint analitik berat & partisi `messages`/
   `audit_logs`/`lead_scores` per bulan.
4. **Webhook scopes API key** — kolom `api_keys.scopes` (`TEXT[]`) sudah tersedia
   (lihat `PATCH /security/api-keys/{id}/scopes`); langkah berikut: terapkan
   pemeriksaan scope di middleware otentikasi API key (saat ini hanya dicek di
   level plan `scale`).
5. **CAC otomatis** — `compute_cac()` saat ini membaca `MONTHLY_MARKETING_SPEND_IDR`
   statis dari `.env`; integrasikan dengan API ads (Google/Meta Ads) untuk angka real-time.
