"""Tests untuk action_executor.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from action_executor import ActionExecutor, ActionStep, _eval_math


# ── Calculator tests ───────────────────────────────────────────────────────────

class TestEvalMath:
    def test_simple_addition(self):
        r = _eval_math("2 + 3")
        assert r["success"] is True
        assert r["result"] == 5.0

    def test_multiplication(self):
        r = _eval_math("10 * 1.5")
        assert r["success"] is True
        assert r["result"] == 15.0

    def test_division(self):
        r = _eval_math("100 / 4")
        assert r["success"] is True
        assert r["result"] == 25.0

    def test_power(self):
        r = _eval_math("2 ** 10")
        assert r["success"] is True
        assert r["result"] == 1024.0

    def test_modulo(self):
        r = _eval_math("17 % 5")
        assert r["success"] is True
        assert r["result"] == 2.0

    def test_complex_expression(self):
        r = _eval_math("(150 * 1.11) / 12")
        assert r["success"] is True
        assert abs(r["result"] - 13.875) < 0.001

    def test_invalid_expression(self):
        r = _eval_math("import os; os.system('ls')")
        assert r["success"] is False

    def test_function_call_blocked(self):
        r = _eval_math("abs(-5)")
        # abs() adalah function call — harus ditolak
        assert r["success"] is False

    def test_string_blocked(self):
        r = _eval_math("'hello' + 'world'")
        assert r["success"] is False

    def test_division_by_zero_returns_error(self):
        r = _eval_math("10 / 0")
        # Python raises ZeroDivisionError
        assert r["success"] is False or r.get("result") == float("inf")

    def test_negative_number(self):
        r = _eval_math("-5 + 10")
        assert r["success"] is True
        assert r["result"] == 5.0

    def test_floor_division(self):
        r = _eval_math("17 // 5")
        assert r["success"] is True
        assert r["result"] == 3.0


# ── ActionStep tests ───────────────────────────────────────────────────────────

class TestActionStep:
    def test_default_status_is_pending(self):
        step = ActionStep(
            step_no=1, description="test", action_type="terminal",
            tool="terminal_execute", params={},
        )
        assert step.status == "pending"

    def test_requires_approval_default_false(self):
        step = ActionStep(
            step_no=1, description="test", action_type="file_read",
            tool="file_read", params={},
        )
        assert step.requires_approval is False


# ── ActionExecutor tests ───────────────────────────────────────────────────────

def _make_executor(mock_llm_json=None):
    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value=None)

    mock_agent = MagicMock()
    mock_agent.api_key = "test-key"
    mock_agent.model = None
    mock_agent.base_url = None

    if mock_llm_json:
        mock_agent._call_llm_json = AsyncMock(side_effect=mock_llm_json)
    else:
        mock_agent._call_llm_json = AsyncMock(return_value={})

    return ActionExecutor(mock_agent, mock_pool, "test-org")


@pytest.mark.asyncio
async def test_eval_math_via_dispatch():
    """Calculator tool harus bisa dipanggil via _dispatch_step."""
    executor = _make_executor()
    step = ActionStep(
        step_no=1, description="Calculate", action_type="calculator",
        tool="calculator", params={"expression": "5 + 3"},
    )
    result = await executor._dispatch_step(step, tool_ctx={
        "pool": executor._pool, "org_id": "test-org",
    })
    assert result["success"] is True
    assert result["result"] == 8.0


@pytest.mark.asyncio
async def test_understand_goal_returns_dict():
    responses = [
        {"domain": "file", "complexity": "simple", "requires_external_access": False, "key_entities": ["script.py"]},
    ]
    executor = _make_executor(mock_llm_json=iter(responses))
    result = await executor.understand_goal("Read the file script.py")
    assert result["domain"] == "file"
    assert result["complexity"] == "simple"


@pytest.mark.asyncio
async def test_plan_goal_returns_action_plan():
    plan_response = {
        "steps": [
            {"step_no": 1, "description": "Read file", "action_type": "file_read",
             "tool": "file_read", "params": {"path": "/tmp/test.py"}, "requires_approval": False},
        ],
        "estimated_duration_seconds": 5,
        "risks": [],
        "requires_approvals": [],
    }
    executor = _make_executor(mock_llm_json=iter([plan_response]))
    plan = await executor.plan_goal("Read the file /tmp/test.py")

    assert len(plan.steps) == 1
    assert plan.steps[0].action_type == "file_read"
    assert plan.steps[0].params["path"] == "/tmp/test.py"


@pytest.mark.asyncio
async def test_verify_goal_returns_dict():
    verify_response = {
        "achieved": True, "confidence": 0.9,
        "achieved_partially": False, "gaps": [], "summary": "Goal tercapai.",
    }
    executor = _make_executor(mock_llm_json=iter([verify_response]))
    result = await executor.verify_goal("Do something", [{"step_no": 1, "success": True}])
    assert result["achieved"] is True


@pytest.mark.asyncio
async def test_fallback_tool_unknown_returns_error():
    executor = _make_executor()
    step = ActionStep(
        step_no=1, description="Unknown", action_type="unknown_action",
        tool="nonexistent_tool", params={},
    )
    result = await executor._fallback_tool(step, tool_ctx={
        "pool": executor._pool, "org_id": "test-org",
    })
    assert result["success"] is False
    assert result.get("skipped") is True


# ── Audit logger tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_logger_fail_open():
    """audit_logger.log_action tidak pernah raise, bahkan jika pool error."""
    from audit_logger import log_action
    mock_pool = AsyncMock()
    mock_pool.fetchrow.side_effect = Exception("DB error")

    result = await log_action(
        mock_pool, org_id="test-org", agent_name="test_agent",
        action_type="file_read", target="/tmp/file.txt",
    )
    assert result is None  # Fail-open: return None, tidak raise


@pytest.mark.asyncio
async def test_audit_logger_success():
    from audit_logger import log_action
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = {"id": "audit-id-123"}

    result = await log_action(
        mock_pool, org_id="test-org", agent_name="terminal_agent",
        action_type="terminal_execute", target="ls -la", status="completed",
    )
    assert result == "audit-id-123"


# ── Recovery manager tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recovery_retries_on_failure():
    from recovery_manager import RecoveryManager
    attempts = []

    async def flaky_func():
        attempts.append(1)
        if len(attempts) < 3:
            return {"success": False, "error": "network error"}
        return {"success": True, "data": "ok"}

    rm = RecoveryManager(max_retries=5)
    result = await rm.with_retry(flaky_func, action_type="test")
    assert result["success"] is True
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_recovery_stops_on_permission_error():
    from recovery_manager import RecoveryManager
    attempts = []

    async def perm_error_func():
        attempts.append(1)
        return {"success": False, "error": "permission denied"}

    rm = RecoveryManager(max_retries=5)
    result = await rm.with_retry(perm_error_func, action_type="file_write")
    assert result["success"] is False
    # Permission error tidak di-retry
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    from recovery_manager import RecoveryManager, _CIRCUIT_BREAKER_THRESHOLD

    async def always_fail():
        return {"success": False, "error": "unknown error"}

    rm = RecoveryManager(max_retries=0)
    for _ in range(_CIRCUIT_BREAKER_THRESHOLD + 1):
        await rm.with_retry(always_fail, action_type="browser_read")

    result = await rm.with_retry(always_fail, action_type="browser_read")
    assert result["success"] is False
    assert result.get("circuit_open") is True
