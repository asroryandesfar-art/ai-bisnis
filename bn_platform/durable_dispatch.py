"""bn_platform/durable_dispatch — jembatan run_task inline → durable job (P0-D D6).

`enqueue_if_durable` dipakai endpoint domain (finance/hr/operations/marketing)
saat `?async=true`: bila feature flag `durable_runtime` aktif untuk org →
antre durable job (agent_jobs) + picu worker; kalau tidak → return None (caller
tetap jalur inline lama). Default flag OFF → perilaku lama byte-identik.
"""
from __future__ import annotations


async def enqueue_if_durable(pool, *, org_id, agent_name: str, goal: str, bot_id=None) -> dict | None:
    """Antre durable job bila flag durable_runtime ON untuk org; else None."""
    from feature_flags import is_enabled
    if not is_enabled("durable_runtime", org_id=str(org_id)):
        return None
    from task_runtime import JobRepository
    job = await JobRepository().enqueue(
        pool, org_id=str(org_id), agent_name=agent_name, goal=goal,
        bot_id=str(bot_id) if bot_id else None)
    try:
        from celery_app import run_pending_jobs_task
        run_pending_jobs_task.delay()
    except Exception:
        pass                                        # worker/beat akan memproses nanti
    return job
