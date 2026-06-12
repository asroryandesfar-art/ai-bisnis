"""
agents/supervisor.py — Supervisor Agent
Koordinator utama: routing, orkestrasi paralel, agregasi hasil.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from base import AgentResult
from cs_agent   import CSAgent
from escalation import EscalationAgent
from analytics  import AnalyticsAgent
from trainer    import TrainerAgent
from memory_agent import MemoryAgent

# Agen Intelligence Platform — berbagi knowledge lewat shared store (Postgres),
# lihat intelligence/ARCHITECTURE.md §3.3
from intelligence.faq_agent       import FAQAgent
from intelligence.sales_agent     import SalesAgent
from intelligence.knowledge_agent import KnowledgeAgent


@dataclass
class SupervisorResult:
    """Hasil akhir dari seluruh pipeline multi-agent."""
    # Dari CS Agent
    final_answer:      str
    confidence:        float
    topics:            list[str]
    suggested_followup: str | None

    # Dari Escalation Agent
    should_escalate:   bool
    escalation_urgency: str
    escalation_reason: str | None
    escalation_message: str | None
    recommended_team:  str | None

    # Dari Analytics Agent
    sentiment:         dict
    intent:            str
    bot_quality_score: float
    friction_points:   list[str]
    product_insights:  list[str]
    conversation_summary: str

    # Dari Trainer Agent
    trainer_score:     float
    improved_response: str | None
    training_examples: list[dict]
    prompt_suggestions: list[str]

    # Dari FAQ Agent — kecocokan dengan FAQ yang sudah terbentuk
    faq_match:         dict | None

    # Dari Sales Agent — sinyal niat beli/keberatan terdeteksi di pesan ini
    sales_signals:           list[dict]
    sales_has_objection:     bool
    sales_recommended_angle: str | None

    # Dari Knowledge Agent — kandidat entitas produk yang disebut
    kg_product_mentions: list[str]

    # Meta
    agent_results:     dict[str, AgentResult]
    total_latency_ms:  int
    errors:            list[str]


class SupervisorAgent:
    """
    Supervisor menggunakan strategi Hierarchical + Parallel:
    1. Jalankan CS Agent dulu untuk dapat jawaban & confidence
    2. Jalankan Escalation + Analytics + Trainer secara PARALEL
       (mereka semua butuh output CS tapi tidak saling bergantung)
    3. Agregasi semua hasil jadi satu SupervisorResult
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        app_url: str = "https://botnesia.id",
    ):
        # Cloud-only: api_key dipakai untuk LLM dan memori.
        kwargs = {"api_key": api_key or "", "base_url": base_url or "", "app_url": app_url}
        if model:
            kwargs["model"] = model

        self.cs_agent        = CSAgent(**kwargs)
        self.escalation_agent = EscalationAgent(**kwargs)
        self.analytics_agent  = AnalyticsAgent(**kwargs)
        self.trainer_agent    = TrainerAgent(**kwargs)
        self.memory_agent     = MemoryAgent(**kwargs, persist_path="data/memory.json")

        # Intelligence Platform — agen ringan (read-mostly di jalur realtime,
        # penulisan berat dilakukan async setelah jawaban terkirim)
        self.faq_agent       = FAQAgent(**kwargs)
        self.sales_agent     = SalesAgent(**kwargs)
        self.knowledge_agent = KnowledgeAgent(**kwargs)

    async def process(self, context: dict) -> SupervisorResult:
        """
        Pipeline utama:
          context wajib berisi:
            - user_message: str
            - messages: list[dict]  (riwayat percakapan)
          context opsional:
            - bot_id, org_id, conversation_id
            - knowledge_base_context: str (dari RAG BotNesia)
            - resolved: bool
        """
        import time
        t_start = time.monotonic()
        errors  = []

        # ── STEP 0: Inject memory (profil user) ───────────────────
        ctx = self.memory_agent.enrich_context(context)

        # ── STEP 1: Intelligence read-only sebelum CS ────────────
        # FAQ, sinyal sales, dan entitas produk harus tersedia sebelum jawaban
        # dibuat agar hasil agent benar-benar memengaruhi respons pengguna.
        faq_result, sales_result, kg_result = await asyncio.gather(
            self.faq_agent.safe_run(ctx),
            self.sales_agent.safe_run(ctx),
            self.knowledge_agent.safe_run(ctx),
            return_exceptions=False,
        )
        if not faq_result.success:
            errors.append(f"faq_agent: {faq_result.error}")
        if not sales_result.success:
            errors.append(f"sales_agent: {sales_result.error}")
        if not kg_result.success:
            errors.append(f"knowledge_agent: {kg_result.error}")

        faq_out = faq_result.output
        sales_out = sales_result.output
        kg_out = kg_result.output
        guidance: list[str] = []
        if faq_out.get("matched") and faq_out.get("suggested_answer"):
            guidance.append(
                "## FAQ terverifikasi dari percakapan sebelumnya\n"
                f"Pertanyaan: {faq_out.get('question', '')}\n"
                f"Jawaban acuan: {faq_out.get('suggested_answer', '')}\n"
                "Gunakan sebagai dasar jika sesuai dengan pertanyaan saat ini."
            )
        if sales_out.get("recommended_angle"):
            guidance.append(
                "## Panduan penanganan calon pelanggan\n"
                + str(sales_out["recommended_angle"])
            )
        if kg_out.get("product_mentions"):
            guidance.append(
                "## Produk yang terdeteksi\n"
                + ", ".join(str(x) for x in kg_out["product_mentions"])
            )
        if guidance:
            existing_kb = (ctx.get("knowledge_base_context") or "").strip()
            ctx = {
                **ctx,
                "knowledge_base_context": "\n\n".join(
                    part for part in [existing_kb, *guidance] if part
                ),
            }

        # ── STEP 2: CS membuat jawaban dengan intelligence context ─
        cs_result = await self.cs_agent.safe_run(ctx)
        if not cs_result.success:
            errors.append(f"cs_agent: {cs_result.error}")

        cs_out = cs_result.output
        cs_answer = cs_out.get("answer") or self.cs_agent._clarify_response(
            context.get("user_message", "")
        )
        cs_confidence = cs_out.get("confidence", 0.5)
        enriched = {
            **ctx,
            "bot_response": cs_answer,
            "cs_confidence": cs_confidence,
        }

        # ── STEP 3: Evaluasi jawaban secara paralel ───────────────
        esc_result, anal_result, train_result, mem_result = await asyncio.gather(
            self.escalation_agent.safe_run(enriched),
            self.analytics_agent.safe_run(enriched),
            self.trainer_agent.safe_run(enriched),
            self.memory_agent.safe_run(enriched),
            return_exceptions=False,
        )
        if not esc_result.success:
            errors.append(f"escalation_agent: {esc_result.error}")
        if not anal_result.success:
            errors.append(f"analytics_agent: {anal_result.error}")
        if not train_result.success:
            errors.append(f"trainer_agent: {train_result.error}")
        if not mem_result.success:
            errors.append(f"memory_agent: {mem_result.error}")

        esc_out = esc_result.output
        anal_out = anal_result.output
        train_out = train_result.output
        mem_out = mem_result.output

        total_ms = int((time.monotonic() - t_start) * 1000)

        # ── STEP 4: Agregasi ─────────────────────────────────────
        return SupervisorResult(
            # CS
            final_answer       = cs_answer,
            confidence         = cs_confidence,
            topics             = cs_out.get("topics", []),
            suggested_followup = cs_out.get("suggested_followup"),

            # Escalation
            should_escalate    = esc_out.get("should_escalate", False),
            escalation_urgency = esc_out.get("urgency", "low"),
            escalation_reason  = esc_out.get("reason"),
            escalation_message = esc_out.get("suggested_message"),
            recommended_team   = esc_out.get("recommended_team"),

            # Analytics
            sentiment              = anal_out.get("sentiment", {"label": "neutral", "score": 0.0}),
            intent                 = anal_out.get("intent", "unknown"),
            bot_quality_score      = anal_out.get("bot_quality_score", cs_confidence),
            friction_points        = anal_out.get("friction_points", []),
            product_insights       = anal_out.get("product_insights", []),
            conversation_summary   = anal_out.get("summary", ""),

            # Trainer
            trainer_score      = train_out.get("overall_score", 0.0),
            improved_response  = train_out.get("improved_response"),
            training_examples  = train_out.get("training_examples", []),
            prompt_suggestions = train_out.get("system_prompt_suggestions", []),

            # FAQ Engine
            faq_match = (
                {
                    "faq_id":           faq_out.get("faq_id"),
                    "question":         faq_out.get("question"),
                    "suggested_answer": faq_out.get("suggested_answer"),
                    "similarity":       faq_out.get("similarity"),
                }
                if faq_out.get("matched") else None
            ),

            # Sales Intelligence
            sales_signals           = sales_out.get("signals", []),
            sales_has_objection     = sales_out.get("has_objection", False),
            sales_recommended_angle = sales_out.get("recommended_angle"),

            # Knowledge Graph
            kg_product_mentions = kg_out.get("product_mentions", []),

            # Meta
            agent_results = {
                "cs_agent":        cs_result,
                "escalation_agent": esc_result,
                "analytics_agent":  anal_result,
                "trainer_agent":    train_result,
                "memory_agent":     mem_result,
                "faq_agent":        faq_result,
                "sales_agent":      sales_result,
                "knowledge_agent":  kg_result,
            },
            total_latency_ms = total_ms,
            errors           = errors,
        )
