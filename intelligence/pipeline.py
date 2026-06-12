"""Shared persistence and local scheduling for the Intelligence Platform."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import conversation_memory, faq_agent, knowledge_agent, sales_agent
from .config import cfg
from .db import get_pool

logger = logging.getLogger("intelligence.pipeline")
_NIGHTLY_LOCK_ID = 4_261_993_701


async def persist_intelligence(
    context: dict,
    result: Any,
    *,
    bot_response: str | None = None,
) -> None:
    """Persist one supervisor result without affecting the chat response."""
    bot_id = context.get("bot_id")
    org_id = context.get("org_id")
    conversation_id = context.get("conversation_id")
    analysis: dict = {}

    try:
        analysis = await conversation_memory.persist_conversation(
            context,
            bot_response=bot_response or result.final_answer,
            sentiment=result.sentiment,
            intent=result.intent,
            topics=result.topics,
            resolved=bool(context.get("resolved", False)),
            should_escalate=result.should_escalate,
            friction_points=result.friction_points,
            quality_score=result.bot_quality_score,
            extra_metrics={
                "product_insights": result.product_insights,
                "trainer_score": result.trainer_score,
                "reasoning_mode_used": result.reasoning_mode_used,
                "confidence_score": result.confidence_score,
                "verification_passed": result.verification_passed,
                "retry_count": result.retry_count,
                "plan": result.plan,
                "specialist_lenses_used": list(result.specialist_results or {}),
            },
        )
    except Exception:
        logger.exception("persist_conversation gagal (bot=%s, conv=%s)", bot_id, conversation_id)

    try:
        if analysis:
            await conversation_memory.upsert_customer_profile(
                context,
                end_user_id=conversation_memory.derive_end_user_id(context),
                topics=analysis.get("topics", []),
                lead_status=analysis.get("lead_status", "none"),
                purchase_status=analysis.get("purchase_status", "none"),
                escalation_status=analysis.get("escalation_status", "none"),
                sentiment_score=float((result.sentiment or {}).get("score", 0.0) or 0.0),
            )
    except Exception:
        logger.exception("upsert_customer_profile gagal (bot=%s)", bot_id)

    try:
        await faq_agent.record_question_signal(
            bot_id=bot_id,
            org_id=org_id,
            conversation_id=conversation_id,
            question_text=context.get("user_message", ""),
            answer_text=bot_response or result.final_answer,
            outcome=analysis.get("outcome", "unresolved"),
            quality_score=result.bot_quality_score,
        )
    except Exception:
        logger.exception("record_question_signal gagal (bot=%s)", bot_id)

    try:
        if result.sales_signals:
            await sales_agent.record_sales_signals(
                bot_id=bot_id,
                org_id=org_id,
                conversation_id=conversation_id,
                signals=result.sales_signals,
                resulted_in_purchase=(
                    analysis.get("purchase_status") == "purchased" if analysis else None
                ),
            )
    except Exception:
        logger.exception("record_sales_signals gagal (bot=%s)", bot_id)

    try:
        if analysis:
            await knowledge_agent.update_graph_from_conversation(
                context,
                intent=analysis.get("intent", "unknown"),
                topics=analysis.get("topics", []),
                friction_points=result.friction_points,
                outcome=analysis.get("outcome", "unresolved"),
                purchase_status=analysis.get("purchase_status", "none"),
                matched_faq_answer=(result.faq_match or {}).get("suggested_answer"),
                summary=analysis.get("summary", ""),
            )
    except Exception:
        logger.exception("update_graph_from_conversation gagal (bot=%s)", bot_id)


async def run_nightly_learning_once() -> dict:
    """Run learning once, guarded against duplicate workers by PostgreSQL."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        locked = await conn.fetchval("SELECT pg_try_advisory_lock($1)", _NIGHTLY_LOCK_ID)
        if not locked:
            return {"skipped": True, "reason": "another worker holds the lock"}
        try:
            from .nightly_jobs import run_daily_learning
            return await run_daily_learning()
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _NIGHTLY_LOCK_ID)


def seconds_until_next_run(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    target = now.replace(
        hour=cfg.nightly_job_hour,
        minute=cfg.nightly_job_minute,
        second=0,
        microsecond=0,
    )
    if target <= now:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


async def nightly_learning_loop(stop_event: asyncio.Event) -> None:
    """Local replacement for Celery beat when only the main API is running."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=seconds_until_next_run())
            continue
        except asyncio.TimeoutError:
            pass
        try:
            result = await run_nightly_learning_once()
            logger.info("Nightly learning selesai: %s", result)
        except Exception:
            logger.exception("Nightly learning gagal")
