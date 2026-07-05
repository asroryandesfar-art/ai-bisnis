"""H-01 — guard eskalasi privilege pada pemberian role RBAC.

Menguji pure function `assert_can_grant_role` / `_role_rank` yang menegakkan:
  - hanya Owner (rank 0) boleh grant owner/admin,
  - aktor tak boleh memberi role lebih tinggi dari role tertingginya.
"""
import pytest
from fastapi import HTTPException

from bn_platform import rbac

OWNER, ADMIN, MANAGER, AGENT, VIEWER = 0, 1, 2, 3, 4  # rank sesuai ROLE_ORDER


def _rank(role):
    return rbac._role_rank(role)


def test_role_rank_order():
    assert _rank("owner") < _rank("admin") < _rank("manager") < _rank("agent") < _rank("viewer")
    assert _rank("tidak-dikenal") >= _rank("viewer")  # role asing = paling rendah


# ── Owner boleh memberi apa pun ─────────────────────────────────────────
@pytest.mark.parametrize("role", ["owner", "admin", "manager", "agent", "viewer"])
def test_owner_can_grant_any_role(role):
    rbac.assert_can_grant_role(OWNER, role)  # tidak raise


# ── Admin TIDAK boleh membuat owner/admin (anti self-promote) ───────────
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_admin_cannot_grant_privileged_role(role):
    with pytest.raises(HTTPException) as exc:
        rbac.assert_can_grant_role(ADMIN, role)
    assert exc.value.status_code == 403


def test_admin_can_grant_lower_roles():
    for role in ("manager", "agent", "viewer"):
        rbac.assert_can_grant_role(ADMIN, role)  # tidak raise


# ── Manager/agent/viewer tak bisa menaikkan siapa pun ke atas dirinya ───
def test_manager_cannot_grant_above_self():
    with pytest.raises(HTTPException):
        rbac.assert_can_grant_role(MANAGER, "admin")
    with pytest.raises(HTTPException):
        rbac.assert_can_grant_role(MANAGER, "owner")
    rbac.assert_can_grant_role(MANAGER, "agent")     # boleh yg lebih rendah
    rbac.assert_can_grant_role(MANAGER, "manager")   # boleh setara


def test_viewer_cannot_escalate():
    for role in ("owner", "admin", "manager", "agent"):
        with pytest.raises(HTTPException):
            rbac.assert_can_grant_role(VIEWER, role)


def test_self_promote_owner_blocked_for_non_owner():
    # skenario audit: admin mencoba menjadikan dirinya owner
    with pytest.raises(HTTPException) as exc:
        rbac.assert_can_grant_role(ADMIN, "owner")
    assert exc.value.status_code == 403
