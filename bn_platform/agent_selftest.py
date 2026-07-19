"""Agent readiness self-test — jalankan/validasi SETIAP agent satu per satu.

Menjawab "pastikan seluruh agent berhasil dieksekusi" secara JUJUR & deterministik
tanpa bergantung pada LLM: untuk tiap agent di registry, benar-benar meng-import
modul + meng-INSTANSIASI class (menjalankan __init__ nyata: load model/koneksi/
config) + memverifikasi ada entrypoint eksekusi yang bisa dipanggil. Menangkap
kelas bug nyata: import error, dependency hilang, konstruktor rusak, config invalid.
Setiap kegagalan dilaporkan dengan error + root cause + suggested fix (tidak
disembunyikan / tidak "dihijaukan" palsu).
"""
import time
import traceback

from fastapi import APIRouter, Depends

import agent_registry
from bn_platform.ai_observability import diagnose_error

# Metode yang dianggap entrypoint eksekusi agent.
_ENTRYPOINTS = ("run", "run_task", "process", "execute", "handle")


def _entrypoint(agent) -> str | None:
    for name in _ENTRYPOINTS:
        if callable(getattr(agent, name, None)):
            return name
    return None


def run_agent_self_test(config: dict) -> dict:
    """Konstruksi + verifikasi setiap agent. Return laporan per-agent."""
    results: list[dict] = []
    seen: set[str] = set()
    for module_path, class_name, category, _channel in (
        *agent_registry.AGENT_DIRECTORY, *agent_registry.ORCHESTRATION_EXTRA
    ):
        if class_name in seen:
            continue
        seen.add(class_name)
        t0 = time.perf_counter()
        entry: dict = {"agent": class_name, "category": category, "module": module_path}
        try:
            agent = agent_registry.build_agent(module_path, class_name, **config)
            entry["name"] = getattr(agent, "name", class_name)
            ep = _entrypoint(agent)
            entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
            if ep:
                entry["status"] = "ok"
                entry["entrypoint"] = ep
            else:
                entry["status"] = "failed"
                entry["error"] = "Tidak ada entrypoint eksekusi (run/run_task/process/execute)"
                entry["root_cause"] = "Agent ter-load tapi tak punya metode eksekusi standar."
                entry["suggested_fix"] = "Tambahkan method run()/run_task() pada class agent."
        except Exception as exc:  # noqa: BLE001 — semua kegagalan konstruksi dilaporkan
            entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
            entry["status"] = "failed"
            detail = str(exc).strip()
            entry["error"] = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
            rc, fix = diagnose_error(entry["error"], traceback.format_exc(), 0)
            entry["root_cause"] = rc
            entry["suggested_fix"] = fix
        results.append(entry)

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "failed")
    # Yang gagal di atas supaya langsung terlihat.
    results.sort(key=lambda r: (r["status"] != "failed", r["agent"]))
    return {"total": len(results), "ok": ok, "failed": failed, "agents": results}


def build_agent_selftest_router(*, get_current_user, agent_config: dict) -> APIRouter:
    router = APIRouter(prefix="/observability", tags=["agent-selftest"])

    @router.post("/self-test")
    async def self_test(user=Depends(get_current_user)):
        """Jalankan readiness self-test untuk semua agent. Read-only, aman."""
        return run_agent_self_test(agent_config)

    return router
