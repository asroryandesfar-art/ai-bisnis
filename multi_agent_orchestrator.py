"""
multi_agent_orchestrator.py — Engine orkestrasi multi-agent tunggal BotNesia.

SATU engine untuk seluruh platform (tidak menduplikasi Supervisor chat maupun
agent). Dipakai HANYA dari permukaan TERAUTENTIKASI + RBAC (lihat
bn_platform/orchestrator.py). Widget publik /chat/{bot_id} tetap memakai
SupervisorAgent (single-voice CS) dan TIDAK menyentuh engine ini.

Alur:
  route (dinamis, registry + RBAC) → jalankan agent PARALEL (timeout + isolasi)
  → agregasi TERSTRUKTUR (summary/detail/conflict/confidence/final)
  → self-verification → hasil + trace observability.

Penemuan agent murni dari agent_registry.orchestration_agents() — tidak ada
tabel dispatch hardcode. Reuse BaseAgent (LLM plumbing + fallback provider) dan
agent yang sudah ada via safe_run().
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import agent_registry
from base import AgentResult, BaseAgent

logger = logging.getLogger("botnesia.orchestrator")

# Batas kedalaman inter-agent communication (cegah loop/rekursi tak terbatas).
MAX_INTER_AGENT_DEPTH = 1
DEFAULT_AGENT_TIMEOUT_SECONDS = 20.0


@dataclass
class OrchestrationResult:
    """Hasil orkestrasi terstruktur (BUKAN concat string)."""
    message:       str
    summary:       str
    final_answer:  str
    confidence:    float
    agents:        list[dict] = field(default_factory=list)   # detail per-agent
    conflicts:     list[str] = field(default_factory=list)
    verification:  dict = field(default_factory=dict)          # {passed, issues}
    routing:       dict = field(default_factory=dict)          # {selected, method, reason}
    trace:         list[dict] = field(default_factory=list)    # observability
    latency_ms:    int = 0
    errors:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "summary": self.summary,
            "final_answer": self.final_answer,
            "confidence": round(self.confidence, 4),
            "agents": self.agents,
            "conflicts": self.conflicts,
            "verification": self.verification,
            "routing": self.routing,
            "trace": self.trace,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
        }


class MultiAgentOrchestrator:
    """Orkestrator multi-agent tunggal (registry-driven, paralel, RBAC-aware)."""

    def __init__(
        self,
        *,
        agent_kwargs: dict | None = None,
        default_timeout: float = DEFAULT_AGENT_TIMEOUT_SECONDS,
    ):
        # Config LLM yang diteruskan ke tiap agent saat di-build (api_key,
        # gemini_api_key, dst — sama seperti yang dipakai SupervisorAgent).
        self.agent_kwargs = dict(agent_kwargs or {})
        self.default_timeout = default_timeout
        # Worker LLM untuk router/aggregator/verifier — reuse BaseAgent plumbing.
        self._worker = BaseAgent(**self.agent_kwargs)

    # ── PUBLIC ────────────────────────────────────────────────────────────
    async def orchestrate(
        self,
        *,
        message: str,
        context: dict,
        allowed_permissions: set[str] | None,
        requested_agents: list[str] | None = None,
        timeout: float | None = None,
        _depth: int = 0,
    ) -> OrchestrationResult:
        t_start = time.monotonic()
        errors: list[str] = []
        timeout = timeout or self.default_timeout

        specs = agent_registry.orchestration_agents(allowed_permissions=allowed_permissions)
        if not specs:
            return OrchestrationResult(
                message=message, summary="Tidak ada agent yang tersedia untuk peran ini.",
                final_answer="Akun Anda tidak memiliki izin untuk memanggil agent mana pun.",
                confidence=0.0, routing={"selected": [], "method": "rbac_empty", "reason": "no permitted agents"},
                latency_ms=int((time.monotonic() - t_start) * 1000),
            )

        # 1) ROUTING dinamis
        selected, method, reason = await self._route(message, specs, requested_agents)

        # 2) SHARED CONTEXT (satu context untuk semua agent)
        shared = self._build_shared_context(message, context, allowed_permissions, _depth)

        # 3) EKSEKUSI PARALEL (timeout + isolasi kegagalan)
        results = await self._run_parallel(selected, shared, timeout)

        # 4) AGREGASI terstruktur
        summary, final_answer, confidence, conflicts, agent_details = await self._aggregate(
            message, selected, results
        )

        # 5) SELF-VERIFICATION (+ satu putaran revisi bila gagal)
        successful = [r for r in results if r.success]
        verification = await self._verify(message, final_answer, results)
        if verification.get("checked") and not verification.get("passed") and successful:
            revised = await self._synthesize(
                message, successful, revision_feedback=verification.get("issues"),
            )
            if revised.get("final_answer"):
                final_answer = revised["final_answer"]
                verification["revised"] = True

        trace = [
            {
                "agent": r.agent,
                "success": r.success,
                "confidence": r.confidence,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in results
        ]
        for r in results:
            if not r.success and r.error:
                errors.append(f"{r.agent}: {r.error}")

        latency_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "orchestrate agents=%s method=%s confidence=%.2f verified=%s latency_ms=%d",
            [s.name for s in selected], method, confidence,
            verification.get("passed"), latency_ms,
        )
        return OrchestrationResult(
            message=message, summary=summary, final_answer=final_answer,
            confidence=confidence, agents=agent_details, conflicts=conflicts,
            verification=verification,
            routing={"selected": [s.name for s in selected], "method": method, "reason": reason},
            trace=trace, latency_ms=latency_ms, errors=errors,
        )

    # ── ROUTING ───────────────────────────────────────────────────────────
    async def _route(
        self,
        message: str,
        specs: list[agent_registry.OrchestrationAgentSpec],
        requested_agents: list[str] | None,
    ) -> tuple[list[agent_registry.OrchestrationAgentSpec], str, str]:
        by_name = {s.name: s for s in specs}
        by_class = {s.class_name: s for s in specs}
        by_cat: dict[str, list] = {}
        for s in specs:
            by_cat.setdefault(s.category, []).append(s)

        # (a) Eksplisit: caller sudah menentukan agent
        if requested_agents:
            chosen: list = []
            for token in requested_agents:
                if token in by_name:
                    chosen.append(by_name[token])
                elif token in by_class:
                    chosen.append(by_class[token])
                elif token in by_cat:
                    chosen.extend(by_cat[token])
            chosen = _dedupe(chosen)
            if chosen:
                return chosen, "explicit", "caller-specified agents"

        # (b) Router LLM
        llm_selected = await self._route_llm(message, specs)
        if llm_selected:
            return llm_selected, "llm", "llm router selection"

        # (c) Fallback heuristik (keyword capability)
        heur = self._route_heuristic(message, specs)
        if heur:
            return heur, "heuristic", "keyword capability match"

        # (d) Default aman: satu agent umum
        default = by_cat.get("general_ai") or by_cat.get("customer_service") or [specs[0]]
        return default[:1], "default", "no match; general agent"

    async def _route_llm(self, message, specs) -> list | None:
        catalog = "\n".join(
            f"- {s.name} (kategori={s.category}): {', '.join(s.capabilities) or 'umum'}"
            for s in specs
        )
        prompt = [
            {"role": "system", "content": (
                "Kamu adalah router multi-agent. Pilih agent yang RELEVAN untuk "
                "menjawab permintaan user. Boleh pilih beberapa bila perlu "
                "kolaborasi lintas-domain. Jawab HANYA JSON: "
                '{"agents": ["<name>", ...], "reason": "<singkat>"}. '
                "Gunakan HANYA name dari daftar."
            )},
            {"role": "user", "content": f"Agent tersedia:\n{catalog}\n\nPermintaan user: {message}\n\nJSON:"},
        ]
        try:
            out = await self._worker._call_llm_json(prompt, temperature=0.0, max_tokens=256, default={})
        except Exception:
            return None
        if out.get("_llm_unavailable"):
            return None
        names = out.get("agents")
        if not isinstance(names, list):
            return None
        by_name = {s.name: s for s in specs}
        chosen = _dedupe([by_name[n] for n in names if n in by_name])
        return chosen or None

    def _route_heuristic(self, message, specs) -> list:
        msg = (message or "").lower()
        chosen: list = []
        for s in specs:
            if any(kw in msg for kw in s.capabilities):
                chosen.append(s)
        return _dedupe(chosen)

    # ── SHARED CONTEXT ────────────────────────────────────────────────────
    def _build_shared_context(
        self, message: str, context: dict, allowed_permissions: set[str] | None, depth: int
    ) -> dict:
        shared = dict(context)
        shared["user_message"] = message
        shared.setdefault("messages", context.get("messages", []))
        shared.setdefault("knowledge_base_context", context.get("knowledge_base_context", ""))
        shared["_allowed_permissions"] = allowed_permissions
        shared["_orchestration_depth"] = depth
        # Inter-agent communication handle (Phase 6) — depth-guarded.
        if depth < MAX_INTER_AGENT_DEPTH:
            shared["_ask_agent"] = self._make_ask_handle(context, allowed_permissions, depth + 1)
        return shared

    def _make_ask_handle(
        self, context: dict, allowed_permissions: set[str] | None, depth: int
    ) -> Callable[[str, str], Awaitable[AgentResult]]:
        async def ask(agent_name: str, subquery: str) -> AgentResult:
            """Minta bantuan agent lain (dipakai antar-agent). Depth-guarded."""
            specs = agent_registry.orchestration_agents(allowed_permissions=allowed_permissions)
            match = next((s for s in specs if s.name == agent_name or s.class_name == agent_name or s.category == agent_name), None)
            if match is None:
                return AgentResult(agent=agent_name, success=False, output={},
                                   latency_ms=0, error="agent tidak tersedia / tidak diizinkan")
            sub_ctx = self._build_shared_context(subquery, context, allowed_permissions, depth)
            return await self._run_one(match, sub_ctx, self.default_timeout)
        return ask

    # ── PARALLEL EXECUTION ────────────────────────────────────────────────
    async def _run_parallel(self, specs, ctx, timeout) -> list[AgentResult]:
        results = await asyncio.gather(
            *(self._run_one(s, ctx, timeout) for s in specs),
            return_exceptions=True,
        )
        out: list[AgentResult] = []
        for spec, res in zip(specs, results):
            if isinstance(res, AgentResult):
                out.append(res)
            else:  # exception bocor (seharusnya jarang; safe_run menangkap)
                out.append(AgentResult(agent=spec.name, success=False, output={},
                                       latency_ms=0, error=str(res)))
        return out

    async def _run_one(self, spec, ctx, timeout) -> AgentResult:
        """Bangun & jalankan satu agent dengan timeout + isolasi."""
        try:
            agent = agent_registry.build_agent(spec.module_path, spec.class_name, **self.agent_kwargs)
        except Exception as e:
            return AgentResult(agent=spec.name, success=False, output={}, latency_ms=0,
                               error=f"gagal init agent: {e}")
        t = time.monotonic()
        try:
            result = await asyncio.wait_for(agent.safe_run(ctx), timeout=timeout)
        except asyncio.TimeoutError:
            return AgentResult(agent=spec.name, success=False, output={},
                               latency_ms=int((time.monotonic() - t) * 1000),
                               error=f"timeout > {timeout}s")
        except Exception as e:
            return AgentResult(agent=spec.name, success=False, output={},
                               latency_ms=int((time.monotonic() - t) * 1000), error=str(e))
        # Normalisasi confidence: pakai field, atau ambil dari output.
        if result.confidence is None:
            conf = result.output.get("confidence") if isinstance(result.output, dict) else None
            if isinstance(conf, (int, float)):
                result.confidence = float(conf) if conf <= 1.0 else float(conf) / 100.0
        return result

    # ── AGGREGATION ───────────────────────────────────────────────────────
    async def _aggregate(self, message, specs, results) -> tuple[str, str, float, list[str], list[dict]]:
        spec_by_agent = {s.name: s for s in specs}
        agent_details: list[dict] = []
        for r in results:
            agent_details.append({
                "agent": r.agent,
                "category": getattr(spec_by_agent.get(r.agent), "category", None),
                "success": r.success,
                "confidence": r.confidence,
                "latency_ms": r.latency_ms,
                "output": r.output if r.success else None,
                "error": r.error,
            })

        successful = [r for r in results if r.success]
        # Confidence gabungan: rata-rata confidence sukses (default 0.5) ×
        # rasio keberhasilan (agent gagal menurunkan keyakinan keseluruhan).
        if results:
            confs = [(r.confidence if r.confidence is not None else 0.5) for r in successful]
            mean_conf = sum(confs) / len(confs) if confs else 0.0
            success_ratio = len(successful) / len(results)
            confidence = round(mean_conf * success_ratio, 4)
        else:
            confidence = 0.0

        if not successful:
            return ("Semua agent gagal memberi hasil.",
                    "Maaf, sistem tidak dapat menyusun jawaban saat ini.",
                    confidence, [], agent_details)

        # Sintesis final via LLM; fallback = ringkasan terstruktur (bukan concat).
        synth = await self._synthesize(message, successful)
        summary = synth.get("summary") or self._fallback_summary(successful)
        final_answer = synth.get("final_answer") or self._fallback_final(message, successful)
        conflicts = synth.get("conflicts") or []
        if not isinstance(conflicts, list):
            conflicts = [str(conflicts)]
        return summary, final_answer, confidence, conflicts, agent_details

    async def _synthesize(self, message, successful, *, revision_feedback=None) -> dict:
        findings = "\n\n".join(
            f"### {r.agent} (confidence={r.confidence})\n{_summarize_output(r.output)}"
            for r in successful
        )
        system = (
            "Kamu adalah Supervisor yang menggabungkan hasil beberapa agent "
            "menjadi SATU jawaban koheren untuk user. Jangan sekadar menyalin; "
            "sintesis. Tandai kontradiksi antar-agent bila ada. Jawab HANYA JSON: "
            '{"summary": "<1-2 kalimat>", "final_answer": "<jawaban lengkap>", '
            '"conflicts": ["<kontradiksi>", ...]}'
        )
        if revision_feedback:
            issues = "; ".join(str(x) for x in revision_feedback)
            system += (
                f"\n\nREVISI: jawaban sebelumnya gagal verifikasi karena: {issues}. "
                "Perbaiki masalah ini dalam final_answer."
            )
        prompt = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Permintaan user: {message}\n\nHasil agent:\n{findings}\n\nJSON:"},
        ]
        try:
            out = await self._worker._call_llm_json(prompt, temperature=0.2, max_tokens=1024, default={})
        except Exception:
            return {}
        if out.get("_llm_unavailable"):
            return {}
        return out

    def _fallback_summary(self, successful) -> str:
        return f"{len(successful)} agent berkontribusi: " + ", ".join(r.agent for r in successful) + "."

    def _fallback_final(self, message, successful) -> str:
        # Struktur berlabel per-agent (bukan concat mentah).
        parts = [f"Ringkasan kontribusi agent untuk: {message}", ""]
        for r in successful:
            parts.append(f"• {r.agent} (confidence={r.confidence if r.confidence is not None else 'n/a'}):")
            parts.append(f"  {_summarize_output(r.output)}")
        return "\n".join(parts)

    # ── SELF-VERIFICATION ─────────────────────────────────────────────────
    async def _verify(self, message, final_answer, results) -> dict:
        """Cek logika/kontradiksi/halusinasi sederhana pada jawaban final."""
        if not final_answer.strip():
            return {"passed": False, "issues": ["jawaban kosong"], "checked": True}
        prompt = [
            {"role": "system", "content": (
                "Kamu adalah verifier. Periksa jawaban terhadap permintaan user: "
                "(1) logika konsisten, (2) tidak ada kontradiksi internal, "
                "(3) tidak mengklaim fakta yang tidak didukung hasil agent. "
                'Jawab HANYA JSON: {"passed": true/false, "issues": ["..."]}'
            )},
            {"role": "user", "content": f"Permintaan: {message}\n\nJawaban:\n{final_answer}\n\nJSON:"},
        ]
        try:
            out = await self._worker._call_llm_json(prompt, temperature=0.0, max_tokens=256, default={})
        except Exception:
            out = {}
        if not out or out.get("_llm_unavailable"):
            # LLM tak tersedia → jangan blokir; tandai belum terverifikasi.
            return {"passed": True, "issues": [], "checked": False}
        passed = bool(out.get("passed", True))
        issues = out.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        return {"passed": passed, "issues": issues, "checked": True}


# ── helpers ──────────────────────────────────────────────────────────────
def _dedupe(specs: list) -> list:
    seen: set[str] = set()
    out = []
    for s in specs:
        if s.class_name not in seen:
            seen.add(s.class_name)
            out.append(s)
    return out


def _summarize_output(output: Any) -> str:
    if not isinstance(output, dict) or not output:
        return str(output or "(tidak ada output)")
    # Ambil field teks paling informatif bila ada.
    for key in ("answer", "summary", "conclusion", "result", "message", "recommended_angle"):
        val = output.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Kalau tak ada, ringkas key→value pendek.
    items = []
    for k, v in list(output.items())[:6]:
        if k.startswith("_"):
            continue
        items.append(f"{k}={str(v)[:120]}")
    return "; ".join(items) or "(output terstruktur)"
