"""Persistent, fail-open tracing for the BotNesia multi-agent pipeline."""
from __future__ import annotations

import contextvars
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

from bn_platform.observability import record_ai_request, record_token_usage

T = TypeVar("T")


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TraceState:
    trace_id: str
    tenant_id: str
    conversation_id: str
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
    """Attach provider token usage to the active agent and request."""
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    state = _trace_state.get()
    current = _execution_tokens.get()
    if current is not None:
        current.prompt_tokens += prompt
        current.completion_tokens += completion
    if state is not None:
        state.request_tokens.prompt_tokens += prompt
        state.request_tokens.completion_tokens += completion
    record_token_usage(
        org_id=state.tenant_id if state else None,
        model=model or "unknown",
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
    )
    return {key: output[key] for key in allowed if key in output}


async def _execute(pool: Any, sql: str, *args: Any) -> None:
    if pool is None:
        return
    try:
        await pool.execute(sql, *args)
    except Exception:
        # Observability must never break the customer response.
        return


async def observe_agent(agent_name: str, context: dict, operation: Callable[[], Awaitable[T]]) -> T:
    """Track one agent lifecycle, including parallel child relationships."""
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

    result: Any = None
    try:
        result = await operation()
        status, error = _status(result)
        confidence = _confidence(result)
        return result
    except Exception as exc:
        status, error, confidence = "error", str(exc), None
        raise
    finally:
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        await _execute(
            state.pool,
            """UPDATE agent_executions
               SET execution_end=$2, duration_ms=$3, status=$4, error_message=$5,
                   confidence_score=$6, prompt_tokens=$7, completion_tokens=$8,
                   total_tokens=$9, metadata=$10::jsonb
               WHERE id=$1""",
            execution_id, datetime.now(timezone.utc), duration_ms, status, error, confidence,
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            json.dumps(_output_summary(result), ensure_ascii=True),
        )
        record_ai_request(
            agent=agent_name,
            success=status in {"success", "skipped"},
            duration_seconds=duration_ms / 1000,
        )
        _execution_tokens.reset(usage_token)
        _execution_id.reset(id_token)


async def trace_request(context: dict, operation: Callable[[], Awaitable[T]]) -> T:
    """Create one request trace and run the supervisor as its root execution."""
    tenant_id = str(context.get("org_id") or context.get("tenant_id") or "")
    conversation_id = str(context.get("conversation_id") or "")
    pool = context.get("_observability_pool")
    if not tenant_id or not conversation_id:
        return await operation()

    trace_id = str(uuid.uuid4())
    state = TraceState(trace_id, tenant_id, conversation_id, pool)
    state_token = _trace_state.set(state)
    started = datetime.now(timezone.utc)
    await _execute(
        pool,
        """INSERT INTO ai_traces
           (id, tenant_id, conversation_id, user_question, status, started_at, created_at)
           VALUES ($1,$2,$3,$4,'running',$5,NOW())""",
        trace_id, tenant_id, conversation_id,
        str(context.get("user_message") or "")[:10000], started,
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
                   prompt_tokens=$5, completion_tokens=$6, total_tokens=$7
               WHERE id=$1""",
            trace_id, final_answer[:20000], trace_status, duration_ms,
            state.request_tokens.prompt_tokens,
            state.request_tokens.completion_tokens,
            state.request_tokens.total_tokens,
        )
        _trace_state.reset(state_token)
