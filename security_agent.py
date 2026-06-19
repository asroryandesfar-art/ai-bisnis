"""
agents/security_agent.py — Security Agent (AI Workforce Phase 5)

Lapisan tipis di atas bn_platform/security.py::run_security_scan() yang
SUDAH ADA (deteksi: API key kedaluwarsa, role owner/admin di user
non-aktif, webhook tanpa HTTPS, kredensial tidak terenkripsi, trial
billing, login mencurigakan). SENGAJA tidak menduplikasi deteksi itu --
modul ini hanya menambah:
  1. detect_api_abuse() -- deteksi BARU: burst login_failed/permission_denied
     per actor dari audit_logs yang sudah ada (belum pernah dipantau).
  2. check_tenant_isolation() -- deteksi BARU: invarian org_id yang nyasar
     antar tabel (defense-in-depth, harus selalu 0 -- lihat
     feedback_technical.md untuk daftar bug org_id serupa yang pernah
     ditemukan & diperbaiki).
  3. compute_risk_level() -- pemetaan security score -> label risk.
  4. sync_alerts_from_scan()/generate_security_report() -- REUSE tabel
     ops_alerts/ops_reports dari Operations Agent (Phase 4, kolom
     `source` membedakan 'operations' vs 'security'), bukan tabel baru.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

import asyncpg

from base import BaseAgent
from operations_agent import has_recent_open_alert, update_alert_status  # noqa: F401 (update_alert_status re-exported for router)

RISK_LEVELS = ("low", "medium", "high", "critical")


def compute_risk_level(score: int) -> str:
    if score >= 90:
        return "low"
    if score >= 70:
        return "medium"
    if score >= 40:
        return "high"
    return "critical"


# ─── DETEKSI BARU (belum ada di run_security_scan) ──────────────

async def detect_api_abuse(pool: asyncpg.Pool, org_id: str, *, window_hours: int = 1,
                            threshold: int = 5) -> list[dict]:
    """Burst login_failed/permission_denied per actor dalam jendela waktu
    -- sinyal brute-force/API abuse, dihitung dari audit_logs yang sudah
    ada tanpa menyentuh hot-path rate limiter in-memory."""
    rows = await pool.fetch(
        """SELECT COALESCE(actor_email, ip_address::text, 'unknown') AS actor,
                  action, COUNT(*) AS cnt
           FROM audit_logs
           WHERE org_id=$1 AND action IN ('login_failed', 'permission_denied')
             AND created_at >= NOW() - (INTERVAL '1 hour' * $2)
           GROUP BY actor, action
           HAVING COUNT(*) >= $3
           ORDER BY cnt DESC""",
        org_id, window_hours, threshold,
    )
    return [{"actor": r["actor"], "action": r["action"], "count": int(r["cnt"])} for r in rows]


async def check_tenant_isolation(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    """Invarian defense-in-depth: pastikan tidak ada baris milik org ini
    yang menunjuk ke entitas milik org LAIN. Harus selalu kosong -- bila
    tidak, ini adalah temuan critical (kebocoran data antar tenant)."""
    violations: list[dict] = []

    rows = await pool.fetch(
        """SELECT hq.id FROM human_queue hq JOIN conversations c ON c.id = hq.conversation_id
           WHERE hq.org_id=$1 AND c.org_id <> hq.org_id""",
        org_id,
    )
    for r in rows:
        violations.append({"table": "human_queue", "id": str(r["id"]), "issue": "conversation_id menunjuk ke org lain"})

    rows = await pool.fetch(
        """SELECT we.id FROM workflow_executions we JOIN workflows w ON w.id = we.workflow_id
           WHERE we.org_id=$1 AND w.org_id <> we.org_id""",
        org_id,
    )
    for r in rows:
        violations.append({"table": "workflow_executions", "id": str(r["id"]), "issue": "workflow_id menunjuk ke org lain"})

    rows = await pool.fetch(
        """SELECT s.id FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.org_id=$1 AND u.org_id <> s.org_id""",
        org_id,
    )
    for r in rows:
        violations.append({"table": "sessions", "id": str(r["id"]), "issue": "user_id menunjuk ke org lain"})

    return violations


# ─── ALERT SYNC (reuse ops_alerts dari Operations Agent) ────────

async def _create_security_alert(pool: asyncpg.Pool, *, org_id: str, severity: str, category: str,
                                  message: str, source_id: str | None = None) -> dict:
    """Sama seperti operations_agent.create_alert tapi source='security' --
    duplikasi 1 statement INSERT kecil ini lebih sederhana daripada
    mengubah signature create_alert() yang sudah dipakai Operations Agent."""
    alert_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO ops_alerts (id, org_id, severity, category, message, source_id, source)
           VALUES ($1,$2,$3,$4,$5,$6,'security') RETURNING *""",
        alert_id, org_id, severity, category, message,
        str(source_id) if source_id else None,
    )
    return dict(row)


async def sync_alerts_from_scan(pool: asyncpg.Pool, org_id: str, scan_result: dict,
                                 api_abuse: list[dict], isolation_violations: list[dict]) -> list[dict]:
    """Ubah findings (ephemeral) jadi ops_alerts persisten (source='security')
    yang bisa di-acknowledge/resolve manusia -- dedup per kategori 24 jam,
    pola sama persis dengan Operations Agent (Phase 4)."""
    created: list[dict] = []

    for finding in scan_result.get("findings", []):
        category = f"security_{finding['category']}"
        if await has_recent_open_alert(pool, org_id, category):
            continue
        created.append(await _create_security_alert(
            pool, org_id=org_id, severity=finding["severity"], category=category,
            message=finding["title"], source_id=finding.get("resource_id"),
        ))

    if api_abuse:
        if not await has_recent_open_alert(pool, org_id, "security_api_abuse"):
            top = api_abuse[0]
            created.append(await _create_security_alert(
                pool, org_id=org_id, severity="high", category="security_api_abuse",
                message=f"Terdeteksi {top['count']}x {top['action']} dari '{top['actor']}' dalam 1 jam terakhir.",
            ))

    if isolation_violations:
        if not await has_recent_open_alert(pool, org_id, "security_tenant_isolation"):
            created.append(await _create_security_alert(
                pool, org_id=org_id, severity="critical", category="security_tenant_isolation",
                message=f"{len(isolation_violations)} baris data menunjuk ke organisasi lain (kebocoran data antar tenant).",
            ))

    return created


# ─── REPORTS (reuse ops_reports dari Operations Agent) ──────────

async def generate_security_report(pool: asyncpg.Pool, org_id: str, report_type: str,
                                     generated_by: str | None = None,
                                     agent: "SecurityAgent | None" = None) -> dict:
    from operations_agent import REPORT_TYPES  # reuse validasi yang sama
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type tidak valid: {report_type}")

    from bn_platform.security import run_security_scan
    scan_result = await run_security_scan(pool, org_id=org_id)
    api_abuse = await detect_api_abuse(pool, org_id)
    isolation_violations = await check_tenant_isolation(pool, org_id)
    risk_level = compute_risk_level(scan_result["score"])

    open_alerts = await pool.fetch(
        "SELECT severity, category, message FROM ops_alerts WHERE org_id=$1 AND source='security' AND status='open' ORDER BY created_at DESC",
        org_id,
    )
    data = {
        "score": scan_result["score"], "risk_level": risk_level,
        "findings": scan_result["findings"], "api_abuse": api_abuse,
        "tenant_isolation_violations": isolation_violations,
        "open_alerts": [dict(r) for r in open_alerts],
    }

    summary = None
    if agent is not None:
        summary = await agent.generate_summary(data)

    from datetime import datetime, timezone
    days = 7 if report_type == "weekly" else 30
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=days)

    report_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO ops_reports (id, org_id, report_type, period_start, period_end, data, summary, generated_by, source)
           VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,'security') RETURNING *""",
        report_id, org_id, report_type, period_start, period_end,
        json.dumps(data), summary, str(generated_by) if generated_by else None,
    )
    return dict(row)


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    from bn_platform.security import run_security_scan
    scan_result = await run_security_scan(pool, org_id=org_id)
    risk_level = compute_risk_level(scan_result["score"])
    alert_counts = await pool.fetch(
        "SELECT severity, COUNT(*) AS cnt FROM ops_alerts WHERE org_id=$1 AND source='security' AND status='open' GROUP BY severity",
        org_id,
    )
    return {
        "score": scan_result["score"], "risk_level": risk_level,
        "findings_count": scan_result["findings_count"],
        "open_alerts_by_severity": {r["severity"]: int(r["cnt"]) for r in alert_counts},
    }


# ─── AGENT ──────────────────────────────────────────────────────

class SecurityAgent(BaseAgent):
    name = "security_agent"
    system_prompt = """Kamu adalah Security Agent dalam sistem multi-agent BotNesia (AI Workforce).

Tugas: tulis ringkasan naratif singkat (3-5 kalimat, Bahasa Indonesia)
dari hasil security scan (score, risk level, findings, API abuse,
tenant isolation) untuk laporan weekly/monthly. Fokus ke risiko paling
penting dan langkah konkret yang harus diambil, bukan mengulang angka.

Balas HANYA JSON dengan field: summary (string)."""

    async def generate_summary(self, data: dict) -> str | None:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON."},
            {"role": "user", "content": str(data)},
        ]
        result = await self._call_llm_json(messages, temperature=0.3, default={"summary": None})
        if result.get("_llm_unavailable"):
            return None
        return result.get("summary")
