"""
celery_app.py — Konfigurasi Celery untuk BotNesia Intelligence Platform.

Dua peran proses terpisah (lihat docker-compose.yml):
  • celery -A celery_app worker  -l info     → eksekusi task async ringan
                                                (persist embedding, update counter)
  • celery -A celery_app beat    -l info     → penjadwal job malam (Auto Learning)

Broker & result backend memakai Redis yang sama dengan cache dashboard.
Task DB-bound bersifat async (asyncpg) — Celery worker (prefork, sinkron)
menjalankannya lewat `asyncio.run()` per task; setiap task membuka pool
asyncpg miliknya sendiri (lihat intelligence/db.py — pool lazy & cached
per-process, aman untuk model worker prefork).
"""
from __future__ import annotations

import asyncio
import logging

from celery import Celery
from celery.schedules import crontab

import vendor_bootstrap  # noqa: F401

from intelligence.config import cfg

logger = logging.getLogger("celery_app")

celery_app = Celery(
    "botnesia_intelligence",
    broker=cfg.redis_url,
    backend=cfg.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="intelligence",
)

celery_app.conf.beat_schedule = {
    "intelligence-nightly-auto-learning": {
        "task": "intelligence.run_daily_learning",
        "schedule": crontab(hour=cfg.nightly_job_hour, minute=cfg.nightly_job_minute),
        "args": (),
    },
    "self-learning-nightly-scan": {
        "task": "intelligence.run_learning_scan_all_orgs",
        # 30 menit setelah nightly-auto-learning, supaya tidak kontensi pool/DB bersamaan.
        "schedule": crontab(hour=cfg.nightly_job_hour, minute=(cfg.nightly_job_minute + 30) % 60),
        "args": (),
    },
}


def _run_async(coro):
    """Jalankan coroutine di event loop baru — aman dipanggil dari task Celery sinkron."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


@celery_app.task(name="intelligence.run_daily_learning", bind=True, max_retries=2, default_retry_delay=300)
def run_daily_learning_task(self, bot_id: str | None = None):
    """Job Auto-Learning malam hari — analisis H-1, FAQ/Sales/KG, generate laporan."""
    from intelligence.nightly_jobs import run_daily_learning
    try:
        return _run_async(run_daily_learning(bot_id))
    except Exception as exc:
        logger.exception("run_daily_learning_task gagal")
        raise self.retry(exc=exc)


@celery_app.task(name="intelligence.run_learning_scan_all_orgs", bind=True, max_retries=2, default_retry_delay=300)
def run_learning_scan_all_orgs_task(self):
    """Job Self-Learning malam hari -- agregasi sales pattern/complaint resolution/
    successful approach jadi organizational_memory candidate insight, semua org
    dengan bot aktif (lihat self_learning_engine.run_learning_scan_all_orgs)."""
    from intelligence.db import get_pool
    from self_learning_engine import run_learning_scan_all_orgs

    async def _run():
        pool = await get_pool()
        return await run_learning_scan_all_orgs(pool)

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.exception("run_learning_scan_all_orgs_task gagal")
        raise self.retry(exc=exc)


@celery_app.task(name="intelligence.persist_conversation_async", bind=True, max_retries=3, default_retry_delay=30)
def persist_conversation_async_task(self, payload: dict):
    """
    Persist percakapan secara async (dipakai sebagai fallback bila ingin
    melepas penulisan dari request path sepenuhnya — lihat catatan di
    routes_intelligence.py `/intel/conversations/{conv_id}/persist`).
    payload: hasil serialisasi context + analytics dari Supervisor.
    """
    from intelligence.conversation_memory import persist_conversation
    try:
        return _run_async(persist_conversation(**payload))
    except Exception as exc:
        logger.exception("persist_conversation_async_task gagal")
        raise self.retry(exc=exc)


@celery_app.task(name="intelligence.record_signals_async", bind=True, max_retries=3, default_retry_delay=30)
def record_signals_async_task(self, faq_payload: dict | None, sales_payload: dict | None):
    """Catat sinyal FAQ & Sales secara async (dipanggil dari agent_api setelah jawaban terkirim)."""
    from intelligence.faq_agent import record_question_signal
    from intelligence.sales_agent import record_sales_signals

    async def _run():
        if faq_payload:
            await record_question_signal(**faq_payload)
        if sales_payload:
            await record_sales_signals(**sales_payload)

    try:
        return _run_async(_run())
    except Exception as exc:
        logger.exception("record_signals_async_task gagal")
        raise self.retry(exc=exc)
