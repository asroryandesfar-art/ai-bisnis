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

import asyncio
import json
from dataclasses import asdict
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
                "Query data internal tenant sendiri dari tabel yang diizinkan. "
                "Selalu otomatis dibatasi ke org tenant ini saja. filter_value HARUS persis salah satu "
                "nilai enum di bawah (bukan ekspresi SQL seperti \"status = 'x'\"), atau dikosongkan untuk "
                "ambil semua baris terbaru: "
                "finance_invoices (filter by status: draft|sent|paid|overdue|cancelled), "
                "hr_candidates (filter by status: new|screened|interview|offered|hired|rejected), "
                "sales_signals (filter by signal_type: pre_purchase_question|reason_buy|reason_cancel|"
                "objection_price|objection_product|objection_service), "
                "workforce_tasks (filter by status: pending|in_progress|blocked|completed|cancelled|escalated), "
                "conversation_analysis (filter by intent, nilai bebas sesuai intent yang ada di tenant ini)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": ["finance_invoices", "hr_candidates", "sales_signals", "workforce_tasks", "conversation_analysis"],
                    },
                    "filter_value": {"type": "string", "description": "Nilai filter opsional -- persis salah satu enum yang relevan, lihat description tool ini"},
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
    "financial_data": {
        "type": "function",
        "function": {
            "name": "financial_data",
            "description": (
                "Ambil harga crypto/saham real-time (CoinGecko/Yahoo Finance) untuk pertanyaan "
                "harga pasar. Sebutkan nama/simbol aset di query (mis. 'bitcoin', 'AAPL', 'tesla')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Nama/simbol aset crypto atau saham yang ingin dicek harganya"},
                },
                "required": ["query"],
            },
        },
    },
    "news_search": {
        "type": "function",
        "function": {
            "name": "news_search",
            "description": "Cari berita terkini via RSS (Google News) untuk pertanyaan bertopik berita/peristiwa terbaru.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topik/kata kunci berita yang dicari"},
                    "limit": {"type": "integer", "description": "Jumlah maksimum hasil, default 5"},
                },
                "required": ["query"],
            },
        },
    },
    "document_generator": {
        "type": "function",
        "function": {
            "name": "document_generator",
            "description": (
                "Generate dokumen PDF/DOCX/XLSX/PPTX dari struktur judul+bagian/tabel/slide. "
                "Hasilnya berupa file_url yang bisa diunduh."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "enum": ["pdf", "docx", "xlsx", "pptx"]},
                    "title": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "description": "Isi dokumen: daftar bagian heading+body",
                        "items": {
                            "type": "object",
                            "properties": {"heading": {"type": "string"}, "body": {"type": "string"}},
                        },
                    },
                    "table_rows": {
                        "type": "array",
                        "description": "Opsional, untuk data tabular -- baris pertama dianggap header",
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                    "slides": {
                        "type": "array",
                        "description": "Opsional, khusus format pptx",
                        "items": {
                            "type": "object",
                            "properties": {"title": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}}},
                        },
                    },
                },
                "required": ["format", "title"],
            },
        },
    },
    "email_reader": {
        "type": "function",
        "function": {
            "name": "email_reader",
            "description": (
                "Baca email Gmail masuk yang belum dibaca (subjek, pengirim, ringkasan) untuk tenant ini. "
                "Read-only -- tidak menandai email sebagai sudah dibaca, tidak mengirim email keluar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Jumlah maksimum email yang diambil, default 5"},
                },
                "required": [],
            },
        },
    },
    "channel_messaging": {
        "type": "function",
        "function": {
            "name": "channel_messaging",
            "description": (
                "Kirim pesan ke pelanggan lewat WhatsApp/Telegram/Instagram/Facebook. "
                "PENTING: pesan TIDAK langsung terkirim -- akan menunggu approval staf tenant dulu "
                "sebelum benar-benar dikirim (safety gate, sama seperti aksi tulis Computer Agent)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": ["whatsapp", "telegram", "instagram", "facebook"]},
                    "recipient": {"type": "string", "description": "ID/nomor penerima pesan, sesuai channel"},
                    "message": {"type": "string", "description": "Isi pesan yang ingin dikirim"},
                },
                "required": ["channel", "recipient", "message"],
            },
        },
    },
    # ── AI Agent Platform Tools ──────────────────────────────────────────────
    "calculator": {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluasi ekspresi matematika (aritmatika, pangkat, modulo). Aman, tidak bisa menjalankan kode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Ekspresi matematika, contoh: '(150 * 1.11) / 12'"},
                },
                "required": ["expression"],
            },
        },
    },
    "terminal_execute": {
        "type": "function",
        "function": {
            "name": "terminal_execute",
            "description": (
                "Eksekusi shell command di server (git, npm, python, docker, dll). "
                "WAJIB izin run_terminal. Command berbahaya (rm -rf, dll) butuh approval tambahan. "
                "Return: stdout, stderr, exit_code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command yang akan dieksekusi"},
                    "timeout": {"type": "integer", "description": "Timeout dalam detik (default 60, maks 300)"},
                    "approval_granted": {"type": "boolean", "description": "Set true jika sudah ada approval eksplisit untuk command berbahaya"},
                },
                "required": ["command"],
            },
        },
    },
    "file_read": {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Baca isi file dari filesystem (bukan knowledge base). Mendukung txt, md, py, ts, js, json, yaml, dll. Butuh izin read_files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path absolut atau relatif ke file"},
                },
                "required": ["path"],
            },
        },
    },
    "file_write": {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Tulis/buat file baru di filesystem. Butuh izin write_files. Belum ada: butuh approval dulu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path file yang akan ditulis"},
                    "content": {"type": "string", "description": "Isi file yang akan ditulis"},
                    "overwrite": {"type": "boolean", "description": "Izinkan overwrite jika file sudah ada (default false)"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "file_list": {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "Daftar file dan folder dalam direktori. Butuh izin read_files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path direktori yang ingin dilihat isinya"},
                    "pattern": {"type": "string", "description": "Filter nama file (glob pattern, contoh: '*.py')"},
                    "recursive": {"type": "boolean", "description": "Cari secara rekursif ke subdirektori"},
                },
                "required": ["path"],
            },
        },
    },
    "webhook_call": {
        "type": "function",
        "function": {
            "name": "webhook_call",
            "description": "Panggil webhook atau REST API eksternal (HTTP GET/POST/PUT/PATCH). SSRF-safe (hanya URL publik).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL endpoint yang akan dipanggil"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method"},
                    "payload": {"type": "object", "description": "Body request (JSON)"},
                    "headers": {"type": "object", "description": "Header HTTP tambahan"},
                },
                "required": ["url"],
            },
        },
    },
    "action_execute": {
        "type": "function",
        "function": {
            "name": "action_execute",
            "description": (
                "Jalankan goal bisnis multi-langkah via Action Executor pipeline. "
                "Pipeline otomatis: Plan → Permission Check → Execute → Verify → Report. "
                "Gunakan untuk goal kompleks yang butuh beberapa tool sekaligus."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Deskripsi goal yang ingin dicapai, sedetail mungkin"},
                },
                "required": ["goal"],
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


async def _exec_financial_data(args: dict, ctx: dict) -> dict:
    import finance_fetcher as ff
    query = args.get("query", "")
    crypto, stocks = await asyncio.gather(ff.fetch_crypto_quotes(query), ff.fetch_stock_quotes(query))
    if not crypto and not stocks:
        return {"success": False, "error": "Tidak ada simbol crypto/saham yang dikenali dari query ini"}
    return {
        "success": True, "summary": ff.combine_market_answers(crypto, stocks),
        "crypto": [asdict(q) for q in crypto], "stocks": [asdict(q) for q in stocks],
    }


async def _exec_news_search(args: dict, ctx: dict) -> dict:
    from news_fetcher import search_news
    query = args.get("query", "")
    limit = args.get("limit") or 5
    items = await search_news(query, limit=limit)
    return {"success": True, "results": [
        {"title": it.title, "link": it.link, "source": it.source, "published": it.published, "summary": it.summary}
        for it in items
    ]}


async def _exec_document_generator(args: dict, ctx: dict) -> dict:
    import document_generator as dg
    import storage_backend
    fmt = (args.get("format") or "pdf").strip().lower()
    spec = dg.normalize_spec(args, fallback_title=args.get("title") or "Dokumen")
    file_bytes, _content_type = dg.generate_document(fmt, spec)
    _, url = storage_backend.save_bytes("agent-task-documents", file_bytes, ext=f".{fmt}")
    pool = ctx.get("pool")
    if pool is not None:
        try:
            await pool.execute(
                """INSERT INTO generated_documents (org_id, bot_id, user_id, format, title, prompt, file_url, status)
                   VALUES ($1,$2,NULL,$3,$4,$5,$6,'completed')""",
                ctx["org_id"], ctx.get("bot_id"), fmt, spec["title"], "Dibuat lewat Task Engine (agent)", url,
            )
        except Exception:
            pass
    return {"success": True, "file_url": url, "format": fmt, "title": spec["title"]}


async def _exec_email_reader(args: dict, ctx: dict) -> dict:
    from main import _get_integrations_auto, _gmail_get_access_token, _gmail_list_unread, _gmail_get_message
    pool = ctx["pool"]
    org_id = ctx["org_id"]
    max_results = max(1, min(20, args.get("max_results") or 5))

    integ = await _get_integrations_auto(pool, str(org_id))
    gmail = dict(integ.get("gmail") or {})
    access_token = (gmail.get("access_token") or "").strip()
    refresh_token = (gmail.get("refresh_token") or "").strip()
    if not (access_token or refresh_token):
        return {"success": False, "error": "Gmail belum terhubung untuk tenant ini"}

    token = await _gmail_get_access_token(access_token, refresh_token)
    msg_ids = await _gmail_list_unread(token, max_results=max_results)
    emails = []
    for mid in msg_ids:
        m = await _gmail_get_message(token, mid)
        headers = {h.get("name", "").lower(): h.get("value", "") for h in (m.get("payload", {}).get("headers") or [])}
        emails.append({
            "id": mid,
            "subject": headers.get("subject", "").strip(),
            "from": headers.get("from", "").strip(),
            "snippet": (m.get("snippet") or "").strip(),
        })
    return {"success": True, "unread_count": len(emails), "emails": emails}


async def _exec_channel_messaging(args: dict, ctx: dict) -> dict:
    """TIDAK PERNAH mengirim langsung -- hanya membuat baris pending_approval.
    Pengiriman sungguhan hanya lewat channel_messaging.approve_task() setelah
    manusia menyetujui (lihat docstring modul channel_messaging.py)."""
    import channel_messaging as cm
    pool = ctx["pool"]
    task = await cm.create_task(
        pool, org_id=ctx["org_id"], bot_id=ctx.get("bot_id"), agent_name=ctx.get("agent_name", "unknown"),
        channel=args.get("channel", ""), recipient=args.get("recipient", ""), message=args.get("message", ""),
    )
    return {
        "success": True, "status": "pending_approval", "task_id": str(task["id"]),
        "note": "Pesan BELUM terkirim -- menunggu approval staf tenant sebelum benar-benar dikirim ke pelanggan.",
    }


async def _exec_calculator(args: dict, ctx: dict) -> dict:
    from action_executor import _eval_math
    return _eval_math(args.get("expression", ""))


async def _exec_terminal_execute(args: dict, ctx: dict) -> dict:
    """Eksekusi terminal command via TerminalService dengan permission gate."""
    from terminal_service import TerminalService
    from permission_manager import PermissionManager
    pool = ctx["pool"]
    org_id = str(ctx["org_id"])
    pm = PermissionManager(pool, org_id)
    svc = TerminalService(pool, org_id, pm, agent_name=ctx.get("agent_name", "tool_executor"),
                          working_dir=ctx.get("working_dir"))
    return await svc.execute(
        args.get("command", ""),
        timeout=int(args.get("timeout", 60)),
        approval_granted=bool(args.get("approval_granted", False)),
    )


async def _exec_file_read(args: dict, ctx: dict) -> dict:
    """Baca file real via FileSystemService."""
    from file_system_service import FileSystemService
    from permission_manager import PermissionManager
    pool = ctx["pool"]
    org_id = str(ctx["org_id"])
    pm = PermissionManager(pool, org_id)
    svc = FileSystemService(pool, org_id, pm, agent_name=ctx.get("agent_name", "tool_executor"),
                            allowed_base_dir=ctx.get("allowed_base_dir"))
    return await svc.read_file(args.get("path", ""))


async def _exec_file_write(args: dict, ctx: dict) -> dict:
    """Tulis file real via FileSystemService (butuh izin write_files)."""
    from file_system_service import FileSystemService
    from permission_manager import PermissionManager
    pool = ctx["pool"]
    org_id = str(ctx["org_id"])
    pm = PermissionManager(pool, org_id)
    svc = FileSystemService(pool, org_id, pm, agent_name=ctx.get("agent_name", "tool_executor"),
                            allowed_base_dir=ctx.get("allowed_base_dir"))
    return await svc.write_file(args.get("path", ""), args.get("content", ""),
                                overwrite=bool(args.get("overwrite", False)))


async def _exec_file_list(args: dict, ctx: dict) -> dict:
    """Daftar file dalam direktori via FileSystemService."""
    from file_system_service import FileSystemService
    from permission_manager import PermissionManager
    pool = ctx["pool"]
    org_id = str(ctx["org_id"])
    pm = PermissionManager(pool, org_id)
    svc = FileSystemService(pool, org_id, pm, agent_name=ctx.get("agent_name", "tool_executor"),
                            allowed_base_dir=ctx.get("allowed_base_dir"))
    return await svc.list_directory(args.get("path", "."), pattern=args.get("pattern", "*"),
                                    recursive=bool(args.get("recursive", False)))


async def _exec_webhook_call(args: dict, ctx: dict) -> dict:
    """Panggil webhook/REST API eksternal via HTTP."""
    import httpx
    from tool_registry import _validate_url
    url = args.get("url", "")
    ok, reason = _validate_url(url)
    if not ok:
        return {"success": False, "error": f"URL tidak valid: {reason}"}
    method = (args.get("method") or "POST").upper()
    payload = args.get("payload") or {}
    headers = {"Content-Type": "application/json", **(args.get("headers") or {})}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, json=payload, headers=headers)
        return {
            "success": resp.status_code < 400,
            "status_code": resp.status_code,
            "response": resp.text[:2000],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _exec_action_execute(args: dict, ctx: dict) -> dict:
    """Jalankan goal bebas via ActionExecutor pipeline."""
    from action_executor import ActionExecutor
    from base import BaseAgent
    pool = ctx["pool"]
    org_id = str(ctx["org_id"])
    api_key = ctx.get("groq_api_key", "")
    model = ctx.get("groq_model")
    base_url = ctx.get("groq_base_url")
    agent = BaseAgent(api_key=api_key, model=model, base_url=base_url)
    executor = ActionExecutor(agent, pool, org_id)
    result = await executor.execute(args.get("goal", ""), tool_ctx=ctx, bot_id=ctx.get("bot_id"))
    return result.to_dict()


_EXECUTORS: dict[str, Callable[[dict, dict], Awaitable[dict]]] = {
    "knowledge_search": _exec_knowledge_search,
    "memory_lookup": _exec_memory_lookup,
    "file_reader": _exec_file_reader,
    "database_query": _exec_database_query,
    "web_search": _exec_web_search,
    "browser_open": _exec_browser_open,
    "browser_extract": _exec_browser_extract,
    "financial_data": _exec_financial_data,
    "news_search": _exec_news_search,
    "document_generator": _exec_document_generator,
    "email_reader": _exec_email_reader,
    "channel_messaging": _exec_channel_messaging,
    # AI Agent Platform extensions
    "calculator": _exec_calculator,
    "terminal_execute": _exec_terminal_execute,
    "file_read": _exec_file_read,
    "file_write": _exec_file_write,
    "file_list": _exec_file_list,
    "webhook_call": _exec_webhook_call,
    "action_execute": _exec_action_execute,
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
