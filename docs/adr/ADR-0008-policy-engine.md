# ADR-0008 — Policy Engine

- **Status:** Accepted — engine + hook PII-memory selesai (P1-C.1); hook tool/url/cost menyusul
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 2 (Cognitive Core), item **P1-C**
- **Terkait:** ADR-0004 (durable runtime), ADR-0006 (memory — konsumen PII-mask), approval workflow existing

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
