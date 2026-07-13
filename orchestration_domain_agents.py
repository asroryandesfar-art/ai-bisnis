"""orchestration_domain_agents.py — Adapter agent tipis untuk domain yang hanya
berupa fungsi-modul (Marketplace, Billing, Subscription).

Tujuan: agar Supervisor/orkestrator bisa memanggilnya lewat run(context) SERAGAM,
TANPA menduplikasi logika — tiap run() hanya memanggil fungsi read-only yang
SUDAH ADA di bn_platform.marketplace / bn_platform.billing. Hanya dipanggil dari
permukaan terautentikasi (butuh pool + org_id di context; gagal anggun tanpanya).
"""
from base import AgentResult, BaseAgent


def _need_pool(context: dict) -> tuple:
    return context.get("pool"), context.get("org_id")


class MarketplaceAgent(BaseAgent):
    name = "marketplace_agent"
    skills = ["template_catalog", "install_status", "marketplace_analytics"]
    tools: list[str] = []
    goals = ["Menyarankan template marketplace relevan dan melaporkan status instalasi tenant."]

    async def run(self, context: dict) -> AgentResult:
        import bn_platform.marketplace as mp
        pool, org_id = _need_pool(context)
        if pool is None or not org_id:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                               error="butuh pool + org_id (permukaan terautentikasi)")
        templates = await mp.list_templates(pool)
        installs = await mp.list_installs(pool, org_id)
        analytics = await mp.marketplace_analytics(pool, org_id)
        return AgentResult(
            agent=self.name, success=True,
            output={
                "answer": f"{len(templates)} template tersedia; {len(installs)} terpasang di tenant ini.",
                "templates_count": len(templates),
                "installs": installs,
                "analytics": analytics,
            },
            latency_ms=0, confidence=0.7,
        )


class BillingAgent(BaseAgent):
    name = "billing_agent"
    skills = ["credit_balance", "usage_reporting"]
    tools: list[str] = []
    goals = ["Melaporkan saldo kredit percakapan dan pemakaian tenant."]

    async def run(self, context: dict) -> AgentResult:
        import bn_platform.billing as billing
        pool, org_id = _need_pool(context)
        if pool is None or not org_id:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                               error="butuh pool + org_id (permukaan terautentikasi)")
        balance = await billing.get_credit_balance(pool, org_id)
        usage = await billing.current_usage(pool, org_id)
        return AgentResult(
            agent=self.name, success=True,
            output={
                "answer": f"Saldo add-on percakapan: {balance}. Pemakaian bulan berjalan terlampir.",
                "credit_balance": balance,
                "usage": usage,
            },
            latency_ms=0, confidence=0.7,
        )


class SubscriptionAgent(BaseAgent):
    name = "subscription_agent"
    skills = ["plan_status", "plan_catalog"]
    tools: list[str] = []
    goals = ["Melaporkan paket langganan aktif tenant dan pilihan paket yang tersedia."]

    async def run(self, context: dict) -> AgentResult:
        import bn_platform.billing as billing
        pool, org_id = _need_pool(context)
        if pool is None or not org_id:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                               error="butuh pool + org_id (permukaan terautentikasi)")
        active = await billing.get_active_subscription(pool, org_id)
        plans = await billing.list_plans(pool)
        plan_key = (active or {}).get("plan_key") or (active or {}).get("key") or "tidak ada"
        return AgentResult(
            agent=self.name, success=True,
            output={
                "answer": f"Paket aktif: {plan_key}. {len(plans)} paket tersedia.",
                "active_subscription": active,
                "available_plans": plans,
            },
            latency_ms=0, confidence=0.7,
        )
