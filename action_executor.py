"""
action_executor.py — Action Executor (AI Agent Platform).

Pipeline utama untuk eksekusi aksi agent secara terstruktur:

    Goal → Plan → Ask Permission → Execute → Observe → Recover → Verify → Summarize

Setiap eksekusi:
1. UNDERSTAND: parse goal + klasifikasi domain
2. PLAN: pecah jadi langkah terurut via LLM
3. PERMISSION: cek izin untuk setiap aksi (gating)
4. EXECUTE: jalankan aksi via service yang tepat
5. OBSERVE: catat hasil setiap langkah
6. RECOVER: recovery otomatis jika ada kegagalan
7. VERIFY: verifikasi apakah goal tercapai
8. SUMMARIZE: buat laporan ringkas

Semua aksi di-log ke audit_logger.
Di-persist ke tabel agent_action_executions.

Tidak ada agent yang memanggil modul ini langsung — ini dipanggil dari:
  - main.py router (endpoint /api/agent/execute)
  - task_engine.run_agent_task() (lewat tool_calling loop)
  - workflow_engine.py (sebagai action step dalam workflow)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from agent_memory_store import AgentMemoryStore
from audit_logger import log_action
from base import BaseAgent
from recovery_manager import RecoveryManager

logger = logging.getLogger(__name__)

_MAX_PLAN_STEPS = 12
_STEP_TIMEOUT = 120  # detik per step
_TOTAL_TIMEOUT = 600  # 10 menit total


@dataclass
class ActionStep:
    step_no: int
    description: str
    action_type: str       # browser_read | browser_write | file_read | file_write | terminal | api | knowledge_search | ...
    tool: str              # nama tool/service
    params: dict
    requires_permission: str = ""
    requires_approval: bool = False
    status: str = "pending"   # pending | running | completed | failed | skipped | pending_approval
    result: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0


@dataclass
class ActionPlan:
    goal: str
    steps: list[ActionStep]
    estimated_duration_seconds: float = 0.0
    risks: list[str] = field(default_factory=list)
    requires_approvals: list[str] = field(default_factory=list)


@dataclass
class ActionExecutionResult:
    execution_id: str
    goal: str
    status: str   # completed | failed | partial | pending_approval
    plan: list[dict]
    observations: list[dict]
    verification: dict
    summary: str
    duration_ms: int
    approved_steps: list[str] = field(default_factory=list)
    pending_approvals: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "goal": self.goal,
            "status": self.status,
            "plan": self.plan,
            "observations": self.observations,
            "verification": self.verification,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "pending_approvals": self.pending_approvals,
        }


class ActionExecutor:
    """
    Pipeline eksekusi aksi enterprise-grade.

    Dipanggil dengan agent sebagai context provider (untuk LLM calls).
    Services (FileSystemService, TerminalService, ComputerUseService) di-inject
    oleh caller.
    """

    def __init__(
        self,
        agent: BaseAgent,
        pool: asyncpg.Pool,
        org_id: str,
        *,
        memory: AgentMemoryStore | None = None,
        recovery: RecoveryManager | None = None,
        filesystem=None,
        terminal=None,
        computer=None,
    ):
        self._agent = agent
        self._pool = pool
        self._org_id = org_id
        self._memory = memory or AgentMemoryStore(pool, org_id)
        self._recovery = recovery or RecoveryManager()
        self._fs = filesystem
        self._terminal = terminal
        self._computer = computer
        self._execution_log: list[dict] = []

    # ─── 1. UNDERSTAND ────────────────────────────────────────────────────────

    async def understand_goal(self, goal: str) -> dict:
        """Klasifikasi domain dan complexity goal."""
        result = await self._agent._call_llm_json(
            [
                {"role": "system", "content": (
                    "Kamu adalah agent analyzer. Klasifikasi goal berikut."
                )},
                {"role": "user", "content": (
                    f"Goal: {goal}\n\n"
                    "Jawab JSON: {\"domain\": \"browser|file|terminal|api|knowledge|mixed\", "
                    "\"complexity\": \"simple|medium|complex\", "
                    "\"requires_external_access\": true|false, "
                    "\"key_entities\": [\"...\"]}"
                )},
            ],
            temperature=0.0, max_tokens=200,
            default={"domain": "mixed", "complexity": "medium", "requires_external_access": False, "key_entities": []},
        )
        return result

    # ─── 2. PLAN ──────────────────────────────────────────────────────────────

    async def plan_goal(self, goal: str, *, domain: str = "mixed") -> ActionPlan:
        """Pecah goal jadi langkah terstruktur dengan estimasi waktu dan risiko."""
        memory_summary = self._memory.get_summary()
        context_str = f"\nKonteks memory agent:\n{memory_summary}" if memory_summary else ""

        result = await self._agent._call_llm_json(
            [
                {"role": "system", "content": (
                    "Kamu adalah action planner. Buat rencana langkah-langkah konkret "
                    "untuk mencapai goal. Setiap langkah HARUS spesifik dan dapat dieksekusi. "
                    "Jawab HANYA JSON."
                )},
                {"role": "user", "content": (
                    f"Goal: {goal}"
                    f"{context_str}\n\n"
                    "Buat rencana eksekusi. Untuk setiap langkah, tentukan:\n"
                    "- action_type: browser_read|browser_write|file_read|file_write|"
                    "terminal|api_call|knowledge_search|document_generate|email_read|channel_message\n"
                    "- tool: nama tool/service yang dipakai\n"
                    "- params: parameter konkret\n"
                    "- requires_approval: true jika aksi berbahaya\n\n"
                    f'Jawab JSON: {{"steps": [{{"step_no": 1, "description": "...", '
                    '"action_type": "...", "tool": "...", "params": {{}}, "requires_approval": false}}, ...],'
                    '"estimated_duration_seconds": 30, "risks": ["..."], '
                    '"requires_approvals": ["langkah yang butuh approval"]}}'
                )},
            ],
            temperature=0.1, max_tokens=1000,
            default={
                "steps": [{"step_no": 1, "description": goal, "action_type": "knowledge_search",
                           "tool": "knowledge_search", "params": {"query": goal}, "requires_approval": False}],
                "estimated_duration_seconds": 10,
                "risks": [],
                "requires_approvals": [],
            },
        )

        raw_steps = result.get("steps") or []
        steps = []
        for s in raw_steps[:_MAX_PLAN_STEPS]:
            steps.append(ActionStep(
                step_no=int(s.get("step_no") or len(steps) + 1),
                description=str(s.get("description") or ""),
                action_type=str(s.get("action_type") or "api_call"),
                tool=str(s.get("tool") or ""),
                params=s.get("params") or {},
                requires_approval=bool(s.get("requires_approval", False)),
            ))

        return ActionPlan(
            goal=goal,
            steps=steps,
            estimated_duration_seconds=float(result.get("estimated_duration_seconds") or 30),
            risks=result.get("risks") or [],
            requires_approvals=result.get("requires_approvals") or [],
        )

    # ─── 3. EXECUTE ───────────────────────────────────────────────────────────

    async def _execute_step(self, step: ActionStep, *, tool_ctx: dict) -> dict:
        """Eksekusi satu step via service/tool yang sesuai."""
        step.status = "running"
        started = time.perf_counter()

        try:
            result = await asyncio.wait_for(
                self._dispatch_step(step, tool_ctx=tool_ctx),
                timeout=_STEP_TIMEOUT,
            )
        except asyncio.TimeoutError:
            result = {"success": False, "error": f"Step timeout setelah {_STEP_TIMEOUT}s"}
        except Exception as e:
            result = {"success": False, "error": str(e)}

        step.duration_ms = int((time.perf_counter() - started) * 1000)
        step.result = result

        if result.get("requires_approval") or result.get("status") == "pending_approval":
            step.status = "pending_approval"
        elif result.get("success"):
            step.status = "completed"
        else:
            step.status = "failed"
            step.error = result.get("error", "")

        # Update memory
        self._memory.record_action(
            step.action_type,
            target=str(step.params)[:200],
            success=step.status == "completed",
            summary=step.description,
        )

        return result

    async def _dispatch_step(self, step: ActionStep, *, tool_ctx: dict) -> dict:
        """Route step ke service yang tepat."""
        at = step.action_type
        p = step.params

        # Browser actions
        if at == "browser_read" and self._computer:
            url = p.get("url", "")
            return await self._computer.navigate_and_read(url, extract=p.get("extract"))
        if at == "browser_write" and self._computer:
            return await self._computer.interact(p.get("goal", step.description), pre_approved=False)

        # File actions
        if at == "file_read" and self._fs:
            return await self._fs.read_file(p.get("path", ""))
        if at == "file_write" and self._fs:
            return await self._fs.write_file(p.get("path", ""), p.get("content", ""))
        if at == "file_list" and self._fs:
            return await self._fs.list_directory(p.get("path", "."))
        if at == "file_search" and self._fs:
            return await self._fs.search_files(p.get("base_path", "."), query=p.get("query", ""))
        if at == "file_edit" and self._fs:
            return await self._fs.edit_file(p.get("path", ""), old_text=p.get("old_text", ""), new_text=p.get("new_text", ""))
        if at == "project_understand" and self._fs:
            return await self._fs.understand_project(p.get("path", "."))

        # Terminal actions
        if at == "terminal" and self._terminal:
            return await self._terminal.execute(p.get("command", ""), timeout=p.get("timeout", 60))
        if at == "git" and self._terminal:
            return await self._terminal.git(p.get("args", "status"), cwd=p.get("cwd"))

        # Tool executor (existing tools)
        if at in {"knowledge_search", "memory_lookup", "file_reader", "database_query",
                  "web_search", "browser_open", "browser_extract", "financial_data",
                  "news_search", "document_generator", "email_reader", "channel_messaging"}:
            import tool_executor as te
            return await te.execute_tool(at if at != "terminal" else step.tool, p, ctx=tool_ctx)

        # Calculator
        if at == "calculator" or step.tool == "calculator":
            return _eval_math(p.get("expression", ""))

        # Fallback ke tool_executor
        return await self._fallback_tool(step, tool_ctx=tool_ctx)

    async def _fallback_tool(self, step: ActionStep, *, tool_ctx: dict) -> dict:
        """Fallback: coba jalankan via tool_executor jika tool dikenali."""
        import tool_executor as te
        tool_name = step.tool or step.action_type
        if tool_name in te.TOOL_SCHEMAS:
            return await te.execute_tool(tool_name, step.params, ctx=tool_ctx)
        return {
            "success": False,
            "error": f"Tool '{step.tool}' atau action_type '{step.action_type}' tidak dikenali",
            "skipped": True,
        }

    # ─── 4. VERIFY ────────────────────────────────────────────────────────────

    async def verify_goal(self, goal: str, observations: list[dict]) -> dict:
        """Verifikasi apakah goal tercapai berdasarkan semua observasi."""
        obs_summary = json.dumps(observations[:10], ensure_ascii=True, default=str)[:3000]
        return await self._agent._call_llm_json(
            [
                {"role": "system", "content": "Kamu verifier internal. Nilai jujur apakah goal tercapai."},
                {"role": "user", "content": (
                    f"Goal: {goal}\n\nHasil observasi:\n{obs_summary}\n\n"
                    'Jawab JSON: {"achieved": true|false, "confidence": 0.0-1.0, '
                    '"achieved_partially": true|false, "gaps": ["..."], "summary": "..."}'
                )},
            ],
            temperature=0.0, max_tokens=300,
            default={"achieved": False, "confidence": 0.0, "gaps": ["Verifikasi tidak dapat dijalankan"], "summary": ""},
        )

    # ─── 5. SUMMARIZE ─────────────────────────────────────────────────────────

    async def summarize_execution(self, goal: str, observations: list[dict], verification: dict) -> str:
        """Buat ringkasan eksekusi yang bisa dibaca user."""
        obs_str = "\n".join(
            f"- Step {o.get('step_no', '?')}: {o.get('description', '')} → {'✓' if o.get('success') else '✗'}"
            for o in observations
        )
        achieved = verification.get("achieved", False)
        gaps = verification.get("gaps", [])
        gap_str = "\n".join(f"- {g}" for g in gaps) if gaps else ""

        status_emoji = "✅" if achieved else ("⚠️" if verification.get("achieved_partially") else "❌")
        parts = [
            f"{status_emoji} **{goal}**",
            "",
            "**Langkah yang dijalankan:**",
            obs_str,
        ]
        if gap_str:
            parts += ["", "**Yang belum selesai:**", gap_str]
        if verification.get("summary"):
            parts += ["", verification["summary"]]

        return "\n".join(parts)

    # ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────

    async def execute(
        self,
        goal: str,
        *,
        tool_ctx: dict | None = None,
        bot_id: str | None = None,
    ) -> ActionExecutionResult:
        """
        Jalankan pipeline eksekusi penuh untuk satu goal.

        Returns ActionExecutionResult yang berisi status, plan, observations,
        verification, dan summary.
        """
        execution_id = str(uuid.uuid4())[:12]
        started_total = time.perf_counter()
        tool_ctx = tool_ctx or {}

        # ── 1. Understand ─────────────────────────────────────────────
        understanding = await self.understand_goal(goal)
        domain = understanding.get("domain", "mixed")

        # ── 2. Plan ───────────────────────────────────────────────────
        plan = await self.plan_goal(goal, domain=domain)

        # ── 3. Execute & Observe ───────────────────────────────────────
        observations: list[dict] = []
        pending_approvals: list[dict] = []

        for step in plan.steps:
            obs = {
                "step_no": step.step_no,
                "description": step.description,
                "action_type": step.action_type,
                "tool": step.tool,
            }

            if step.requires_approval:
                pending_approvals.append({
                    "step_no": step.step_no,
                    "description": step.description,
                    "action_type": step.action_type,
                    "params": step.params,
                })
                obs["status"] = "pending_approval"
                obs["success"] = False
                observations.append(obs)
                continue

            # Jalankan dengan recovery
            result = await self._recovery.with_retry(
                self._execute_step, step,
                tool_ctx=tool_ctx,
                action_type=step.action_type,
            )

            obs["status"] = step.status
            obs["success"] = step.status == "completed"
            obs["error"] = step.error or None
            obs["duration_ms"] = step.duration_ms

            if step.status == "pending_approval":
                pending_approvals.append({
                    "step_no": step.step_no,
                    "description": step.description,
                    "action_type": step.action_type,
                    "params": step.params,
                    "log_id": result.get("log_id"),
                })

            # Masukkan preview hasil (bukan full output — jaga token)
            if result.get("success"):
                preview = {}
                for k in ["text", "file_url", "path", "final_url", "rows", "summary", "answer"]:
                    if k in result:
                        val = result[k]
                        preview[k] = str(val)[:500] if isinstance(val, str) else val
                obs["result_preview"] = preview
            else:
                obs["result_preview"] = {"error": result.get("error", "")}

            observations.append(obs)

            # Stop jika terlalu banyak kegagalan berturut-turut
            consecutive_failures = sum(1 for o in observations[-3:] if not o.get("success"))
            if consecutive_failures >= 3:
                logger.warning("action_executor: 3 kegagalan berturut-turut, stop eksekusi")
                break

        # ── 4. Verify ─────────────────────────────────────────────────
        verification = await self.verify_goal(goal, observations)

        # ── 5. Summarize ──────────────────────────────────────────────
        summary = await self.summarize_execution(goal, observations, verification)

        # ── 6. Determine final status ─────────────────────────────────
        if pending_approvals:
            status = "pending_approval"
        elif verification.get("achieved"):
            status = "completed"
        elif verification.get("achieved_partially"):
            status = "partial"
        else:
            status = "failed"

        duration_ms = int((time.perf_counter() - started_total) * 1000)

        # ── 7. Persist ────────────────────────────────────────────────
        exec_id = await self._persist(
            execution_id=execution_id,
            goal=goal,
            status=status,
            plan=[{"step_no": s.step_no, "description": s.description, "action_type": s.action_type} for s in plan.steps],
            observations=observations,
            verification=verification,
            summary=summary,
            duration_ms=duration_ms,
            bot_id=bot_id,
        )

        await self._memory.save_to_db()

        return ActionExecutionResult(
            execution_id=exec_id or execution_id,
            goal=goal,
            status=status,
            plan=[{"step_no": s.step_no, "description": s.description, "action_type": s.action_type, "tool": s.tool}
                  for s in plan.steps],
            observations=observations,
            verification=verification,
            summary=summary,
            duration_ms=duration_ms,
            pending_approvals=pending_approvals,
        )

    async def _persist(
        self,
        *,
        execution_id: str,
        goal: str,
        status: str,
        plan: list[dict],
        observations: list[dict],
        verification: dict,
        summary: str,
        duration_ms: int,
        bot_id: str | None,
    ) -> str | None:
        try:
            row = await self._pool.fetchrow(
                """INSERT INTO agent_action_executions
                   (id, org_id, bot_id, goal, status, plan, observations,
                    verification, summary, duration_ms, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10,NOW())
                   RETURNING id""",
                execution_id, self._org_id, bot_id, goal, status,
                json.dumps(plan), json.dumps(observations, default=str),
                json.dumps(verification), summary, duration_ms,
            )
            return str(row["id"]) if row else None
        except Exception as e:
            logger.debug("action_executor._persist gagal: %s", e)
            return None


# ─── Calculator tool ──────────────────────────────────────────────────────────

def _eval_math(expression: str) -> dict:
    """Evaluasi ekspresi matematika sederhana dengan aman."""
    import ast
    import operator

    _SAFE_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos,
    }

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Tipe tidak didukung")
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Operator tidak didukung: {type(node.op).__name__}")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Operator unary tidak didukung")
            return op(_eval(node.operand))
        raise ValueError(f"Ekspresi tidak didukung: {type(node).__name__}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree.body)
        return {"success": True, "expression": expression, "result": result}
    except Exception as e:
        return {"success": False, "error": f"Evaluasi gagal: {e}", "expression": expression}


# ─── Schema SQL ───────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_action_executions (
    id            TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    org_id        UUID NOT NULL,
    bot_id        UUID,
    goal          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'completed',
    plan          JSONB NOT NULL DEFAULT '[]',
    observations  JSONB NOT NULL DEFAULT '[]',
    verification  JSONB NOT NULL DEFAULT '{}',
    summary       TEXT,
    duration_ms   INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_action_exec_org
    ON agent_action_executions(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_action_exec_status
    ON agent_action_executions(org_id, status, created_at DESC);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    try:
        await pool.execute(SCHEMA_SQL)
    except Exception as e:
        logger.warning("action_executor.ensure_schema: %s", e)
