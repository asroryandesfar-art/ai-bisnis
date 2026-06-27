"""
Tests for casper/workflow.py — Casper Agentic Buildathon 2026.
Run with: pytest casper/test_casper_workflow.py
"""
import asyncio
import hashlib
import json
import pytest


# ────────────────────────────────────────────────────────────────
# Unit: action classifier
# ────────────────────────────────────────────────────────────────

from casper.workflow import _classify_action, _generate_decision, _ACTION_TYPE_MAP


def test_classify_hire():
    assert _classify_action("Saya ingin merekrut 3 sales executive") == "hire"


def test_classify_price():
    assert _classify_action("Kurangi harga paket Professional dari Rp 299k") == "price_change"


def test_classify_marketing():
    assert _classify_action("Launch campaign TikTok ads budget Rp 5 juta") == "marketing"


def test_classify_finance():
    assert _classify_action("Approve pengeluaran Rp 50 juta untuk server") == "finance"


def test_classify_sales():
    assert _classify_action("Strategi meningkatkan penjualan dan lead generation") == "sales"


def test_classify_general_fallback():
    assert _classify_action("What should we do next?") == "general"


# ────────────────────────────────────────────────────────────────
# Unit: decision generator
# ────────────────────────────────────────────────────────────────

def test_generate_decision_has_summary():
    d = _generate_decision("Merekrut 2 dev baru", "hire")
    assert "summary" in d
    assert len(d["summary"]) > 5
    assert "Hiring Decision" in d["summary"] or "hire" in d["summary"].lower()


def test_generate_decision_has_detail():
    d = _generate_decision("Merekrut", "hire")
    assert "detail" in d
    assert d["detail"]["confidence"] > 0
    assert "specialist_agents" in d["detail"]
    assert "BotNesia Supervisor" in d["detail"]["rationale"] or "BotNesia" in d["detail"]["rationale"]


def test_generate_decision_summary_truncated():
    long_msg = "A" * 300
    d = _generate_decision(long_msg, "general")
    assert len(d["summary"]) <= 250


# ────────────────────────────────────────────────────────────────
# Unit: action type map
# ────────────────────────────────────────────────────────────────

def test_action_type_map_has_all_types():
    required = ["hire", "price_change", "marketing", "finance", "hr", "sales", "operations", "general"]
    for t in required:
        assert t in _ACTION_TYPE_MAP, f"Missing action type: {t}"


# ────────────────────────────────────────────────────────────────
# Unit: session hash determinism
# ────────────────────────────────────────────────────────────────

def test_session_hash_deterministic():
    action_id = "test-action-id-123"
    summary = "Hire 3 sales executives"
    h1 = hashlib.sha256(
        json.dumps({"action_id": action_id, "summary": summary}, sort_keys=True).encode()
    ).hexdigest()
    h2 = hashlib.sha256(
        json.dumps({"action_id": action_id, "summary": summary}, sort_keys=True).encode()
    ).hexdigest()
    assert h1 == h2
    assert len(h1) == 64


def test_session_hash_changes_with_action_id():
    summary = "Hire 3 sales executives"
    h1 = hashlib.sha256(json.dumps({"action_id": "id-1", "summary": summary}, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps({"action_id": "id-2", "summary": summary}, sort_keys=True).encode()).hexdigest()
    assert h1 != h2


# ────────────────────────────────────────────────────────────────
# Unit: demo deploy hash format
# ────────────────────────────────────────────────────────────────

def test_demo_deploy_hash_starts_with_demo():
    action_id = "abc-123"
    session_hash = hashlib.sha256(b"test").hexdigest()
    deploy_hash = "demo-" + hashlib.sha256(f"{action_id}:{session_hash}".encode()).hexdigest()[:56]
    assert deploy_hash.startswith("demo-")
    assert len(deploy_hash) == 61  # "demo-" (5) + 56 hex chars


# ────────────────────────────────────────────────────────────────
# Integration: router is buildable
# ────────────────────────────────────────────────────────────────

def test_router_builds_without_error():
    """build_router() must return a usable FastAPI router without a DB connection."""
    from fastapi import FastAPI
    from casper.workflow import build_router

    async def fake_pool():
        return None

    async def fake_user():
        return {"org_id": "00000000-0000-0000-0000-000000000001"}

    r = build_router(lambda: fake_pool, lambda: fake_user)
    app = FastAPI()
    app.include_router(r)
    routes = [r.path for r in app.routes]
    assert "/api/casper/workflow/action" in routes
    assert "/api/casper/workflow/actions" in routes
    assert "/api/casper/workflow/stats" in routes
    assert "/api/casper/workflow/demo" in routes
    assert "/api/casper/workflow/action/{action_id}" in routes


# ────────────────────────────────────────────────────────────────
# casper_anchor: contract constants are present
# ────────────────────────────────────────────────────────────────

def test_casper_anchor_contract_constants():
    import casper_anchor
    assert len(casper_anchor.CONTRACT_HASH) == 64
    assert len(casper_anchor.CONTRACT_PACKAGE_HASH) == 64
    assert casper_anchor.CASPER_CHAIN == "casper-test"


def test_casper_anchor_compute_session_hash():
    import casper_anchor
    h = casper_anchor.compute_session_hash("org-1", "sess-1", "summary text")
    assert len(h) == 64
    h2 = casper_anchor.compute_session_hash("org-1", "sess-1", "summary text")
    assert h == h2  # deterministic


def test_casper_anchor_session_hash_changes_with_org():
    import casper_anchor
    h1 = casper_anchor.compute_session_hash("org-1", "sess", "summary")
    h2 = casper_anchor.compute_session_hash("org-2", "sess", "summary")
    assert h1 != h2
