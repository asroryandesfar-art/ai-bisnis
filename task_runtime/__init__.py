"""task_runtime — Durable Task Runtime untuk BotNesia (P0-D).

Membuka eksekusi task otonom berjam-jam yang tahan restart/crash: Queue →
Checkpoint → Resume → Recovery → Cancel/Pause → Retry → Timeout → DLQ.

Status: D1 (schema + JobRepository) selesai. D2+ (runner step-based, worker
Celery, API, DLQ) menyusul. Lihat docs/adr/ADR-0004-durable-task-runtime.md.

Additive: tabel agent_jobs/agent_job_steps berdampingan; agent_task_executions
(laporan final) TIDAK berubah. Default TASK_RUNTIME=inline (jalur lama).
"""
from task_runtime.schema import ensure_job_schema, JOB_SCHEMA_SQL
from task_runtime.repository import JobRepository

__all__ = ["ensure_job_schema", "JOB_SCHEMA_SQL", "JobRepository"]
