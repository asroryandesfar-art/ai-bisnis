# ADR-0008 — Policy Engine

- **Status:** Accepted — engine + hook PII-memory (P1-C.1) + hook tool/url @execute_tool + ruleset per-org DB (P1-C.2) selesai
- **Tanggal:** 2026-07-22 (P1-C.2: 2026-07-23)
- **Konteks fase:** Fase 2 (Cognitive Core), item **P1-C**
- **Terkait:** ADR-0004 (durable runtime), ADR-0006 (memory — konsumen PII-mask), ADR-0014 (terminal), approval workflow existing

## Addendum P1-C.2 (2026-07-23) — hook enforcement + ruleset per-org
Policy engine kini DITEGAKKAN di titik dispatch tool tunggal `tool_executor.
execute_tool` via `_policy_gate` (flag-gated `is_enabled("policy_engine", org_id)`,
**fail-open** — error internal policy tak pernah memutus eksekusi):
- **URL blacklist → BLOCK** untuk tool ber-argumen `url` (web_read/browser_open/
  webhook_call) SEBELUM dispatch (mis. cegah exfil/SSRF ke domain terlarang).
- **Tool berbahaya → APPROVAL** (`dangerous_tools`, kini termasuk nama executor
  NYATA: terminal_execute/file_write/action_execute — sebelumnya cuma nama abstrak
  yang tak match dispatch).

Ruleset **per-org** dari tabel baru `org_policy_rules` (JSONB, additive, di-merge
atas `DEFAULT_RULES`) via `policy_engine.loader.load_org_policy` (cache 5s pakai
`perf_cache` agar tak query DB tiap tool-call) + `set_org_policy` (invalidasi cache).
Default OFF / tanpa baris → perilaku byte-identik. GOTCHA: main pool tanpa jsonb
codec → `_coerce_rules` parse string. `check_cost` belum di-wire di dispatch (biaya
tak diketahui saat dispatch tool — hook cost menyusul di jalur model/LLM). `mask`
tetap dipakai di memory (P1-C.1).

## Konteks
Audit: cek governance TERSEBAR (denylist terminal, SSRF, approval per-tempat) —
tak ada engine terpadu untuk aturan deklaratif (cost>limit→approval, blacklist→
block, PII→mask, tool berbahaya→approval). Sulit audit & ubah konsisten.

## Keputusan
Modul mandiri `policy_engine` — `PolicyEngine(rules)` (default + override per-org)
menghasilkan `Decision(action ∈ allow|block|approval|mask, reason, detail)`:
- `check_tool` (dangerous_tools → approval, kecuali `approved`),
- `check_url` (blacklist_domains → block, cocok host + subdomain),
- `check_cost` (cost > cost_limit_usd → approval),
- `mask` (redaksi PII: email/phone/long-number → placeholder).
Pure (tanpa I/O) → testable & dipakai di banyak titik. Reuse approval workflow yang
sudah ada (mengembalikan APPROVAL, bukan mengeksekusi approval).

## Alternatif
1. **OPA/Rego (policy-as-code eksternal).** Ditolak: berat/ops untuk kebutuhan awal.
2. **Cek tersebar (status quo).** Ditolak: tak konsisten, sulit audit.
3. **Engine deklaratif mandiri (DIPILIH).** Risiko kecil, pure, testable, reuse approval existing.

## Konsekuensi
**Positif:** governance konsisten & terpusat; PII tak lagi tersimpan mentah di memori jangka-panjang (hook pertama). **Batasan:** pola PII heuristik (email/phone/number) — bisa diperluas; hook lengkap (tool_executor/web-intelligence/cost) bertahap.

## Rencana
- **P1-C.1 (selesai):** engine + 8 test; **hook PII-mask** di `DurableJobRunner` sebelum simpan episodic memory (gate `is_enabled("policy_engine", org_id)`). 1 test integrasi (PII ter-redaksi di `agent_memories`).
- **P1-C.2:** hook `check_tool` di tool_executor (dangerous → approval queue), `check_url` di web-intelligence (blacklist), `check_cost` di jalur biaya; ruleset per-org via DB + admin UI.

## Rollback
Flag `policy_engine` OFF → tak ada masking/enforcement baru (perilaku lama). Engine pure, bisa idle.
