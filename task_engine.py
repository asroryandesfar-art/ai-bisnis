"""
task_engine.py — Task Engine runtime (AI Workforce Phase 2).

Implementasi nyata diagram yang diminta:

    Goal -> Plan -> Subtasks -> Tool Selection -> Execution -> Verification -> Report

`run_agent_task()` BUKAN tambahan jalur ke-2 yang menyaingi pola
intent-classify-then-dispatch yang sudah ACTIVE di tiap domain agent
(`finance_agent.parse_intent()` dkk, termasuk Sales Agent yang sudah
organik dipakai) -- ini pintu masuk BARU untuk goal bebas/multi-step yang
butuh tool, dipanggil lewat method `run_task()` yang ditambahkan ke
masing-masing agent (lihat Phase 3). Setiap pemanggilan menghasilkan satu
baris `agent_task_executions` (lihat bn_platform/schema_platform.sql §10j)
-- log execution history nyata, bukan klaim.
"""
from __future__ import annotations

import json

import asyncpg

import tool_executor
from base import BaseAgent


async def run_agent_task(
    agent: BaseAgent,
    goal: str,
    *,
    pool: asyncpg.Pool,
    org_id: str,
    bot_id: str | None = None,
    ctx: dict | None = None,
) -> dict:
    """Jalankan satu goal bebas lewat agent tertentu, end-to-end, dan
    persist hasilnya. `ctx` opsional: end_user_id, searxng_url,
    search_api_key, groq_api_key/groq_model/groq_base_url (dipakai
    browser_open/browser_extract -- default ke kredensial agent sendiri
    kalau tidak dikirim)."""
    extra_ctx = dict(ctx or {})
    tool_ctx = {
        "pool": pool, "org_id": org_id, "bot_id": bot_id,
        "groq_api_key": extra_ctx.pop("groq_api_key", agent.api_key),
        "groq_model": extra_ctx.pop("groq_model", agent.model),
        "groq_base_url": extra_ctx.pop("groq_base_url", agent.base_url),
        **extra_ctx,
    }
    available_tools = list(getattr(agent, "tools", []) or [])

    # ── 1. PLAN: pecah goal jadi subtask + tool relevan ──────────
    plan = await agent._call_llm_json(
        [
            {"role": "system", "content": (
                f"Kamu adalah {agent.name}. Tools yang tersedia untukmu: {available_tools or 'tidak ada'}."
            )},
            {"role": "user", "content": (
                f"Goal: {goal}\n\n"
                "Pecah goal ini jadi 1-4 subtask konkret (urutan logis), dan sebutkan tool mana "
                "saja (dari daftar tools tersedia di atas) yang relevan untuk menyelesaikannya. "
                'Jawab HANYA JSON: {"subtasks": ["..."], "relevant_tools": ["..."]}'
            )},
        ],
        temperature=0.1, max_tokens=400,
        default={"subtasks": [goal], "relevant_tools": available_tools},
    )
    subtasks = plan.get("subtasks") or [goal]
    if not isinstance(subtasks, list) or not subtasks:
        subtasks = [goal]
    relevant_tools = [t for t in (plan.get("relevant_tools") or available_tools) if t in available_tools]
    tool_schemas = tool_executor.available_tool_schemas(relevant_tools)

    # ── 2/3. SUBTASKS -> TOOL SELECTION -> EXECUTION ─────────────
    # Catatan: sengaja TIDAK pakai agent.system_prompt di sini -- itu prompt
    # untuk parse_intent() (mis. FinanceAgent-nya menyuruh "Balas HANYA JSON
    # dengan field: action..."), yang kalau ikut dikirim ke tool-calling loop
    # bikin model bingung antara format tool_call OpenAI-compatible vs format
    # JSON-aksi lama-nya sendiri -- terbukti live menyebabkan Groq menolak
    # generasi tool_call dengan 400 tool_use_failed.
    task_system_prompt = (
        f"Kamu adalah {agent.name} yang sedang mengerjakan satu subtask dari sebuah goal. "
        "Gunakan tools yang tersedia kalau perlu data nyata, lalu jawab subtask ini dengan "
        "kalimat biasa (bukan JSON aksi internal)."
    )
    subtask_results: list[dict] = []
    all_tool_calls: list[dict] = []
    for subtask in subtasks:
        exec_result = await agent._call_llm_with_tools(
            [
                {"role": "system", "content": task_system_prompt},
                {"role": "user", "content": subtask},
            ],
            tools=tool_schemas, tool_ctx=tool_ctx,
        )
        subtask_results.append({"subtask": subtask, "answer": exec_result["final_answer"]})
        all_tool_calls.extend(exec_result["tool_calls"])

    report = "\n".join(f"- {r['subtask']}: {r['answer']}" for r in subtask_results)

    # ── 4. VERIFICATION ───────────────────────────────────────────
    verification = await agent._call_llm_json(
        [
            {"role": "system", "content": (
                "Kamu adalah verifier internal. Nilai jujur apakah laporan di bawah benar-benar "
                "menjawab goal yang diminta, berdasarkan tool_calls yang benar-benar dieksekusi "
                "(jangan anggap berhasil kalau tool_calls menunjukkan error/skipped)."
            )},
            {"role": "user", "content": (
                f"Goal: {goal}\n\nLaporan:\n{report}\n\n"
                f"Tool calls yang dieksekusi: {json.dumps(all_tool_calls, ensure_ascii=True, default=str)[:3000]}\n\n"
                'Jawab HANYA JSON: {"verified": true|false, "reasoning": "..."}'
            )},
        ],
        temperature=0.0, max_tokens=300,
        default={"verified": False, "reasoning": "Verifikasi LLM gagal dijalankan (mis. API key kosong/rate limit)."},
    )
    verified = bool(verification.get("verified"))
    status = "completed" if verified else "failed"

    record = {
        "org_id": org_id, "bot_id": bot_id, "agent_name": agent.name, "goal": goal,
        "plan": {"subtasks": subtasks, "relevant_tools": relevant_tools},
        "tool_calls": all_tool_calls, "verification": verification, "report": report, "status": status,
    }
    saved = await _persist_task_execution(pool, record)
    return {**record, "id": saved["id"], "created_at": str(saved["created_at"])}


async def _persist_task_execution(pool: asyncpg.Pool, record: dict) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO agent_task_executions
           (id, org_id, bot_id, agent_name, goal, plan, tool_calls, verification, report, status, created_at)
           VALUES (uuid_generate_v4(), $1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8,$9,NOW())
           RETURNING id, created_at""",
        record["org_id"], record["bot_id"], record["agent_name"], record["goal"],
        json.dumps(record["plan"]), json.dumps(record["tool_calls"], default=str),
        json.dumps(record["verification"]), record["report"], record["status"],
    )
    return dict(row)
