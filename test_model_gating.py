"""P0-3 — Model gating per paket + token cap (anti-abuse & cost bound).

Menguji keputusan routing (pure) dan pembatas input/output (pure), tanpa
memanggil LLM live. Tujuan: paket murah tidak jatuh ke model mahal, dan input
abusif tidak meledakkan biaya.
"""
import main
from base import MAX_INPUT_CHARS, MAX_OUTPUT_TOKENS, _cap_input_messages


# ── Model tier per plan ──────────────────────────────────────────────────
def test_low_plans_use_cheap_tier():
    for plan in ("free", "starter", "", None, "unknown_plan", "STARTER"):
        assert main.model_tier_for_plan(plan) == "cheap", plan


def test_paid_plans_use_full_tier():
    for plan in ("pro", "business", "enterprise", "Business", "PRO"):
        assert main.model_tier_for_plan(plan) == "full", plan


# ── Output token ceiling ───────────────────────────────────────────────────
def test_output_and_input_ceilings():
    assert MAX_OUTPUT_TOKENS == 2048
    assert MAX_INPUT_CHARS == 48_000


# ── Input char cap (anti-abuse) ────────────────────────────────────────────
def test_cap_input_under_budget_returns_same_list():
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "halo"}]
    assert _cap_input_messages(msgs) is msgs  # tak ada perubahan bila di bawah budget


def test_cap_input_trims_oldest_keeps_system_and_latest():
    big = "x" * 30_000
    msgs = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": big},        # tertua non-system
        {"role": "assistant", "content": big},
        {"role": "user", "content": "latest"},   # terbaru
    ]
    out = _cap_input_messages(msgs, max_chars=48_000)
    total = sum(len(m["content"]) for m in out)
    assert total <= 48_000
    assert out[0]["role"] == "system" and out[0]["content"] == "SYS"   # system dipertahankan
    assert out[-1]["content"] == "latest"                             # terbaru dipertahankan
    assert len(out) < len(msgs)                                       # tertua dibuang


def test_cap_input_truncates_single_giant_message():
    msgs = [{"role": "user", "content": "y" * 100_000}]
    out = _cap_input_messages(msgs, max_chars=48_000)
    assert len(out) == 1
    assert len(out[0]["content"]) == 48_000


def test_cap_input_does_not_mutate_original():
    big = "z" * 60_000
    original = [{"role": "user", "content": big}]
    _cap_input_messages(original, max_chars=48_000)
    assert len(original[0]["content"]) == 60_000  # asli tak berubah
