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

# ── Doktrin "pelatihan" Casper Engineer (senior engineer kelas dunia) ────────
# Proses kerja kanonik: tiap tahap output di bawahnya menuntut BUKTI, bukan
# asumsi. Diselaraskan di system_prompt + rubrik self-score.
ENGINEERING_PROCESS = (
    "Observe", "Verify", "Collect Evidence", "Analyze", "Critique",
    "Improve", "Plan", "Implement", "Review", "Test", "Report",
)

# Pola arsitektur yang harus DIKENALI & DINAMAI (dengan bukti) saat analisis —
# bukan pola yang "seharusnya" ada.
ARCHITECTURE_PATTERNS = (
    "layered", "clean-architecture", "hexagonal", "domain-driven-design",
    "event-driven", "microservices", "modular-monolith", "mvc", "cqrs",
)

# Rubrik penilaian mandiri (skala 0..10 tiap dimensi). Ambang lulus 9 — di
# bawahnya menandai retrain_needed (dimensi mana yang perlu dilatih ulang).
SCORE_DIMENSIONS = (
    "accuracy", "reasoning", "architecture", "security",
    "maintainability", "scalability", "professionalism",
)
SCORE_PASS_THRESHOLD = 9.0

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


def _audit_evidence(analysis) -> dict:
    """Deterministik (TANPA LLM): pisahkan klaim FAKTA-berbukti dari ASUMSI /
    klaim tanpa bukti di `evidence_log`. Menegakkan aturan anti-asumsi bahkan
    saat LLM down. `integrity` = proporsi klaim yang benar-benar berbukti
    (None bila tak ada evidence_log). `unverified` = klaim yang HARUS
    diinvestigasi sebelum dijadikan dasar keputusan."""
    log = analysis.get("evidence_log") if isinstance(analysis, dict) else None
    if not isinstance(log, list) or not log:
        return {"verified": [], "unverified": [], "integrity": None}
    verified, unverified = [], []
    for item in log:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        evidence = str(item.get("evidence") or "").strip()
        ctype = str(item.get("type") or "").strip().lower()
        if evidence and ctype == "fact":
            verified.append({"claim": claim, "evidence": evidence[:300]})
        else:
            unverified.append({"claim": claim,
                               "evidence": evidence[:300] or "(tidak ada)",
                               "type": ctype or "assumption"})
    total = len(verified) + len(unverified)
    integrity = round(len(verified) / total, 3) if total else None
    return {"verified": verified, "unverified": unverified, "integrity": integrity}


class CasperEngineerAgent(BaseAgent):
    """Agen software-engineer otonom. Menghasilkan artefak engineering yang
    terstruktur & teraudit untuk sebuah goal, mengikuti pilar Senior Engineer +
    Tech Lead + QA + Architect. Setiap tahap fail-open (LLM down -> default aman,
    ditandai `_llm_unavailable`) supaya deterministik & bisa diuji tanpa API."""

    name = "casper_engineer"
    system_prompt = (
        "Kamu adalah Casper Engineer — AI Software Engineer otonom kelas dunia yang "
        "bekerja sekaligus sebagai Senior Software Engineer, Tech Lead, QA Engineer, "
        "dan Solution Architect.\n\n"
        "DISIPLIN BERBASIS BUKTI (WAJIB):\n"
        "- Setiap kesimpulan HARUS didukung bukti konkret: path file, nomor baris, "
        "nama simbol (fungsi/kelas), atau hasil pembacaan tool. Tanpa bukti = asumsi.\n"
        "- Bedakan tegas FAKTA (terverifikasi dari repo) vs ASUMSI (belum terverifikasi) "
        "dan beri label eksplisit. JANGAN pernah menyajikan asumsi sebagai fakta.\n"
        "- DILARANG mengarang struktur folder, nama file, dependency, atau perilaku "
        "kode yang belum kamu baca. Bila belum ada bukti, tandai 'perlu diverifikasi' "
        "dan sebutkan aksi baca yang harus dilakukan — jangan menebak.\n"
        "- Jangan menyatakan sebuah fitur/kode 'tidak ada' tanpa benar-benar mencarinya.\n"
        "- Bila konteks repo tidak lengkap/tak cukup untuk menilai dengan aman, HENTIKAN "
        "audit dan minta/lakukan investigasi dulu — jangan memaksakan kesimpulan.\n\n"
        "PROSES KERJA KANONIK: Observe -> Verify -> Collect Evidence -> Analyze -> "
        "Critique -> Improve -> Plan -> Implement -> Review -> Test -> Report.\n\n"
        "ARSITEKTUR: kenali & namai pola NYATA yang terlihat (layered, clean, "
        "hexagonal, DDD, event-driven, microservices, modular-monolith, CQRS) DENGAN "
        "BUKTI, bukan pola yang 'seharusnya'.\n\n"
        "Utamakan: paham tujuan sebelum bertindak, hormati konvensi project, rencana "
        "eksploratif yang aman, kode production (clean/scalable/maintainable/secure), "
        "uji, dan kritik hasil sendiri. Jangan menulis kode tanpa rencana. Balas HANYA "
        "dalam format JSON yang diminta."
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
            "structure": "", "architecture": "", "dependencies": [], "conventions": [],
            "existing_patterns": [], "integration_points": [], "constraints": [],
            "evidence_log": [], "_llm_unavailable": True,
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
                    "titik integrasi, dan batasan. Namai pola ARSITEKTUR nyata yang terlihat "
                    f"(mis. {', '.join(ARCHITECTURE_PATTERNS[:6])}).\n\n"
                    "WAJIB berbasis bukti: untuk tiap klaim penting isi `evidence_log` dengan "
                    "bukti dari KONTEKS REPO di atas (path/nama file/simbol) dan tandai "
                    "type='fact' bila terlihat langsung, atau type='assumption' bila hanya "
                    "dugaan yang masih perlu dibaca. JANGAN mengarang.\n\n"
                    'Jawab HANYA JSON: {"structure": "<ringkas>", "architecture": "<nama pola>", '
                    '"dependencies": ["..."], "conventions": ["..."], "existing_patterns": ["..."], '
                    '"integration_points": ["..."], "constraints": ["..."], '
                    '"evidence_log": [{"claim": "...", "evidence": "file/simbol", "type": "fact|assumption"}]}'
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

    # ── Tahap 5: SELF-SCORE (rubrik pelatihan) ──────────────────────────
    async def _score(self, goal: str, plan: dict, analysis: dict,
                     verification: dict, critique: dict) -> dict:
        """Nilai mandiri hasil audit/rencana pada rubrik 7-dimensi (0..10).
        Skor tinggi HANYA jika didukung bukti nyata. Ambang & retrain dihitung
        deterministik di `_finalize_score` (bukan dipercayakan ke LLM). Fail-open."""
        out = await self._call_llm_json(
            [
                {"role": "system", "content": (
                    "Kamu penilai mandiri Casper Engineer (mentor senior). Nilai kualitas "
                    "hasil audit/rencana engineering ini secara JUJUR & KETAT pada skala "
                    f"0..10 untuk tiap dimensi: {', '.join(SCORE_DIMENSIONS)}. Skor tinggi "
                    "HANYA bila didukung bukti nyata (bukan klaim). Balas HANYA JSON."
                )},
                {"role": "user", "content": (
                    f"GOAL:\n{goal}\n\nPLAN:\n{json.dumps(plan, ensure_ascii=False)[:2000]}\n\n"
                    f"REPO ANALYSIS:\n{json.dumps(analysis, ensure_ascii=False)[:2000]}\n\n"
                    f"VERIFICATION:\n{json.dumps(verification, ensure_ascii=False)[:800]}\n\n"
                    f"CRITIQUE:\n{json.dumps(critique, ensure_ascii=False)[:1500]}\n\n"
                    'Jawab HANYA JSON: {"scores": {"accuracy": 0-10, "reasoning": 0-10, '
                    '"architecture": 0-10, "security": 0-10, "maintainability": 0-10, '
                    '"scalability": 0-10, "professionalism": 0-10}, "justification": "<ringkas kenapa>"}'
                )},
            ],
            temperature=0.0, max_tokens=700,
            default={"scores": {}, "justification": "", "_llm_unavailable": True},
        )
        return self._finalize_score(out)

    @staticmethod
    def _finalize_score(out: dict) -> dict:
        """Normalisasi skor LLM -> rubrik final. Hitung overall + tentukan dimensi
        terlemah & retrain_needed (any dim < ambang) secara deterministik."""
        raw = out.get("scores") if isinstance(out, dict) else None
        scores: dict[str, float] = {}
        if isinstance(raw, dict):
            for dim in SCORE_DIMENSIONS:
                try:
                    scores[dim] = max(0.0, min(10.0, round(float(raw.get(dim)), 2)))
                except (TypeError, ValueError):
                    continue
        overall = round(sum(scores.values()) / len(scores), 2) if scores else None
        weakest = sorted((d for d in scores if scores[d] < SCORE_PASS_THRESHOLD),
                         key=lambda d: scores[d])
        return {
            "scores": scores,
            "overall": overall,
            "pass_threshold": SCORE_PASS_THRESHOLD,
            "weakest_dimensions": weakest,
            "retrain_needed": bool(weakest) if scores else None,
            "justification": str(out.get("justification") or "")[:800],
            "_llm_unavailable": bool(out.get("_llm_unavailable")),
        }

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
        # Rubrik pelatihan: nilai mandiri hasil (Observe..Report) & tandai retrain.
        self_score = await self._score(goal, plan, analysis, verification, critique)
        # Anti-asumsi (deterministik): mana klaim berbukti vs yang wajib diinvestigasi.
        evidence = _audit_evidence(analysis)

        # LLM benar-benar down di SEMUA tahap -> tandai degraded (bukan sukses palsu).
        degraded = all(
            stage.get("_llm_unavailable")
            for stage in (plan, analysis, verification, critique, self_score)
            if isinstance(stage, dict)
        )
        confidence = None
        try:
            confidence = float(critique.get("overall_confidence")) if not degraded else None
        except (TypeError, ValueError):
            confidence = None

        # Gerbang: repo tak lengkap -> HALT (jangan paksakan kesimpulan tanpa bukti).
        repo_incomplete = bool(analysis.get("_needs_repo_context"))
        if repo_incomplete:
            status = "repo_incomplete"
        elif degraded:
            status = "degraded"
        elif verification.get("complete"):
            status = "verified"
        else:
            status = "needs_review"

        output = {
            "goal": goal,
            "planning": plan,
            "repository_analysis": analysis,
            "self_verification": verification,
            "self_critique": {"issues": critique.get("issues", []),
                              "improved_plan": critique.get("improved_plan", {})},
            "self_score": self_score,
            "evidence_integrity": evidence,
            "confidence": confidence,
            "status": status,
            "needs_repo_context": repo_incomplete,
            "retrain_needed": self_score.get("retrain_needed"),
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
