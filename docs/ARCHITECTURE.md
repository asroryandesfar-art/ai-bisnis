# BotNesia — Arsitektur Sistem (Master Overview)

> Dokumen ini adalah **peta navigasi** arsitektur BotNesia secara keseluruhan.
> Untuk detail mendalam per subsistem, lihat dokumen rujukan yang ditautkan di
> setiap bagian — dokumen ini tidak menduplikasi isinya, hanya menyatukan
> potongan-potongan yang sebelumnya tersebar di beberapa file.
>
> Status: production. Single Postgres instance, single FastAPI process per
> app (`main.py` dan `agent_api.py` terpisah), deployment saat ini di VM
> tunggal di belakang Cloudflare Tunnel (lihat [DEPLOYMENT.md](DEPLOYMENT.md)).

## 1. Lapisan sistem (tiga generasi pembangunan)

BotNesia dibangun dalam tiga gelombang besar, masing-masing **memperluas**
gelombang sebelumnya tanpa rebuild — prinsip ini dipegang konsisten di
seluruh proyek:

| Lapisan | Isi | Dokumen detail |
|---|---|---|
| **0 — Core** | `main.py`: auth, organizations/users/bots, chat pipeline, conversations/messages, dokumen & knowledge base, upload, webhook channel dasar | (tidak ada doc terpisah — baca `main.py` + `schema.sql`) |
| **1 — Intelligence Platform** | `intelligence/`: Conversation Memory, FAQ Engine, Sales Intelligence, Knowledge Graph, Auto-Learning malam hari (Celery beat) | [`intelligence/ARCHITECTURE.md`](../intelligence/ARCHITECTURE.md) |
| **2 — Business Platform** | `bn_platform/`: RBAC multi-tenant, billing & subscription, human handoff, omnichannel, security/audit, observability, lead generation, marketplace, revenue intelligence | [`bn_platform/ARCHITECTURE.md`](../bn_platform/ARCHITECTURE.md) |
| **3 — AI Workforce (Phase 1-10)** | 7 "karyawan AI" (Finance/Marketing/HR/Operations/Security/Executive/Workforce-Orchestrator) + Self-Learning Company + Enterprise Dashboard — **dijelaskan di bawah, belum punya doc detail terpisah sebelum dokumen ini** | §2 di bawah |

Catatan penomoran fase yang membingungkan jika dilihat di git log: ada DUA
urutan "Phase N" yang berbeda konteks — (a) fase pembangunan Business
Platform awal (Phase 2 platform, Phase 3 Multimodal, Phase 4 Marketplace),
dan (b) 10 fase "AI Workforce" yang dibangun belakangan (Finance Agent =
AI Workforce Phase 1, dst). Dokumen ini memakai penamaan **AI Workforce
Phase 1-10** secara konsisten untuk gelombang ketiga.

## 2. AI Workforce — 7 karyawan AI + orkestrasi + pembelajaran organisasi

Setiap "karyawan AI" adalah modul top-level (`<domain>_agent.py`) + router
`bn_platform/<domain>.py` (prefix `/api/<domain>`) + tabel domain sendiri di
`bn_platform/schema_platform.sql`. **Tidak ada satupun yang dipanggil dari
pipeline chat pelanggan (`main.py` `chat()` / `supervisor.py` `_process()`)**
— mereka hanya dapat diakses lewat endpoint REST `/api/*` yang
diautentikasi, dan didaftarkan ke `SupervisorAgent.__init__` murni sebagai
referensi (bukan dipanggil). Ini adalah keputusan keamanan yang disengaja:
AI Workforce mengelola operasional bisnis tenant, bukan menjawab pelanggan.

| Fase | Agent | File inti | Tabel | Fungsi |
|---|---|---|---|---|
| 1 | Finance Agent | `finance_agent.py` | `finance_invoices/payments/expenses/transactions/reports` | Invoice, expense, payment, revenue/profit/cashflow/forecast |
| 2 | Marketing Agent | `marketing_agent.py` | `marketing_campaigns/content/engagement` | Generate konten, content calendar, campaign analytics |
| 3 | HR Agent | `hr_agent.py` | `hr_candidates/employees/evaluations/training_records` | CV screening, scoring, evaluasi, rekomendasi training |
| 4 | Operations Agent | `operations_agent.py` | `ops_alerts`, `ops_reports` (`source='operations'`) | Health score tenant, SLA/workflow monitoring, alert, laporan berkala |
| 5 | Security Agent | `security_agent.py` | `ops_alerts`/`ops_reports` (`source='security'`, kolom ditambahkan via `ALTER TABLE`, bukan tabel baru) | Deteksi API abuse, cek isolasi tenant, risk score |
| 6 | Executive Agent | `executive_agent.py` | `ops_reports` (`source='executive'`) | Sintesis lintas-domain (asyncio.gather ke 5 agent lain), company health score, executive brief (satu-satunya LLM call lintas-domain) |
| 7 | Workforce Orchestrator | `workforce_orchestrator.py` | `workforce_tasks` | Task lintas-agent, deteksi konflik, eskalasi overdue, human approval gate |
| 8 | Self Learning Company | `self_learning_engine.py` | `organizational_memory` | Distilasi pola sales/komplain/approach sukses dari data percakapan nyata — **satu-satunya** modul AI Workforce yang menyuntik konteks (read-only, sudah human-approved) ke `main.py chat()` |
| 9 | Enterprise Dashboard | `frontend/app.js`/`components.js` | — | Konsolidasi nav "AI WORKFORCE" + halaman overview lintas-7-domain + dashboard utama berbasis data nyata |
| 10 | Dokumentasi | `docs/*.md` (dokumen ini) | — | — |

### 2.1 Pola keamanan yang berulang di setiap fase

1. **Reuse, don't rebuild** — Phase 5/6 memperluas tabel `ops_alerts`/`ops_reports`
   milik Phase 4 lewat kolom `source` baru, bukan membuat tabel paralel.
2. **Human-approval gate untuk keputusan berdampak** — setiap aksi yang
   benar-benar mengubah perilaku sistem (menyelesaikan task berisiko,
   menyetujui insight pembelajaran organisasi) butuh `*.approve` permission
   (owner/admin saja) dan kolom `approved_by`/`approved_at` eksplisit. Lihat
   [SECURITY.md](SECURITY.md) §4.
3. **Idempotent upsert yang tidak menimpa status manusia** — `ON CONFLICT
   (org_id, dedup_key) DO UPDATE SET ... ` selalu mengecualikan kolom
   `status` dari `SET`, supaya scan ulang tidak diam-diam membatalkan
   keputusan manusia yang sudah direview.
4. **Tidak ada LLM di hot path chat pelanggan** — `build_organizational_learning_context()`
   (Phase 8) murni query SQL read-only; satu-satunya LLM call lintas-domain
   (`ExecutiveAgent.generate_executive_brief()`) hanya dipanggil dari
   endpoint `/api/executive/reports/generate`, tidak pernah dari `/chat`.

## 3. Diagram alur permintaan (ringkas)

```
Pelanggan (WhatsApp/Telegram/Instagram/Website)
        │
        ▼
  Webhook channel (bn_platform/omnichannel.py)
        │
        ▼
  main.py chat()  ──▶  Supervisor (supervisor.py)  ──▶  Agent terpilih
        │                                                  (cs_agent / sales /
        │  + intelligence context (FAQ, sales pattern,      faq / dst — TIDAK
        │    customer profile dari intelligence/)            termasuk AI Workforce)
        │  + organizational learning context (read-only,
        │    Phase 8, hanya insight yang sudah di-approve)
        ▼
  Jawaban ke pelanggan + log ke conversation_analysis,
  ai_answer_quality, audit_logs


Pemilik bisnis / tim internal (dashboard web)
        │
        ▼
  frontend/app.js  ──▶  /api/{finance,marketing,hr,operations,
        │                  security,executive,workforce,learning}/*
        ▼               (RBAC-gated, org_id-scoped, audit-logged)
  bn_platform/<domain>.py router ──▶ <domain>_agent.py / engine
        │
        ▼
  PostgreSQL (org_id-scoped tables)
```

## 4. Struktur folder (ringkas — lihat [`bn_platform/ARCHITECTURE.md`](../bn_platform/ARCHITECTURE.md) §1 untuk versi lengkap Phase 2)

```
ai bisnis/
├── main.py                  # Core API: auth, org/user/bot, chat pipeline, upload
├── agent_api.py             # Multi-agent FastAPI app terpisah (legacy multi-agent demo)
├── supervisor.py            # Orkestrator agent customer-chat (TIDAK memanggil AI Workforce)
├── base.py                  # BaseAgent: _call_llm / _call_llm_json (Groq, multi-model)
├── schema.sql                # Skema core (organizations/users/bots/conversations/...)
│
├── intelligence/             # Lapisan 1 — Conversation Memory, FAQ, Sales, Knowledge Graph
│   ├── schema_intelligence.sql
│   └── ARCHITECTURE.md
│
├── bn_platform/              # Lapisan 2+3 — Business Platform + AI Workforce
│   ├── schema_platform.sql   # RBAC, billing, omnichannel, + semua tabel AI Workforce
│   ├── rbac.py / billing.py / omnichannel.py / security.py / ...   (Phase 2)
│   ├── finance.py / marketing.py / hr.py / operations.py /
│   │   executive.py / workforce.py / self_learning.py              (AI Workforce)
│   └── ARCHITECTURE.md       # Detail Phase 2 (RBAC/billing/omnichannel/dst)
│
├── finance_agent.py / marketing_agent.py / hr_agent.py /
│   operations_agent.py / security_agent.py / executive_agent.py /
│   workforce_orchestrator.py / self_learning_engine.py              # AI Workforce — logic agent
│
├── frontend/                 # SPA vanilla JS (app.js, components.js, api-client.js, styles.css)
│   └── public/assets/        # Logo, ikon statis
│
├── docs/                      # Dokumen ini + DATABASE/API/SECURITY/DEPLOYMENT.md
├── deploy/                    # Konfigurasi Cloudflare Tunnel
└── test_*.py (70+ file)        # Pytest, satu file per modul/agent
```

## 5. Dokumen rujukan

- [DATABASE.md](DATABASE.md) — semua tabel di 3 file schema, dikelompokkan per domain
- [API.md](API.md) — semua endpoint REST, diverifikasi langsung dari source (bukan tebakan)
- [SECURITY.md](SECURITY.md) — model auth, RBAC, enkripsi, audit, isolasi tenant, human-approval gate
- [DEPLOYMENT.md](DEPLOYMENT.md) — urutan migrasi, layanan systemd, runbook deploy production
- [`bn_platform/ARCHITECTURE.md`](../bn_platform/ARCHITECTURE.md) — detail Phase 2 (RBAC/billing/omnichannel/observability/marketplace/revenue intelligence)
- [`intelligence/ARCHITECTURE.md`](../intelligence/ARCHITECTURE.md) — detail Phase 1 (Conversation Memory/FAQ/Sales/Knowledge Graph)
- [`docs/DEPLOY_BOTNESIA_ID.md`](DEPLOY_BOTNESIA_ID.md) — runbook produksi Cloudflare Tunnel ke `botnesia.id`
