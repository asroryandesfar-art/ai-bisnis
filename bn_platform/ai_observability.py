"""Tenant-scoped API for AI execution metrics and trace inspection."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query

# Eksekusi yang masih 'running' lebih lama dari ini dianggap ZOMBIE (proses mati
# sebelum sempat menulis status akhir) → ditandai stalled/OFFLINE, bukan "running".
STALL_SECONDS = int(os.getenv("AGENT_STALL_SECONDS", "120"))


def is_stalled(last_status: str | None, last_seen_at, *, now=None, stall_seconds: int = STALL_SECONDS) -> bool:
    """True bila eksekusi tersangkut di 'running' melewati ambang stall."""
    if last_status != "running" or last_seen_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
        return (now - last_seen_at).total_seconds() > stall_seconds
    except Exception:
        return False


def diagnose_error(error_message: str | None, error_stack: str | None, retry_count: int) -> tuple[str, str]:
    """Root cause + suggested fix berbasis aturan (deterministik, bukan mock).

    Mengklasifikasi kegagalan dari pesan+stacktrace ke kategori yang bisa
    ditindaklanjuti. Dipakai panel error-detail dashboard.
    """
    text = f"{error_message or ''} {error_stack or ''}".lower()

    def has(*keys: str) -> bool:
        return any(k in text for k in keys)

    if has("rate limit", "429", "too many requests"):
        rc = "Rate limit provider AI."
        fix = "Kurangi frekuensi/panjang prompt, atau naikkan kuota/plan provider LLM."
    elif has("event loop is closed", "timeout", "timed out", "connect", "network",
             "502", "503", "504", "temporarily", "service unavailable"):
        rc = "Kegagalan transient (timeout/jaringan/provider sementara)."
        fix = "Otomatis di-retry (exponential backoff). Bila berulang: cek koneksi & status provider LLM, atau naikkan AGENT_RETRY_MAX / timeout."
    elif has("api key", "unauthorized", "401", "403", "forbidden", "permission", "invalid key"):
        rc = "Kredensial atau permission bermasalah."
        fix = "Verifikasi API key provider di .env dan RBAC permission untuk agent ini."
    elif has("json", "parse", "expecting value", "decode"):
        rc = "Output LLM tidak sesuai format yang diharapkan (parsing gagal)."
        fix = "Perketat instruksi format/skema output di prompt, atau tambah fallback parsing."
    elif has("keyerror", "attributeerror", "typeerror", "valueerror", "indexerror", "nonetype"):
        rc = "Bug logika / data tak terduga di kode agent."
        fix = "Lihat stacktrace di bawah; perbaiki penanganan input/None pada agent terkait + tambah unit test."
    elif has("modulenotfounderror", "importerror", "no module named"):
        rc = "Dependency belum terpasang."
        fix = "Pasang paket yang hilang (lihat nama modul di stacktrace) lalu restart layanan."
    else:
        rc = "Kegagalan belum terklasifikasi."
        fix = "Periksa stacktrace lengkap untuk detail; tambahkan penanganan error spesifik + test."

    if retry_count:
        rc = f"{rc} (sudah {retry_count}× auto-retry sebelum gagal)"
    return rc, fix


def build_ai_observability_router(*, get_pool: Callable, get_current_user: Callable) -> APIRouter:
    router = APIRouter(prefix="/observability", tags=["ai-observability"])

    @router.get("/summary")
    async def summary(
        days: int = Query(7, ge=1, le=90),
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        org_id = user["org_id"]
        totals = await pool.fetchrow(
            """WITH windowed AS (
                   SELECT *
                   FROM agent_executions
                   WHERE tenant_id=$1 AND created_at >= NOW() - make_interval(days => $2::int)
               ),
               latest AS (
                   SELECT DISTINCT ON (agent_name) agent_name, status
                   FROM windowed
                   ORDER BY agent_name, execution_start DESC
               )
               SELECT
                   COUNT(*) FILTER (WHERE status='running' AND execution_start >= NOW() - INTERVAL '5 minutes') AS active_agents,
                   (SELECT COUNT(*) FROM latest WHERE status='error') AS failed_agents,
                   COALESCE(AVG(duration_ms) FILTER (WHERE status <> 'running'), 0)::float AS average_latency_ms,
                   COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens,
                   COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0)::bigint AS completion_tokens,
                   COALESCE(100.0 * COUNT(*) FILTER (WHERE status IN ('success','skipped')) /
                       NULLIF(COUNT(*) FILTER (WHERE status <> 'running'), 0), 0)::float AS success_rate,
                   COALESCE(100.0 * COUNT(*) FILTER (WHERE status='error') /
                       NULLIF(COUNT(*) FILTER (WHERE status <> 'running'), 0), 0)::float AS error_rate
               FROM windowed""",
            org_id, days,
        )
        agents = await pool.fetch(
            """WITH windowed AS (
                   SELECT *
                   FROM agent_executions
                   WHERE tenant_id=$1 AND created_at >= NOW() - make_interval(days => $2::int)
               ),
               latest AS (
                   SELECT DISTINCT ON (agent_name)
                          agent_name, status AS last_status, error_message AS last_error
                   FROM windowed
                   ORDER BY agent_name, execution_start DESC
               )
               SELECT w.agent_name,
                      COUNT(*)::int AS executions,
                      COUNT(*) FILTER (WHERE w.status='error')::int AS failures,
                      COALESCE(SUM(w.retry_count),0)::int AS retries,
                      COALESCE(AVG(w.duration_ms),0)::float AS average_latency_ms,
                      COALESCE(SUM(w.total_tokens),0)::bigint AS total_tokens,
                      MAX(w.execution_start) AS last_seen_at,
                      l.last_status,
                      l.last_error
               FROM windowed w
               JOIN latest l ON l.agent_name=w.agent_name
               GROUP BY w.agent_name, l.last_status, l.last_error
               ORDER BY executions DESC, agent_name""",
            org_id, days,
        )
        traces = await pool.fetch(
            """SELECT id, conversation_id, user_question, status, duration_ms,
                      prompt_tokens, completion_tokens, total_tokens, started_at,
                      (SELECT COUNT(*) FROM agent_executions ae WHERE ae.trace_id=t.id) AS agent_count
               FROM ai_traces t
               WHERE tenant_id=$1 AND created_at >= NOW() - make_interval(days => $2::int)
               ORDER BY started_at DESC LIMIT 50""",
            org_id, days,
        )
        agent_rows = []
        for row in agents:
            d = dict(row)
            d["stalled"] = is_stalled(d.get("last_status"), d.get("last_seen_at"))
            agent_rows.append(d)
        return {
            "window_days": days,
            "stall_seconds": STALL_SECONDS,
            "metrics": dict(totals or {}),
            "agents": agent_rows,
            "traces": [dict(row) for row in traces],
        }

    @router.get("/traces/{trace_id}")
    async def trace_detail(
        trace_id: str,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        trace = await pool.fetchrow(
            """SELECT id, tenant_id, conversation_id, user_question, final_answer,
                      status, started_at, ended_at, duration_ms,
                      prompt_tokens, completion_tokens, total_tokens
               FROM ai_traces WHERE id=$1 AND tenant_id=$2""",
            trace_id, user["org_id"],
        )
        if not trace:
            raise HTTPException(404, "Trace tidak ditemukan")
        executions = await pool.fetch(
            """SELECT id, parent_execution_id, agent_name, sequence_no,
                      execution_start, execution_end, duration_ms, status,
                      error_message, confidence_score::float AS confidence_score,
                      prompt_tokens, completion_tokens, total_tokens, metadata
               FROM agent_executions
               WHERE trace_id=$1 AND tenant_id=$2
               ORDER BY sequence_no, execution_start""",
            trace_id, user["org_id"],
        )
        return {"trace": dict(trace), "executions": [dict(row) for row in executions]}

    @router.get("/agents/{agent_name}/last-error")
    async def agent_last_error(
        agent_name: str,
        days: int = Query(7, ge=1, le=90),
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Detail kegagalan TERAKHIR sebuah agent untuk panel error yang diklik:
        Agent / Task / Error / Stacktrace / Retry Count / Root Cause / Suggested Fix."""
        row = await pool.fetchrow(
            """SELECT e.id, e.agent_name, e.status, e.error_message, e.error_stack,
                      e.retry_count, e.duration_ms, e.execution_start, e.trace_id,
                      e.conversation_id, t.user_question AS task
               FROM agent_executions e
               LEFT JOIN ai_traces t ON t.id = e.trace_id
               WHERE e.tenant_id=$1 AND e.agent_name=$2 AND e.status='error'
                 AND e.created_at >= NOW() - make_interval(days => $3::int)
               ORDER BY e.execution_start DESC LIMIT 1""",
            user["org_id"], agent_name, days,
        )
        if not row:
            raise HTTPException(404, "Tidak ada eksekusi error untuk agent ini di window tsb")
        d = dict(row)
        root_cause, suggested_fix = diagnose_error(
            d.get("error_message"), d.get("error_stack"), int(d.get("retry_count") or 0))
        d["root_cause"] = root_cause
        d["suggested_fix"] = suggested_fix
        return d

    return router
