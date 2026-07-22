# ADR-0011 — Runtime Observability (dashboard operator realtime)

- **Status:** Accepted — `task_runtime.RuntimeMonitor` + API `/api/runtime/*` (health/evaluations/stream SSE) selesai
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 3 (Efisiensi & Operabilitas), item **P2-C**
- **Terkait:** ADR-0004 (durable runtime), ADR-0007 (Evaluation), `/observability` (AI traces existing)

## Konteks
Observability existing (`bn_platform/ai_observability.py` `/observability`) kuat untuk
**AI traces / token / cost** atas `ai_traces`+`agent_executions`. Tapi subsistem
BARU — **durable runtime** (`agent_jobs`, P0-D) & **Evaluation** (`task_evaluations`,
P1-D) — belum punya view operator: tak ada cara melihat backlog antrian, job
in-flight vs macet (lease kedaluwarsa), worker aktif, DLQ, throughput, atau tren
skor per-agen. Untuk operasi "kelas dunia" ini wajib terlihat realtime.

## Keputusan
Modul agregasi read-only **`task_runtime.RuntimeMonitor`** (org-scoped, tanpa skema
baru):
- `health_snapshot` → `queue` (semua status 0-filled), `backlog`, `in_flight`
  (running + lease valid), `stalled` (running/pausing/cancelling + lease
  kedaluwarsa → kandidat recovery), `dead_letter`, `throughput`
  (completed/failed 1h & window + `success_rate`), `workers` (lease_owner aktif),
  `evaluation` (avg_overall/count/judged% window).
- `evaluation_trends` → skor per-agen (avg/min/max/n/judged%/last_at).

Router **`/api/runtime/*`** (RBAC `workforce.read`, org-scoped): `GET /health`,
`GET /evaluations`, `GET /stream` (SSE snapshot berkala = realtime). Bagian
Evaluation **fail-open** (tabel absen → nol) agar tak pernah 500.

## Alternatif
1. **Perluas `/observability/summary`.** Ditolak: ranah beda (traces vs runtime/queue), query & konsumen berbeda; menggabung bikin endpoint gemuk.
2. **Push via event_bus → WS.** Ditunda: event_bus in-process (produser di worker Celery, proses beda dari web) → tak andal lintas-proses; snapshot-poll SSE dari DB deterministik & cukup untuk gate awal.
3. **Modul agregasi read-only + SSE poll (DIPILIH).** Additive, akurat (sumber = DB), tanpa skema/koupling baru.

## Konsekuensi
**Positif:** operator melihat kesehatan runtime + kualitas (skor Evaluation) realtime
→ deteksi backlog/worker mati/regresi skor lebih dini; melengkapi trio P2 (Cost
Router + Prompt A/B + skor kini TERLIHAT). **Batasan:** SSE = poll DB tiap
`interval_s` (bukan push murni) — beban ringan, tapi banyak koneksi stream perlu
diperhatikan (batasi `max_ticks`); metrik worker berbasis lease `agent_jobs`
(bukan heartbeat proses Celery langsung) — worker yang idle tanpa job tak tampil.

## Rencana
- **P2-C (selesai):** RuntimeMonitor + API health/evaluations/stream + 5 test.
- **P2-C.2:** panel UI dashboard (chart backlog/throughput/skor, tabel worker/DLQ,
  tombol retry DLQ ke `/api/jobs/{id}/retry`); heartbeat worker Celery eksplisit;
  alert threshold (backlog/stalled/skor turun).

## Rollback
Modul & router additive/read-only. Hapus mount → endpoint hilang, nol dampak ke
jalur lain. Tak ada skema/tabel baru untuk di-drop.
