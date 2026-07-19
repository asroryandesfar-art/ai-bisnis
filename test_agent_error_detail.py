"""Error-detail panel — root cause / suggested fix rule-based + endpoint.

diagnose_error() harus deterministik dan mengklasifikasi ke kategori yang bisa
ditindaklanjuti (transient / rate-limit / permission / bug logika / dependency).
"""
from bn_platform.ai_observability import diagnose_error
import main


def test_diagnose_transient_notes_retry():
    rc, fix = diagnose_error("ReadTimeout: timed out", None, 3)
    assert "transient" in rc.lower()
    assert "3" in rc                       # retry count dicatat
    assert fix


def test_diagnose_rate_limit():
    rc, fix = diagnose_error("429 too many requests", None, 0)
    assert "rate limit" in rc.lower()


def test_diagnose_permission():
    rc, fix = diagnose_error("401 Unauthorized: invalid api key", None, 0)
    assert ("kredensial" in rc.lower()) or ("permission" in rc.lower())
    assert "api key" in fix.lower() or "rbac" in fix.lower()


def test_diagnose_logic_bug():
    rc, fix = diagnose_error("KeyError: 'x'", "Traceback ... KeyError: 'x'", 0)
    assert ("bug" in rc.lower()) or ("logika" in rc.lower())


def test_diagnose_dependency():
    rc, fix = diagnose_error("ModuleNotFoundError: No module named 'foo'", None, 0)
    assert "dependency" in rc.lower()


def test_diagnose_unclassified_still_returns_actionable():
    rc, fix = diagnose_error("sesuatu yang aneh", None, 0)
    assert rc and fix                       # selalu ada root cause + fix


def test_last_error_route_present():
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/observability/agents/{agent_name}/last-error" in paths
