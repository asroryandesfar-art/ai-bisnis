"""task_runtime.worker — pemroses durable job (P0-D D4).

Inti worker BEBAS-Celery (testable): `run_one_job` klaim satu job lalu jalankan
via DurableJobRunner; `drain_jobs` proses beberapa. Binding Celery (celery_app.py)
memanggil `drain_jobs` periodik (beat) + saat enqueue (best-effort) — recovery job
lease-kadaluarsa terjadi otomatis lewat `claim_next` (D1).

`make_registry_agent_builder` = builder produksi: cari agent by name di
agent_registry lalu `build_agent(**agent_kwargs)`. Diinjeksi supaya worker tetap
mandiri & testable dengan fake agent.
"""
from __future__ import annotations

import importlib
from typing import Awaitable, Callable

from task_runtime.repository import JobRepository
from task_runtime.runner import DurableJobRunner


async def run_one_job(pool, *, owner: str, lease_s: int = 60,
                      agent_builder: Callable[[str, dict], object],
                      publish: Callable[..., Awaitable] | None = None) -> str | None:
    """Klaim & jalankan SATU job. Return status akhir, atau None bila antrean kosong."""
    repo = JobRepository()
    job = await repo.claim_next(pool, owner=owner, lease_s=lease_s)
    if job is None:
        return None
    runner = DurableJobRunner(repo, agent_builder=agent_builder)
    return await runner.run(pool, job, owner=owner, publish=publish)


async def drain_jobs(pool, *, owner: str, agent_builder: Callable[[str, dict], object],
                     lease_s: int = 60, publish: Callable[..., Awaitable] | None = None,
                     max_jobs: int = 10) -> int:
    """Proses hingga `max_jobs` job yang tersedia. Return jumlah yang diproses."""
    processed = 0
    for _ in range(max(1, max_jobs)):
        status = await run_one_job(pool, owner=owner, lease_s=lease_s,
                                   agent_builder=agent_builder, publish=publish)
        if status is None:
            break
        processed += 1
    return processed


def make_registry_agent_builder(agent_kwargs: dict) -> Callable[[str, dict], object]:
    """Builder produksi: resolusi agent_name → (module_path, class_name) dari
    agent_registry (AGENT_DIRECTORY + ORCHESTRATION_EXTRA), lalu build_agent.
    Tidak menyaring override-run (durable job memakai pola run_task)."""
    import agent_registry

    def _builder(agent_name: str, ctx: dict):
        for module_path, class_name, _cat, _ch in (
            *agent_registry.AGENT_DIRECTORY, *agent_registry.ORCHESTRATION_EXTRA
        ):
            try:
                cls = getattr(importlib.import_module(module_path), class_name)
            except Exception:
                continue
            if getattr(cls, "name", class_name) == agent_name or class_name == agent_name:
                return agent_registry.build_agent(module_path, class_name, **agent_kwargs)
        raise ValueError(f"agent tak dikenal untuk durable job: {agent_name}")

    return _builder
