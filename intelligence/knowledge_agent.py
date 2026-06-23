"""
intelligence/knowledge_agent.py — KNOWLEDGE GRAPH

Membangun & memperbarui relasi otomatis antar entitas bisnis:

    User ↔ Produk ↔ Pertanyaan ↔ Masalah ↔ Solusi ↔ Penjualan

Setiap percakapan menambah/menebalkan node & edge (graf yang terus tumbuh —
"weight" naik tiap kali relasi yang sama muncul lagi). Graf ini dipakai untuk:
  - visualisasi di dashboard (`/intel/knowledge-graph/{bot_id}`),
  - query "pelanggan yang bertanya X biasanya juga peduli Y" (cross-sell),
  - bahan agent lain (mis. CSAgent bisa tahu masalah apa yang biasanya
    menyertai pertanyaan serupa).

Ekstraksi entitas memakai heuristik ringan (topik dari AnalyticsAgent, friction
points, pola "paket/produk/layanan <nama>") — cukup untuk membangun graf yang
berguna tanpa menambah biaya LLM di jalur realtime. Bisa ditingkatkan ke NER
berbasis LLM saat skala data sudah besar (lihat TODO di `_extract_products`).
"""
from __future__ import annotations

import re

from base import AgentResult, BaseAgent

from .db import get_pool

_PRODUCT_RE = re.compile(
    r"\b(?:paket|produk|layanan|fitur|plan|langganan)\s+([a-zA-Z0-9\- ]{2,24})",
    re.IGNORECASE,
)

_RELATIONS = {
    "asks": "asks",
    "has_problem": "has_problem",
    "resolved_by": "resolved_by",
    "leads_to_sale": "leads_to_sale",
    "interested_in": "interested_in",
    "mentions": "mentions",
}


def _user_label(context: dict) -> tuple[str, str | None]:
    meta = context.get("metadata") or {}
    end_user_id = meta.get("end_user_id") or meta.get("user_id") or meta.get("userId")
    if end_user_id:
        return f"User {end_user_id}", str(end_user_id)
    conv_id = str(context.get("conversation_id") or "")
    return f"Pengunjung {conv_id[:8]}", None


def _extract_products(text: str) -> list[str]:
    """
    TODO(scale-up): saat volume percakapan besar, ganti dengan NER berbasis LLM
    batch (mis. dijalankan di nightly_jobs) untuk presisi entitas yang lebih
    tinggi — pola regex ini sengaja konservatif (presisi > recall) supaya graf
    tidak dibanjiri node sampah.
    """
    found = []
    for m in _PRODUCT_RE.finditer(text or ""):
        name = m.group(1).strip().title()
        if name and name not in found:
            found.append(f"Paket/Produk: {name}")
    return found[:5]


# ════════════════════════════════════════════════════════════════
# 1. REAL-TIME — ekstraksi entitas ringan untuk Supervisor
# ════════════════════════════════════════════════════════════════

class KnowledgeAgent(BaseAgent):
    """
    Agent ringan: hanya MENGEKSTRAK kandidat entitas dari pesan saat ini
    (tanpa I/O DB di jalur realtime). Penulisan graf dilakukan async via
    `update_graph_from_conversation()` setelah jawaban terkirim.
    """
    name = "knowledge_agent"
    skills = ["entity_extraction", "knowledge_graph_building"]
    tools: list[str] = []
    goals = [
        "Mengenali entitas (produk, masalah, topik) yang disebut pelanggan agar bisa dirajut menjadi peta pengetahuan bisnis.",
    ]
    system_prompt = (
        "Kamu adalah Knowledge Graph Agent dalam sistem multi-agent BotNesia. "
        "Tugasmu: mengenali entitas (produk, masalah, topik) yang disebut "
        "pelanggan agar bisa dirajut menjadi peta pengetahuan bisnis."
    )

    async def run(self, context: dict) -> AgentResult:
        user_message = context.get("user_message") or ""
        products = _extract_products(user_message)
        return AgentResult(
            agent=self.name,
            success=True,
            output={"product_mentions": products},
            latency_ms=0,
        )


# ════════════════════════════════════════════════════════════════
# 2. PERSISTENSI GRAF — upsert node & edge (dipanggil setelah persist)
# ════════════════════════════════════════════════════════════════

async def _upsert_node(conn, *, bot_id: str, org_id: str, node_type: str, label: str,
                       ref_id: str | None = None, weight_inc: int = 1) -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO kg_nodes (bot_id, org_id, node_type, label, ref_id, weight)
        VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT (bot_id, node_type, label) DO UPDATE SET
            weight = kg_nodes.weight + $6,
            ref_id = COALESCE(EXCLUDED.ref_id, kg_nodes.ref_id),
            updated_at = NOW()
        RETURNING id
        """,
        bot_id, org_id, node_type, label, ref_id, weight_inc,
    )
    return str(row["id"])


async def _upsert_edge(conn, *, bot_id: str, org_id: str, source_id: str, target_id: str,
                       relation: str, weight_inc: int = 1) -> None:
    if source_id == target_id:
        return
    await conn.execute(
        """
        INSERT INTO kg_edges (bot_id, org_id, source_id, target_id, relation, weight)
        VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT (source_id, target_id, relation) DO UPDATE SET
            weight = kg_edges.weight + $6,
            updated_at = NOW()
        """,
        bot_id, org_id, source_id, target_id, relation, weight_inc,
    )


async def update_graph_from_conversation(
    context: dict,
    *,
    intent: str,
    topics: list[str],
    friction_points: list[str],
    outcome: str,
    purchase_status: str,
    matched_faq_answer: str | None,
    summary: str,
) -> dict:
    """
    Titik masuk utama — dipanggil bersamaan dengan conversation_memory.persist_conversation
    (fire-and-forget). Membangun/menebalkan subgraf untuk SATU percakapan:

        User --asks--> Pertanyaan(topik)
        User --has_problem--> Masalah(friction)
        Pertanyaan --resolved_by--> Solusi (jawaban FAQ / ringkasan)
        User --interested_in--> Produk (disebut eksplisit)
        User --leads_to_sale--> Penjualan          (bila purchase_status == purchased)
        Produk --leads_to_sale--> Penjualan
    """
    bot_id = context.get("bot_id")
    org_id = context.get("org_id")
    conversation_id = str(context.get("conversation_id") or "")
    user_message = context.get("user_message") or ""

    user_label, end_user_ref = _user_label(context)
    products = _extract_products(user_message)

    nodes_created = 0
    edges_created = 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await _upsert_node(
                conn, bot_id=bot_id, org_id=org_id, node_type="user",
                label=user_label, ref_id=end_user_ref,
            )
            nodes_created += 1

            question_ids: list[str] = []
            for topic in (topics or [])[:5]:
                q_id = await _upsert_node(
                    conn, bot_id=bot_id, org_id=org_id, node_type="question",
                    label=f"Pertanyaan: {topic}",
                )
                question_ids.append(q_id)
                await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                   source_id=user_id, target_id=q_id, relation=_RELATIONS["asks"])
                nodes_created += 1
                edges_created += 1

            problem_ids: list[str] = []
            for fp in (friction_points or [])[:5]:
                p_id = await _upsert_node(
                    conn, bot_id=bot_id, org_id=org_id, node_type="problem", label=fp,
                )
                problem_ids.append(p_id)
                await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                   source_id=user_id, target_id=p_id, relation=_RELATIONS["has_problem"])
                nodes_created += 1
                edges_created += 1

            # Solusi: prioritaskan jawaban FAQ yang cocok (sudah terbukti), fallback ringkasan
            solution_text = (matched_faq_answer or "").strip() or (summary or "").strip()
            solution_id = None
            if solution_text and outcome == "resolved":
                solution_id = await _upsert_node(
                    conn, bot_id=bot_id, org_id=org_id, node_type="solution",
                    label=solution_text[:200],
                )
                nodes_created += 1
                for q_id in question_ids:
                    await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                       source_id=q_id, target_id=solution_id, relation=_RELATIONS["resolved_by"])
                    edges_created += 1
                for p_id in problem_ids:
                    await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                       source_id=p_id, target_id=solution_id, relation=_RELATIONS["resolved_by"])
                    edges_created += 1

            product_ids: list[str] = []
            for label in products:
                pr_id = await _upsert_node(
                    conn, bot_id=bot_id, org_id=org_id, node_type="product", label=label,
                )
                product_ids.append(pr_id)
                await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                   source_id=user_id, target_id=pr_id, relation=_RELATIONS["interested_in"])
                nodes_created += 1
                edges_created += 1

            if purchase_status == "purchased":
                sale_id = await _upsert_node(
                    conn, bot_id=bot_id, org_id=org_id, node_type="sale",
                    label=f"Penjualan via percakapan {conversation_id[:8]}",
                    ref_id=conversation_id,
                )
                nodes_created += 1
                await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                   source_id=user_id, target_id=sale_id, relation=_RELATIONS["leads_to_sale"])
                edges_created += 1
                for pr_id in product_ids:
                    await _upsert_edge(conn, bot_id=bot_id, org_id=org_id,
                                       source_id=pr_id, target_id=sale_id, relation=_RELATIONS["leads_to_sale"])
                    edges_created += 1

    return {"nodes_touched": nodes_created, "edges_touched": edges_created}


# ════════════════════════════════════════════════════════════════
# 3. QUERY — subgraph & traversal untuk dashboard / agent lain
# ════════════════════════════════════════════════════════════════

async def get_subgraph(bot_id: str, *, node_type: str | None = None, limit: int = 200) -> dict:
    """Ambil node & edge teratas (by weight) untuk visualisasi dashboard."""
    pool = await get_pool()
    if node_type:
        node_rows = await pool.fetch(
            """SELECT id, node_type, label, ref_id, weight FROM kg_nodes
               WHERE bot_id = $1 AND node_type = $2
               ORDER BY weight DESC LIMIT $3""",
            bot_id, node_type, limit,
        )
    else:
        node_rows = await pool.fetch(
            """SELECT id, node_type, label, ref_id, weight FROM kg_nodes
               WHERE bot_id = $1 ORDER BY weight DESC LIMIT $2""",
            bot_id, limit,
        )
    node_ids = [r["id"] for r in node_rows]
    edge_rows = await pool.fetch(
        """SELECT id, source_id, target_id, relation, weight FROM kg_edges
           WHERE bot_id = $1 AND source_id = ANY($2::uuid[]) AND target_id = ANY($2::uuid[])
           ORDER BY weight DESC LIMIT $3""",
        bot_id, node_ids, limit * 2,
    )
    return {
        "nodes": [dict(r) for r in node_rows],
        "edges": [dict(r) for r in edge_rows],
    }


async def get_related_nodes(bot_id: str, node_id: str, *, hops: int = 1, limit: int = 50) -> dict:
    """Traversal sederhana 1-2 hop dari sebuah node (mis. 'apa saja yang terkait dengan produk X?')."""
    hops = max(1, min(2, hops))
    pool = await get_pool()
    rows = await pool.fetch(
        """
        WITH RECURSIVE hop(node_id, depth) AS (
            SELECT $2::uuid, 0
            UNION
            SELECT CASE WHEN e.source_id = h.node_id THEN e.target_id ELSE e.source_id END, h.depth + 1
            FROM kg_edges e
            JOIN hop h ON (e.source_id = h.node_id OR e.target_id = h.node_id)
            WHERE h.depth < $3 AND e.bot_id = $1
        )
        SELECT DISTINCT n.id, n.node_type, n.label, n.weight, h.depth
        FROM hop h
        JOIN kg_nodes n ON n.id = h.node_id
        WHERE h.depth > 0
        ORDER BY h.depth ASC, n.weight DESC
        LIMIT $4
        """,
        bot_id, node_id, hops, limit,
    )
    return {"node_id": node_id, "related": [dict(r) for r in rows]}
