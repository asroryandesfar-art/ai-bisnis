"""task_runtime.runner — DurableJobRunner (P0-D D2/D3).

Menjalankan SATU job sebagai langkah-langkah ber-checkpoint sehingga tahan crash
(resume dari step terakhir) & bisa cancel/pause secara cooperative:

    plan -> subtask×N -> verify -> report(+persist)

Setiap step menyimpan `checkpoint` = SELURUH state kumulatif → resume cukup memuat
step 'done' terakhir. Runner me-reuse primitif agent (`_call_llm_json` /
`_call_llm_with_tools`) & `task_engine._persist_task_execution` supaya baris final
`agent_task_executions` IDENTIK dengan jalur inline lama (tak menyentuh task_engine).

Event bus (P0-C) diterbitkan di batas job (TaskStarted/Finished/Failed) — best-effort.
Jalur inline lama (`task_engine.run_agent_task`) TIDAK diubah.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

import tool_executor

# Fase runner (urutan). Jumlah step dinamis (subtask bisa banyak).
_PHASE_PLAN = "plan"
_PHASE_SUBTASK = "subtask"
_PHASE_VERIFY = "verify"
_PHASE_REPORT = "report"


class JobStopped(Exception):
    """Sinyal internal: job dihentikan cooperative (cancel/pause) di boundary."""
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


class DurableJobRunner:
    def __init__(self, repo, *, agent_builder: Callable[[str, dict], object]):
        """`agent_builder(agent_name, ctx) -> BaseAgent` diinjeksi supaya testable
        (produksi: agent_registry.build_agent)."""
        self.repo = repo
        self._build_agent = agent_builder

    async def run(self, pool, job: dict, *, owner: str = "runner",
                  publish: Callable[..., Awaitable] | None = None) -> str:
        """Jalankan job sampai completed/cancelled/paused/failed/dead_letter.
        Return status akhir. Idempoten terhadap resume (skip step yang sudah 'done')."""
        job_id, org_id = job["id"], job["org_id"]
        await self._emit(publish, "TaskStarted", job)

        # ── Resume: muat state dari checkpoint step 'done' terakhir ──────────
        last = await self.repo.latest_done_step(pool, job_id)
        state = dict(last["checkpoint"]) if last and last.get("checkpoint") else {}
        next_seq = (last["seq"] + 1) if last else 0
        phase = state.get("_phase", _PHASE_PLAN)

        agent = self._build_agent(job["agent_name"], job.get("ctx") or {})
        goal = job["goal"]
        tool_ctx = self._tool_ctx(agent, pool, org_id, job.get("bot_id"), job.get("ctx") or {})
        available_tools = list(getattr(agent, "tools", []) or [])
        step_timeout = int(job.get("step_timeout_s") or 120)

        try:
            # ── PLAN ────────────────────────────────────────────────────────
            if phase == _PHASE_PLAN:
                await self._boundary(pool, job_id, org_id)
                plan = await self._with_timeout(self._plan(agent, goal, available_tools), step_timeout)
                subtasks = plan["subtasks"]
                relevant_tools = plan["relevant_tools"]
                state.update({"_phase": _PHASE_SUBTASK, "plan": {"subtasks": subtasks, "relevant_tools": relevant_tools},
                              "subtasks": subtasks, "relevant_tools": relevant_tools,
                              "subtask_results": [], "all_tool_calls": [], "sub_i": 0})
                next_seq = await self._save(pool, job_id, next_seq, _PHASE_PLAN, state, output=plan)
                await self._progress(pool, job_id, state)
                phase = _PHASE_SUBTASK

            # ── SUBTASKS (satu step per subtask; resume dari sub_i) ─────────
            if phase == _PHASE_SUBTASK:
                subtasks = state["subtasks"]
                tool_schemas = tool_executor.available_tool_schemas(state["relevant_tools"])
                while state.get("sub_i", 0) < len(subtasks):
                    await self._boundary(pool, job_id, org_id)
                    i = state["sub_i"]
                    exec_result = await self._with_timeout(
                        self._run_subtask(agent, goal, subtasks[i], tool_schemas, tool_ctx), step_timeout)
                    state["subtask_results"].append({"subtask": subtasks[i], "answer": exec_result["final_answer"]})
                    state["all_tool_calls"].extend(exec_result["tool_calls"])
                    state["sub_i"] = i + 1
                    next_seq = await self._save(pool, job_id, next_seq, _PHASE_SUBTASK, state,
                                                tool_calls=exec_result["tool_calls"])
                    await self._progress(pool, job_id, state)
                state["_phase"] = _PHASE_VERIFY
                phase = _PHASE_VERIFY

            # ── VERIFY ──────────────────────────────────────────────────────
            report = "\n".join(f"- {r['subtask']}: {r['answer']}" for r in state["subtask_results"])
            if phase == _PHASE_VERIFY:
                await self._boundary(pool, job_id, org_id)
                verification = await self._with_timeout(
                    self._verify(agent, goal, report, state["all_tool_calls"]), step_timeout)
                state["verification"] = verification
                state["_phase"] = _PHASE_REPORT
                next_seq = await self._save(pool, job_id, next_seq, _PHASE_VERIFY, state, output=verification)
                phase = _PHASE_REPORT

            # ── REPORT + persist final (agent_task_executions) ─────────────
            verification = state.get("verification", {})
            verified = bool(verification.get("verified"))
            status = "completed" if verified else "failed"
            import task_engine
            saved = await task_engine._persist_task_execution(pool, {
                "org_id": org_id, "bot_id": job.get("bot_id"), "agent_name": agent.name, "goal": goal,
                "plan": state.get("plan", {}), "tool_calls": state.get("all_tool_calls", []),
                "verification": verification, "report": report, "status": status,
            })
            await self._save(pool, job_id, next_seq, _PHASE_REPORT, {**state, "_phase": _PHASE_REPORT},
                             output={"execution_id": str(saved["id"])})
            final = "completed" if verified else self._retry_or_dlq(job)
            await self.repo.set_status(pool, job_id, final, progress_pct=100,
                                       result_execution_id=str(saved["id"]),
                                       last_error=None if verified else "verification gagal")
            await self._emit(publish, "TaskFinished" if verified else "TaskFailed", job)
            return final

        except JobStopped as stop:
            return stop.status
        except Exception as exc:                       # error tak terduga → retry/DLQ
            final = self._retry_or_dlq(job)
            await self.repo.set_status(pool, job_id, final, last_error=str(exc)[:500])
            await self._emit(publish, "TaskFailed", job)
            return final

    # ── boundary cancel/pause (cooperative) ─────────────────────────────────
    async def _boundary(self, pool, job_id, org_id):
        cur = await self.repo.get(pool, job_id, org_id=org_id)
        st = (cur or {}).get("status")
        if st == "cancelling":
            await self.repo.set_status(pool, job_id, "cancelled")
            raise JobStopped("cancelled")
        if st == "pausing":
            await self.repo.set_status(pool, job_id, "paused")
            raise JobStopped("paused")

    def _retry_or_dlq(self, job) -> str:
        return "dead_letter" if int(job.get("attempts", 0)) >= int(job.get("max_attempts", 3)) else "queued"

    async def _save(self, pool, job_id, seq, kind, state, *, output=None, tool_calls=None) -> int:
        await self.repo.save_step(pool, job_id=job_id, seq=seq, kind=kind, status="done",
                                  checkpoint=state, output=output, tool_calls=tool_calls)
        return seq + 1

    async def _progress(self, pool, job_id, state):
        subs = state.get("subtasks") or []
        total = len(subs) + 3                          # plan + subtasks + verify + report
        done = 1 + int(state.get("sub_i", 0)) + (1 if state.get("_phase") in (_PHASE_REPORT,) else 0)
        pct = max(0, min(99, int(done / max(total, 1) * 100)))
        await self.repo.set_status(pool, job_id, "running", progress_pct=pct)

    async def _with_timeout(self, coro, timeout_s):
        return await asyncio.wait_for(coro, timeout=timeout_s)

    async def _emit(self, publish, event_type, job):
        if publish is None:
            return
        try:
            await publish(event_type, {"job_id": job["id"], "agent": job.get("agent_name")},
                          org_id=job.get("org_id"))
        except Exception:
            pass

    # ── tahap (reuse primitif agent; sejajar task_engine, tak menyentuhnya) ─
    def _tool_ctx(self, agent, pool, org_id, bot_id, ctx):
        extra = dict(ctx or {})
        return {"pool": pool, "org_id": org_id, "bot_id": bot_id, "agent_name": agent.name,
                "groq_api_key": extra.pop("groq_api_key", getattr(agent, "api_key", None)),
                "groq_model": extra.pop("groq_model", getattr(agent, "model", None)),
                "groq_base_url": extra.pop("groq_base_url", getattr(agent, "base_url", None)),
                **extra}

    async def _plan(self, agent, goal, available_tools) -> dict:
        out = await agent._call_llm_json(
            [{"role": "system", "content": f"Kamu adalah {agent.name}. Tools tersedia: {available_tools or 'tidak ada'}."},
             {"role": "user", "content": (
                 f"Goal: {goal}\n\nPecah goal jadi 1-4 subtask konkret (urutan logis) & sebutkan tool relevan.\n"
                 'Jawab HANYA JSON: {"subtasks": ["..."], "relevant_tools": ["..."]}')}],
            temperature=0.1, max_tokens=400,
            default={"subtasks": [goal], "relevant_tools": available_tools})
        subtasks = out.get("subtasks") or [goal]
        if not isinstance(subtasks, list) or not subtasks:
            subtasks = [goal]
        relevant = [t for t in (out.get("relevant_tools") or available_tools) if t in available_tools]
        return {"subtasks": subtasks, "relevant_tools": relevant}

    async def _run_subtask(self, agent, goal, subtask, tool_schemas, tool_ctx) -> dict:
        return await agent._call_llm_with_tools(
            [{"role": "system", "content": (
                f"Kamu adalah {agent.name} yang mengerjakan satu subtask dari sebuah goal. Gunakan tools bila "
                "perlu data nyata, lalu jawab subtask dengan kalimat biasa.")},
             {"role": "user", "content": f"Goal keseluruhan: {goal}\n\nSubtask sekarang: {subtask}"}],
            tools=tool_schemas, tool_ctx=tool_ctx)

    async def _verify(self, agent, goal, report, all_tool_calls) -> dict:
        return await agent._call_llm_json(
            [{"role": "system", "content": (
                "Kamu verifier internal. Nilai jujur apakah laporan benar-benar menjawab goal berdasar "
                "tool_calls yang benar-benar dieksekusi.")},
             {"role": "user", "content": (
                 f"Goal: {goal}\n\nLaporan:\n{report}\n\n"
                 f"Tool calls: {json.dumps(all_tool_calls, ensure_ascii=True, default=str)[:3000]}\n\n"
                 'Jawab HANYA JSON: {"verified": true|false, "reasoning": "..."}')}],
            temperature=0.0, max_tokens=300,
            default={"verified": False, "reasoning": "Verifikasi LLM gagal."})
