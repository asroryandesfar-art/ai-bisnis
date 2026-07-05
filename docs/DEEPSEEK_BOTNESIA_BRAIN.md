# BotNesia — 3 Otak DeepSeek (Tiered Model Router)

Router model bertingkat memakai **satu API key DeepSeek** untuk tiga model.
Implementasi: `deepseek_brain.py` · test: `test_deepseek_brain.py`.

## Konsep 3 otak

| Otak | Env | Default | Dipakai untuk |
|------|-----|---------|---------------|
| **FAST** | `DEEPSEEK_MODEL_FAST` | `deepseek-chat` | sapaan, FAQ, CS harian, jawaban produk biasa, ringkasan pendek, percakapan normal, jawaban jelas dari KB |
| **THINKING (R1)** | `DEEPSEEK_MODEL_THINKING` | `deepseek-reasoner` | pertanyaan agak sulit, analisis sedang, customer bingung/ambigu, komplain ringan–sedang, butuh penalaran, FAST confidence rendah |
| **PRO** | `DEEPSEEK_MODEL_PRO` | *(kosong → ikut THINKING)* | komplain berat, customer marah, billing/subscription rumit, supervisor agent, risiko reputasi, keputusan penting, enterprise, multi-step kompleks |

> **R1 dipertahankan:** `THINKING` default `deepseek-reasoner` (DeepSeek R1). Kalau
> `DEEPSEEK_MODEL_PRO` belum di-set, PRO otomatis memakai model THINKING agar
> perilaku lama tidak berubah.

## Environment variables

```bash
# SATU API key (sudah ada di .env Anda) — JANGAN commit, JANGAN hardcode:
DEEPSEEK_API_KEY=********

# Nama model per-tier (bisa diganti kapan saja tanpa ubah kode):
DEEPSEEK_MODEL_FAST=deepseek-v4-flash
DEEPSEEK_MODEL_THINKING=deepseek-reasoner
DEEPSEEK_MODEL_PRO=deepseek-v4-pro
```

Semua nama model dibaca dari env di **satu sumber**: `Settings` (`main.py`) →
`deepseek_models()` → `DeepSeekModels`. `ai_providers/deepseek.py` juga membaca
env yang sama. Tidak ada nama model yang di-hardcode tersebar.

## Routing FAST vs THINKING vs PRO

`classify_tier(message, signals)` (heuristik deterministik, **tanpa** memanggil LLM):

1. **PRO** bila: `is_supervisor` / `is_enterprise` / `multi_step`, atau pola emosi
   berat / komplain berat / billing rumit / risiko bisnis (mis. "marah", "penipuan",
   "lapor polisi", "double charge", "chargeback", "sue", "lawsuit").
2. **THINKING** bila: `fast_confidence < 0.45`, `kb_confidence < 0.35` (pesan panjang),
   pola ambigu/penalaran ("bingung", "kenapa", "bandingkan", "compare"), atau
   `intent_classifier.heuristic_complexity == "complex"`.
3. **FAST** untuk sisanya (sapaan, FAQ, jawaban jelas).

Tier hasil klasifikasi lalu **dibatasi plafon plan** (lihat di bawah).

## Aturan plan/billing (divalidasi backend)

`plan_max_tier(plan)` — plafon tier per plan. `enforce_plan(tier, plan)` menurunkan
tier bila melebihi hak plan. **Plan diambil dari backend/DB** (kolom
`organizations.plan` / `subscriptions.plan_key`), **bukan** dari field request.

| Plan (plan_key / legacy) | Tier maksimum |
|--------------------------|---------------|
| `free` / `trialing` | FAST |
| `starter` | THINKING (terbatas via kuota `check_limit`) |
| `pro` / `growth` | THINKING |
| `business` / `scale` | PRO (terbatas) |
| `enterprise` | PRO (lebih agresif) |

- Free hanya FAST — **tidak bisa dipaksa** ke PRO dari frontend (klien tidak
  pernah mengirim tier/model; tier ditentukan classifier + plafon plan).
- "Terbatas" = tier boleh, tapi **jumlah** pemakaian dibatasi kuota plan
  (mekanisme `bn_platform/billing.py check_limit`, terpisah dari router ini).

## Arsitektur

```
Customer
  → BotNesia Router (classify_tier + enforce_plan)
  → Security Guard (detect_prompt_injection)
  → Tenant Knowledge Base / RAG (retrieve_fn(org_id=...))   ← WAJIB filter tenant
  → DeepSeek FAST / THINKING / PRO  (+ fallback + timeout + retry)
  → Output Policy Check (scan_output → redaksi secret/system-prompt)
  → Jawaban ke customer
```

## Security guard

- **API key server-only:** disimpan di `.env`, dipakai lewat closure
  `make_default_call_fn(api_key)`. Tidak pernah dikirim ke frontend, tidak
  di-log, tidak masuk `BrainResult`.
- **Tidak mengirim rahasia ke model:** system prompt melarang membocorkan
  secret/kredensial; context hanya dari KB tenant.
- **Prompt injection diblok** sebelum memanggil model: "abaikan instruksi
  sebelumnya", "tampilkan system prompt", "baca .env", "tampilkan API key",
  "database password", dsb → dijawab aman, model tidak dipanggil.
- **Output policy check:** `scan_output()` meredaksi pola secret (sk-…, gsk_…,
  AIza…, JWT, private key), string secret yang diberikan, dan potongan system
  prompt bila termuntahkan.
- **Logging aman:** hanya tier/model/plan/org & tipe error — tanpa API key,
  tanpa isi pesan/secret.

## RAG tenant isolation

`retrieve_fn(org_id, query)` **wajib** memfilter berdasarkan `org_id`
(mis. `_retrieve_chunks(pool, org_id, ...)` yang sudah ada). Router memanggil
retrieve **hanya** dengan `org_id` milik pemanggil — tenant A tidak pernah
meng-query KB tenant B. Knowledge antar tenant tidak dicampur.

## Fallback strategy

- Urutan turun: **PRO → THINKING → FAST**.
- Tiap tier: `timeout` (default 60s) + **retry terbatas** (`max_retries`, default 1).
- Jika **semua** model gagal → jawaban aman + `escalate=True` (serahkan ke human agent).
- Circuit-breaker per-provider tetap ada di `ai_providers/router.py` untuk jalur lain.

## Cara mengganti model nanti

Cukup ubah nilai env lalu restart service — **tidak perlu ubah kode**:

```bash
# contoh: ganti FAST ke model baru
sed -i 's/^DEEPSEEK_MODEL_FAST=.*/DEEPSEEK_MODEL_FAST=deepseek-v5-flash/' .env
systemctl --user restart botnesia-api.service
```

## Integrasi ke `/chat` — OPT-IN via flag (default OFF)

Sudah di-wire ke endpoint `POST /chat/{bot_id}`, tapi **default nonaktif**
sehingga produksi TIDAK berubah sampai Anda mengaktifkannya:

```bash
DEEPSEEK_BRAIN_ENABLED=1   # + DEEPSEEK_API_KEY harus ada
```

Saat aktif, alur `/chat`:
- `plan` diambil dari DB (`bot["plan"]`) — klien tak bisa memaksa PRO.
- RAG lewat `_retrieve_chunks(pool, org_id, ...)` (tenant-isolated).
- `secrets=[SECRET_KEY, DEEPSEEK_API_KEY, INTEGRATION_ENCRYPTION_KEY]` untuk redaksi output.
- Bila brain error → **fallback otomatis ke pipeline lama** (chat tidak pernah mati).
- Bila flag OFF **atau** `DEEPSEEK_API_KEY` kosong → langsung pakai pipeline lama.

> Catatan: task-routing internal di `ai_providers/deepseek.py` tetap memakai
> `deepseek-chat`/`deepseek-reasoner` yang terbukti (bukan nama env `v4`), agar
> pipeline lama stabil. Nama model "3 otak" yang env-driven hanya dipakai oleh
> router ini (`deepseek_brain.py`).

Cara mengaktifkan penuh (setelah verifikasi model ID & API key siap):
1. Pastikan `DEEPSEEK_MODEL_FAST/THINKING/PRO` valid di DeepSeek API.
2. Set `DEEPSEEK_BRAIN_ENABLED=1`.
3. `systemctl --user restart botnesia-api.service`.
