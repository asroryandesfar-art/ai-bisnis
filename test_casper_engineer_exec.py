"""Casper Engineer -> Local Agent bridge: auto-repo ingestion (read-only)."""
import asyncio

from casper_engineer_exec import gather_repo_context


def _fake_execute(responses, calls):
    async def execute(org_id, tool, args, *, device_id=None, initiated_by="", timeout=30, pool=None):
        calls.append({"tool": tool, "args": args, "device_id": device_id, "initiated_by": initiated_by})
        return responses.get(tool, {"success": False})
    return execute


def test_builds_context_from_scan_and_tree():
    calls = []
    responses = {
        "scan_project": {"success": True, "project_type": "python/fastapi", "total_files": 42,
                         "ext_count": {".py": 30, ".js": 10, ".md": 2},
                         "found_files": {"requirements.txt": {"preview": "fastapi\nasyncpg"},
                                         "README.md": {"preview": "# BotNesia"}}},
        "tree": {"success": True, "tree": "root/\n  main.py\n  bn_platform/"},
    }
    ctx, meta = asyncio.run(gather_repo_context(_fake_execute(responses, calls), "org-1", None, path="/proj"))
    assert "python/fastapi" in ctx
    assert "requirements.txt" in ctx and "fastapi" in ctx
    assert "STRUCTURE" in ctx and "main.py" in ctx
    assert meta["scanned"] is True and meta["project_type"] == "python/fastapi" and meta["total_files"] == 42
    # HANYA tool read-only yang dipanggil (tak boleh write_file/run_command).
    tools = {c["tool"] for c in calls}
    assert tools == {"scan_project", "tree"}
    assert all(c["initiated_by"] == "casper_engineer" for c in calls)
    assert all(c["args"].get("path") == "/proj" for c in calls)


def test_scan_failure_is_not_fatal():
    calls = []
    responses = {"scan_project": {"success": False, "error": "dir not found"},
                 "tree": {"success": False}}
    ctx, meta = asyncio.run(gather_repo_context(_fake_execute(responses, calls), "org-1", None))
    assert ctx == ""                     # tak ada konten, tapi tidak crash
    assert meta["scanned"] is False


def test_device_id_forwarded():
    calls = []
    responses = {"scan_project": {"success": True, "project_type": "node"}, "tree": {"success": True, "tree": "x"}}
    asyncio.run(gather_repo_context(_fake_execute(responses, calls), "org-1", None, device_id="dev-9"))
    assert all(c["device_id"] == "dev-9" for c in calls)
