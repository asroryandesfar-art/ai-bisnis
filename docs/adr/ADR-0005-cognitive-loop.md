# ADR-0005 — Cognitive Loop (Planner→Worker→Critic)

- **Status:** Accepted — modul inti selesai (P1-A.1); integrasi konsumen menyusul (P1-A.2)
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 2 (Cognitive Core), item **P1-A** — gap #1 audit
- **Terkait:** ADR-0004 (durable runtime — tempat loop berjalan sbg job ber-checkpoint), ADR-0002 (feature flag)

## Konteks
Audit menemukan: eksekusi task **satu-lintasan** — orkestrator = ensemble paralel +
1× revisi (`multi_agent_orchestrator.py:122`), `task_engine` = plan→exec→verify sekali
lalu `failed` bila gagal. **Tidak ada** loop Critic→Worker-fix→(gagal)→Planner-replan.
Ini membatasi kualitas & keandalan jawaban untuk task kompleks.

## Keputusan
Modul mandiri `cognitive_loop.CognitiveLoop` mengimplementasikan state-machine:
Planner → Worker → Critic → (accept | revise | replan) → … → Done. Critic memberi
`score` (0..1) + `action`; Supervisor (loop) berhenti saat: diterima (score≥threshold
atau accept), budget habis (`max_iters`/`deadline_s`), atau **degraded** (LLM down →
best-effort, tak loop tak-hingga). Dependency-injected (agent cukup `_call_llm_json`),
fail-open, `worker_fn` opsional untuk mengganti Worker LLM dengan tool-loop
(`task_engine`) tanpa mengubah loop.

## Alternatif
1. **Perbanyak revisi di orchestrator (dari 1 → N).** Ditolak: tetap tanpa replan & tanpa Supervisor/budget; logika tercampur di orchestrator.
2. **Framework agent eksternal (LangGraph dsb).** Ditolak: dependency/lock-in besar untuk kebutuhan yang jelas & kecil.
3. **Modul loop mandiri (DIPILIH).** Risiko kecil (additive, fail-open, testable tanpa API), reusable oleh agent mana pun, gate flag.

## Konsekuensi
**Positif:** kualitas jawaban naik (perbaikan iteratif + replan), keandalan (budget/degraded guard), reusable & teruji deterministik.
**Batasan/mitigasi:** iterasi = lebih banyak panggilan LLM (biaya/latensi) → dibatasi `max_iters`/`deadline_s` + gate flag + jalan di durable runtime (tiap iterasi = step ber-checkpoint) agar aman untuk task panjang.

## Rencana
- **P1-A.1 (selesai):** modul `cognitive_loop` + 7 test (accept/revise/replan/max-iters/threshold/degraded/custom-worker). Zero wiring.
- **P1-A.2 (menyusul):** integrasi — `worker_fn` = tool-loop task_engine; jalankan loop sebagai durable job (checkpoint per-iterasi); ekspos via endpoint/agent method, gate `is_enabled("cognitive_loop", org_id)` (default OFF → jalur lama).
- **P1-A.3:** umpan skor Critic ke Evaluation (P1-D) & observability.

## Rollback
Konsumen di belakang flag → OFF = jalur single-pass lama. Modul bisa idle tanpa efek.
