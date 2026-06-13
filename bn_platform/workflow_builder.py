"""AI Workflow Builder — dashboard untuk membuat, mempublikasikan, dan menguji
workflow otomasi AI Agent (mirip n8n/Zapier/Make): Trigger -> Condition ->
Agent -> Action -> Notification, lengkap dengan riwayat eksekusi."""
from __future__ import annotations

import json
import uuid
from typing import Annotated, Awaitable, Callable

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from workflow_engine import NODE_CATALOG, run_workflow
from .security import write_audit_log

GetPool = Callable[..., Awaitable[asyncpg.Pool]]
GetCurrentUser = Callable[..., Awaitable[dict]]
GetAgentConfig = Callable[[], dict]

WORKFLOW_STATUSES = {"draft", "published", "disabled"}


def _jsonb(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else []
    if value is None:
        return default if default is not None else []
    return value


def _row_with_jsonb(row: dict, fields: list[str]) -> dict:
    out = dict(row)
    for field in fields:
        if field in out:
            out[field] = _jsonb(out[field])
    return out


class WorkflowCreateRequest(BaseModel):
    name: str
    description: str | None = None
    trigger_type: str = "manual_trigger"
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    nodes: list[dict] | None = None
    edges: list[dict] | None = None


class WorkflowTestRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


def build_workflow_builder_router(
    *,
    get_pool: GetPool,
    get_current_user: GetCurrentUser,
    get_agent_config: GetAgentConfig,
    enqueue_handoff_fn=None,
) -> APIRouter:
    router = APIRouter(prefix="/workflow-builder", tags=["workflow-builder"])

    async def _get_bot(pool: asyncpg.Pool, bot_id: str, org_id: str) -> dict:
        bot = await pool.fetchrow("SELECT id, name FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id)
        if not bot:
            raise HTTPException(404, "Bot tidak ditemukan")
        return dict(bot)

    async def _get_workflow(pool: asyncpg.Pool, workflow_id: str, org_id: str) -> dict:
        row = await pool.fetchrow("SELECT * FROM workflows WHERE id=$1 AND org_id=$2", workflow_id, org_id)
        if not row:
            raise HTTPException(404, "Workflow tidak ditemukan")
        return _row_with_jsonb(dict(row), ["nodes", "edges"])

    @router.get("/node-catalog")
    async def node_catalog(user: Annotated[dict, Depends(get_current_user)]):
        return {"categories": NODE_CATALOG}

    @router.get("/bots/{bot_id}/workflows")
    async def list_workflows(
        bot_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)
        rows = await pool.fetch(
            """SELECT id, bot_id, name, description, status, trigger_type,
                      created_at, updated_at, published_at
               FROM workflows WHERE org_id=$1 AND (bot_id=$2 OR bot_id IS NULL)
               ORDER BY updated_at DESC""",
            org_id, bot_id,
        )
        return {"workflows": [dict(r) for r in rows]}

    @router.post("/bots/{bot_id}/workflows", status_code=201)
    async def create_workflow(
        bot_id: str,
        body: WorkflowCreateRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        await _get_bot(pool, bot_id, org_id)
        if body.trigger_type not in NODE_CATALOG["trigger"]:
            raise HTTPException(422, "trigger_type tidak valid")

        workflow_id = str(uuid.uuid4())
        row = await pool.fetchrow(
            """INSERT INTO workflows (id, org_id, bot_id, name, description, trigger_type, nodes, edges, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
            workflow_id, org_id, bot_id, body.name, body.description, body.trigger_type,
            json.dumps(body.nodes), json.dumps(body.edges), user.get("id"),
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="create", resource_type="workflow", resource_id=workflow_id,
            metadata={"name": body.name, "trigger_type": body.trigger_type, "bot_id": bot_id},
        )
        return _row_with_jsonb(dict(row), ["nodes", "edges"])

    @router.get("/workflows/{workflow_id}")
    async def get_workflow(
        workflow_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        return await _get_workflow(pool, workflow_id, user["org_id"])

    @router.patch("/workflows/{workflow_id}")
    async def update_workflow(
        workflow_id: str,
        body: WorkflowUpdateRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        wf = await _get_workflow(pool, workflow_id, org_id)

        name = body.name if body.name is not None else wf["name"]
        description = body.description if body.description is not None else wf["description"]
        trigger_type = body.trigger_type if body.trigger_type is not None else wf["trigger_type"]
        if trigger_type not in NODE_CATALOG["trigger"]:
            raise HTTPException(422, "trigger_type tidak valid")
        nodes = body.nodes if body.nodes is not None else wf["nodes"]
        edges = body.edges if body.edges is not None else wf["edges"]

        row = await pool.fetchrow(
            """UPDATE workflows SET name=$1, description=$2, trigger_type=$3, nodes=$4, edges=$5, updated_at=NOW()
               WHERE id=$6 RETURNING *""",
            name, description, trigger_type, json.dumps(nodes), json.dumps(edges), workflow_id,
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workflow", resource_id=workflow_id,
            metadata={"name": name, "trigger_type": trigger_type},
        )
        return _row_with_jsonb(dict(row), ["nodes", "edges"])

    @router.post("/workflows/{workflow_id}/publish")
    async def publish_workflow(
        workflow_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        wf = await _get_workflow(pool, workflow_id, org_id)
        if not any(n.get("category") == "trigger" for n in wf["nodes"]):
            raise HTTPException(422, "Workflow harus memiliki trigger node sebelum dipublish.")

        row = await pool.fetchrow(
            """UPDATE workflows SET status='published', published_at=NOW(), updated_at=NOW()
               WHERE id=$1 RETURNING *""",
            workflow_id,
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workflow", resource_id=workflow_id,
            metadata={"name": wf["name"], "status": "published"},
        )
        return _row_with_jsonb(dict(row), ["nodes", "edges"])

    @router.post("/workflows/{workflow_id}/unpublish")
    async def unpublish_workflow(
        workflow_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        wf = await _get_workflow(pool, workflow_id, org_id)
        row = await pool.fetchrow(
            "UPDATE workflows SET status='draft', updated_at=NOW() WHERE id=$1 RETURNING *",
            workflow_id,
        )
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="update", resource_type="workflow", resource_id=workflow_id,
            metadata={"name": wf["name"], "status": "draft"},
        )
        return _row_with_jsonb(dict(row), ["nodes", "edges"])

    @router.delete("/workflows/{workflow_id}")
    async def delete_workflow(
        workflow_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        wf = await _get_workflow(pool, workflow_id, org_id)
        await pool.execute("DELETE FROM workflows WHERE id=$1", workflow_id)
        await write_audit_log(
            pool, org_id=org_id, actor_user_id=user["id"], actor_email=user.get("email"),
            action="delete", resource_type="workflow", resource_id=workflow_id,
            metadata={"name": wf["name"]},
        )
        return {"deleted": True}

    @router.post("/workflows/{workflow_id}/test")
    async def test_workflow(
        workflow_id: str,
        body: WorkflowTestRequest,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        wf = await _get_workflow(pool, workflow_id, org_id)
        if not any(n.get("category") == "trigger" for n in wf["nodes"]):
            raise HTTPException(422, "Workflow harus memiliki trigger node untuk dites.")

        execution_id = await run_workflow(
            pool, {"id": wf["id"], "nodes": wf["nodes"], "edges": wf["edges"]},
            trigger_type=wf["trigger_type"], trigger_payload=body.payload,
            org_id=org_id, bot_id=wf["bot_id"],
            agent_config=get_agent_config(), enqueue_handoff_fn=enqueue_handoff_fn,
        )
        execution = await pool.fetchrow("SELECT * FROM workflow_executions WHERE id=$1", execution_id)
        steps = await pool.fetch(
            "SELECT * FROM workflow_execution_steps WHERE execution_id=$1 ORDER BY started_at",
            execution_id,
        )
        return {
            "execution": _row_with_jsonb(dict(execution), ["trigger_payload"]),
            "steps": [_row_with_jsonb(dict(s), ["input", "output"]) for s in steps],
        }

    @router.get("/workflows/{workflow_id}/executions")
    async def list_executions(
        workflow_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
        limit: int = 20,
    ):
        org_id = user["org_id"]
        await _get_workflow(pool, workflow_id, org_id)
        limit = max(1, min(100, limit))
        rows = await pool.fetch(
            """SELECT id, trigger_type, status, error, started_at, finished_at, duration_ms
               FROM workflow_executions WHERE workflow_id=$1
               ORDER BY started_at DESC LIMIT $2""",
            workflow_id, limit,
        )
        return {"executions": [dict(r) for r in rows]}

    @router.get("/executions/{execution_id}")
    async def get_execution(
        execution_id: str,
        user: Annotated[dict, Depends(get_current_user)],
        pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ):
        org_id = user["org_id"]
        execution = await pool.fetchrow(
            "SELECT * FROM workflow_executions WHERE id=$1 AND org_id=$2", execution_id, org_id
        )
        if not execution:
            raise HTTPException(404, "Execution tidak ditemukan")
        steps = await pool.fetch(
            "SELECT * FROM workflow_execution_steps WHERE execution_id=$1 ORDER BY started_at",
            execution_id,
        )
        return {
            "execution": _row_with_jsonb(dict(execution), ["trigger_payload"]),
            "steps": [_row_with_jsonb(dict(s), ["input", "output"]) for s in steps],
        }

    return router
