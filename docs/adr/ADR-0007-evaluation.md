# ADR-0007 — Evaluation Framework

- **Status:** Accepted — P1-D.1 (evaluator + auto-eval durable) selesai; dashboard/AB menyusul
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 2 (Cognitive Core), item **P1-D**
- **Terkait:** ADR-0005 (cognitive Critic), ADR-0004 (durable runtime — sumber task), P0-C (event bus)

## Konteks
Audit: tak ada skor kualitas objektif pasca-task → sulit A/B, sulit deteksi regresi
kualitas, tak ada sinyal untuk kalibrasi Cost Router/prompt. Critic loop menilai
SAAT eksekusi; dibutuhkan penilaian SETELAH selesai yang tersimpan & bisa diagregasi.

## Keputusan
Modul mandiri `evaluation` + tabel `task_evaluations`. `Evaluator.evaluate` menghitung:
- **Deterministik (tanpa LLM):** tool_success, answered, verified, confidence.
- **LLM-judge (opsional, `judge_agent` diinjeksi, fail-open):** accuracy,
  hallucination(-free), reasoning_quality, citation.
`overall` = rata-rata TERTIMBANG dimensi yang tersedia. Terintegrasi ke
`DurableJobRunner` (param `evaluator`): **otomatis skor tiap job selesai** (linear
& cognitive) lalu simpan — gate `is_enabled("evaluation", org_id)`, best-effort
(gagal eval tak menggagalkan job).

## Alternatif
1. **LLM-judge saja.** Ditolak: mahal & bising untuk tiap task; deterministik dulu, judge opsional.
2. **Eval via event bus (subscribe TaskFinished).** Ditunda: event bus in-process → produser di worker Celery, konsumen harus di proses yang sama; integrasi langsung di runner lebih sederhana & pasti jalan. (Redis-Streams event bus = jalur masa depan.)
3. **Eval in-runner + deterministik + judge opsional (DIPILIH).** Risiko kecil, pasti tereksekusi di worker, testable.

## Konsekuensi
**Positif:** sinyal kualitas objektif tersimpan per-task; fondasi A/B, deteksi regresi, kalibrasi Cost Router (P2). **Batasan:** LLM-judge menambah 1 panggilan LLM/task (opsional, gate); overall tertimbang = heuristik awal (bisa dikalibrasi).

## Rencana
- **P1-D.1 (selesai):** `evaluation` (schema + Evaluator deterministik+judge+store) + auto-eval di DurableJobRunner (linear & cognitive) gate flag. 6 test (deterministik/empty/judge/failopen/store + auto-eval runner).
- **P1-D.2:** endpoint/list + dashboard skor realtime (P2-C); umpan ke Cost Router (P2-A) & prompt A/B (P2-B).
- **P1-D.3:** event-bus Redis-Streams → eval async lintas-proses + replay.

## Rollback
Flag `evaluation` OFF → tak ada skor ditulis. Tabel additive; evaluator opsional (None → no-op).
