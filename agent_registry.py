"""
agent_registry.py — Agent Directory + Admin Agent (AI Agent Platform Phase 5).

Katalog deklaratif setiap "digital employee" agent di platform ini (BUKAN
agent mesin-internal reasoning pipeline seperti Devil's Advocate/Verification/
Planner/Intent Classifier -- itu komponen reasoning, bukan "karyawan").
`list_agents()` membaca atribut `skills`/`tools`/`goals` yang SUDAH ADA di
tiap class lewat import dinamis -- tidak hardcode duplikat supaya tidak
drift kalau atribut itu berubah. `AdminAgent` murni agregasi fakta (gaya
`executive_agent.gather_synthesis_data()`), tanpa LLM -- saran lintas-domain
sudah jadi tugas Executive Agent, tidak diduplikasi di sini.
"""
from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass

import asyncpg

from base import BaseAgent

CHAT_PIPELINE = "chat_pipeline"
AUTHENTICATED_API = "authenticated_api"

# (module_path, class_name, category, channel)
AGENT_DIRECTORY: list[tuple[str, str, str, str]] = [
    ("cs_agent", "CSAgent", "customer_service", CHAT_PIPELINE),
    ("intelligence.sales_agent", "SalesAgent", "sales", CHAT_PIPELINE),
    ("intelligence.faq_agent", "FAQAgent", "knowledge", CHAT_PIPELINE),
    ("intelligence.knowledge_agent", "KnowledgeAgent", "knowledge", CHAT_PIPELINE),
    ("finance_agent", "FinanceAgent", "finance", AUTHENTICATED_API),
    ("marketing_agent", "MarketingAgent", "marketing", AUTHENTICATED_API),
    ("hr_agent", "HRAgent", "hr", AUTHENTICATED_API),
    ("operations_agent", "OperationsAgent", "operations", AUTHENTICATED_API),
    ("security_agent", "SecurityAgent", "security", AUTHENTICATED_API),
    ("executive_agent", "ExecutiveAgent", "executive", AUTHENTICATED_API),
    ("workforce_orchestrator", "WorkforceOrchestratorAgent", "workforce", AUTHENTICATED_API),
    ("self_learning_engine", "SelfLearningAgent", "self_learning", AUTHENTICATED_API),
    ("general_ai_agent", "GeneralAIAgent", "general_ai", CHAT_PIPELINE),
    ("research_agent", "ResearchAgent", "research", AUTHENTICATED_API),
    ("computer_agent", "ComputerAgent", "computer_use", CHAT_PIPELINE),
]


# ── Orkestrasi multi-agent (endpoint internal terautentikasi) ───────────────
# Agent tambahan yang BUKAN "digital employee" di AGENT_DIRECTORY tapi valid
# dipanggil orkestrator internal (support/analitik). Format sama:
# (module_path, class_name, category, channel).
ORCHESTRATION_EXTRA: list[tuple[str, str, str, str]] = [
    ("analytics", "AnalyticsAgent", "analytics", AUTHENTICATED_API),
    ("memory_agent", "MemoryAgent", "memory", AUTHENTICATED_API),
    ("web_search_agent", "SearchAgent", "search", AUTHENTICATED_API),
    ("orchestration_domain_agents", "MarketplaceAgent", "marketplace", AUTHENTICATED_API),
    ("orchestration_domain_agents", "BillingAgent", "billing", AUTHENTICATED_API),
    ("orchestration_domain_agents", "SubscriptionAgent", "subscription", AUTHENTICATED_API),
    # Casper Engineer — agen software-engineer otonom (modul terpisah dari Casper Blockchain).
    ("casper_engineer", "CasperEngineerAgent", "engineering", AUTHENTICATED_API),
]

# Permission RBAC yang diwajibkan agar sebuah kategori boleh dipanggil di
# orkestrator internal. None = cukup terautentikasi (aman lintas-peran).
# Sumber tunggal; TIDAK menduplikasi tabel dispatch — routing tetap dinamis.
AGENT_PERMISSION_BY_CATEGORY: dict[str, str | None] = {
    "customer_service": None,
    "sales":            None,
    "general_ai":       None,
    "memory":           None,
    "knowledge":        "knowledge.read",
    "analytics":        "analytics.read",
    "finance":          "finance.read",
    "marketing":        "marketing.read",
    "hr":               "hr.read",
    "operations":       "operations.read",
    "security":         "security.read",
    "executive":        "analytics.read",
    "workforce":        "workforce.read",
    "self_learning":    "learning.read",
    "research":         "research.read",
    "search":           "research.read",
    "computer_use":     "computer_agent.read",
    "marketplace":      "bots.read",
    "billing":          "billing.read",
    "subscription":     "billing.read",
    "engineering":      "workforce.write",
}

# Kata kunci per kategori untuk router FALLBACK heuristik (dipakai hanya bila
# router LLM tidak tersedia/mengembalikan sampah). Bukan satu-satunya jalan
# routing; sekadar jaring pengaman deterministik.
AGENT_CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    "finance":   ["biaya", "harga", "gaji", "budget", "anggaran", "invoice", "profit", "cashflow", "revenue", "keuangan", "expense", "pajak"],
    "hr":        ["karyawan", "rekrut", "perekrutan", "kandidat", "interview", "gaji", "training", "cuti", "hr", "sdm", "onboarding"],
    "marketing": ["campaign", "konten", "iklan", "marketing", "promosi", "sosial media", "audience", "branding"],
    "analytics": ["analitik", "metrik", "statistik", "tren", "grafik", "conversion", "performa", "dashboard"],
    "research":  ["riset", "pelajari", "referensi", "sumber", "research", "analisa mendalam"],
    "search":    ["cari", "temukan", "terkini", "berita", "terbaru", "google", "web"],
    "operations":["operasional", "sla", "uptime", "kesehatan sistem", "alert", "insiden"],
    "security":  ["keamanan", "risiko", "audit", "kerentanan", "security", "breach"],
    "knowledge": ["dokumen", "kebijakan", "prosedur", "knowledge", "panduan", "sop"],
    "sales":     ["jual", "penawaran", "closing", "prospek", "diskon", "deal"],
    "customer_service": ["komplain", "keluhan", "bantuan", "refund", "layanan"],
    "marketplace": ["template", "marketplace", "pasang", "install", "katalog"],
    "billing":   ["kredit", "saldo", "tagihan", "billing", "pemakaian", "kuota"],
    "subscription": ["langganan", "paket", "plan", "upgrade", "downgrade", "subscription"],
    "executive": ["eksekutif", "ringkasan bisnis", "strategi", "board", "c-level"],
    "workforce": ["tugas", "task", "koordinasi", "konflik", "workforce", "assignment"],
    "self_learning": ["pembelajaran", "insight", "pola", "learning", "perbaikan otomatis"],
}


@dataclass
class OrchestrationAgentSpec:
    """Deskriptor satu agent yang bisa dipanggil orkestrator internal."""
    name:         str
    class_name:   str
    category:     str
    module_path:  str
    permission:   str | None
    capabilities: list[str]


def _overrides_run(cls: type) -> bool:
    """True bila class benar-benar mengimplementasikan run() sendiri.

    Dasar penemuan DINAMIS: hanya agent dengan run(context) sendiri yang bisa
    di-orkestrasi seragam via safe_run(). Agent berbasis fungsi-modul (mis.
    operations/security tanpa run()) otomatis TIDAK terdaftar sampai punya run()
    — tak perlu daftar hardcode terpisah.
    """
    return getattr(cls, "run", None) is not getattr(BaseAgent, "run", None)


def build_agent(module_path: str, class_name: str, **kwargs) -> BaseAgent:
    """Instansiasi agent secara dinamis dari (module_path, class_name).

    Kwarg yang tidak diterima __init__ agent DIBUANG otomatis (kecuali agent
    memakai **kwargs) supaya config LLM bersama aman dipakai lintas agent yang
    signature-nya beda-beda — tanpa TypeError.
    """
    import inspect
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    try:
        sig = inspect.signature(cls.__init__)
        has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_var_kw:
            allowed = set(sig.parameters) - {"self"}
            kwargs = {k: v for k, v in kwargs.items() if k in allowed}
    except (TypeError, ValueError):
        pass
    return cls(**kwargs)


def orchestration_agents(
    *, allowed_permissions: set[str] | None = None
) -> list[OrchestrationAgentSpec]:
    """Daftar agent yang boleh dipanggil orkestrator, difilter RBAC.

    Penemuan dinamis: gabung AGENT_DIRECTORY + ORCHESTRATION_EXTRA, sisakan yang
    override run(), lalu filter berdasarkan permission efektif user. Bila
    allowed_permissions None → tanpa filter (mis. konteks super-admin/test).
    """
    specs: list[OrchestrationAgentSpec] = []
    seen: set[str] = set()
    for module_path, class_name, category, _channel in (*AGENT_DIRECTORY, *ORCHESTRATION_EXTRA):
        if class_name in seen:
            continue
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception:
            continue
        if not _overrides_run(cls):
            continue
        perm = AGENT_PERMISSION_BY_CATEGORY.get(category)
        if (
            perm is not None
            and allowed_permissions is not None
            and perm not in allowed_permissions
            and "*" not in allowed_permissions
        ):
            continue
        seen.add(class_name)
        specs.append(OrchestrationAgentSpec(
            name=getattr(cls, "name", class_name),
            class_name=class_name,
            category=category,
            module_path=module_path,
            permission=perm,
            capabilities=AGENT_CAPABILITY_KEYWORDS.get(category, []),
        ))
    return specs


def list_agents() -> list[dict]:
    agents: list[dict] = []
    for module_path, class_name, category, channel in AGENT_DIRECTORY:
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception:
            continue
        agents.append({
            "name": getattr(cls, "name", class_name),
            "class_name": class_name,
            "category": category,
            "channel": channel,
            "skills": list(getattr(cls, "skills", [])),
            "tools": list(getattr(cls, "tools", [])),
            "goals": list(getattr(cls, "goals", [])),
        })
    return agents


def get_agent(name: str) -> dict | None:
    for agent in list_agents():
        if agent["name"] == name:
            return agent
    return None


class AdminAgent(BaseAgent):
    name = "admin_agent"
    skills = ["agent_directory", "platform_health_overview"]
    tools: list[str] = []
    goals = [
        "Menyediakan daftar lengkap agent yang ada di platform beserta skills/tools/goals-nya.",
        "Menyediakan ringkasan aktivitas lintas-sistem (execution log, workforce, computer agent) untuk Agent Center Dashboard.",
    ]

    async def platform_overview(self, pool: asyncpg.Pool, org_id: str) -> dict:
        import execution_log
        import workforce_orchestrator
        import computer_agent

        async def _pending_local_agent_commands() -> list:
            rows = await pool.fetch(
                "SELECT id FROM local_agent_commands WHERE org_id=$1 AND status='pending_approval'",
                org_id,
            )
            return [dict(r) for r in rows]

        results = await asyncio.gather(
            execution_log.execution_log_summary(pool, org_id),
            workforce_orchestrator.dashboard_summary(pool, org_id),
            computer_agent.list_tasks(pool, org_id=org_id, status="pending_approval"),
            _pending_local_agent_commands(),
            return_exceptions=True,
        )

        def _safe(value: object, fallback):
            return fallback if isinstance(value, Exception) else value

        execution_summary, workforce_summary, pending_ca_tasks, pending_la_commands = results
        agents = list_agents()
        return {
            "agents": {
                "total": len(agents),
                "by_category": {agent["category"]: sum(1 for a in agents if a["category"] == agent["category"]) for agent in agents},
                "items": agents,
            },
            "execution_log": _safe(execution_summary, {"by_source_type": {}, "by_status": {}}),
            "workforce": _safe(workforce_summary, {}),
            "computer_agent_pending_approval_count": len(_safe(pending_ca_tasks, [])),
            "local_agent_pending_approval_count": len(_safe(pending_la_commands, [])),
        }
