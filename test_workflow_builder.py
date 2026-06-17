"""Tests untuk AI Workflow Builder: workflow_engine (template/condition helpers,
node executors, execution engine, trigger dispatch) dan
bn_platform/workflow_builder.py (router CRUD, publish/test/executions).

Mengikuti pola FakePool + _route (test_knowledge_builder.py) dan mock
_call_llm_json (test_reasoning_pipeline.py) — tidak ada panggilan Groq atau
database sungguhan.
"""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from base import BaseAgent
import workflow_engine as we
from bn_platform.workflow_builder import (
    WorkflowCreateRequest,
    WorkflowUpdateRequest,
    WorkflowTestRequest,
    build_workflow_builder_router,
)


# ─── Helpers ────────────────────────────────────────────────────

def _route(router, path, method):
    for r in router.routes:
        if r.path.endswith(path) and method in r.methods:
            return r.endpoint
    raise AssertionError(f"route not found: {method} {path}")


# ─── Template / condition helpers ──────────────────────────────

def test_render_template_interpolates_and_handles_missing():
    assert we._render_template("Halo {{name}}!", {"name": "Budi"}) == "Halo Budi!"
    assert we._render_template("{{missing}}", {}) == ""
    assert json.loads(we._render_template("{{tags}}", {"tags": ["a", "b"]})) == ["a", "b"]


def test_evaluate_condition_confidence():
    result, actual = we._evaluate_condition("confidence", "gte", 0.6, {"confidence": 0.8})
    assert result is True and actual == 0.8
    result, _ = we._evaluate_condition("confidence", "lt", 0.6, {"confidence": 0.8})
    assert result is False


def test_evaluate_condition_tags():
    result, _ = we._evaluate_condition("tags", "contains", "promo", {"tags": ["Promo", "x"]})
    assert result is True
    result, _ = we._evaluate_condition("tags", "not_contains", "promo", {"tags": ["promo"]})
    assert result is False


def test_evaluate_condition_intent_and_customer_type():
    result, _ = we._evaluate_condition("intent", "equals", "refund", {"intent": "Refund"})
    assert result is True
    result, _ = we._evaluate_condition("customer_type", "in", "warm,hot", {"customer_type": "hot"})
    assert result is True
    result, _ = we._evaluate_condition("customer_type", "not_equals", "cold", {"customer_type": "cold"})
    assert result is False


# ─── Per-category node executors ────────────────────────────────

def test_exec_trigger_and_condition():
    result = asyncio.run(we._exec_trigger({"type": "manual_trigger"}, {}))
    assert result["output"]["trigger_type"] == "manual_trigger"

    node = {"type": "confidence", "config": {"operator": "gte", "value": 0.5}}
    result = asyncio.run(we._exec_condition(node, {"confidence": 0.9}))
    assert result["output"]["branch"] == "true"

    result = asyncio.run(we._exec_condition(node, {"confidence": 0.1}))
    assert result["output"]["branch"] == "false"


def test_exec_agent_skipped_without_config():
    result = asyncio.run(we._exec_agent({"type": "cs_agent", "config": {}}, {}, agent_config=None))
    assert result["status"] == "skipped"


def test_exec_agent_success(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        return {"output": "Halo, ini balasan agent."}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)
    context = {}
    result = asyncio.run(we._exec_agent(
        {"type": "sales_agent", "config": {"instruction": "jawab pelanggan"}}, context,
        agent_config={"api_key": "test-key"},
    ))
    assert result["status"] == "success"
    assert context["agent_output"] == "Halo, ini balasan agent."
    assert context["agent_role"] == "sales_agent"


def test_exec_agent_llm_unavailable(monkeypatch):
    async def fake_call_llm(self, messages, temperature=0.3, max_tokens=1024, response_format=None):
        raise RuntimeError("429 quota")

    monkeypatch.setattr(BaseAgent, "_call_llm", fake_call_llm)
    result = asyncio.run(we._exec_agent({"type": "cs_agent", "config": {}}, {}, agent_config={"api_key": "test-key"}))
    assert result["status"] == "failed"


class FakePool:
    def __init__(self, fetchrow_result=None, fetch_result=None):
        self.calls = []
        self.fetchrow_result = fetchrow_result
        self.fetch_result = fetch_result or []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_result

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.fetch_result


def test_action_send_message_inserts_and_updates_conversation():
    pool = FakePool()
    context = {"conversation_id": "conv-1", "agent_output": "Balasan AI"}
    node = {"config": {"message": "{{agent_output}}"}}
    result = asyncio.run(we._action_send_message(node, context, pool=pool))
    assert result["status"] == "success"
    assert result["output"]["text"] == "Balasan AI"
    assert any("INSERT INTO messages" in c[1] for c in pool.calls)
    assert any("UPDATE conversations" in c[1] for c in pool.calls)


def test_action_send_message_skipped_without_conversation():
    pool = FakePool()
    result = asyncio.run(we._action_send_message({"config": {}}, {}, pool=pool))
    assert result["status"] == "skipped"


def test_action_handoff_skipped_without_fn():
    pool = FakePool()
    context = {"conversation_id": "conv-1"}
    result = asyncio.run(we._action_handoff(
        {"config": {}}, context, pool=pool, org_id="org-1",
        enqueue_handoff_fn=None, default_reason="r", default_priority="medium",
    ))
    assert result["status"] == "skipped"


def test_action_handoff_calls_enqueue_fn():
    pool = FakePool()
    context = {"conversation_id": "conv-1"}
    calls = []

    async def fake_enqueue(pool_, *, org_id, conversation_id, reason, priority):
        calls.append((org_id, conversation_id, reason, priority))
        return {"id": "ticket-1"}

    result = asyncio.run(we._action_handoff(
        {"config": {"reason": "manual", "priority": "urgent"}}, context, pool=pool, org_id="org-1",
        enqueue_handoff_fn=fake_enqueue, default_reason="workflow_automation", default_priority="medium",
    ))
    assert result["status"] == "success"
    assert calls == [("org-1", "conv-1", "manual", "urgent")]


def test_action_update_crm_merges_tags():
    pool = FakePool(fetchrow_result={"id": "profile-1", "preferred_topics": ["promo", "vip"]})
    context = {"end_user_id": "user-1", "tags": ["promo"]}
    node = {"config": {"tags": "vip, loyal"}}
    result = asyncio.run(we._action_update_crm(node, context, pool=pool, bot_id="bot-1"))
    assert result["status"] == "success"
    assert result["output"]["preferred_topics"] == ["promo", "vip"]


def test_action_update_crm_skipped_without_end_user():
    pool = FakePool()
    result = asyncio.run(we._action_update_crm({"config": {}}, {}, pool=pool, bot_id="bot-1"))
    assert result["status"] == "skipped"


def test_exec_notification_logs_without_webhook():
    node = {"config": {"to": "{{end_user_email}}", "subject": "Hi", "body": "{{agent_output}}"}}
    context = {"end_user_email": "user@example.com", "agent_output": "Balasan AI"}
    result = asyncio.run(we._exec_notification(node, context))
    assert result["status"] == "success"
    assert result["output"]["delivery"] == "logged"
    assert result["output"]["to"] == "user@example.com"
    assert result["output"]["body"] == "Balasan AI"


def test_exec_notification_posts_to_webhook(monkeypatch):
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            FakeAsyncClient.last_call = (url, json)
            return FakeResponse()

    monkeypatch.setattr(we.httpx, "AsyncClient", FakeAsyncClient)
    node = {"config": {"to": "ops@x.com", "subject": "Hi", "body": "Body", "webhook_url": "https://hook.example/notify"}}
    result = asyncio.run(we._exec_notification(node, {}))
    assert result["status"] == "success"
    assert result["output"]["delivery"] == "webhook"
    assert FakeAsyncClient.last_call[0] == "https://hook.example/notify"


# ─── Execution engine: run_workflow / trigger_workflows ─────────

def _linear_workflow():
    return {
        "id": "wf-1",
        "nodes": [
            {"id": "trg", "category": "trigger", "type": "manual_trigger", "config": {}},
            {"id": "cond", "category": "condition", "type": "confidence", "config": {"operator": "gte", "value": 0.5}},
            {"id": "agent", "category": "agent", "type": "cs_agent", "config": {}},
            {"id": "send", "category": "action", "type": "send_message", "config": {"message": "{{agent_output}}"}},
            {"id": "notify", "category": "notification", "type": "email_notification", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "agent", "source_handle": "true"},
            {"id": "e3", "source": "agent", "target": "send"},
            {"id": "e4", "source": "cond", "target": "notify", "source_handle": "false"},
        ],
    }


def test_run_workflow_true_branch(monkeypatch):
    async def fake_call_llm_json(self, messages, temperature=0.2, max_tokens=512, default=None):
        return {"output": "Balasan AI"}

    monkeypatch.setattr(BaseAgent, "_call_llm_json", fake_call_llm_json)
    pool = FakePool()
    execution_id = asyncio.run(we.run_workflow(
        pool, _linear_workflow(), trigger_type="manual_trigger",
        trigger_payload={"confidence": 0.9, "conversation_id": "conv-1"},
        org_id="org-1", bot_id="bot-1", agent_config={"api_key": "test-key"},
    ))
    assert execution_id

    inserts = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO workflow_executions" in c[1]]
    assert len(inserts) == 1

    steps = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO workflow_execution_steps" in c[1]]
    node_ids = [c[2][2] for c in steps]
    assert node_ids == ["trg", "cond", "agent", "send"]

    final = [c for c in pool.calls if c[0] == "execute" and "UPDATE workflow_executions" in c[1]]
    assert final and final[0][2][0] == "success"


def test_run_workflow_false_branch_hits_notification(monkeypatch):
    pool = FakePool()
    execution_id = asyncio.run(we.run_workflow(
        pool, _linear_workflow(), trigger_type="manual_trigger",
        trigger_payload={"confidence": 0.1},
        org_id="org-1", bot_id="bot-1", agent_config=None,
    ))
    assert execution_id
    steps = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO workflow_execution_steps" in c[1]]
    node_ids = [c[2][2] for c in steps]
    assert node_ids == ["trg", "cond", "notify"]


def test_run_workflow_retries_failing_node():
    workflow = {
        "id": "wf-2",
        "nodes": [
            {"id": "trg", "category": "trigger", "type": "manual_trigger", "config": {}},
            {"id": "bad", "category": "action", "type": "unknown_action", "config": {"retries": 2}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "bad"}],
    }
    pool = FakePool()
    execution_id = asyncio.run(we.run_workflow(
        pool, workflow, trigger_type="manual_trigger", trigger_payload={},
        org_id="org-1", bot_id="bot-1",
    ))
    assert execution_id
    steps = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO workflow_execution_steps" in c[1]]
    bad_attempts = [c for c in steps if c[2][2] == "bad"]
    assert len(bad_attempts) == 3  # 1 + retries(2)
    assert all(c[2][5] == "failed" for c in bad_attempts)

    final = [c for c in pool.calls if c[0] == "execute" and "UPDATE workflow_executions" in c[1]]
    assert final[0][2][0] == "failed"


def test_trigger_workflows_runs_matching_published_workflows():
    workflow = _linear_workflow()
    row = {"id": "wf-1", "nodes": json.dumps(workflow["nodes"]), "edges": json.dumps(workflow["edges"])}
    pool = FakePool(fetch_result=[row])
    execution_ids = asyncio.run(we.trigger_workflows(
        pool, org_id="org-1", bot_id="bot-1", trigger_type="manual_trigger",
        payload={"confidence": 0.1}, agent_config=None,
    ))
    assert len(execution_ids) == 1
    inserts = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO workflow_executions" in c[1]]
    assert inserts[0][2][2] == "wf-1"


# ─── Router: bn_platform/workflow_builder ───────────────────────

class RouterFakePool:
    def __init__(self, *, bot=None, workflow=None, workflows=None, executions=None, execution=None, steps=None):
        self.bot = bot
        self.workflow = workflow
        self.workflows = workflows or []
        self.executions = executions or []
        self.execution = execution
        self.steps = steps or []
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        q = " ".join(sql.split())
        if "FROM bots WHERE id=" in q:
            return self.bot
        if "INSERT INTO workflows" in q and "RETURNING" in q:
            wf_id, org_id, bot_id, name, description, trigger_type, nodes_json, edges_json, created_by = args
            self.workflow = {
                "id": wf_id, "org_id": org_id, "bot_id": bot_id, "name": name, "description": description,
                "trigger_type": trigger_type, "nodes": nodes_json, "edges": edges_json, "status": "draft",
                "created_by": created_by, "created_at": "now", "updated_at": "now", "published_at": None,
            }
            return self.workflow
        if "UPDATE workflows SET name=" in q and "RETURNING" in q:
            name, description, trigger_type, nodes_json, edges_json, workflow_id, _org_id = args
            self.workflow.update({
                "name": name, "description": description, "trigger_type": trigger_type,
                "nodes": nodes_json, "edges": edges_json,
            })
            return self.workflow
        if "status='published'" in q and "RETURNING" in q:
            self.workflow["status"] = "published"
            return self.workflow
        if "status='draft'" in q and "RETURNING" in q:
            self.workflow["status"] = "draft"
            return self.workflow
        if "FROM workflows WHERE id=" in q:
            return self.workflow
        if "FROM workflow_executions WHERE id=" in q:
            return self.execution
        return None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        q = " ".join(sql.split())
        if "FROM workflows WHERE org_id=" in q:
            return self.workflows
        if "FROM workflow_executions WHERE workflow_id=" in q:
            return self.executions
        if "FROM workflow_execution_steps WHERE execution_id=" in q:
            return self.steps
        return []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


def _build_router(pool, **kwargs):
    async def get_pool():
        return pool

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    def get_agent_config():
        return {"api_key": ""}

    def require_permission(_permission_key):
        return get_current_user

    return build_workflow_builder_router(
        get_pool=get_pool, get_current_user=get_current_user,
        get_agent_config=get_agent_config, require_permission=require_permission, **kwargs,
    )


def test_router_gates_every_route_with_bots_read_or_write_permission():
    """Sebelumnya semua route di workflow_builder.py cuma Depends(get_current_user)
    -- role apa pun (termasuk yang tanpa hak bots.write) bisa create/update/
    delete/publish workflow atau test-run-nya dengan trigger_payload bebas
    (lihat fix #3 enqueue_handoff -- jalur exploit konkretnya). require_permission(key)
    dievaluasi saat build_workflow_builder_router() dipanggil (default arg di
    signature route), jadi ini bisa diverifikasi tanpa perlu trigger resolusi
    Depends FastAPI sungguhan."""
    requested_keys = []

    def recording_require_permission(key):
        requested_keys.append(key)
        async def _checker(user=None, pool=None):
            return user
        return _checker

    async def get_pool():
        return RouterFakePool()

    async def get_current_user():
        return {"org_id": "org-1", "id": "user-1"}

    build_workflow_builder_router(
        get_pool=get_pool, get_current_user=get_current_user,
        get_agent_config=lambda: {"api_key": ""},
        require_permission=recording_require_permission,
    )

    # 6 endpoint mutasi (create/update/publish/unpublish/delete/test)
    assert requested_keys.count("bots.write") == 6
    # 5 endpoint baca (node-catalog/list/get/list-executions/get-execution)
    assert requested_keys.count("bots.read") == 5
    assert set(requested_keys) == {"bots.read", "bots.write"}


def test_node_catalog_endpoint():
    router = _build_router(RouterFakePool())
    handler = _route(router, "/node-catalog", "GET")
    result = asyncio.run(handler(user={"org_id": "org-1"}))
    assert set(result["categories"].keys()) == {"trigger", "condition", "agent", "action", "notification"}


def test_create_workflow_rejects_invalid_trigger_type():
    pool = RouterFakePool(bot={"id": "bot-1", "name": "Agent"})
    router = _build_router(pool)
    handler = _route(router, "/bots/{bot_id}/workflows", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            bot_id="bot-1", body=WorkflowCreateRequest(name="Wf", trigger_type="bogus"),
            user={"org_id": "org-1", "id": "user-1"}, pool=pool,
        ))
    assert exc.value.status_code == 422


def test_create_get_update_workflow_roundtrip():
    pool = RouterFakePool(bot={"id": "bot-1", "name": "Agent"})
    router = _build_router(pool)
    create_handler = _route(router, "/bots/{bot_id}/workflows", "POST")
    created = asyncio.run(create_handler(
        bot_id="bot-1", body=WorkflowCreateRequest(name="Workflow Baru", trigger_type="manual_trigger"),
        user={"org_id": "org-1", "id": "user-1"}, pool=pool,
    ))
    assert created["name"] == "Workflow Baru"
    assert created["nodes"] == []

    get_handler = _route(router, "/workflows/{workflow_id}", "GET")
    fetched = asyncio.run(get_handler(workflow_id=created["id"], user={"org_id": "org-1"}, pool=pool))
    assert fetched["id"] == created["id"]

    update_handler = _route(router, "/workflows/{workflow_id}", "PATCH")
    updated = asyncio.run(update_handler(
        workflow_id=created["id"],
        body=WorkflowUpdateRequest(name="Renamed", nodes=[{"id": "trg", "category": "trigger", "type": "manual_trigger"}]),
        user={"org_id": "org-1", "id": "user-1"}, pool=pool,
    ))
    assert updated["name"] == "Renamed"
    assert updated["nodes"][0]["id"] == "trg"

    # Defense-in-depth: the UPDATE statement itself must scope by org_id, not
    # just the _get_workflow() ownership check that runs before it.
    update_call = next(c for c in pool.calls if c[0] == "fetchrow" and "UPDATE workflows SET name=" in c[1])
    assert "org_id" in update_call[1]
    assert update_call[2][-1] == "org-1"


def test_publish_requires_trigger_node():
    workflow = {
        "id": "wf-1", "org_id": "org-1", "bot_id": "bot-1", "name": "Wf", "description": None,
        "trigger_type": "manual_trigger", "nodes": json.dumps([{"id": "a", "category": "action", "type": "send_message"}]),
        "edges": json.dumps([]), "status": "draft", "created_by": "user-1",
        "created_at": "now", "updated_at": "now", "published_at": None,
    }
    pool = RouterFakePool(workflow=workflow)
    router = _build_router(pool)
    handler = _route(router, "/workflows/{workflow_id}/publish", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(workflow_id="wf-1", user={"org_id": "org-1"}, pool=pool))
    assert exc.value.status_code == 422


def test_publish_and_unpublish_workflow():
    workflow = {
        "id": "wf-1", "org_id": "org-1", "bot_id": "bot-1", "name": "Wf", "description": None,
        "trigger_type": "manual_trigger",
        "nodes": json.dumps([{"id": "trg", "category": "trigger", "type": "manual_trigger"}]),
        "edges": json.dumps([]), "status": "draft", "created_by": "user-1",
        "created_at": "now", "updated_at": "now", "published_at": None,
    }
    pool = RouterFakePool(workflow=workflow)
    router = _build_router(pool)

    publish_handler = _route(router, "/workflows/{workflow_id}/publish", "POST")
    published = asyncio.run(publish_handler(workflow_id="wf-1", user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert published["status"] == "published"
    publish_call = next(c for c in pool.calls if c[0] == "fetchrow" and "status='published'" in c[1])
    assert "org_id" in publish_call[1]
    assert publish_call[2] == ("wf-1", "org-1")

    unpublish_handler = _route(router, "/workflows/{workflow_id}/unpublish", "POST")
    unpublished = asyncio.run(unpublish_handler(workflow_id="wf-1", user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert unpublished["status"] == "draft"
    unpublish_call = next(c for c in pool.calls if c[0] == "fetchrow" and "status='draft'" in c[1])
    assert "org_id" in unpublish_call[1]
    assert unpublish_call[2] == ("wf-1", "org-1")


def test_delete_workflow():
    workflow = {
        "id": "wf-1", "org_id": "org-1", "bot_id": "bot-1", "name": "Wf", "description": None,
        "trigger_type": "manual_trigger", "nodes": json.dumps([]), "edges": json.dumps([]),
        "status": "draft", "created_by": "user-1", "created_at": "now", "updated_at": "now", "published_at": None,
    }
    pool = RouterFakePool(workflow=workflow)
    router = _build_router(pool)
    handler = _route(router, "/workflows/{workflow_id}", "DELETE")
    result = asyncio.run(handler(workflow_id="wf-1", user={"org_id": "org-1", "id": "user-1"}, pool=pool))
    assert result == {"deleted": True}
    delete_call = next(c for c in pool.calls if c[0] == "execute" and "DELETE FROM workflows" in c[1])
    # Defense-in-depth: the DELETE itself must scope by org_id, not just the
    # _get_workflow() ownership check that runs before it.
    assert "org_id" in delete_call[1]
    assert delete_call[2] == ("wf-1", "org-1")


def test_test_workflow_requires_trigger_node():
    workflow = {
        "id": "wf-1", "org_id": "org-1", "bot_id": "bot-1", "name": "Wf", "description": None,
        "trigger_type": "manual_trigger", "nodes": json.dumps([{"id": "a", "category": "action", "type": "send_message"}]),
        "edges": json.dumps([]), "status": "draft", "created_by": "user-1",
        "created_at": "now", "updated_at": "now", "published_at": None,
    }
    pool = RouterFakePool(workflow=workflow)
    router = _build_router(pool)
    handler = _route(router, "/workflows/{workflow_id}/test", "POST")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(workflow_id="wf-1", body=WorkflowTestRequest(), user={"org_id": "org-1"}, pool=pool))
    assert exc.value.status_code == 422


def test_test_workflow_runs_and_returns_steps(monkeypatch):
    workflow = {
        "id": "wf-1", "org_id": "org-1", "bot_id": "bot-1", "name": "Wf", "description": None,
        "trigger_type": "manual_trigger",
        "nodes": json.dumps([{"id": "trg", "category": "trigger", "type": "manual_trigger"}]),
        "edges": json.dumps([]), "status": "draft", "created_by": "user-1",
        "created_at": "now", "updated_at": "now", "published_at": None,
    }
    execution = {
        "id": "exec-1", "org_id": "org-1", "workflow_id": "wf-1", "bot_id": "bot-1",
        "trigger_type": "manual_trigger", "trigger_payload": json.dumps({}), "status": "success",
        "error": None, "started_at": "now", "finished_at": "now", "duration_ms": 5,
    }
    steps = [{
        "id": "step-1", "execution_id": "exec-1", "node_id": "trg", "node_type": "manual_trigger",
        "category": "trigger", "status": "success", "attempt": 1, "input": json.dumps({}),
        "output": json.dumps({"trigger_type": "manual_trigger"}), "error": None,
        "started_at": "now", "finished_at": "now", "duration_ms": 1,
    }]
    pool = RouterFakePool(workflow=workflow, execution=execution, steps=steps)

    import bn_platform.workflow_builder as wf_router_module

    async def fake_run_workflow(pool_, wf_, *, trigger_type, trigger_payload, org_id, bot_id, agent_config, enqueue_handoff_fn):
        return "exec-1"

    monkeypatch.setattr(wf_router_module, "run_workflow", fake_run_workflow)
    router = _build_router(pool)
    handler = _route(router, "/workflows/{workflow_id}/test", "POST")
    result = asyncio.run(handler(workflow_id="wf-1", body=WorkflowTestRequest(payload={"foo": "bar"}), user={"org_id": "org-1"}, pool=pool))
    assert result["execution"]["id"] == "exec-1"
    assert result["steps"][0]["output"]["trigger_type"] == "manual_trigger"


def test_list_executions_and_get_execution():
    executions = [{"id": "exec-1", "trigger_type": "manual_trigger", "status": "success", "error": None,
                    "started_at": "now", "finished_at": "now", "duration_ms": 5}]
    execution = {
        "id": "exec-1", "org_id": "org-1", "workflow_id": "wf-1", "bot_id": "bot-1",
        "trigger_type": "manual_trigger", "trigger_payload": json.dumps({}), "status": "success",
        "error": None, "started_at": "now", "finished_at": "now", "duration_ms": 5,
    }
    workflow = {
        "id": "wf-1", "org_id": "org-1", "bot_id": "bot-1", "name": "Wf", "description": None,
        "trigger_type": "manual_trigger", "nodes": json.dumps([]), "edges": json.dumps([]),
        "status": "draft", "created_by": "user-1", "created_at": "now", "updated_at": "now", "published_at": None,
    }
    pool = RouterFakePool(workflow=workflow, executions=executions, execution=execution, steps=[])
    router = _build_router(pool)

    list_handler = _route(router, "/workflows/{workflow_id}/executions", "GET")
    result = asyncio.run(list_handler(workflow_id="wf-1", user={"org_id": "org-1"}, pool=pool, limit=20))
    assert result["executions"][0]["id"] == "exec-1"

    get_handler = _route(router, "/executions/{execution_id}", "GET")
    result = asyncio.run(get_handler(execution_id="exec-1", user={"org_id": "org-1"}, pool=pool))
    assert result["execution"]["id"] == "exec-1"
    assert result["steps"] == []


def test_get_execution_not_found_raises_404():
    pool = RouterFakePool(execution=None)
    router = _build_router(pool)
    handler = _route(router, "/executions/{execution_id}", "GET")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(execution_id="missing", user={"org_id": "org-1"}, pool=pool))
    assert exc.value.status_code == 404


# ─── main.py trigger dispatch wiring ────────────────────────────

def test_dispatch_workflow_trigger_calls_trigger_workflows(monkeypatch):
    import main

    pool = FakePool()

    async def fake_get_pool_safe(timeout=None):
        return pool

    calls = []

    async def fake_trigger_workflows(pool_, *, org_id, bot_id, trigger_type, payload=None, agent_config=None, enqueue_handoff_fn=None):
        calls.append((org_id, bot_id, trigger_type, payload))
        return []

    monkeypatch.setattr(main, "get_pool_safe", fake_get_pool_safe)
    monkeypatch.setattr(we, "trigger_workflows", fake_trigger_workflows)

    asyncio.run(main._dispatch_workflow_trigger("new_customer", {"conversation_id": "conv-1"}, org_id="org-1", bot_id="bot-1"))

    assert calls == [("org-1", "bot-1", "new_customer", {"conversation_id": "conv-1"})]


def test_on_new_lead_workflow_trigger_builds_payload(monkeypatch):
    import main

    calls = []

    async def fake_dispatch(trigger_type, payload, *, org_id, bot_id):
        calls.append((trigger_type, payload, org_id, bot_id))

    monkeypatch.setattr(main, "_dispatch_workflow_trigger", fake_dispatch)

    asyncio.run(main._on_new_lead_workflow_trigger(
        org_id="org-1", bot_id="bot-1", end_user_id="user-1", category="hot", score=88.5,
        end_user={"display_name": "Budi", "email": "budi@example.com", "preferred_topics": ["promo"]},
    ))

    assert len(calls) == 1
    trigger_type, payload, org_id, bot_id = calls[0]
    assert trigger_type == "new_lead"
    assert org_id == "org-1" and bot_id == "bot-1"
    assert payload["end_user_id"] == "user-1"
    assert payload["category"] == "hot"
    assert payload["score"] == 88.5
    assert payload["customer_type"] == "hot"
    assert payload["end_user_name"] == "Budi"
    assert payload["tags"] == ["promo"]


# ─── Schema / routes / UI presence ──────────────────────────────

def test_workflow_builder_routes_schema_and_ui_are_present():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/workflow-builder/node-catalog" in paths
    assert "/api/workflow-builder/bots/{bot_id}/workflows" in paths
    assert "/api/workflow-builder/workflows/{workflow_id}" in paths
    assert "/api/workflow-builder/workflows/{workflow_id}/publish" in paths
    assert "/api/workflow-builder/workflows/{workflow_id}/unpublish" in paths
    assert "/api/workflow-builder/workflows/{workflow_id}/test" in paths
    assert "/api/workflow-builder/workflows/{workflow_id}/executions" in paths
    assert "/api/workflow-builder/executions/{execution_id}" in paths

    schema = (Path(__file__).resolve().parent / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS workflows" in schema
    assert "CREATE TABLE IF NOT EXISTS workflow_executions" in schema
    assert "CREATE TABLE IF NOT EXISTS workflow_execution_steps" in schema

    platform_schema = (Path(__file__).resolve().parent / "bn_platform/schema_platform.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS workflows" in platform_schema

    frontend = (Path(__file__).resolve().parent / "frontend/app.js").read_text()
    assert "renderWorkflowBuilder" in frontend
    assert "workflow-builder" in frontend

    api_client = (Path(__file__).resolve().parent / "frontend/api-client.js").read_text()
    assert "wfNodeCatalog" in api_client
    assert "wfPublish" in api_client

    components = (Path(__file__).resolve().parent / "frontend/components.js").read_text()
    assert "workflow-builder" in components
