"""
workflow_engine.py — AI Workflow Builder execution engine.

Node-based automation untuk AI Agent (mirip n8n/Zapier/Make), dengan pipeline:
Trigger -> Condition -> Agent -> Action -> Notification.

Isi modul ini:
- NODE_CATALOG / AGENT_PERSONAS — katalog tipe node untuk palette & validasi
  config di frontend Workflow Builder.
- WorkflowAgent — wrapper BaseAgent ringan untuk node kategori "agent"
  (CS/Sales/FAQ/Knowledge/Verification Agent), pakai persona prompt berbeda.
- run_workflow() — jalankan satu workflow: graph traversal node-by-node,
  retry per node, logging tiap step, dan riwayat eksekusi (workflow_executions
  + workflow_execution_steps).
- trigger_workflows() — cari semua workflow published milik tenant yang cocok
  dengan satu event trigger, lalu jalankan masing-masing (dipanggil
  fire-and-forget dari main.py / bn_platform).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid

import asyncpg
import httpx

from base import BaseAgent

# ─────────────────────────────────────────────────────────────
# Node catalog (untuk palette & form konfigurasi di frontend)
# ─────────────────────────────────────────────────────────────

_AGENT_CONFIG_FIELDS = [
    {"key": "instruction", "label": "Instruksi tambahan untuk agent", "type": "textarea", "default": ""},
]

_PRIORITY_OPTIONS = [
    {"value": "low", "label": "Low"},
    {"value": "medium", "label": "Medium"},
    {"value": "high", "label": "High"},
    {"value": "urgent", "label": "Urgent"},
]

NODE_CATALOG: dict[str, dict[str, dict]] = {
    "trigger": {
        "message_received": {
            "label": "Message Received",
            "description": "Dipicu setiap kali pelanggan mengirim pesan baru ke bot.",
            "config_fields": [],
        },
        "new_lead": {
            "label": "New Lead",
            "description": "Dipicu saat skor lead pelanggan naik menjadi warm/hot.",
            "config_fields": [],
        },
        "new_customer": {
            "label": "New Customer",
            "description": "Dipicu saat percakapan pertama dari pelanggan baru dimulai.",
            "config_fields": [],
        },
        "new_ticket": {
            "label": "New Ticket",
            "description": "Dipicu saat tiket human handoff baru masuk ke antrian.",
            "config_fields": [],
        },
        "manual_trigger": {
            "label": "Manual Trigger",
            "description": "Dijalankan manual lewat tombol Test di Workflow Builder.",
            "config_fields": [],
        },
    },
    "condition": {
        "intent": {
            "label": "Intent",
            "description": "Cek intent percakapan hasil analisis AI.",
            "config_fields": [
                {"key": "operator", "label": "Operator", "type": "select", "default": "equals", "options": [
                    {"value": "equals", "label": "Sama dengan"},
                    {"value": "not_equals", "label": "Tidak sama dengan"},
                    {"value": "in", "label": "Salah satu dari (pisahkan koma)"},
                ]},
                {"key": "value", "label": "Nilai intent", "type": "text", "default": ""},
            ],
        },
        "confidence": {
            "label": "Confidence",
            "description": "Cek skor confidence jawaban AI (0-1).",
            "config_fields": [
                {"key": "operator", "label": "Operator", "type": "select", "default": "gte", "options": [
                    {"value": "gte", "label": ">="},
                    {"value": "lte", "label": "<="},
                    {"value": "gt", "label": ">"},
                    {"value": "lt", "label": "<"},
                    {"value": "eq", "label": "="},
                ]},
                {"key": "value", "label": "Nilai (0-1)", "type": "number", "default": 0.6},
            ],
        },
        "customer_type": {
            "label": "Customer Type",
            "description": "Cek tipe pelanggan (new/returning/hot/warm/cold).",
            "config_fields": [
                {"key": "operator", "label": "Operator", "type": "select", "default": "equals", "options": [
                    {"value": "equals", "label": "Sama dengan"},
                    {"value": "not_equals", "label": "Tidak sama dengan"},
                    {"value": "in", "label": "Salah satu dari (pisahkan koma)"},
                ]},
                {"key": "value", "label": "Tipe pelanggan", "type": "text", "default": "new"},
            ],
        },
        "tags": {
            "label": "Tags",
            "description": "Cek apakah topik/tag percakapan mengandung nilai tertentu.",
            "config_fields": [
                {"key": "operator", "label": "Operator", "type": "select", "default": "contains", "options": [
                    {"value": "contains", "label": "Mengandung"},
                    {"value": "not_contains", "label": "Tidak mengandung"},
                ]},
                {"key": "value", "label": "Tag", "type": "text", "default": ""},
            ],
        },
    },
    "agent": {
        "cs_agent": {"label": "CS Agent", "description": "Agen customer service umum.", "config_fields": _AGENT_CONFIG_FIELDS},
        "sales_agent": {"label": "Sales Agent", "description": "Agen penjualan & follow-up lead.", "config_fields": _AGENT_CONFIG_FIELDS},
        "faq_agent": {"label": "FAQ Agent", "description": "Agen khusus menjawab pertanyaan umum (FAQ).", "config_fields": _AGENT_CONFIG_FIELDS},
        "knowledge_agent": {"label": "Knowledge Agent", "description": "Agen pencarian & sintesis knowledge base.", "config_fields": _AGENT_CONFIG_FIELDS},
        "verification_agent": {"label": "Verification Agent", "description": "Agen verifikasi kualitas jawaban sebelum dikirim.", "config_fields": _AGENT_CONFIG_FIELDS},
    },
    "action": {
        "send_message": {
            "label": "Send Message",
            "description": "Kirim balasan tambahan ke percakapan.",
            "config_fields": [
                {"key": "message", "label": "Pesan (boleh pakai {{agent_output}})", "type": "textarea", "default": "{{agent_output}}"},
            ],
        },
        "create_ticket": {
            "label": "Create Ticket",
            "description": "Buat tiket human handoff baru di antrian.",
            "config_fields": [
                {"key": "reason", "label": "Alasan", "type": "text", "default": "workflow_automation"},
                {"key": "priority", "label": "Prioritas", "type": "select", "default": "medium", "options": _PRIORITY_OPTIONS},
            ],
        },
        "human_handoff": {
            "label": "Human Handoff",
            "description": "Eskalasi percakapan ke tim manusia.",
            "config_fields": [
                {"key": "reason", "label": "Alasan", "type": "text", "default": "human_handoff_requested"},
                {"key": "priority", "label": "Prioritas", "type": "select", "default": "high", "options": _PRIORITY_OPTIONS},
            ],
        },
        "update_crm": {
            "label": "Update CRM",
            "description": "Tambahkan tag ke profil pelanggan (customer_profiles).",
            "config_fields": [
                {"key": "tags", "label": "Tag tambahan (pisahkan koma)", "type": "text", "default": ""},
            ],
        },
    },
    "notification": {
        "email_notification": {
            "label": "Email Notification",
            "description": "Kirim notifikasi (email/webhook) ke tim internal.",
            "config_fields": [
                {"key": "to", "label": "Tujuan", "type": "text", "default": "{{end_user_email}}"},
                {"key": "subject", "label": "Subjek", "type": "text", "default": "Notifikasi BotNesia"},
                {"key": "body", "label": "Isi pesan", "type": "textarea", "default": "{{agent_output}}"},
                {"key": "webhook_url", "label": "Webhook URL (opsional)", "type": "text", "default": ""},
            ],
        },
    },
}

AGENT_PERSONAS: dict[str, str] = {
    "cs_agent": (
        "Kamu adalah CS Agent BotNesia — menjawab pertanyaan pelanggan dengan ramah, "
        "jelas, dan berdasarkan konteks percakapan yang tersedia. Balas dalam Bahasa Indonesia."
    ),
    "sales_agent": (
        "Kamu adalah Sales Agent BotNesia — fokus membantu calon pelanggan memahami produk/"
        "paket, mendorong follow-up yang relevan tanpa memaksa, dan menyoroti manfaut konkret. "
        "Balas dalam Bahasa Indonesia."
    ),
    "faq_agent": (
        "Kamu adalah FAQ Agent BotNesia — jawab pertanyaan umum secara singkat, padat, dan "
        "akurat berdasarkan konteks yang tersedia. Jika tidak ada di konteks, katakan belum "
        "tersedia. Balas dalam Bahasa Indonesia."
    ),
    "knowledge_agent": (
        "Kamu adalah Knowledge Agent BotNesia — cari dan sintesis informasi paling relevan dari "
        "knowledge base/konteks percakapan untuk menjawab kebutuhan pengguna secara terstruktur. "
        "Balas dalam Bahasa Indonesia."
    ),
    "verification_agent": (
        "Kamu adalah Verification Agent BotNesia — periksa apakah jawaban/konteks sebelumnya "
        "sudah akurat, lengkap, dan tidak mengarang fakta. Beri ringkasan verifikasi singkat. "
        "Balas dalam Bahasa Indonesia."
    ),
}

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _jsonb(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else []
    if value is None:
        return default if default is not None else []
    return value


def _safe_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _render_template(template: str, context: dict) -> str:
    def repl(match: re.Match) -> str:
        value = context.get(match.group(1))
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return _TEMPLATE_RE.sub(repl, template or "")


def _evaluate_condition(node_type: str, operator: str, expected, context: dict) -> tuple[bool, object]:
    """Evaluasi satu condition node. Return (result, actual_value)."""
    if node_type == "confidence":
        actual = context.get("confidence")
        try:
            actual_f = float(actual)
            expected_f = float(expected)
        except (TypeError, ValueError):
            return False, actual
        ops = {
            "gte": actual_f >= expected_f,
            "lte": actual_f <= expected_f,
            "gt":  actual_f > expected_f,
            "lt":  actual_f < expected_f,
            "eq":  actual_f == expected_f,
        }
        return ops.get(operator, ops["gte"]), actual

    if node_type == "tags":
        actual = context.get("tags") or []
        tags = [str(t).lower() for t in actual]
        expected_s = str(expected or "").lower().strip()
        result = expected_s in tags
        if operator == "not_contains":
            result = not result
        return result, actual

    if node_type == "intent":
        actual = context.get("intent")
    elif node_type == "customer_type":
        actual = context.get("customer_type")
    else:
        actual = None

    actual_s = str(actual or "").lower().strip()
    expected_s = str(expected or "").lower().strip()
    if operator == "not_equals":
        return actual_s != expected_s, actual
    if operator == "in":
        options = [o.strip() for o in expected_s.split(",") if o.strip()]
        return actual_s in options, actual
    return actual_s == expected_s, actual


# ─────────────────────────────────────────────────────────────
# Agent node executor
# ─────────────────────────────────────────────────────────────

class WorkflowAgent(BaseAgent):
    """Agen LLM generik untuk node kategori 'agent' — persona berbeda per tipe."""
    name = "workflow_agent"

    def __init__(self, persona_prompt: str, **kwargs):
        super().__init__(**kwargs)
        self.system_prompt = persona_prompt

    async def run_node(self, *, instruction: str, context: dict) -> dict:
        ctx_keys = (
            "message", "answer", "intent", "confidence", "tags", "customer_type",
            "end_user_name", "agent_output",
        )
        ctx_snippet = _safe_json({k: context.get(k) for k in ctx_keys if k in context})[:2000]
        messages = [
            {
                "role": "system",
                "content": self.system_prompt + "\n\nBalas HANYA dalam format JSON: {\"output\": \"...\"}.",
            },
            {
                "role": "user",
                "content": (
                    f"Konteks percakapan (JSON):\n{ctx_snippet}\n\n"
                    f"Instruksi:\n{instruction}"
                ),
            },
        ]
        return await self._call_llm_json(messages, default={"output": ""})


# ─────────────────────────────────────────────────────────────
# Per-category node executors
# ─────────────────────────────────────────────────────────────

async def _exec_trigger(node: dict, context: dict) -> dict:
    return {"status": "success", "output": {"trigger_type": node.get("type")}}


async def _exec_condition(node: dict, context: dict) -> dict:
    cfg = node.get("config") or {}
    operator = cfg.get("operator") or "equals"
    expected = cfg.get("value")
    result, actual = _evaluate_condition(node.get("type") or "", operator, expected, context)
    return {
        "status": "success",
        "output": {
            "operator": operator, "expected": expected, "actual": actual,
            "result": result, "branch": "true" if result else "false",
        },
    }


async def _exec_agent(node: dict, context: dict, *, agent_config: dict | None) -> dict:
    if not agent_config or not agent_config.get("api_key"):
        return {"status": "skipped", "output": {"reason": "AI belum dikonfigurasi (GROQ_API_KEY kosong)."}}

    node_type = node.get("type") or "cs_agent"
    persona = AGENT_PERSONAS.get(node_type, AGENT_PERSONAS["cs_agent"])
    agent = WorkflowAgent(
        persona,
        api_key=agent_config.get("api_key"),
        model=agent_config.get("model"),
        base_url=agent_config.get("base_url"),
        app_url=agent_config.get("app_url") or "https://botnesia.id",
    )
    cfg = node.get("config") or {}
    instruction = (cfg.get("instruction") or "").strip() or (
        "Berikan respons yang relevan untuk pelanggan berdasarkan konteks percakapan ini."
    )
    result = await agent.run_node(instruction=instruction, context=context)
    if result.get("_llm_unavailable"):
        return {"status": "failed", "output": result, "error": "LLM tidak tersedia"}

    output_text = str(result.get("output") or "")
    context["agent_output"] = output_text
    context["agent_role"] = node_type
    return {"status": "success", "output": {"output": output_text, "role": node_type}}


async def _action_send_message(node: dict, context: dict, *, pool: asyncpg.Pool) -> dict:
    conv_id = context.get("conversation_id")
    if not conv_id:
        return {"status": "skipped", "output": {"reason": "Tidak ada conversation_id pada konteks."}}

    cfg = node.get("config") or {}
    template = cfg.get("message") or "{{agent_output}}"
    text = _render_template(template, context).strip()
    if not text:
        text = str(context.get("agent_output") or context.get("answer") or "").strip()
    if not text:
        return {"status": "skipped", "output": {"reason": "Tidak ada teks pesan untuk dikirim."}}

    msg_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO messages (id, conversation_id, role, content, model)
           VALUES ($1,$2,'assistant',$3,'workflow:automation')""",
        msg_id, conv_id, text,
    )
    await pool.execute(
        "UPDATE conversations SET msg_count=msg_count+1, last_msg_at=NOW() WHERE id=$1",
        conv_id,
    )
    context["last_sent_message"] = text
    return {"status": "success", "output": {"message_id": msg_id, "conversation_id": conv_id, "text": text}}


async def _action_handoff(
    node: dict, context: dict, *, pool: asyncpg.Pool, org_id: str,
    enqueue_handoff_fn, default_reason: str, default_priority: str,
) -> dict:
    conv_id = context.get("conversation_id")
    if not conv_id:
        return {"status": "skipped", "output": {"reason": "Tidak ada conversation_id pada konteks."}}
    if enqueue_handoff_fn is None:
        return {"status": "skipped", "output": {"reason": "Modul handoff tidak tersedia."}}

    cfg = node.get("config") or {}
    reason = cfg.get("reason") or default_reason
    priority = cfg.get("priority") or default_priority
    await enqueue_handoff_fn(pool, org_id=org_id, conversation_id=conv_id, reason=reason, priority=priority)
    return {"status": "success", "output": {"conversation_id": conv_id, "reason": reason, "priority": priority}}


async def _action_update_crm(node: dict, context: dict, *, pool: asyncpg.Pool, bot_id: str | None) -> dict:
    end_user_id = context.get("end_user_id")
    if not (bot_id and end_user_id):
        return {"status": "skipped", "output": {"reason": "Tidak ada end_user_id/bot_id pada konteks."}}

    cfg = node.get("config") or {}
    extra = cfg.get("tags")
    if isinstance(extra, str):
        extra_tags = [t.strip() for t in extra.split(",") if t.strip()]
    else:
        extra_tags = [str(t).strip() for t in (extra or []) if str(t).strip()]
    tags = extra_tags or [str(t).strip() for t in (context.get("tags") or []) if str(t).strip()]
    if not tags:
        return {"status": "skipped", "output": {"reason": "Tidak ada tag untuk diterapkan."}}

    row = await pool.fetchrow(
        """UPDATE customer_profiles
           SET preferred_topics = ARRAY(SELECT DISTINCT unnest(preferred_topics || $1::text[])),
               updated_at = NOW()
           WHERE bot_id=$2 AND end_user_id=$3
           RETURNING id, preferred_topics""",
        tags, bot_id, end_user_id,
    )
    if not row:
        return {"status": "skipped", "output": {"reason": "Profil pelanggan tidak ditemukan."}}
    return {"status": "success", "output": {"end_user_id": end_user_id, "preferred_topics": list(row["preferred_topics"] or [])}}


async def _exec_action(node: dict, context: dict, *, pool: asyncpg.Pool, org_id: str, bot_id: str | None, enqueue_handoff_fn) -> dict:
    node_type = node.get("type")
    if node_type == "send_message":
        return await _action_send_message(node, context, pool=pool)
    if node_type == "create_ticket":
        return await _action_handoff(
            node, context, pool=pool, org_id=org_id, enqueue_handoff_fn=enqueue_handoff_fn,
            default_reason="workflow_automation", default_priority="medium",
        )
    if node_type == "human_handoff":
        return await _action_handoff(
            node, context, pool=pool, org_id=org_id, enqueue_handoff_fn=enqueue_handoff_fn,
            default_reason="human_handoff_requested", default_priority="high",
        )
    if node_type == "update_crm":
        return await _action_update_crm(node, context, pool=pool, bot_id=bot_id)
    return {"status": "failed", "output": {}, "error": f"Tipe action tidak dikenal: {node_type}"}


async def _exec_notification(node: dict, context: dict) -> dict:
    cfg = node.get("config") or {}
    to = _render_template(cfg.get("to") or "{{end_user_email}}", context)
    subject = _render_template(cfg.get("subject") or "Notifikasi BotNesia", context)
    body = _render_template(cfg.get("body") or "{{agent_output}}", context)
    webhook_url = (cfg.get("webhook_url") or "").strip()
    payload = {"to": to, "subject": subject, "body": body}

    if not webhook_url:
        return {"status": "success", "output": {**payload, "delivery": "logged"}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        return {"status": "success", "output": {**payload, "delivery": "webhook", "webhook_status": resp.status_code}}
    except Exception as e:
        return {"status": "failed", "output": payload, "error": f"Webhook gagal: {e}"}


async def _execute_node(
    node: dict, context: dict, *, pool: asyncpg.Pool, org_id: str, bot_id: str | None,
    agent_config: dict | None, enqueue_handoff_fn,
) -> dict:
    category = node.get("category")
    try:
        if category == "trigger":
            return await _exec_trigger(node, context)
        if category == "condition":
            return await _exec_condition(node, context)
        if category == "agent":
            return await _exec_agent(node, context, agent_config=agent_config)
        if category == "action":
            return await _exec_action(node, context, pool=pool, org_id=org_id, bot_id=bot_id, enqueue_handoff_fn=enqueue_handoff_fn)
        if category == "notification":
            return await _exec_notification(node, context)
        return {"status": "failed", "output": {}, "error": f"Kategori node tidak dikenal: {category}"}
    except Exception as e:
        return {"status": "failed", "output": {}, "error": str(e)}


async def _persist_step(pool: asyncpg.Pool, execution_id: str, node: dict, attempt: int, result: dict, duration_ms: int) -> None:
    await pool.execute(
        """INSERT INTO workflow_execution_steps
           (id, execution_id, node_id, node_type, category, status, attempt, input, output, error, finished_at, duration_ms)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),$11)""",
        str(uuid.uuid4()), execution_id,
        str(node.get("id") or ""), str(node.get("type") or ""), str(node.get("category") or ""),
        result.get("status", "failed"), attempt,
        _safe_json(node.get("config") or {}), _safe_json(result.get("output") or {}),
        result.get("error"), duration_ms,
    )


# ─────────────────────────────────────────────────────────────
# Execution engine
# ─────────────────────────────────────────────────────────────

async def run_workflow(
    pool: asyncpg.Pool,
    workflow: dict,
    *,
    trigger_type: str,
    trigger_payload: dict | None,
    org_id: str,
    bot_id: str | None = None,
    agent_config: dict | None = None,
    enqueue_handoff_fn=None,
    max_steps: int = 50,
) -> str:
    """Jalankan satu workflow (graph traversal + retry + logging). Return execution_id."""
    execution_id = str(uuid.uuid4())
    t_start = time.monotonic()
    trigger_payload = trigger_payload or {}

    await pool.execute(
        """INSERT INTO workflow_executions (id, org_id, workflow_id, bot_id, trigger_type, trigger_payload, status)
           VALUES ($1,$2,$3,$4,$5,$6,'running')""",
        execution_id, org_id, workflow["id"], bot_id, trigger_type, _safe_json(trigger_payload),
    )

    nodes = {n["id"]: n for n in _jsonb(workflow.get("nodes")) if n.get("id")}
    edges = _jsonb(workflow.get("edges"))
    adjacency: dict[str, list[dict]] = {}
    for e in edges:
        adjacency.setdefault(e.get("source"), []).append(e)

    current = next((n for n in nodes.values() if n.get("category") == "trigger"), None)

    context: dict = dict(trigger_payload)
    status, error = "success", None
    visited: set[str] = set()
    steps_run = 0

    while current is not None:
        if current["id"] in visited or steps_run >= max_steps:
            break
        visited.add(current["id"])
        steps_run += 1

        node_cfg = current.get("config") or {}
        max_attempts = max(1, min(5, int(node_cfg.get("retries", 0) or 0) + 1))
        step_result: dict = {"status": "failed", "output": {}, "error": None}

        for attempt in range(1, max_attempts + 1):
            t_step = time.monotonic()
            step_result = await _execute_node(
                current, context, pool=pool, org_id=org_id, bot_id=bot_id,
                agent_config=agent_config, enqueue_handoff_fn=enqueue_handoff_fn,
            )
            duration_ms = int((time.monotonic() - t_step) * 1000)
            await _persist_step(pool, execution_id, current, attempt, step_result, duration_ms)
            if step_result.get("status") != "failed":
                break
            if attempt < max_attempts:
                await asyncio.sleep(min(0.2 * attempt, 1.0))

        if step_result.get("status") == "failed":
            status, error = "failed", step_result.get("error") or "Step gagal dieksekusi."
            break

        outs = adjacency.get(current["id"], [])
        if not outs:
            current = None
            continue

        if current.get("category") == "condition":
            branch = step_result["output"].get("branch", "false")
            next_edge = next(
                (e for e in outs if str(e.get("source_handle") or e.get("label") or "").lower() == branch),
                None,
            )
            if next_edge is None:
                next_edge = next((e for e in outs if not e.get("source_handle") and not e.get("label")), None)
        else:
            next_edge = outs[0]

        current = nodes.get(next_edge["target"]) if next_edge else None

    duration_ms = int((time.monotonic() - t_start) * 1000)
    await pool.execute(
        """UPDATE workflow_executions
           SET status=$1, error=$2, finished_at=NOW(), duration_ms=$3
           WHERE id=$4""",
        status, error, duration_ms, execution_id,
    )
    return execution_id


async def trigger_workflows(
    pool: asyncpg.Pool,
    *,
    org_id: str,
    bot_id: str | None,
    trigger_type: str,
    payload: dict | None = None,
    agent_config: dict | None = None,
    enqueue_handoff_fn=None,
) -> list[str]:
    """Cari semua workflow published milik tenant yang cocok dengan satu event
    trigger, lalu jalankan masing-masing. Return list execution_id."""
    rows = await pool.fetch(
        """SELECT id, nodes, edges FROM workflows
           WHERE org_id=$1 AND status='published' AND trigger_type=$2
             AND (bot_id=$3 OR bot_id IS NULL)""",
        org_id, trigger_type, bot_id,
    )
    execution_ids: list[str] = []
    for row in rows:
        workflow = {"id": row["id"], "nodes": _jsonb(row["nodes"]), "edges": _jsonb(row["edges"])}
        execution_ids.append(await run_workflow(
            pool, workflow,
            trigger_type=trigger_type, trigger_payload=payload,
            org_id=org_id, bot_id=bot_id,
            agent_config=agent_config, enqueue_handoff_fn=enqueue_handoff_fn,
        ))
    return execution_ids
