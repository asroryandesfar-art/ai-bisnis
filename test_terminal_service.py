"""Tests untuk terminal_service.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from terminal_service import TerminalService, _needs_approval, _build_safe_env
from recovery_manager import _classify_error


# ── Pure function tests ────────────────────────────────────────────────────────

class TestNeedsApproval:
    def test_rm_rf_needs_approval(self):
        needs, reason = _needs_approval("rm -rf /tmp/test")
        assert needs is True
        assert "rm -rf" in reason.lower() or "berbahaya" in reason.lower()

    def test_ls_does_not_need_approval(self):
        needs, _ = _needs_approval("ls -la")
        assert needs is False

    def test_git_status_safe(self):
        needs, _ = _needs_approval("git status")
        assert needs is False

    def test_dd_needs_approval(self):
        needs, _ = _needs_approval("dd if=/dev/zero of=/dev/null")
        assert needs is True

    def test_shutdown_needs_approval(self):
        needs, _ = _needs_approval("shutdown -h now")
        assert needs is True

    def test_npm_install_safe(self):
        needs, _ = _needs_approval("npm install express")
        assert needs is False

    def test_docker_rm_force_needs_approval(self):
        needs, _ = _needs_approval("docker rm -f my_container")
        assert needs is True


class TestBuildSafeEnv:
    def test_path_preserved(self):
        env = _build_safe_env()
        assert "PATH" in env

    def test_no_secrets_leaked(self):
        env = _build_safe_env()
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "OPENAI_API_KEY" not in env
        assert "GROQ_API_KEY" not in env

    def test_extra_vars_included(self):
        env = _build_safe_env({"MY_CUSTOM_VAR": "hello"})
        assert env["MY_CUSTOM_VAR"] == "hello"


class TestClassifyError:
    def test_timeout_error(self):
        assert _classify_error("Request timed out after 30s") == "timeout"

    def test_network_error(self):
        assert _classify_error("Connection refused to 127.0.0.1:5432") == "network"

    def test_permission_error(self):
        assert _classify_error("Permission denied: /etc/shadow") == "permission"

    def test_not_found(self):
        assert _classify_error("File not found: /tmp/missing.txt") == "not_found"

    def test_rate_limit(self):
        assert _classify_error("429 Too Many Requests") == "rate_limit"

    def test_unknown_error(self):
        assert _classify_error("Something weird happened") == "unknown"


# ── Service tests (mock permission + subprocess) ──────────────────────────────

def _make_service(allowed=True):
    mock_pool = AsyncMock()
    mock_pm = AsyncMock()
    mock_pm.check = AsyncMock(return_value={"allowed": allowed, "mode": "allow_always", "grant_id": "g1"})
    return TerminalService(mock_pool, "test-org", mock_pm)


@pytest.mark.asyncio
async def test_execute_denied_without_permission():
    svc = _make_service(allowed=False)
    result = await svc.execute("ls -la")

    assert result["success"] is False
    assert "requires_permission" in result
    assert result["requires_permission"] == "run_terminal"


@pytest.mark.asyncio
async def test_execute_dangerous_without_approval():
    svc = _make_service(allowed=True)
    result = await svc.execute("rm -rf /tmp/test")

    assert result["success"] is False
    assert result.get("status") == "pending_approval"
    assert result.get("requires_approval") is True


@pytest.mark.asyncio
async def test_execute_dangerous_with_approval():
    svc = _make_service(allowed=True)
    # rm -rf pada direktori yang tidak ada — tidak akan crash tapi exit_code mungkin bukan 0
    result = await svc.execute("rm -rf /tmp/NONEXISTENT_BOTNESIA_TEST_DIR", approval_granted=True)
    # Harus dieksekusi (bukan blocked)
    assert "exit_code" in result
    assert "command" in result


@pytest.mark.asyncio
async def test_execute_simple_command():
    svc = _make_service(allowed=True)
    result = await svc.execute("echo hello_botnesia_test")

    assert result["success"] is True
    assert "hello_botnesia_test" in result["stdout"]
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_execute_records_in_history():
    svc = _make_service(allowed=True)
    await svc.execute("echo command1")
    await svc.execute("echo command2")

    history = svc.get_history()
    assert len(history) >= 2
    assert any("echo command1" in h["command"] for h in history)


@pytest.mark.asyncio
async def test_empty_command_returns_error():
    svc = _make_service(allowed=True)
    result = await svc.execute("")

    assert result["success"] is False
    assert "kosong" in result["error"].lower() or "empty" in result["error"].lower()


@pytest.mark.asyncio
async def test_git_shortcut():
    svc = _make_service(allowed=True)
    result = await svc.git("--version")

    # git harus ada di sistem
    assert result["exit_code"] == 0
    assert "git" in result["stdout"].lower()


@pytest.mark.asyncio
async def test_list_processes():
    svc = _make_service(allowed=True)
    result = await svc.list_processes()

    assert result["success"] is True
    assert len(result["stdout"]) > 0


@pytest.mark.asyncio
async def test_timeout_respected():
    svc = _make_service(allowed=True)
    result = await svc.execute("sleep 10", timeout=1)

    assert result["success"] is False
    assert "timeout" in result["error"].lower()
