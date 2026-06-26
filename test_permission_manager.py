"""Tests untuk permission_manager.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from permission_manager import (
    Permission, PermissionManager, GrantMode,
    _TERMINAL_DANGEROUS_PATTERNS,
)


# ── Unit tests (no DB) ────────────────────────────────────────────────────────

class TestPermissionEnum:
    def test_all_permissions_defined(self):
        expected = {
            "read_files", "write_files", "delete_files", "run_terminal",
            "browser_access", "browser_write", "github_access", "database_access",
            "email_access", "api_access", "clipboard", "camera", "microphone", "screen",
        }
        actual = {p.value for p in Permission}
        assert actual == expected

    def test_grant_modes(self):
        assert GrantMode.ALLOW_ONCE.value == "allow_once"
        assert GrantMode.ALLOW_ALWAYS.value == "allow_always"
        assert GrantMode.DENY.value == "deny"


class TestDangerousCommand:
    def test_rm_rf_is_dangerous(self):
        pm = PermissionManager.__new__(PermissionManager)
        is_danger, reason = pm.is_dangerous_command("rm -rf /var/data")
        assert is_danger is True
        assert "rm -rf" in reason

    def test_normal_ls_safe(self):
        pm = PermissionManager.__new__(PermissionManager)
        is_danger, _ = pm.is_dangerous_command("ls -la /home/user")
        assert is_danger is False

    def test_git_status_safe(self):
        pm = PermissionManager.__new__(PermissionManager)
        is_danger, _ = pm.is_dangerous_command("git status")
        assert is_danger is False

    def test_dd_is_dangerous(self):
        pm = PermissionManager.__new__(PermissionManager)
        is_danger, _ = pm.is_dangerous_command("dd if=/dev/zero of=/dev/sda")
        assert is_danger is True


class TestRequiredPermission:
    def setup_method(self):
        self.pm = PermissionManager.__new__(PermissionManager)

    def test_file_read_maps_to_read_files(self):
        assert self.pm.required_permission("file_read") == Permission.READ_FILES

    def test_file_delete_maps_to_delete_files(self):
        assert self.pm.required_permission("file_delete") == Permission.DELETE_FILES

    def test_terminal_maps_to_run_terminal(self):
        assert self.pm.required_permission("terminal") == Permission.RUN_TERMINAL

    def test_browser_read_maps_to_browser_access(self):
        assert self.pm.required_permission("browser_read") == Permission.BROWSER_ACCESS

    def test_unknown_maps_to_api_access(self):
        assert self.pm.required_permission("unknown_action") == Permission.API_ACCESS


class TestIsDangerous:
    def setup_method(self):
        self.pm = PermissionManager.__new__(PermissionManager)

    def test_delete_files_is_dangerous(self):
        assert self.pm.is_dangerous(Permission.DELETE_FILES) is True

    def test_run_terminal_is_dangerous(self):
        assert self.pm.is_dangerous(Permission.RUN_TERMINAL) is True

    def test_read_files_not_dangerous(self):
        assert self.pm.is_dangerous(Permission.READ_FILES) is False

    def test_browser_access_not_dangerous(self):
        assert self.pm.is_dangerous(Permission.BROWSER_ACCESS) is False


# ── DB-backed tests ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_returns_not_set_when_table_missing():
    """Jika tabel belum ada, check() harus return not_set (bukan crash)."""
    mock_pool = AsyncMock()
    mock_pool.fetchrow.side_effect = Exception("table does not exist")

    pm = PermissionManager(mock_pool, "test-org-id")
    result = await pm.check(Permission.READ_FILES)

    assert result["allowed"] is False
    assert result["mode"] == "not_set"


@pytest.mark.asyncio
async def test_check_allow_always_returns_true():
    mock_pool = AsyncMock()
    row = {"id": "grant-uuid", "grant_mode": "allow_always", "used_at": None, "expires_at": None}
    mock_pool.fetchrow.return_value = row

    pm = PermissionManager(mock_pool, "test-org")
    result = await pm.check(Permission.BROWSER_ACCESS)

    assert result["allowed"] is True
    assert result["mode"] == "allow_always"


@pytest.mark.asyncio
async def test_check_deny_returns_false():
    mock_pool = AsyncMock()
    row = {"id": "grant-uuid", "grant_mode": "deny", "used_at": None, "expires_at": None}
    mock_pool.fetchrow.return_value = row

    pm = PermissionManager(mock_pool, "test-org")
    result = await pm.check(Permission.RUN_TERMINAL)

    assert result["allowed"] is False
    assert result["mode"] == "deny"


@pytest.mark.asyncio
async def test_check_allow_once_used_returns_false():
    """allow_once yang sudah dipakai (used_at != None) harus return False."""
    from datetime import datetime, timezone
    mock_pool = AsyncMock()
    row = {
        "id": "grant-uuid",
        "grant_mode": "allow_once",
        "used_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "expires_at": None,
    }
    mock_pool.fetchrow.return_value = row

    pm = PermissionManager(mock_pool, "test-org")
    result = await pm.check(Permission.WRITE_FILES)

    assert result["allowed"] is False
    assert result["mode"] == "used"


@pytest.mark.asyncio
async def test_grant_calls_db():
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"id": "new-grant-id"}

    pm = PermissionManager(mock_pool, "test-org")
    grant_id = await pm.grant(Permission.READ_FILES, GrantMode.ALLOW_ALWAYS, granted_by="user@test.com")

    assert grant_id == "new-grant-id"
    mock_pool.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_calls_db():
    mock_pool = AsyncMock()
    mock_pool.execute.return_value = "UPDATE 2"

    pm = PermissionManager(mock_pool, "test-org")
    count = await pm.revoke(Permission.RUN_TERMINAL)

    assert count == 2
    mock_pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_grants_returns_empty_on_error():
    mock_pool = AsyncMock()
    mock_pool.fetch.side_effect = Exception("connection error")

    pm = PermissionManager(mock_pool, "test-org")
    result = await pm.list_grants()

    assert result == []
