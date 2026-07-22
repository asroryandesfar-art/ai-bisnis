# ADR-0015 — Runtime Operations panel (UI)

- **Status:** Accepted — modul frontend `runtime_observability.js` + route `runtime` di nav selesai
- **Tanggal:** 2026-07-23
- **Konteks:** UI — surface P2-C (Runtime Observability) & P1-D (Evaluation) ke operator
- **Terkait:** ADR-0011 (runtime observability API), ADR-0007 (Evaluation), `web_intelligence.js` (preseden modul)

## Konteks
Backend enterprise makin tebal (durable runtime, evaluation, cost router, prompt
registry, policy) tapi banyak yang tak punya UI. Khususnya P2-C `/api/runtime/*`
(health/evaluations) — kesehatan antrean/worker/DLQ + skor kualitas — tak terlihat
operator. `/observability` existing hanya AI traces/token/cost (beda ranah).

## Keputusan
Modul frontend mandiri **`frontend/runtime_observability.js`** (pola dependency-
injected `web_intelligence.js`: `createRuntimeObservability({el,setPage,toast,state,
api})` → `{ runtime: renderFn }` yang di-spread app.js). Satu route **`runtime`**
("Runtime Ops") di grup nav **agent-os** (dekat observability/costs). Menampilkan:
- Metric cards: Backlog, In-flight, **Stalled** (lease kedaluwarsa→recovery),
  Dead-letter, Success rate, Avg eval score (trend-warna sesuai ambang).
- Queue chips per-status; tabel Workers (lease aktif); tabel Evaluation per-agen
  (avg/min-max/judged%/last).
- Window selector (1h/24h/7d/30d) + **auto-refresh 5s** selama route aktif (stop
  saat pindah route). Read-only. Tanpa mock — hanya yang API kembalikan.

API client: `runtimeHealth`/`runtimeEvaluations`. i18n: 3 key (id+en). Icon nav
khusus `runtime`.

## Alternatif
1. **Tambah tab di `/observability`.** Ditolak: ranah beda (AI traces vs runtime/queue); campur bikin view berat. Panel terpisah lebih jelas.
2. **Server-render di app.js (renderObservability style).** Ditolak: app.js sudah 4900+ baris; modul mandiri (spt web_intelligence) lebih rapi & terisolasi.
3. **Modul frontend mandiri + route nav (DIPILIH).** Konsisten preseden, additive, terisolasi.

## Konsekuensi
**Positif:** operator kini melihat kesehatan durable runtime + skor kualitas realtime
tanpa curl; menutup "backend kuat, operator buta". Additive: hanya menambah route/
modul, tak mengubah view lain. **Batasan:** poll REST tiap 5s (bukan WS push);
data mengikuti batas API (worker berbasis lease, bukan heartbeat proses); butuh
permission `workforce.read`. Belum ada aksi (retry DLQ) dari panel — read-only dulu.

## Rencana
- **(selesai):** panel read-only + nav + auto-refresh. Frontend statis (tanpa build), diserve /ui/*.
- **(selesai) actionable:** bagian **Jobs** (filter status + tabel) dengan aksi per-status
  → **Retry** DLQ (`/api/jobs/{id}/retry`), **Cancel/Pause/Resume** (queued/running/paused).
  Aksi via delegasi klik pada `#runtime-body` (tahan innerHTML-swap saat refresh); cancel
  minta konfirmasi; sukses → toast + refresh. api-client: jobsList/jobRetry/jobCancel/jobPause/jobResume.
- **berikutnya:** chart tren, alert threshold; panel serupa untuk Prompt A/B (P2-B) & policy rules (P1-C.2).

## Rollback
Hapus route dari whitelist + nav + renderers spread → panel hilang, nol dampak.
Modul & endpoint additive/idle.
