"""
casper_engineer.py — Casper Engineer (Autonomous Engineering Agent).

Modul BARU yang berjalan BERDAMPINGAN dengan Casper Blockchain (casper/workflow.py,
casper_anchor.py) — TIDAK mengubah tanggung jawab modul blockchain sama sekali.

Casper Engineer adalah `BaseAgent` yang menstruktur kerja software-engineering
otonom sesuai pilar yang diminta:

    Goal -> Planning -> Repository Analysis -> Self-Verification
         -> Self-Critique -> Improved Plan

Ia MEMAKAI ULANG mesin yang sudah ada, bukan menduplikasi:
  - base.BaseAgent._call_llm_json  -> reasoning terstruktur (fail-open)
  - base.BaseAgent.run_task        -> Plan->Subtask->Tool->Execute->Verify->Report
                                       (task_engine.py) untuk EKSEKUSI nyata via
                                       tool framework / Local Agent (fase 2, digate).

v1 (file ini): "otak" engineering — planning, pemahaman repo, dekomposisi tugas,
self-verification, dan self-critique yang menghasilkan rencana yang diperbaiki.
Tidak mengeksekusi kode arbitrer di server. Eksekusi nyata (coding/testing/deploy)
disalurkan lewat Local Agent yang sudah ada (mesin user + approval) di fase 2 —
karena agent ini mewarisi `run_task()`, penambahan tool repo tidak butuh rework.
"""
from __future__ import annotations

import json

from base import AgentResult, BaseAgent

# Kategori severity untuk self-critique (dipakai UI untuk pewarnaan).
SEVERITIES = ("critical", "high", "medium", "low")
CRITIQUE_CATEGORIES = ("correctness", "security", "performance", "architecture", "maintainability", "ux")

_MAX_GOAL = 4000
_MAX_REPO_CTX = 12000


def _clip(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text[:limit]


class CasperEngineerAgent(BaseAgent):
    """Agen software-engineer otonom. Menghasilkan artefak engineering yang
    terstruktur & teraudit untuk sebuah goal, mengikuti pilar Senior Engineer +
    Tech Lead + QA + Architect. Setiap tahap fail-open (LLM down -> default aman,
    ditandai `_llm_unavailable`) supaya deterministik & bisa diuji tanpa API."""

    name = "casper_engineer"
    system_prompt = (
        "Kamu adalah Casper Engineer — AI Software Engineer otonom kelas dunia yang "
        "bekerja sekaligus sebagai Senior Software Engineer, Tech Lead, QA Engineer, "
        "dan Solution Architect. Kamu mengutamakan: memahami tujuan sebelum bertindak, "
        "membaca & menghormati konvensi project yang ada, membuat rencana eksploratif "
        "yang aman, menulis kode production (clean, scalable, maintainable, secure), "
        "menguji, dan mengkritik hasil sendiri. Jangan pernah langsung menulis kode "
        "tanpa rencana. Balas HANYA dalam format JSON yang diminta."
    )

    # Metadata untuk agent_registry.list_agents() (dibaca lewat atribut, tak hardcode duplikat).
    skills = [
        "planning", "repository_analysis", "task_decomposition",
        "self_verification", "self_critique", "risk_assessment",
    ]
    tools: list[str] = []  # fase 2: repo_read/repo_grep/run_tests via Local Agent (digate)
    goals = [
        "Menyelesaikan pekerjaan software-engineering end-to-end dengan kualitas production",
        "Merencanakan sebelum mengeksekusi, lalu memverifikasi & mengkritik hasil sendiri",
    ]

    # ── Tahap 1: PLANNING ───────────────────────────────────────────────
    async def _plan(self, goal: str, repo_context: str) -> dict:
        default = {
            "understanding": "", "subtasks": [], "execution_order": [],
            "risks": [], "_llm_unavailable": True,
        }
        out = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": (
                    f"GOAL:\n{goal}\n\n"
                    + (f"KONTEKS REPO (opsional):\n{repo_context}\n\n" if repo_context else "")
                    + "Sebelum menulis kode apa pun, buat rencana. Pahami tujuannya, pecah "
                    "menjadi subtask konkret (urutan logis), tentukan urutan eksekusi terbaik, "
                    "dan perkirakan risiko utama beserta mitigasinya.\n\n"
                    'Jawab HANYA JSON: {"understanding": "<ringkas tujuan sebenarnya>", '
                    '"subtasks": [{"id": 1, "title": "...", "detail": "..."}], '
                    '"execution_order": [1,2,3], '
                    '"risks": [{"risk": "...", "severity": "critical|high|medium|low", "mitigation": "..."}]}'
                )},
            ],
            temperature=0.2, max_tokens=1100, default=default,
        )
        return out

    # ── Tahap 2: REPOSITORY ANALYSIS ────────────────────────────────────
    async def _analyze_repo(self, goal: str, repo_context: str) -> dict:
        default = {
            "structure": "", "dependencies": [], "conventions": [],
            "existing_patterns": [], "integration_points": [], "constraints": [],
            "_llm_unavailable": True,
        }
        if not repo_context:
            # Tanpa konteks repo, beri arahan APA yang harus diperiksa — bukan mengarang isi.
            return {
                "structure": "", "dependencies": [], "conventions": [],
                "existing_patterns": [],
                "integration_points": [],
                "constraints": [
                    "Konteks repo belum diberikan. Sebelum implementasi, Casper Engineer "
                    "harus membaca struktur folder, dependency, konvensi penamaan, dan pola "
                    "yang ada agar implementasi tidak bertentangan dengan project."
                ],
                "_needs_repo_context": True,
            }
        out = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": (
                    f"GOAL:\n{goal}\n\nKONTEKS REPO:\n{repo_context}\n\n"
                    "Analisis repository ini agar implementasi SELARAS dengan project (jangan "
                    "membuat sesuatu yang bertentangan). Identifikasi struktur, dependency, "
                    "konvensi penamaan/gaya kode, pola yang sudah ada yang bisa dipakai ulang, "
                    "titik integrasi, dan batasan.\n\n"
                    'Jawab HANYA JSON: {"structure": "<ringkas>", "dependencies": ["..."], '
                    '"conventions": ["..."], "existing_patterns": ["..."], '
                    '"integration_points": ["..."], "constraints": ["..."]}'
                )},
            ],
            temperature=0.1, max_tokens=1000, default=default,
        )
        return out

    # ── Tahap 3: SELF-VERIFICATION ──────────────────────────────────────
    async def _verify(self, goal: str, plan: dict, analysis: dict) -> dict:
        default = {"complete": False, "gaps": [], "reasoning": "Verifikasi LLM tak tersedia.",
                   "_llm_unavailable": True}
        out = await self._call_llm_json(
            [
                {"role": "system", "content": (
                    "Kamu verifier internal Casper Engineer. Nilai jujur apakah rencana + "
                    "analisis benar-benar cukup untuk mencapai goal secara production, atau "
                    "masih ada lubang (langkah hilang, asumsi berbahaya, tidak selaras repo)."
                )},
                {"role": "user", "content": (
                    f"GOAL:\n{goal}\n\nPLAN:\n{json.dumps(plan, ensure_ascii=False)[:3500]}\n\n"
                    f"REPO ANALYSIS:\n{json.dumps(analysis, ensure_ascii=False)[:2500]}\n\n"
                    'Jawab HANYA JSON: {"complete": true|false, "gaps": ["..."], "reasoning": "..."}'
                )},
            ],
            temperature=0.0, max_tokens=600, default=default,
        )
        return out

    # ── Tahap 4: SELF-CRITIQUE -> IMPROVED PLAN ─────────────────────────
    async def _critique(self, goal: str, plan: dict, analysis: dict, verification: dict) -> dict:
        default = {"issues": [], "improved_plan": plan, "overall_confidence": 0.0,
                   "_llm_unavailable": True}
        out = await self._call_llm_json(
            [
                {"role": "system", "content": (
                    "Kamu Casper Engineer dalam mode self-critic (Tech Lead + Security + QA + "
                    "Architect). Kritik rencanamu sendiri secara tajam, lalu perbaiki. Cari "
                    f"masalah pada kategori: {', '.join(CRITIQUE_CATEGORIES)}."
                )},
                {"role": "user", "content": (
                    f"GOAL:\n{goal}\n\nPLAN:\n{json.dumps(plan, ensure_ascii=False)[:3000]}\n\n"
                    f"VERIFICATION:\n{json.dumps(verification, ensure_ascii=False)[:1200]}\n\n"
                    "Temukan bug/security/performance/architecture/maintainability/UX issue pada "
                    "rencana ini, lalu hasilkan rencana yang DIPERBAIKI (mengatasi issue tsb).\n\n"
                    'Jawab HANYA JSON: {"issues": [{"category": "correctness|security|performance|'
                    'architecture|maintainability|ux", "severity": "critical|high|medium|low", '
                    '"detail": "...", "fix": "..."}], '
                    '"improved_plan": {"summary": "...", "steps": ["..."]}, '
                    '"overall_confidence": 0.0}'
                )},
            ],
            temperature=0.2, max_tokens=1300, default=default,
        )
        return out

    async def run(self, context: dict) -> AgentResult:
        """context: {goal|user_message, repo_context?}. Menghasilkan artefak
        engineering terstruktur. Dipanggil lewat safe_run() (observability)."""
        goal = _clip(context.get("goal") or context.get("user_message") or "", _MAX_GOAL)
        repo_context = _clip(context.get("repo_context") or "", _MAX_REPO_CTX)
        if not goal:
            return AgentResult(
                agent=self.name, success=False, output={"error": "goal kosong"},
                latency_ms=0, error="goal kosong",
            )

        plan = await self._plan(goal, repo_context)
        analysis = await self._analyze_repo(goal, repo_context)
        verification = await self._verify(goal, plan, analysis)
        critique = await self._critique(goal, plan, analysis, verification)

        # LLM benar-benar down di SEMUA tahap -> tandai degraded (bukan sukses palsu).
        degraded = all(
            stage.get("_llm_unavailable")
            for stage in (plan, analysis, verification, critique)
            if isinstance(stage, dict)
        )
        confidence = None
        try:
            confidence = float(critique.get("overall_confidence")) if not degraded else None
        except (TypeError, ValueError):
            confidence = None

        output = {
            "goal": goal,
            "planning": plan,
            "repository_analysis": analysis,
            "self_verification": verification,
            "self_critique": {"issues": critique.get("issues", []),
                              "improved_plan": critique.get("improved_plan", {})},
            "confidence": confidence,
            "status": "degraded" if degraded else ("verified" if verification.get("complete") else "needs_review"),
            "needs_repo_context": bool(analysis.get("_needs_repo_context")),
        }
        return AgentResult(
            agent=self.name, success=not degraded, output=output,
            latency_ms=0, error="LLM tidak tersedia" if degraded else None,
            confidence=confidence,
        )
