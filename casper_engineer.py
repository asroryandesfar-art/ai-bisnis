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

import asyncio
import json

from base import AgentResult, BaseAgent

# Kategori severity untuk self-critique (dipakai UI untuk pewarnaan).
SEVERITIES = ("critical", "high", "medium", "low")
CRITIQUE_CATEGORIES = ("correctness", "security", "performance", "architecture", "maintainability", "ux")

# Phase 2b: tool Local Agent yang boleh diusulkan/dieksekusi Casper Engineer.
# Superset = tool read-only + tulis. Keamanan aktual (denylist destruktif,
# secret-guard, approval) DITEGAKKAN DI SISI PERANGKAT (botnesia_local_agent.py),
# bukan di sini — allowlist ini hanya batas pertama supaya agent tak mengarang
# tool acak. write_file & run_command WAJIB approval user di mesinnya.
READONLY_TOOLS = ("read_file", "list_dir", "find_files", "get_info", "search_text", "tree", "scan_project")
WRITE_TOOLS = ("write_file", "run_command")
EXECUTABLE_TOOLS = READONLY_TOOLS + WRITE_TOOLS

_MAX_GOAL = 4000
_MAX_REPO_CTX = 12000


def _summarize_tool_result(result) -> str:
    """Padatkan hasil tool Local Agent jadi ringkas supaya konteks loop tak meledak."""
    if not isinstance(result, dict):
        return str(result)[:400]
    if not result.get("success"):
        return f"gagal: {str(result.get('error') or '')[:200]}"
    for key in ("content", "tree", "output", "stdout", "matches", "files", "entries", "preview", "found_files"):
        if result.get(key):
            return f"{key}: {str(result[key])[:600]}"
    return str({k: v for k, v in result.items() if k != "success"})[:400]


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

        # Planning & repository-analysis saling independen -> jalankan paralel
        # (pangkas latensi ~separuh untuk 2 tahap terberat). Verify & critique
        # bergantung pada keduanya -> tetap berurutan.
        plan, analysis = await asyncio.gather(
            self._plan(goal, repo_context),
            self._analyze_repo(goal, repo_context),
        )
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

    # ── Phase 2b: usulkan langkah eksekusi konkret (tool Local Agent) ────
    async def propose_steps(self, goal: str, plan: dict, repo_context: str = "") -> dict:
        """Ubah rencana jadi urutan langkah tool Local Agent yang konkret & aman.
        Hanya tool di EXECUTABLE_TOOLS; baca dulu sebelum tulis; langkah kecil.
        write_file/run_command TETAP butuh approval user di perangkat. Fail-open."""
        goal = _clip(goal, _MAX_GOAL)
        default = {"steps": [], "_llm_unavailable": True}
        tool_spec = (
            "read_file{path} · list_dir{path} · find_files{path,pattern} · search_text{path,query} · "
            "tree{path} · scan_project{path} · get_info{path} · "
            "write_file{path,content} · run_command{command}"
        )
        out = await self._call_llm_json(
            [
                {"role": "system", "content": (
                    "Kamu Casper Engineer menyusun langkah eksekusi untuk dijalankan oleh Local "
                    "Agent di mesin user. Utamakan keamanan: baca/inspeksi dulu sebelum menulis; "
                    "langkah kecil & reversibel; jalankan test setelah perubahan. JANGAN perintah "
                    "destruktif (rm -rf, dsb) atau membaca secret (.env, kunci). Balas HANYA JSON."
                )},
                {"role": "user", "content": (
                    f"GOAL:\n{goal}\n\n"
                    + (f"PLAN:\n{json.dumps(plan, ensure_ascii=False)[:2500]}\n\n" if plan else "")
                    + (f"REPO:\n{repo_context[:3000]}\n\n" if repo_context else "")
                    + f"Tool tersedia (nama{{arg}}): {tool_spec}\n\n"
                    'Susun urutan langkah konkret. Jawab HANYA JSON: {"steps": [{"tool": "<nama>", '
                    '"args": {"...": "..."}, "rationale": "<kenapa>"}]}'
                )},
            ],
            temperature=0.2, max_tokens=1400, default=default,
        )
        steps = []
        for s in (out.get("steps") or [])[:20]:
            tool = str((s or {}).get("tool") or "").strip()
            args = s.get("args") if isinstance(s, dict) else None
            if tool in EXECUTABLE_TOOLS and isinstance(args, dict):
                steps.append({
                    "tool": tool, "args": args,
                    "rationale": str(s.get("rationale") or "")[:400],
                    "requires_approval": tool in WRITE_TOOLS,
                })
        return {"steps": steps, "_llm_unavailable": bool(out.get("_llm_unavailable"))}

    # ── Phase 2c: loop investigasi repo OTONOM (read-only) ──────────────
    async def investigate(self, goal: str, execute, org_id: str, pool, *,
                          device_id: str | None = None, max_rounds: int = 5) -> dict:
        """Loop agentik READ-ONLY: tiap ronde agent memilih SATU aksi baca
        berikutnya berdasar temuan sebelumnya, sampai 'done' atau max_rounds.
        HANYA READONLY_TOOLS yang dieksekusi (tool tulis diabaikan demi keamanan).
        `execute` diinjeksi (LocalAgentManager.execute) -> bisa diuji tanpa perangkat.
        Return {findings, trace, rounds}."""
        goal = _clip(goal, _MAX_GOAL)
        spec = ("read_file{path} · list_dir{path} · find_files{path,pattern} · "
                "search_text{path,query} · tree{path} · scan_project{path} · get_info{path}")
        observations: list[str] = []
        trace: list[dict] = []
        for _ in range(max(1, min(max_rounds, 10))):
            decision = await self._call_llm_json(
                [
                    {"role": "system", "content": (
                        "Kamu Casper Engineer menginvestigasi repo (READ-ONLY) untuk memahami "
                        "kode sebelum merencanakan. Pilih SATU aksi baca berikutnya, atau selesai "
                        "bila sudah cukup paham. Jangan menebak isi file — baca. Balas HANYA JSON."
                    )},
                    {"role": "user", "content": (
                        f"GOAL:\n{goal}\n\nTemuan sejauh ini:\n{chr(10).join(observations) or '(belum ada)'}\n\n"
                        f"Tool baca tersedia: {spec}\n\n"
                        'Aksi berikutnya? JSON: {"done": false, "tool": "<nama>", "args": {"...":"..."}, '
                        '"reason": "..."} ATAU {"done": true, "summary": "<ringkas temuan kunci>"}'
                    )},
                ],
                temperature=0.1, max_tokens=500, default={"done": True, "_llm_unavailable": True},
            )
            if decision.get("_llm_unavailable"):
                break
            if decision.get("done"):
                if decision.get("summary"):
                    observations.append("RINGKASAN: " + str(decision["summary"])[:1000])
                break
            tool = str(decision.get("tool") or "").strip()
            args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
            if tool not in READONLY_TOOLS:   # keamanan: loop otonom TIDAK boleh tulis/perintah
                trace.append({"tool": tool, "skipped": "not-readonly"})
                observations.append(f"(dilewati: '{tool}' bukan tool read-only)")
                continue
            try:
                result = await execute(org_id, tool, args, device_id=device_id,
                                       initiated_by="casper_engineer_investigate", timeout=30, pool=pool)
            except Exception as exc:
                # Perangkat lepas / error -> hentikan loop dengan aman (bukan crash).
                trace.append({"tool": tool, "args": args, "error": str(exc)[:200]})
                break
            ok = bool(isinstance(result, dict) and result.get("success"))
            trace.append({"tool": tool, "args": args, "success": ok})
            observations.append(f"[{tool} {json.dumps(args, ensure_ascii=False)[:80]}] -> {_summarize_tool_result(result)}")
        return {"findings": "\n".join(observations)[:_MAX_REPO_CTX], "trace": trace, "rounds": len(trace)}
