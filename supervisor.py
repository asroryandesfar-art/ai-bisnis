"""
agents/supervisor.py — Supervisor Agent
Koordinator utama: routing, orkestrasi paralel, agregasi hasil.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from base import AgentResult
from cs_agent   import CSAgent
from escalation import EscalationAgent
from analytics  import AnalyticsAgent
from trainer    import TrainerAgent
from memory_agent import MemoryAgent
from intent_classifier import IntentClassifier, heuristic_complexity
from planner_agent import PlannerAgent, DEFAULT_PLAN
from reasoning_agent import ReasoningAgent
from verification_agent import VerificationAgent
from agent_observability import observe_agent, trace_request

MAX_RETRIES = 2

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

    # Adaptive reasoning pipeline (mode "pro")
    reasoning_mode_used: str = "standard"   # "standard" | "pro"
    confidence_score:    float | None = None  # 0-100
    verification_passed: bool | None = None
    retry_count:         int = 0
    plan:                dict | None = None
    specialist_results:  dict = field(default_factory=dict)
    verification_issues: list[str] = field(default_factory=list)
    suggest_pro_mode:    bool = False
    prompt_tokens:       int = 0
    completion_tokens:   int = 0
    total_tokens:        int = 0
    routed_model:       str = ""
    task_complexity:    str = "simple"


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

        # Adaptive reasoning pipeline
        self.intent_classifier = IntentClassifier(**kwargs)
        self.planner_agent     = PlannerAgent(**kwargs)
        self.reasoning_agent   = ReasoningAgent(**kwargs)
        self.verification_agent = VerificationAgent(**kwargs)

    async def process(self, context: dict) -> SupervisorResult:
        return await trace_request(context, lambda: self._process(context))

    async def _process(self, context: dict) -> SupervisorResult:
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

        # ── STEP 1.5: Klasifikasi kompleksitas (hanya jika reasoning_mode pro) ─
        reasoning_mode = context.get("reasoning_mode", "standard")
        classification = {"complexity": "simple", "source": "skipped"}
        if reasoning_mode == "pro":
            classification = await observe_agent(
                "intent_classifier", ctx,
                lambda: self.intent_classifier.classify(context.get("user_message", "")),
            )

        reasoning_mode_used = "standard"
        plan: dict | None = None
        specialist_outputs: dict = {}
        confidence_score: float | None = None
        verification_passed: bool | None = None
        verification_issues: list[str] = []
        retry_count = 0
        extra_agent_results: dict[str, AgentResult] = {}

        if reasoning_mode == "pro" and classification.get("complexity") == "complex":
            reasoning_mode_used = "pro"

            # ── STEP A: Planner menentukan lensa analisis yang relevan ─
            plan_result = await self.planner_agent.safe_run(ctx)
            if not plan_result.success:
                errors.append(f"planner_agent: {plan_result.error}")
            plan = plan_result.output or dict(DEFAULT_PLAN)
            extra_agent_results["planner_agent"] = plan_result
            ctx["_plan"] = plan

            # ── STEP B: Jalankan lensa analisis (paralel; risk belakangan) ─
            agents_to_invoke = plan.get("agents_to_invoke", [])
            lenses = [l for l in agents_to_invoke if l != "risk"]
            if lenses:
                lens_results = await asyncio.gather(
                    *(self.reasoning_agent.run_lens(l, ctx) for l in lenses)
                )
                for lens, result in zip(lenses, lens_results):
                    specialist_outputs[lens] = result.output
                    extra_agent_results[f"reasoning_agent:{lens}"] = result

            if "risk" in agents_to_invoke:
                cross_context = "\n\n".join(
                    f"{l}: {out.get('conclusion', '')}"
                    for l, out in specialist_outputs.items()
                    if out.get("conclusion")
                )
                risk_result = await self.reasoning_agent.run_lens(
                    "risk", ctx, cross_context=cross_context
                )
                specialist_outputs["risk"] = risk_result.output
                extra_agent_results["reasoning_agent:risk"] = risk_result

            # ── STEP C: Sintesis jawaban akhir dari hasil tim spesialis ─
            cs_synth = await observe_agent(
                "cs_agent:synthesis", ctx,
                lambda: self.cs_agent.synthesize(ctx, specialist_outputs),
            )
            cs_answer = cs_synth.get("answer") or self.cs_agent._clarify_response(
                context.get("user_message", "")
            )
            confidence_score = cs_synth.get("confidence_score", 50)
            cs_topics = cs_synth.get("topics", [])
            cs_followup = cs_synth.get("suggested_followup")

            # ── STEP D: Verifikasi jawaban + retry terbatas ─
            verify_out: dict = {}
            while True:
                verify_out = await observe_agent(
                    "verification_agent", ctx,
                    lambda: self.verification_agent.verify(ctx, cs_answer, specialist_outputs),
                )
                if verify_out.get("_llm_unavailable"):
                    verification_passed = True  # don't retry-storm during an outage
                else:
                    verification_passed = (
                        bool(verify_out.get("verified", True))
                        and verify_out.get("confidence_score", 100) >= 80
                    )
                verification_issues = verify_out.get("issues", [])
                confidence_score = round(
                    (confidence_score + verify_out.get("confidence_score", confidence_score)) / 2
                )
                if verification_passed or retry_count >= MAX_RETRIES:
                    break
                retry_count += 1
                ctx["_verification_feedback"] = (
                    f"Jawaban sebelumnya memiliki masalah: {'; '.join(verification_issues)}. "
                    "Perbaiki jawaban."
                )
                cs_synth = await observe_agent(
                    "cs_agent:synthesis", ctx,
                    lambda: self.cs_agent.synthesize(ctx, specialist_outputs),
                )
                cs_answer = cs_synth.get("answer") or cs_answer
                confidence_score = cs_synth.get("confidence_score", confidence_score)
                cs_topics = cs_synth.get("topics", cs_topics)
                cs_followup = cs_synth.get("suggested_followup", cs_followup)

            extra_agent_results["verification_agent"] = AgentResult(
                agent="verification_agent", success=True, output=verify_out, latency_ms=0
            )
            cs_confidence = confidence_score / 100.0
            cs_result = AgentResult(agent="cs_agent", success=True, output=cs_synth, latency_ms=0)
        else:
            # ── STEP 2: CS membuat jawaban dengan intelligence context (jalur cepat) ─
            cs_result = await self.cs_agent.safe_run(ctx)
            if not cs_result.success:
                errors.append(f"cs_agent: {cs_result.error}")

            cs_out = cs_result.output
            cs_answer = cs_out.get("answer") or self.cs_agent._clarify_response(
                context.get("user_message", "")
            )
            cs_confidence = cs_out.get("confidence")
            if cs_confidence is None:
                cs_confidence = 0.8 if faq_out.get("matched") else 0.6
                if cs_out.get("_retried"):
                    cs_confidence -= 0.15
            cs_topics = cs_out.get("topics", [])
            cs_followup = cs_out.get("suggested_followup")

        enriched = {
            **ctx,
            "bot_response": cs_answer,
            "cs_confidence": cs_confidence,
            "specialist_results": specialist_outputs,
            "plan": plan,
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

        # Bot Standard yang kena pertanyaan kompleks: kasih tahu user bahwa
        # mode Pro tersedia untuk analisis lebih mendalam (cek heuristik gratis).
        suggest_pro_mode = (
            reasoning_mode_used == "standard"
            and reasoning_mode != "pro"
            and heuristic_complexity(context.get("user_message", "")) == "complex"
        )

        # ── STEP 4: Agregasi ─────────────────────────────────────
        return SupervisorResult(
            # CS
            final_answer       = cs_answer,
            confidence         = cs_confidence,
            topics             = cs_topics,
            suggested_followup = cs_followup,

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
                **extra_agent_results,
            },
            total_latency_ms = total_ms,
            errors           = errors,

            # Adaptive reasoning pipeline
            reasoning_mode_used = reasoning_mode_used,
            confidence_score    = confidence_score,
            verification_passed = verification_passed,
            retry_count         = retry_count,
            plan                = plan,
            specialist_results  = specialist_outputs,
            verification_issues = verification_issues,
            suggest_pro_mode    = suggest_pro_mode,
        )
