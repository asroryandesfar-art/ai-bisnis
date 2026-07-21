# ADR-0004 — Durable Task Runtime (`task_runtime`)

- **Status:** Accepted — **D1–D3 selesai** (schema + repository + runner); D4–D6 menyusul
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 1 Fondasi Platform, item **P0-D** (terberat)
- **Terkait:** ADR-0001 (shared state / lock), ADR-0002 (feature flags / canary), ADR-0003 (event bus)

## Konteks
Task agent kini dijalankan `await` **inline di HTTP handler** (`finance.py`, `hr.py`,
`operations.py`, `marketing.py` → `task_engine.run_agent_task`) — single pass, persist
1 baris saat SELESAI. Tidak ada Queue/Checkpoint/Resume/Recovery/Cancel/Pause/DLQ →
tak bisa task berjam-jam; worker HTTP tertahan LLM lama. Ini blocker proposisi
"autonomous".

## Keputusan
Runtime durable berbasis **Celery (broker Redis yang sudah ada, `celery_app.py`)** +
state di Postgres. Tabel BARU `agent_jobs` (state hidup) + `agent_job_steps` (checkpoint
per langkah). **BUKAN** pengganti `agent_task_executions` — itu tetap laporan final saat
job `completed` (backward compatible; UI/pembaca lama tak berubah).

- **Checkpoint**: tiap step tulis `checkpoint` (state akumulatif), bukan hanya di akhir.
- **Resume**: worker load step 'done' terakhir → lanjut.
- **Recovery**: `lease_until` (heartbeat); job running dgn lease kadaluarsa → di-reclaim (`claim_next`).
- **Cancel/Pause**: status `cancelling`/`pausing` dicek di boundary step (cooperative).
- **Retry/DLQ**: `attempts`/`max_attempts` → `dead_letter`.
- **Klaim aman**: `FOR UPDATE SKIP LOCKED` → dua worker tak dapat job sama.
- **Idempotency**: `idempotency_key` unik per-org → enqueue aman diulang.

Migrasi jalur pemakai `run_task` inline → enqueue durable di-gate **feature flag**
`TASK_RUNTIME` / `is_enabled("durable_runtime", org_id)` (P0-B), default **inline**
(perilaku lama). Progres & event via **event bus** (P0-C, `TaskStarted/Finished/Failed`).

## Alternatif
1. **Celery murni tanpa state DB.** Ditolak: tak ada checkpoint/resume granular, sulit audit.
2. **Runtime bikin-sendiri.** Ditolak: reinvent; Celery+Redis sudah ada & teruji.
3. **Celery + state Postgres (DIPILIH).** Reuse infra; checkpoint/resume/recovery eksplisit; SKIP LOCKED atomik.

## Konsekuensi
**Positif:** membuka autonomous berjam-jam; lepaskan worker HTTP dari LLM lama →
throughput naik; fondasi cognitive-loop (P1) & web-intelligence pipeline (P3).
**Negatif / mitigasi:** kompleksitas naik (worker, lease, DLQ) — dikelola bertahap
D1..D6, tiap slice tes; risiko regresi saat pecah `task_engine` → golden test output final.

## Rencana bertahap (slices)
- **D1 (selesai):** schema `agent_jobs`/`agent_job_steps` (additive, `ensure_optional_schema`) + `JobRepository` (enqueue/idempotency, claim `FOR UPDATE SKIP LOCKED`, lease renew, recovery `find_expired`, checkpoint `save_step`/`latest_done_step`, control cancel/pause/resume, list). 8 test vs Postgres nyata. **Idle** — belum ada worker; nol perubahan perilaku.
- **D2/D3 (selesai):** `DurableJobRunner` step-based (plan→subtask×N→verify→report) dengan checkpoint per-step (state kumulatif), **resume** dari step 'done' terakhir, **cancel/pause cooperative** di boundary, **retry/DLQ** (attempts vs max_attempts), timeout per-step, progres. Me-reuse primitif agent (`_call_llm_json`/`_call_llm_with_tools`) + `task_engine._persist_task_execution` → baris final `agent_task_executions` identik; **task_engine inline TAK diubah** (hindari regresi). 4 test vs Postgres nyata (completed+persist, resume-skip-plan, cancel, retry→DLQ). Terbitkan TaskStarted/Finished/Failed (event bus P0-C, best-effort). Belum ada worker (D4).
- **D4:** Celery task `run_job` (queue `agent_jobs`) + lease (StateStore) + recovery beat.
- **D5:** API `/api/jobs/*` (enqueue/status/SSE/cancel/pause/resume) + param `async` di router domain (flag `TASK_RUNTIME`).
- **D6:** DLQ + replay + timeout/backoff + chaos test (kill-worker→resume).

## Rollback
`TASK_RUNTIME=inline` (default) → jalur sinkron lama (tetap ada). Tabel job idle;
tanpa migrasi untuk di-revert. Nol data-loss (`agent_task_executions` tetap laporan final).

## Exit criteria (P0-D)
Chaos kill-worker→resume (tanpa ulang step / tanpa duplikat side-effect); cancel/pause/
timeout/DLQ/replay; golden regresi `agent_task_executions` identik; 2-worker no double-claim;
full suite hijau di mode inline & durable; canary 1 agent 48 jam bersih.
