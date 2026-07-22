# ADR-0010 — Prompt Management (registry versi/rollback/A-B)

- **Status:** Accepted — paket `prompt_registry` + `BaseAgent.resolved_system_prompt` + API `/api/prompts` + UI panel selesai
- **Tanggal:** 2026-07-22 (UI + list-names: 2026-07-23)
- **Konteks fase:** Fase 3 (Efisiensi & Operabilitas), item **P2-B**
- **Terkait:** ADR-0002 (feature flag), ADR-0007 (Evaluation — kalibrasi varian), ADR-0009 (Cost Router), ADR-0015 (pola panel)

## Addendum (2026-07-23) — UI panel + discovery
Ditambah endpoint discovery **`GET /api/prompts`** (`PromptRegistry.list_names`):
ringkasan tiap prompt milik org (jumlah versi/varian/aktif/terbaru) — sebelumnya
API hanya keyed-by-name tanpa cara menemukan nama yang ada. Panel operator
**`frontend/prompt_registry.js`** (route `prompts` "Prompt Registry" di nav agent-os,
pola modul mandiri ADR-0015): daftar prompt (kiri) → tabel versi (kanan) dengan aksi
**Activate (rollback=exclusive)** / **A/B (non-exclusive)** / **Deactivate**, form
**Create version** (content/variant/weight/activate, datalist nama), dan **Resolve**
preview (versi/varian yang akan terpilih). Read+write via `/api/prompts/*` (RBAC
workforce.read/write). Additive; frontend statis. +1 test (list_names).

## Konteks
Prompt sistem tiap agen **hardcoded** sebagai class attribute (mis.
`CSAgent.system_prompt`). Tak ada riwayat versi, tak bisa rollback cepat saat
prompt regresi, dan tak bisa A/B (uji dua prompt lalu pilih yang skornya lebih
tinggi). Mengubah prompt = ubah kode + deploy → lambat & berisiko.

## Keputusan
Paket mandiri **`prompt_registry`**: tabel `agent_prompts` (riwayat versi immutable
per `name`+`org`+`variant`; `org_id` NULL = default global, baris ber-org menang).
`PromptRegistry(pool)`:
- `create_version` (auto-increment versi, opsional langsung aktif),
- `activate(version, exclusive)` — `exclusive=True` → **rollback** (tepat 1 aktif);
  `exclusive=False` → **A/B** (>1 varian aktif),
- `resolve` — pilih baris aktif; >1 varian → pilih **berbobot DETERMINISTIK**
  (`sha256(name:bucket_key) % total_weight`) agar org/sesi sama selalu dapat varian
  sama; tak ada baris aktif → fallback `default` (= prompt hardcoded).

Konsumsi via **`BaseAgent.resolved_system_prompt(org_id, bucket_key)`** — gate
`is_enabled("prompt_registry", org_id)`; OFF / registry kosong → `self.system_prompt`
**byte-identik**. API tenant `/api/prompts/*` (RBAC `workforce.read/write`,
rate-limited, org-scoped) untuk list/create/activate/deactivate/resolve.

## Alternatif
1. **Simpan prompt di kolom bot (`bots.system_prompt`).** Sudah ada untuk prompt per-bot end-user, tapi tak menutup prompt kelas agen internal (finance/hr/dst) & tak punya versi/A-B. Berbeda ranah.
2. **File YAML + reload.** Ditolak: tak per-tenant, tak A-B, butuh deploy/reload; DB lebih operabilitas-friendly & multi-tenant.
3. **Registry DB + fallback hardcoded (DIPILIH).** Additive, reversible (flag), per-tenant, versi+rollback+A-B, default byte-identik.

## Konsekuensi
**Positif:** ubah/rollback prompt tanpa deploy; A/B prompt lalu kalibrasi dari
`task_evaluations` (P1-D) — prompt terbaik menang berdasarkan skor, bukan tebakan.
**Batasan/GOTCHA:** resolusi menyentuh DB per panggilan saat flag ON (belum ada
cache in-proc — cukup untuk gate awal, tambah cache bila jadi hot path);
`resolved_system_prompt` fail-open (error → default) agar tak pernah memutus agen;
API sengaja **org-scoped only** (tak bisa sentuh tenant lain / global) — default
global dikelola via script/migration, bukan API tenant.

## Rencana
- **P2-B (selesai):** paket + schema + `BaseAgent.resolved_system_prompt` + API + 9 test.
- **P2-B.2:** adopsi di agen prioritas (CS/finance) pada titik build system-message;
  panel UI prompt (list/diff/rollback/A-B); auto-promosi varian dari skor Evaluation.
  Cache in-proc ber-TTL bila resolusi jadi hot path.

## Rollback
Flag `prompt_registry` OFF (default) → semua agen pakai `self.system_prompt` (byte-
identik). Paket, singleton, tabel, dan API bersifat additive/idle. Drop tabel
`agent_prompts` aman (tak dirujuk jalur lama).
