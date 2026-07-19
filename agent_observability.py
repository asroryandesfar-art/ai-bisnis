"""Persistent, fail-open tracing for the BotNesia multi-agent pipeline."""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from bn_platform.observability import record_ai_request, record_token_usage
from cost_intelligence import choose_model, estimate_cost_usd, reset_model_route, set_model_route

T = TypeVar("T")

# ── Auto-retry untuk kegagalan TRANSIENT (timeout/jaringan/API sementara) ──
# Provider LLM sudah retry di level HTTP; ini jaring pengaman level-agent untuk
# error transient yang lolos dari provider. Konfigurasi via env.
_RETRY_MAX = int(os.getenv("AGENT_RETRY_MAX", "3"))
_RETRY_BASE_DELAY = float(os.getenv("AGENT_RETRY_BASE_DELAY", "0.5"))
_RETRY_MAX_DELAY = float(os.getenv("AGENT_RETRY_MAX_DELAY", "8"))
_TRANSIENT_TYPES = (
    httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError,
    httpx.RemoteProtocolError, httpx.PoolTimeout, asyncio.TimeoutError,
    ConnectionError,
)
_TRANSIENT_KEYWORDS = (
    "timed out", "timeout", "temporarily unavailable", "service unavailable",
    "connection reset", "connection aborted", "rate limit", "too many requests",
    "502", "503", "504", "bad gateway", "gateway timeout",
)


# ── Realtime event publisher (di-wire main ke ObservabilityHub) ──
# None = tidak ada dashboard realtime (fail-open). Dipanggil non-blocking.
_event_publisher: Callable[[str, dict], Any] | None = None


def set_event_publisher(fn: Callable[[str, dict], Any] | None) -> None:
    global _event_publisher
    _event_publisher = fn


def _emit(org_id: str, event: dict) -> None:
    """Publish event realtime tanpa memblokir jalur eksekusi (fire-and-forget)."""
    if not _event_publisher or not org_id:
        return
    try:
        coro = _event_publisher(org_id, event)
        if asyncio.iscoroutine(coro):
            task = asyncio.ensure_future(coro)
            task.add_done_callback(lambda t: t.exception())  # jangan bocorkan exc
    except Exception:
        pass


def _is_transient(exc: BaseException) -> bool:
    """True bila error layak di-retry (transient), bukan bug logika/permanen."""
    if isinstance(exc, _TRANSIENT_TYPES):
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) in (429, 500, 502, 503, 504):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in _TRANSIENT_KEYWORDS)


@dataclass
class ModelUsage:
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: Decimal


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_usages: list[ModelUsage] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TraceState:
    trace_id: str
    tenant_id: str
    conversation_id: str
    channel: str = "widget"
    actual_model: str = ""
    pool: Any = None
    sequence: int = 0
    request_tokens: TokenUsage = field(default_factory=TokenUsage)

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence


_trace_state: contextvars.ContextVar[TraceState | None] = contextvars.ContextVar("botnesia_trace_state", default=None)
_execution_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("botnesia_execution_id", default=None)
_execution_tokens: contextvars.ContextVar[TokenUsage | None] = contextvars.ContextVar("botnesia_execution_tokens", default=None)


def add_token_usage(*, model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Attach provider token usage and estimated cost to the active execution."""
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    model_name = model or "unknown"
    state = _trace_state.get()
    current = _execution_tokens.get()
    if current is not None:
        current.prompt_tokens += prompt
        current.completion_tokens += completion
        current.model_usages.append(
            ModelUsage(
                model=model_name,
                prompt_tokens=prompt,
                completion_tokens=completion,
                estimated_cost=estimate_cost_usd(model_name, prompt, completion),
            )
        )
    if state is not None:
        state.request_tokens.prompt_tokens += prompt
        state.request_tokens.completion_tokens += completion
        state.actual_model = model_name
    record_token_usage(
        org_id=state.tenant_id if state else None,
        model=model_name,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


def _confidence(value: Any) -> float | None:
    output = getattr(value, "output", None)
    if isinstance(output, dict):
        raw = output.get("confidence_score", output.get("confidence"))
    elif isinstance(value, dict):
        raw = value.get("confidence_score", value.get("confidence"))
    else:
        raw = getattr(value, "confidence_score", None)
    return float(raw) if isinstance(raw, (int, float)) else None


def _status(value: Any) -> tuple[str, str | None]:
    success = getattr(value, "success", True)
    error = getattr(value, "error", None)
    output = getattr(value, "output", value if isinstance(value, dict) else None)
    if success is False:
        return "error", str(error or "Agent execution failed")
    if isinstance(output, dict) and output.get("skipped"):
        return "skipped", None
    return "success", None


def _output_summary(value: Any) -> dict:
    output = getattr(value, "output", value if isinstance(value, dict) else {})
    if not isinstance(output, dict):
        return {}
    allowed = (
        "reasoning_summary", "conclusion", "limitations", "suggested_next_action",
        "verified", "issues", "complexity", "source", "matched", "has_objection",
        "should_escalate", "urgency", "intent", "skipped", "reason",
        "risk_if_wrong", "needs_clarification", "severity",
        "needs_revision", "overstatement_risk", "revised",
        "causal_links_count", "root_hypotheses_count",
        "uncertainty_band", "uncertainty_score", "uncertainty_reasons",
    )
    return {key: output[key] for key in allowed if key in output}


async def _execute(pool: Any, sql: str, *args: Any) -> None:
    if pool is None:
        return
    try:
        await pool.execute(sql, *args)
    except Exception:
        # Observability and cost accounting must never break customer responses.
        return


async def observe_agent(agent_name: str, context: dict, operation: Callable[[], Awaitable[T]]) -> T:
    """Track one agent lifecycle, token usage, and provider cost."""
    state = _trace_state.get()
    if state is None:
        return await operation()

    execution_id = str(uuid.uuid4())
    parent_id = _execution_id.get()
    sequence = state.next_sequence()
    started_at = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    usage = TokenUsage()
    id_token = _execution_id.set(execution_id)
    usage_token = _execution_tokens.set(usage)
    await _execute(
        state.pool,
        """INSERT INTO agent_executions
           (id, trace_id, parent_execution_id, tenant_id, conversation_id,
            agent_name, sequence_no, execution_start, status, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'running',NOW())""",
        execution_id, state.trace_id, parent_id, state.tenant_id,
        state.conversation_id, agent_name, sequence, started_at,
    )
    _emit(state.tenant_id, {"type": "agent", "agent_name": agent_name,
                            "status": "running", "trace_id": state.trace_id,
                            "ts": started_at.isoformat()})

    result: Any = None
    retry_count = 0
    error_stack: str | None = None
    try:
        # Auto-retry TRANSIENT dengan exponential backoff (maks _RETRY_MAX).
        # Error non-transient (bug logika, permission, value) gagal cepat.
        while True:
            try:
                result = await operation()
                break
            except Exception as exc:  # noqa: BLE001 — klasifikasi transient di bawah
                # Cegah multiplikasi retry pada observe_agent BERSARANG (mis.
                # supervisor membungkus operation yang juga memanggil observe_agent):
                # exception transient yang sudah di-retry di level dalam ditandai,
                # sehingga wrapper luar tidak me-retry ulang.
                already_retried = getattr(exc, "_bn_retried", False)
                if already_retried or retry_count >= _RETRY_MAX or not _is_transient(exc):
                    if _is_transient(exc) and retry_count and not already_retried:
                        try:
                            exc._bn_retried = True
                        except Exception:
                            pass
                    raise
                retry_count += 1
                await _execute(
                    state.pool,
                    "UPDATE agent_executions SET status='retrying', retry_count=$2 WHERE id=$1",
                    execution_id, retry_count,
                )
                _emit(state.tenant_id, {"type": "agent", "agent_name": agent_name,
                                        "status": "retrying", "retry_count": retry_count,
                                        "trace_id": state.trace_id})
                await asyncio.sleep(min(_RETRY_BASE_DELAY * (2 ** (retry_count - 1)), _RETRY_MAX_DELAY))
        status, error = _status(result)
        confidence = _confidence(result)
        return result
    except Exception as exc:
        # str(exc) bisa KOSONG untuk sejumlah exception (mis. CancelledError,
        # TimeoutError tanpa pesan) → dulu error_message tersimpan blank sehingga
        # dashboard menampilkan FAILED tanpa alasan. Selalu sertakan tipe exception
        # agar setiap kegagalan punya root cause yang bisa dibaca.
        _detail = str(exc).strip()
        error = f"{type(exc).__name__}: {_detail}" if _detail else type(exc).__name__
        if retry_count:
            error = f"{error} (setelah {retry_count} retry)"
        # Stacktrace lengkap untuk panel error-detail (dipangkas agar tak membengkak).
        error_stack = traceback.format_exc()[-6000:]
        status, confidence = "error", None
        raise
    finally:
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        await _execute(
            state.pool,
            """UPDATE agent_executions
               SET execution_end=$2, duration_ms=$3, status=$4, error_message=$5,
                   confidence_score=$6, prompt_tokens=$7, completion_tokens=$8,
                   total_tokens=$9, metadata=$10::jsonb, retry_count=$11, error_stack=$12
               WHERE id=$1""",
            execution_id, datetime.now(timezone.utc), duration_ms, status, error, confidence,
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            json.dumps(_output_summary(result), ensure_ascii=True), retry_count, error_stack,
        )
        _emit(state.tenant_id, {"type": "agent", "agent_name": agent_name,
                                "status": status, "retry_count": retry_count,
                                "error_message": error, "duration_ms": duration_ms,
                                "trace_id": state.trace_id})
        for model_usage in usage.model_usages:
            await _execute(
                state.pool,
                """INSERT INTO cost_records
                   (id, tenant_id, conversation_id, trace_id, execution_id,
                    model_name, agent_name, prompt_tokens, completion_tokens,
                    token_count, estimated_cost, currency, channel, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'USD',$12,NOW())""",
                str(uuid.uuid4()), state.tenant_id, state.conversation_id,
                state.trace_id, execution_id, model_usage.model, agent_name,
                model_usage.prompt_tokens, model_usage.completion_tokens,
                model_usage.prompt_tokens + model_usage.completion_tokens,
                model_usage.estimated_cost, state.channel,
            )
        record_ai_request(
            agent=agent_name,
            success=status in {"success", "skipped"},
            duration_seconds=duration_ms / 1000,
        )
        _execution_tokens.reset(usage_token)
        _execution_id.reset(id_token)


async def trace_request(context: dict, operation: Callable[[], Awaitable[T]]) -> T:
    """Create one request trace and select the cost-efficient model tier."""
    tenant_id = str(context.get("org_id") or context.get("tenant_id") or "")
    conversation_id = str(context.get("conversation_id") or "")
    pool = context.get("_observability_pool")
    if not tenant_id or not conversation_id:
        return await operation()

    trace_id = str(uuid.uuid4())
    metadata = context.get("metadata") or {}
    channel = str(metadata.get("channel") or context.get("channel") or "widget")
    route = choose_model(
        str(context.get("user_message") or ""),
        str(context.get("reasoning_mode") or "standard"),
        str(context.get("_cheap_model") or "llama-3.1-8b-instant"),
        str(context.get("_strong_model") or "meta-llama/llama-4-scout-17b-16e-instruct"),
    )
    route_token = set_model_route(route)
    state = TraceState(
        trace_id=trace_id, tenant_id=tenant_id, conversation_id=conversation_id,
        channel=channel, actual_model=route.model, pool=pool,
    )
    state_token = _trace_state.set(state)
    started = datetime.now(timezone.utc)
    await _execute(
        pool,
        """INSERT INTO ai_traces
           (id, tenant_id, conversation_id, user_question, status, started_at,
            routed_model, task_complexity, channel, created_at)
           VALUES ($1,$2,$3,$4,'running',$5,$6,$7,$8,NOW())""",
        trace_id, tenant_id, conversation_id,
        str(context.get("user_message") or "")[:10000], started,
        route.model, route.complexity, channel,
    )

    final_answer = ""
    trace_status = "error"
    try:
        result = await observe_agent("supervisor_agent", context, operation)
        final_answer = str(getattr(result, "final_answer", "") or "")
        try:
            result.prompt_tokens = state.request_tokens.prompt_tokens
            result.completion_tokens = state.request_tokens.completion_tokens
            result.total_tokens = state.request_tokens.total_tokens
            result.routed_model = state.actual_model
            result.task_complexity = route.complexity
        except (AttributeError, TypeError):
            pass
        trace_status = "error" if getattr(result, "errors", []) and not final_answer else "success"
        return result
    finally:
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        await _execute(
            pool,
            """UPDATE ai_traces
               SET final_answer=$2, status=$3, ended_at=NOW(), duration_ms=$4,
                   prompt_tokens=$5, completion_tokens=$6, total_tokens=$7,
                   routed_model=$8
               WHERE id=$1""",
            trace_id, final_answer[:20000], trace_status, duration_ms,
            state.request_tokens.prompt_tokens,
            state.request_tokens.completion_tokens,
            state.request_tokens.total_tokens,
            state.actual_model,
        )
        _trace_state.reset(state_token)
        reset_model_route(route_token)
