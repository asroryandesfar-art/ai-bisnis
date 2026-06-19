"""
agents/operations_agent.py — Operations Agent (AI Workforce Phase 4)

Tenant health monitoring, workflow monitoring, SLA monitoring, dan
weekly/monthly report dengan critical alert. SENGAJA tidak menduplikasi
data: semua sinyal diagregasi read-only dari tabel yang sudah ada
(workflow_executions, human_queue, ai_improvement_recommendations,
conversations) -- mengikuti pola improvement_engine.py yang sudah ada.
Hanya menulis ke 2 tabel baru: ops_alerts (alert yang butuh tindak lanjut
manusia) dan ops_reports (snapshot laporan).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg

from base import BaseAgent

ALERT_SEVERITIES = {"low", "medium", "high", "critical"}
ALERT_STATUSES = {"open", "acknowledged", "resolved"}
REPORT_TYPES = {"weekly", "monthly"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── HEALTH METRICS (read-only agregasi, tanpa LLM) ────────────

async def detect_workflow_health(pool: asyncpg.Pool, org_id: str, days: int = 7) -> dict:
    row = await pool.fetchrow(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE status='success') AS success_cnt,
                  COUNT(*) FILTER (WHERE status='failed') AS failed_cnt,
                  ROUND(AVG(duration_ms)::numeric, 0) AS avg_duration_ms
           FROM workflow_executions
           WHERE org_id=$1 AND started_at >= NOW() - (INTERVAL '1 day' * $2)""",
        org_id, days,
    )
    total = int(row["total"])
    failed = int(row["failed_cnt"])
    success_rate = round((int(row["success_cnt"]) / total) * 100, 1) if total > 0 else None
    recent_failures = await pool.fetch(
        """SELECT id, workflow_id, error, started_at FROM workflow_executions
           WHERE org_id=$1 AND status='failed' AND started_at >= NOW() - (INTERVAL '1 day' * $2)
           ORDER BY started_at DESC LIMIT 5""",
        org_id, days,
    )
    return {
        "total_executions": total, "failed_count": failed, "success_rate_pct": success_rate,
        "avg_duration_ms": int(row["avg_duration_ms"]) if row["avg_duration_ms"] is not None else None,
        "recent_failures": [
            {"id": str(r["id"]), "workflow_id": str(r["workflow_id"]), "error": r["error"],
             "started_at": r["started_at"].isoformat() if r["started_at"] else None}
            for r in recent_failures
        ],
    }


async def detect_sla_health(pool: asyncpg.Pool, org_id: str, days: int = 7) -> dict:
    row = await pool.fetchrow(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE status='resolved' AND resolved_at > sla_due_at) AS breached_cnt,
                  ROUND((AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60)
                    FILTER (WHERE status='resolved'))::numeric, 1) AS avg_resolution_minutes
           FROM human_queue
           WHERE org_id=$1 AND created_at >= NOW() - (INTERVAL '1 day' * $2)""",
        org_id, days,
    )
    total = int(row["total"])
    breached = int(row["breached_cnt"])
    breach_rate = round((breached / total) * 100, 1) if total > 0 else None
    return {
        "total_handoffs": total, "breached_count": breached, "breach_rate_pct": breach_rate,
        "avg_resolution_minutes": float(row["avg_resolution_minutes"]) if row["avg_resolution_minutes"] is not None else None,
    }


async def detect_tenant_activity(pool: asyncpg.Pool, org_id: str) -> dict:
    row = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '7 days') AS convs_7d,
             COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '30 days') AS convs_30d,
             MAX(last_msg_at) AS last_activity_at
           FROM conversations WHERE org_id=$1""",
        org_id,
    )
    last_activity = row["last_activity_at"]
    is_inactive = (last_activity is None) or (last_activity < _now() - timedelta(days=14))
    return {
        "conversations_7d": int(row["convs_7d"]), "conversations_30d": int(row["convs_30d"]),
        "last_activity_at": last_activity.isoformat() if last_activity else None,
        "is_inactive": bool(is_inactive),
    }


def compute_health_score(workflow_health: dict, sla_health: dict, tenant_activity: dict) -> dict:
    score = 100
    reasons = []
    if workflow_health.get("success_rate_pct") is not None and workflow_health["success_rate_pct"] < 90:
        penalty = round((90 - workflow_health["success_rate_pct"]) * 0.5)
        score -= penalty
        reasons.append(f"Workflow success rate {workflow_health['success_rate_pct']}% (di bawah 90%)")
    if sla_health.get("breach_rate_pct") is not None and sla_health["breach_rate_pct"] > 10:
        penalty = round((sla_health["breach_rate_pct"] - 10) * 0.5)
        score -= penalty
        reasons.append(f"SLA breach rate {sla_health['breach_rate_pct']}% (di atas 10%)")
    if tenant_activity.get("is_inactive"):
        score -= 30
        reasons.append("Tidak ada aktivitas percakapan dalam 14 hari terakhir")
    score = max(0, min(100, score))
    label = "healthy" if score >= 80 else ("warning" if score >= 50 else "critical")
    return {"score": score, "label": label, "reasons": reasons}


async def top_improvement_recommendations(pool: asyncpg.Pool, org_id: str, limit: int = 5) -> list[dict]:
    """Surface (BUKAN regenerasi) rekomendasi dari improvement_engine.py yang
    sudah ada -- Operations Agent tidak menduplikasi logika deteksinya."""
    rows = await pool.fetch(
        """SELECT id, category, severity, title, occurrence_count, status FROM ai_improvement_recommendations
           WHERE org_id=$1 AND status IN ('new','reviewed')
           ORDER BY (severity='critical') DESC, (severity='high') DESC, occurrence_count DESC
           LIMIT $2""",
        org_id, limit,
    )
    return [
        {"id": str(r["id"]), "category": r["category"], "severity": r["severity"],
         "title": r["title"], "occurrence_count": r["occurrence_count"], "status": r["status"]}
        for r in rows
    ]


# ─── ALERTS ─────────────────────────────────────────────────────

async def create_alert(pool: asyncpg.Pool, *, org_id: str, severity: str, category: str,
                        message: str, source_type: str | None = None,
                        source_id: str | None = None) -> dict:
    if severity not in ALERT_SEVERITIES:
        raise ValueError(f"severity tidak valid: {severity}")
    alert_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO ops_alerts (id, org_id, severity, category, message, source_type, source_id)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
        alert_id, org_id, severity, category, message, source_type,
        str(source_id) if source_id else None,
    )
    return dict(row)


async def has_recent_open_alert(pool: asyncpg.Pool, org_id: str, category: str, hours: int = 24) -> bool:
    """Cegah spam alert duplikat untuk kategori yang sama dalam jendela waktu."""
    row = await pool.fetchval(
        """SELECT 1 FROM ops_alerts WHERE org_id=$1 AND category=$2 AND status='open'
             AND created_at >= NOW() - (INTERVAL '1 hour' * $3) LIMIT 1""",
        org_id, category, hours,
    )
    return bool(row)


async def update_alert_status(pool: asyncpg.Pool, *, org_id: str, alert_id: str, status: str,
                                actor_id: str | None) -> dict | None:
    if status not in ALERT_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    if status == "acknowledged":
        row = await pool.fetchrow(
            """UPDATE ops_alerts SET status=$1, acknowledged_by=$2, acknowledged_at=NOW()
               WHERE id=$3 AND org_id=$4 RETURNING *""",
            status, str(actor_id) if actor_id else None, alert_id, org_id,
        )
    elif status == "resolved":
        row = await pool.fetchrow(
            "UPDATE ops_alerts SET status=$1, resolved_at=NOW() WHERE id=$2 AND org_id=$3 RETURNING *",
            status, alert_id, org_id,
        )
    else:
        row = await pool.fetchrow(
            "UPDATE ops_alerts SET status=$1 WHERE id=$2 AND org_id=$3 RETURNING *", status, alert_id, org_id,
        )
    return dict(row) if row else None


async def run_health_scan(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    """Deteksi masalah (no-LLM, heuristik ambang batas) lalu buat ops_alerts
    baru bila belum ada alert OPEN untuk kategori yang sama dalam 24 jam."""
    workflow_health = await detect_workflow_health(pool, org_id)
    sla_health = await detect_sla_health(pool, org_id)
    tenant_activity = await detect_tenant_activity(pool, org_id)

    created: list[dict] = []

    if workflow_health.get("success_rate_pct") is not None and workflow_health["success_rate_pct"] < 80:
        if not await has_recent_open_alert(pool, org_id, "workflow_failure"):
            created.append(await create_alert(
                pool, org_id=org_id, severity="high", category="workflow_failure",
                message=f"Workflow success rate turun ke {workflow_health['success_rate_pct']}% (7 hari terakhir).",
            ))

    if sla_health.get("breach_rate_pct") is not None and sla_health["breach_rate_pct"] > 20:
        if not await has_recent_open_alert(pool, org_id, "sla_breach"):
            created.append(await create_alert(
                pool, org_id=org_id, severity="high", category="sla_breach",
                message=f"SLA breach rate {sla_health['breach_rate_pct']}% (7 hari terakhir, di atas ambang 20%).",
            ))

    if tenant_activity.get("is_inactive"):
        if not await has_recent_open_alert(pool, org_id, "tenant_inactivity"):
            created.append(await create_alert(
                pool, org_id=org_id, severity="critical", category="tenant_inactivity",
                message="Tidak ada aktivitas percakapan dalam 14 hari terakhir.",
            ))

    recs = await top_improvement_recommendations(pool, org_id, limit=20)
    critical_recs = [r for r in recs if r["severity"] == "critical"]
    if len(critical_recs) >= 3:
        if not await has_recent_open_alert(pool, org_id, "improvement_backlog"):
            created.append(await create_alert(
                pool, org_id=org_id, severity="medium", category="improvement_backlog",
                message=f"{len(critical_recs)} rekomendasi improvement berseverity critical belum ditindaklanjuti.",
            ))

    return created


# ─── REPORTS ────────────────────────────────────────────────────

async def _build_report_data(pool: asyncpg.Pool, org_id: str, days: int) -> dict:
    workflow_health = await detect_workflow_health(pool, org_id, days=days)
    sla_health = await detect_sla_health(pool, org_id, days=days)
    tenant_activity = await detect_tenant_activity(pool, org_id)
    health = compute_health_score(workflow_health, sla_health, tenant_activity)
    recommendations = await top_improvement_recommendations(pool, org_id, limit=5)
    open_alerts = await pool.fetch(
        "SELECT severity, category, message FROM ops_alerts WHERE org_id=$1 AND status='open' ORDER BY created_at DESC",
        org_id,
    )
    return {
        "health": health, "workflow_health": workflow_health, "sla_health": sla_health,
        "tenant_activity": tenant_activity, "top_recommendations": recommendations,
        "open_alerts": [dict(r) for r in open_alerts],
    }


async def generate_report(pool: asyncpg.Pool, org_id: str, report_type: str,
                           generated_by: str | None = None, agent: "OperationsAgent | None" = None) -> dict:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type tidak valid: {report_type}")
    days = 7 if report_type == "weekly" else 30
    period_end = _now()
    period_start = period_end - timedelta(days=days)
    data = await _build_report_data(pool, org_id, days)

    summary = None
    if agent is not None:
        summary = await agent.generate_summary(data)

    report_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO ops_reports (id, org_id, report_type, period_start, period_end, data, summary, generated_by)
           VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8) RETURNING *""",
        report_id, org_id, report_type, period_start, period_end,
        json.dumps(data), summary, str(generated_by) if generated_by else None,
    )
    return dict(row)


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    workflow_health = await detect_workflow_health(pool, org_id, days=7)
    sla_health = await detect_sla_health(pool, org_id, days=7)
    tenant_activity = await detect_tenant_activity(pool, org_id)
    health = compute_health_score(workflow_health, sla_health, tenant_activity)
    alert_counts = await pool.fetch(
        "SELECT severity, COUNT(*) AS cnt FROM ops_alerts WHERE org_id=$1 AND status='open' GROUP BY severity",
        org_id,
    )
    return {
        "health": health, "workflow_health": workflow_health, "sla_health": sla_health,
        "tenant_activity": tenant_activity,
        "open_alerts_by_severity": {r["severity"]: int(r["cnt"]) for r in alert_counts},
    }


# ─── AGENT ──────────────────────────────────────────────────────

class OperationsAgent(BaseAgent):
    name = "operations_agent"
    system_prompt = """Kamu adalah Operations Agent dalam sistem multi-agent BotNesia (AI Workforce).

Tugas: tulis ringkasan naratif singkat (3-5 kalimat, Bahasa Indonesia)
dari data health/metrics operasional yang diberikan, untuk laporan
weekly/monthly bisnis tenant. Fokus ke insight yang actionable, bukan
sekadar mengulang angka.

Balas HANYA JSON dengan field: summary (string)."""

    async def generate_summary(self, metrics: dict) -> str | None:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON."},
            {"role": "user", "content": str(metrics)},
        ]
        result = await self._call_llm_json(messages, temperature=0.3, default={"summary": None})
        if result.get("_llm_unavailable"):
            return None
        return result.get("summary")
