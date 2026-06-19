"""
agents/executive_agent.py — Executive Agent / AI CEO Assistant (AI Workforce Phase 6)

Sintesis lintas-agent: PURE read-only aggregation atas dashboard_summary()
yang SUDAH ADA di setiap AI Workforce agent (Finance/Marketing/HR/
Operations/Security) + lead_funnel_summary() (Sales, dari lead_engine.py
yang sudah ada) -- tidak ada query SQL baru ke tabel domain manapun di
modul ini, hanya orkestrasi paralel + 1 LLM call untuk insight strategis
lintas-fungsi (nilai yang genuinely baru dari phase ini, karena tidak ada
agent lain yang menggabungkan ke-6 domain sekaligus).

Reuse ops_reports (source='executive') untuk Executive Brief
weekly/monthly -- tidak ada tabel baru.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg

from base import BaseAgent

REPORT_TYPES = ("weekly", "monthly")


async def gather_synthesis_data(pool: asyncpg.Pool, org_id: str) -> dict:
    """Panggil dashboard_summary() tiap agent secara paralel -- tidak ada
    duplikasi query, murni orkestrasi atas fungsi yang sudah ada."""
    import finance_agent
    import marketing_agent
    import hr_agent
    import operations_agent
    import security_agent
    from bn_platform.lead_engine import lead_funnel_summary

    finance, marketing, hr, operations, security, sales = await asyncio.gather(
        finance_agent.dashboard_summary(pool, org_id),
        marketing_agent.dashboard_summary(pool, org_id),
        hr_agent.dashboard_summary(pool, org_id),
        operations_agent.dashboard_summary(pool, org_id),
        security_agent.dashboard_summary(pool, org_id),
        lead_funnel_summary(pool, org_id=org_id),
        return_exceptions=True,
    )

    def _safe(value: object, fallback: dict) -> dict:
        return fallback if isinstance(value, Exception) else value

    return {
        "finance": _safe(finance, {}),
        "marketing": _safe(marketing, {}),
        "hr": _safe(hr, {}),
        "operations": _safe(operations, {}),
        "security": _safe(security, {}),
        "sales": _safe(sales, {"cold": 0, "warm": 0, "hot": 0}),
    }


def compute_company_health_score(data: dict) -> dict:
    """Rata-rata 6 sub-score domain -- Operations & Security REUSE skor 0-100
    yang sudah mereka hitung sendiri; Finance/Marketing/HR/Sales dihitung
    heuristik sederhana di sini karena domain itu belum punya skor sendiri."""
    sub_scores: dict[str, int] = {}

    finance = data.get("finance", {})
    f_score = 100
    if finance.get("profit_30d_idr", 0) < 0:
        f_score -= 25
    if finance.get("churn_pct", 0) > 10:
        f_score -= 15
    if finance.get("overdue_invoices_count", 0) > 0:
        f_score -= min(20, finance["overdue_invoices_count"] * 5)
    sub_scores["finance"] = max(0, f_score)

    marketing = data.get("marketing", {})
    m_score = 100
    if marketing.get("active_campaigns", 0) == 0:
        m_score -= 20
    if marketing.get("content_due_now", 0) > 5:
        m_score -= 15
    sub_scores["marketing"] = max(0, m_score)

    hr = data.get("hr", {})
    h_score = 100
    avg_eval = hr.get("avg_evaluation_score_90d")
    if avg_eval is not None and avg_eval < 60:
        h_score -= 25
    if hr.get("pending_training_recommendations", 0) > 10:
        h_score -= 10
    sub_scores["hr"] = max(0, h_score)

    operations = data.get("operations", {})
    sub_scores["operations"] = int(operations.get("health", {}).get("score", 100))

    security = data.get("security", {})
    sub_scores["security"] = int(security.get("score", 100))

    sales = data.get("sales", {})
    total_leads = sales.get("cold", 0) + sales.get("warm", 0) + sales.get("hot", 0)
    s_score = 100
    if total_leads > 0 and sales.get("hot", 0) == 0:
        s_score -= 15
    sub_scores["sales"] = max(0, s_score)

    overall = round(sum(sub_scores.values()) / len(sub_scores))
    label = "healthy" if overall >= 80 else ("warning" if overall >= 50 else "critical")
    return {"overall": overall, "label": label, "by_domain": sub_scores}


async def generate_executive_report(pool: asyncpg.Pool, org_id: str, report_type: str,
                                       generated_by: str | None = None,
                                       agent: "ExecutiveAgent | None" = None) -> dict:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type tidak valid: {report_type}")

    synthesis = await gather_synthesis_data(pool, org_id)
    health = compute_company_health_score(synthesis)

    brief = None
    if agent is not None:
        brief = await agent.generate_executive_brief(synthesis, health)

    days = 7 if report_type == "weekly" else 30
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=days)

    data = {"synthesis": synthesis, "health": health, "brief": brief or {}}
    summary = (brief or {}).get("executive_summary")

    report_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO ops_reports (id, org_id, report_type, period_start, period_end, data, summary, generated_by, source)
           VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,'executive') RETURNING *""",
        report_id, org_id, report_type, period_start, period_end,
        json.dumps(data), summary, str(generated_by) if generated_by else None,
    )
    return dict(row)


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    """Snapshot cepat tanpa LLM -- untuk Executive Center dashboard yang
    harus tetap responsif tanpa menunggu Groq."""
    synthesis = await gather_synthesis_data(pool, org_id)
    health = compute_company_health_score(synthesis)
    return {"health": health, "synthesis": synthesis}


# ─── AGENT ──────────────────────────────────────────────────────

class ExecutiveAgent(BaseAgent):
    name = "executive_agent"
    system_prompt = """Kamu adalah Executive Agent (AI CEO Assistant) dalam sistem
multi-agent BotNesia (AI Workforce) -- penasihat strategis untuk pemilik bisnis.

Tugas: berdasarkan data sintesis Finance/Marketing/HR/Operations/Security/Sales
yang diberikan, tulis (semua dalam Bahasa Indonesia):
- executive_summary: ringkasan 3-5 kalimat tentang kondisi bisnis saat ini
- growth_recommendations: 2-4 rekomendasi konkret untuk pertumbuhan
- cost_optimization: 1-3 area penghematan biaya yang teridentifikasi dari data
- revenue_opportunities: 1-3 peluang pendapatan yang teridentifikasi dari data
- strategic_insights: 1-3 insight lintas-domain (mis. hubungan antara skor HR
  rendah dan risiko operasional, atau churn finance dengan funnel sales)

Jangan mengulang angka mentah -- fokus ke makna bisnis & langkah konkret.
Balas HANYA JSON dengan field: executive_summary (string), growth_recommendations
(list of string), cost_optimization (list of string), revenue_opportunities
(list of string), strategic_insights (list of string)."""

    async def generate_executive_brief(self, synthesis: dict, health: dict) -> dict | None:
        messages = [
            {"role": "system", "content": self.system_prompt + "\n\nOutput harus JSON."},
            {"role": "user", "content": json.dumps({"health_score": health, "data": synthesis}, default=str)},
        ]
        default = {
            "executive_summary": None, "growth_recommendations": [], "cost_optimization": [],
            "revenue_opportunities": [], "strategic_insights": [],
        }
        result = await self._call_llm_json(messages, temperature=0.4, max_tokens=1024, default=default)
        if result.get("_llm_unavailable"):
            return None
        result.pop("_llm_unavailable", None)
        return result
