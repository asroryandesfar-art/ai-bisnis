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

Sejak AI Agent Platform Phase: menambahkan service catalog untuk semua
service baru (ComputerUseService, FileSystemService, TerminalService, dll)
via `describe_agent_platform()` — murni dokumentasi, tidak ada eksekusi.
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


AGENT_PLATFORM_SERVICES: dict[str, dict] = {
    "ComputerUseService": {
        "module": "computer_use_service",
        "description": "Browser automation + native app interaction dengan permission gate",
        "capabilities": ["navigate", "read_text", "screenshot", "scroll", "click", "fill", "submit",
                         "inspect_desktop", "move_mouse", "double_click", "right_click", "drag",
                         "type_text", "press_hotkey", "open_application", "login", "scrape_page"],
        "requires_permission": ["browser_access", "browser_write", "screen"],
    },
    "FileSystemService": {
        "module": "file_system_service",
        "description": "Operasi file dengan permission gate (read/write/edit/rename/move/delete/compress/extract)",
        "capabilities": ["read_file", "write_file", "edit_file", "rename_file", "move_file",
                         "copy_file", "delete_file", "list_directory", "search_files",
                         "compress", "extract", "understand_project"],
        "requires_permission": ["read_files", "write_files", "delete_files"],
    },
    "TerminalService": {
        "module": "terminal_service",
        "description": "Shell command execution dengan timeout, approval gate, dan audit",
        "capabilities": ["execute", "git", "run_python", "npm", "pnpm", "docker",
                         "read_log", "kill_process", "list_processes"],
        "requires_permission": ["run_terminal"],
    },
    "PermissionManager": {
        "module": "permission_manager",
        "description": "Enterprise permission model: Allow Once/Always/Deny per resource per org",
        "capabilities": ["check", "grant", "revoke", "list_grants"],
        "permissions": ["read_files", "write_files", "delete_files", "run_terminal",
                        "browser_access", "browser_write", "github_access", "database_access",
                        "email_access", "api_access", "clipboard", "camera", "microphone", "screen"],
    },
    "SandboxManager": {
        "module": "sandbox_manager",
        "description": "Isolasi eksekusi: temporary workspace, rollback, resource limits",
        "capabilities": ["create_session", "rollback", "cleanup", "session (context manager)"],
    },
    "ActionExecutor": {
        "module": "action_executor",
        "description": "Pipeline: Understand→Plan→Permission→Execute→Observe→Recover→Verify→Summarize",
        "capabilities": ["execute", "understand_goal", "plan_goal", "verify_goal", "summarize_execution"],
    },
    "RecoveryManager": {
        "module": "recovery_manager",
        "description": "Auto-retry dengan backoff eksponensial + circuit breaker + fallback",
        "capabilities": ["with_retry", "with_fallback", "reset_circuit", "get_circuit_status"],
    },
    "AgentMemoryStore": {
        "module": "agent_memory_store",
        "description": "Agent-level memory: project structure, file history, terminal history, browser history",
        "capabilities": ["record_file_opened", "record_command", "record_url_visited",
                         "record_action", "update_project_structure", "get_summary",
                         "save_to_db", "load_from_db"],
    },
    "AuditLogger": {
        "module": "audit_logger",
        "description": "Audit trail semua aksi agent ke tabel agent_audit_log",
        "capabilities": ["log_action", "update_log", "list_logs"],
    },
}


def describe_agent_platform_service(name: str) -> dict:
    """Lookup service catalog AI Agent Platform."""
    return AGENT_PLATFORM_SERVICES.get(name, {"description": "Service tidak dikenal.", "module": "-"})


def list_agent_platform_services() -> list[str]:
    """Daftar semua service AI Agent Platform."""
    return list(AGENT_PLATFORM_SERVICES.keys())


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
