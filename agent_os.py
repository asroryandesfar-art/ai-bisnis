"""
agent_os.py — Agent OS Layer (transparansi pipeline) untuk BotNesia.

Modul ini TIDAK memanggil LLM, TIDAK mengubah state apapun, dan TIDAK
dipanggil dari `supervisor.py`'s `_process()`. Ini murni lapisan PELAPORAN
di atas pipeline yang SUDAH ADA -- `SupervisorAgent._process()` sudah
menjalankan plan -> tool-select -> execute -> verify -> retry -> report
secara penuh lewat modul-modul yang sudah berdiri sendiri (planner_agent,
reasoning_controller, cs_agent, verification_agent, reflection_engine,
uncertainty_engine). `build_execution_report()` di sini cuma membaca ulang
field yang sudah ada di `SupervisorResult` dan menyusunnya ke bentuk
"Agent OS 6-stage" supaya bisa ditampilkan (dashboard/identity) tanpa
membongkar pipeline aslinya.

Dipanggil oleh consumer DI LUAR pipeline (mis. endpoint dashboard di fase
berikutnya) -- bukan oleh `supervisor.py` sendiri, supaya modul ini tetap
nol-coupling terhadap jalur chat yang sudah stabil.
"""
from __future__ import annotations

from typing import Any

AGENT_OS_STAGES: dict[str, dict] = {
    "planning": {
        "description": "Menyusun rencana analisis (lensa spesialis mana yang relevan) untuk pertanyaan kompleks.",
        "implementation": "planner_agent.PlannerAgent",
    },
    "tool_selection": {
        "description": "Menentukan sumber pengetahuan/tool mana yang relevan (memory, knowledge base, web search, dst) beserta alasannya.",
        "implementation": "reasoning_controller.ReasoningController.analyze (knowledge_routing)",
    },
    "execution": {
        "description": "Menjalankan lensa spesialis (Pro mode) dan menyusun jawaban akhir.",
        "implementation": "reasoning_agent.ReasoningAgent + cs_agent.CSAgent.synthesize",
    },
    "verification": {
        "description": "Memeriksa kualitas jawaban: risiko halusinasi, kelengkapan, konsistensi.",
        "implementation": "verification_agent.VerificationAgent",
    },
    "retry": {
        "description": "Mengulang sintesis (maksimal beberapa kali) bila verifikasi belum lolos confidence minimum.",
        "implementation": "supervisor.SupervisorAgent._process MAX_RETRIES loop",
    },
    "reporting": {
        "description": "Self-check akhir terhadap reasoning brief, lalu menetapkan band confidence (High/Medium/Low) untuk dilaporkan ke user.",
        "implementation": "reflection_engine.reflect + uncertainty_engine.UncertaintyEngine",
    },
}


def describe_stage(name: str) -> dict:
    """Lookup-with-default, mirror tool_registry.describe_tool()."""
    return AGENT_OS_STAGES.get(name, {"description": "Stage tidak dikenal.", "implementation": "-"})


def build_execution_report(result: Any) -> dict:
    """Reshape SupervisorResult yang sudah ada menjadi laporan 6-stage Agent OS.

    `result` adalah instance supervisor.SupervisorResult (diketik Any di sini
    supaya modul ini tidak perlu import supervisor.py -- hindari circular
    import, karena supervisor.py-lah yang nanti bisa memanggil modul ini,
    bukan sebaliknya). Fungsi ini murni, tidak mengubah `result` sama sekali.
    """
    reasoning_brief = getattr(result, "reasoning_brief", None) or {}
    knowledge_routing = reasoning_brief.get("knowledge_routing") if isinstance(reasoning_brief, dict) else None

    return {
        "planning": {
            **describe_stage("planning"),
            "data": getattr(result, "plan", None),
        },
        "tool_selection": {
            **describe_stage("tool_selection"),
            "data": knowledge_routing,
        },
        "execution": {
            **describe_stage("execution"),
            "data": {
                "reasoning_mode_used": getattr(result, "reasoning_mode_used", None),
                "specialist_results": getattr(result, "specialist_results", None),
            },
        },
        "verification": {
            **describe_stage("verification"),
            "data": {
                "verification_passed": getattr(result, "verification_passed", None),
                "verification_issues": getattr(result, "verification_issues", None),
                "confidence_score": getattr(result, "confidence_score", None),
            },
        },
        "retry": {
            **describe_stage("retry"),
            "data": {"retry_count": getattr(result, "retry_count", None)},
        },
        "reporting": {
            **describe_stage("reporting"),
            "data": {
                "reflection_review": getattr(result, "reflection_review", None),
                "uncertainty_band": getattr(result, "uncertainty_band", None),
                "uncertainty_score": getattr(result, "uncertainty_score", None),
                "uncertainty_reasons": getattr(result, "uncertainty_reasons", None),
            },
        },
    }
