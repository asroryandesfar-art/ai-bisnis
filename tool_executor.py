"""
tool_executor.py — Tool Framework runtime (AI Workforce Phase 2).

Beda dengan `tool_registry.py` (katalog PASIF, dokumentasi "tool apa yang
tersedia" untuk dibaca manusia/kode lain): modul ini punya 2 hal yang
sebelumnya TIDAK ADA di codebase manapun --
  1. `TOOL_SCHEMAS` -- skema JSON gaya OpenAI/Groq function-calling, yang
     benar-benar dikirim ke LLM lewat `BaseAgent._call_llm_with_tools()`
     (lihat base.py) supaya model bisa MEMILIH SENDIRI tool mana yang
     dipanggil (bukan dispatch if/else manual berbasis intent-classify).
  2. `execute_tool()` -- eksekutor REAL untuk setiap tool, semua membungkus
     implementasi yang SUDAH ADA dan SUDAH terbukti jalan (Computer Agent,
     `main._retrieve_chunks`, `memory_agent.MemoryStore`, dst) -- tidak ada
     satu pun yang mock/placeholder. Tool yang genuinely belum dikonfigurasi
     (mis. `web_search` tanpa SEARXNG_URL) mengembalikan error/skipped yang
     jujur, BUKAN hasil palsu.

ctx (dict) yang wajib dikirim caller ke `execute_tool()`:
  pool, org_id (wajib semua tool) -- bot_id, end_user_id (tool tertentu)
  -- groq_api_key/groq_model/groq_base_url (browser_open/browser_extract,
  butuh LLM sendiri untuk planning Computer Agent).
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import asyncpg

TOOL_SCHEMAS: dict[str, dict] = {
    "knowledge_search": {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "Cari informasi di knowledge base tenant (dokumen/FAQ/SOP yang sudah diupload ke BotNesia).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Kata kunci atau pertanyaan yang dicari"}},
                "required": ["query"],
            },
        },
    },
    "memory_lookup": {
        "type": "function",
        "function": {
            "name": "memory_lookup",
            "description": "Ambil profil/fakta tersimpan dan ringkasan percakapan sebelumnya untuk satu end-user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "end_user_id": {"type": "string", "description": "ID end-user yang ingin dilihat memorinya"},
                },
                "required": ["end_user_id"],
            },
        },
    },
    "file_reader": {
        "type": "function",
        "function": {
            "name": "file_reader",
            "description": "Baca isi satu dokumen yang sudah di-ingest ke knowledge base tenant, berdasarkan document_id.",
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "UUID dokumen di knowledge base tenant"}},
                "required": ["document_id"],
            },
        },
    },
    "database_query": {
        "type": "function",
        "function": {
            "name": "database_query",
            "description": (
                "Query data internal tenant sendiri dari tabel yang diizinkan: "
                "finance_invoices, hr_candidates, sales_signals, workforce_tasks, conversation_analysis. "
                "Selalu otomatis dibatasi ke org tenant ini saja."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": ["finance_invoices", "hr_candidates", "sales_signals", "workforce_tasks", "conversation_analysis"],
                    },
                    "filter_value": {"type": "string", "description": "Nilai filter opsional (lihat filter_column yang diizinkan per tabel)"},
                },
                "required": ["table"],
            },
        },
    },
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Pencarian web umum (search engine) untuk topik di luar berita/finansial/dokumen tenant.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    "browser_open": {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": "Buka sebuah URL di browser sungguhan, baca teksnya, dan ambil screenshot halaman.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL lengkap yang ingin dibuka"}},
                "required": ["url"],
            },
        },
    },
    "browser_extract": {
        "type": "function",
        "function": {
            "name": "browser_extract",
            "description": "Buka sebuah URL dan ekstrak informasi spesifik sesuai instruksi (mis. 'ambil 5 judul artikel terbaru').",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "instruction": {"type": "string", "description": "Apa yang harus diekstrak dari halaman tersebut"},
                },
                "required": ["url", "instruction"],
            },
        },
    },
}

# table -> (kolom yang boleh dibaca, kolom yang boleh dipakai sebagai filter_value)
_QUERY_ALLOWLIST: dict[str, tuple[list[str], str | None]] = {
    "finance_invoices": (["id", "invoice_number", "customer_name", "amount_idr", "status", "due_date", "created_at"], "status"),
    "hr_candidates": (["id", "name", "position_applied", "score", "status", "created_at"], "status"),
    "sales_signals": (["id", "signal_type", "text_snippet", "resulted_in_purchase", "created_at"], "signal_type"),
    "workforce_tasks": (["id", "domain", "title", "status", "priority", "created_at"], "status"),
    "conversation_analysis": (["conversation_id", "intent", "sentiment_label", "outcome", "quality_score", "analyzed_at"], "intent"),
}


def available_tool_schemas(names: list[str]) -> list[dict]:
    """Subset TOOL_SCHEMAS sesuai nama yang diminta caller (mis. agent.tools)."""
    return [TOOL_SCHEMAS[n] for n in names if n in TOOL_SCHEMAS]


async def _exec_knowledge_search(args: dict, ctx: dict) -> dict:
    from main import _retrieve_chunks  # lazy import: hindari circular (main.py import banyak agent)
    pool: asyncpg.Pool = ctx["pool"]
    chunks = await _retrieve_chunks(pool, ctx["org_id"], args.get("query", ""), bot_id=ctx.get("bot_id"), top_k=5)
    return {"success": True, "results": [{"content": c.get("content", "")[:800], "source": c.get("source_id")} for c in chunks]}


async def _exec_memory_lookup(args: dict, ctx: dict) -> dict:
    from memory_agent import get_memory_store
    pool: asyncpg.Pool = ctx["pool"]
    end_user_id = args.get("end_user_id") or ctx.get("end_user_id")
    if not end_user_id:
        return {"success": False, "error": "end_user_id tidak tersedia"}
    store = get_memory_store()
    profile = await store.get_profile(end_user_id, ctx["org_id"], ctx.get("bot_id", ""), pool=pool)
    return {"success": True, "profile": profile.to_context_string(), "facts_count": len(getattr(profile, "facts", []) or [])}


async def _exec_file_reader(args: dict, ctx: dict) -> dict:
    pool: asyncpg.Pool = ctx["pool"]
    document_id = args.get("document_id", "")
    doc = await pool.fetchrow(
        "SELECT id, filename, summary, status FROM documents WHERE id=$1 AND org_id=$2",
        document_id, ctx["org_id"],
    )
    if not doc:
        return {"success": False, "error": "Dokumen tidak ditemukan di knowledge base tenant ini"}
    chunks = await pool.fetch(
        "SELECT content FROM knowledge_chunks WHERE source_id=$1 AND org_id=$2 ORDER BY created_at LIMIT 20",
        document_id, ctx["org_id"],
    )
    content = "\n\n".join(c["content"] for c in chunks)[:4000]
    return {"success": True, "filename": doc["filename"], "summary": doc["summary"], "content": content}


async def _exec_database_query(args: dict, ctx: dict) -> dict:
    pool: asyncpg.Pool = ctx["pool"]
    table = args.get("table", "")
    if table not in _QUERY_ALLOWLIST:
        return {"success": False, "error": f"Tabel '{table}' tidak diizinkan. Pilihan: {list(_QUERY_ALLOWLIST)}"}
    columns, filter_col = _QUERY_ALLOWLIST[table]
    col_sql = ", ".join(columns)
    filter_value = args.get("filter_value")
    if filter_value and filter_col:
        sql = f"SELECT {col_sql} FROM {table} WHERE org_id=$1 AND {filter_col}=$2 ORDER BY created_at DESC LIMIT 20"
        rows = await pool.fetch(sql, ctx["org_id"], filter_value)
    else:
        sql = f"SELECT {col_sql} FROM {table} WHERE org_id=$1 ORDER BY created_at DESC LIMIT 20"
        rows = await pool.fetch(sql, ctx["org_id"])
    return {"success": True, "table": table, "row_count": len(rows), "rows": [dict(r) for r in rows]}


async def _exec_web_search(args: dict, ctx: dict) -> dict:
    from web_search_agent import search
    return await search(
        args.get("query", ""),
        searxng_url=ctx.get("searxng_url", ""),
        tavily_api_key=ctx.get("search_api_key", ""),
    )


async def _exec_browser_open(args: dict, ctx: dict) -> dict:
    from computer_agent import ComputerAgent
    agent = ComputerAgent(api_key=ctx.get("groq_api_key", ""), model=ctx.get("groq_model"), base_url=ctx.get("groq_base_url"))
    url = args.get("url", "")
    steps = [{"action": "navigate", "target": url}, {"action": "read_text", "target": ""}, {"action": "screenshot", "target": ""}]
    return await agent.execute_read_only(steps)


async def _exec_browser_extract(args: dict, ctx: dict) -> dict:
    from computer_agent import ComputerAgent
    agent = ComputerAgent(api_key=ctx.get("groq_api_key", ""), model=ctx.get("groq_model"), base_url=ctx.get("groq_base_url"))
    goal = f"Buka {args.get('url', '')} lalu {args.get('instruction', 'baca isinya')}"
    steps = await agent.plan_actions(goal)
    return await agent.execute_read_only(steps)


_EXECUTORS: dict[str, Callable[[dict, dict], Awaitable[dict]]] = {
    "knowledge_search": _exec_knowledge_search,
    "memory_lookup": _exec_memory_lookup,
    "file_reader": _exec_file_reader,
    "database_query": _exec_database_query,
    "web_search": _exec_web_search,
    "browser_open": _exec_browser_open,
    "browser_extract": _exec_browser_extract,
}


async def execute_tool(name: str, args: dict, *, ctx: dict) -> dict:
    """Jalankan satu tool nyata. ctx wajib berisi minimal {pool, org_id}."""
    executor = _EXECUTORS.get(name)
    if executor is None:
        return {"success": False, "error": f"Tool '{name}' tidak dikenal"}
    try:
        return await executor(args, ctx)
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def parse_tool_call_args(raw: str) -> dict:
    """Parse argumen JSON dari tool_call LLM dengan aman (tidak pernah raise)."""
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
