"""Tests untuk policy_engine (P1-C) — pure, tanpa I/O."""
from policy_engine import PolicyEngine, ALLOW, BLOCK, APPROVAL


def test_dangerous_tool_needs_approval():
    pe = PolicyEngine()
    assert pe.check_tool("run_command").action == APPROVAL
    assert pe.check_tool("run_command", approved=True).action == ALLOW   # sudah di-approve
    assert pe.check_tool("web_read").action == ALLOW                     # tool aman


def test_blacklist_domain_blocked():
    pe = PolicyEngine({"blacklist_domains": ["bad.example"]})
    assert pe.check_url("https://bad.example/x").action == BLOCK
    assert pe.check_url("https://sub.bad.example/y").action == BLOCK     # subdomain
    assert pe.check_url("https://good.example/z").action == ALLOW


def test_cost_limit_triggers_approval():
    pe = PolicyEngine({"cost_limit_usd": 0.50})
    assert pe.check_cost(0.75).action == APPROVAL
    assert pe.check_cost(0.25).action == ALLOW
    assert PolicyEngine().check_cost(1000).action == ALLOW              # tanpa limit → allow


def test_mask_pii():
    pe = PolicyEngine()
    masked, found = pe.mask("Hubungi a@b.com atau 081234567890 ya")
    assert "[EMAIL]" in masked and "[PHONE]" in masked
    assert "a@b.com" not in masked and "081234567890" not in masked
    assert set(found) == {"email", "phone"}


def test_mask_long_number_but_not_phone_double_count():
    pe = PolicyEngine()
    masked, found = pe.mask("kartu 4111111111111111 penting")
    assert "[SENSITIVE_NUMBER]" in masked and "4111111111111111" not in masked
    assert "long_number" in found


def test_mask_disabled_returns_unchanged():
    pe = PolicyEngine({"mask_pii": False})
    text = "email a@b.com"
    masked, found = pe.mask(text)
    assert masked == text and found == []


def test_no_pii_found_empty():
    masked, found = PolicyEngine().mask("teks biasa tanpa data sensitif")
    assert found == [] and masked == "teks biasa tanpa data sensitif"


def test_evaluate_dispatch():
    pe = PolicyEngine({"cost_limit_usd": 0.1})
    assert pe.evaluate(kind="tool", tool_name="run_command").action == APPROVAL
    assert pe.evaluate(kind="cost", cost_usd=1.0).action == APPROVAL
    assert pe.evaluate(kind="url", url="https://ok.example").action == ALLOW
    assert pe.evaluate(kind="unknown").action == ALLOW
