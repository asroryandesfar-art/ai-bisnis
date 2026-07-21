# ADR-0001 — Shared State Abstraction (`platform_state`)

- **Status:** Accepted — **P0-A SELESAI** (C1–C5 semua diterapkan; A2 WS di-defer)
- **Tanggal:** 2026-07-21
- **Konteks fase:** Fase 1 Fondasi Platform, item **P0-A**
- **Terkait:** ADR durable-runtime (P0-D, menyusul), feature-flag (P0-B)

## Konteks
State kritis BotNesia tersimpan **in-process per-worker**, terbukti di audit:
- Rate limiter: `bn_platform/security.py:46 _org_timestamps` (deque, sinkron)
- Circuit breaker: `ai_providers/router.py:68 _breaker`
- Working-memory STM: `memory_agent.py:266 _global_store`
- WS device registry: `local_agent_router.LocalAgentManager`

Konsekuensi multi-worker: rate-limit efektif ×N worker, circuit-breaker tak
sinkron, STM tak konsisten, device terikat satu worker. Ini **blocker utama
horizontal scaling** menuju target ribuan worker / jutaan tenant.

## Keputusan
Perkenalkan satu **abstraksi `StateStore`** (async) dengan dua backend berkontrak
identik: `InProcessStateStore` (default, perilaku sekarang) dan `RedisStateStore`
(opt-in, lintas-worker). Pemilihan via `STATE_BACKEND` (default `inprocess`).
Konsumen (rate-limit, circuit-breaker, STM, lock) direfactor memakai interface —
signature pemanggil publik tidak berubah.

`rate_incr` dirancang meniru **persis** semantik `_check_rate_limit` (sliding-window
log; slot tidak dikonsumsi saat ditolak) → migrasi behavior-preserving & teruji.

## Alternatif yang dipertimbangkan
1. **Redis langsung tanpa abstraksi.** Ditolak: memaksa Redis di dev/test, sulit
   rollback, coupling erat.
2. **Memcached / Hazelcast.** Ditolak: Redis sudah jadi broker Celery (`celery_app.py:31`)
   — reuse infra, nol dependency baru.
3. **DB-only (Postgres advisory lock/tabel).** Ditolak untuk rate/breaker: latensi &
   beban tulis tinggi; Postgres tetap dipakai untuk state durable (job runtime).
4. **Abstraksi + dua backend (DIPILIH).** Risiko terkecil (default = perilaku lama),
   maintainability tertinggi (satu kontrak, tes kontrak bersama), scalable (Redis),
   biaya operasional rendah (reuse Redis existing).

## Konsekuensi
**Positif:** horizontal scaling terbuka; rate-limit/breaker konsisten lintas worker;
tes kontrak tunggal menjamin parity; rollback = ganti env → perilaku lama byte-identik.
**Negatif / mitigasi:** Redis jadi dependency shared-state → fail-open untuk rate-limit
& breaker hybrid lokal saat Redis down; latensi Redis per-call breaker → cache lokal
TTL pendek (C4).

## Rencana bertahap
- **C1 (selesai):** paket `platform_state/` (interface + InProcess + 12 contract test). Zero wiring, zero-behavior-change.
- **C2 (selesai):** `RedisStateStore` (Lua atomik untuk `rate_incr`/`release_lock`) + `STATE_BACKEND`/`REDIS_URL` + wiring startup fail-open (`main._init_shared_state`). 10 parity test via fakeredis+lupa + 3 wiring test. Default tetap inprocess. **Catatan clock:** rate-limit ZSET memakai wall-clock klien (`time.time()`) — konsisten antar-worker dengan asumsi NTP/same-host; varian pakai `redis TIME` server-side adalah follow-up bila skew antar-host jadi masalah.
- **C3 (selesai):** rate-limiter `security._check_rate_limit` → `StateStore.rate_incr` (key prefix `rl:`). Fungsi jadi **async**; codemod `await` seragam di **24 call-site** (12 modul bn_platform + indirection main.py), diverifikasi 100% statik (grep: nol call tanpa `await`). Default in-process = perilaku & pesan 429 identik; `STATE_BACKEND=redis` → rate-limit lintas-worker. Bukan 5 call-site seperti asumsi awal — ternyata 24; codemod async dipilih (bukan sync-redis) demi integritas abstraksi + verifikasi statik penuh. Test paritas in-process & Redis (`test_rate_limit_shared_state.py`).
- **C4 (selesai):** circuit-breaker `ai_providers/router.py` HYBRID — fast-path lokal (in-process) + mirror `open_until` (wall-clock) ke `StateStore` (`cb:{provider}`). `is_open/ok/fail` jadi async; baca lintas-worker DI-THROTTLE (`_SYNC_TTL=1s/provider`) supaya tak menambah latensi jalur panas LLM (bench `is_open` ~2.1M ops/s). `state()` tetap sync (dipakai `status()`, tanpa I/O). 25 call-site di router.py di-await (verifikasi statik). Cross-worker: provider yang di-open satu worker terlihat worker lain ≤1s (bila redis). 5 test (unit + cross-worker via shared store).
- **C5:** working-memory STM → `StateStore`.
- **C5 (selesai):** working-memory STM (`memory_agent.MemoryStore`) → `StateStore.lpush_trim/lrange` (`mem:stm:{conv}`, trim 60 + TTL 1h). `add_to_stm/clear_stm` jadi async (+`get_recent` async baru); 2 call-site di-await. **Temuan:** STM ternyata **write-only/vestigial** — `get_recent`/`get_stm` tak pernah dibaca untuk reasoning, `_short` dict tumbuh selamanya (leak). Migrasi ini memperbaiki leak (TTL di redis) & menutup state in-process terakhir. **Rekomendasi follow-up:** wire `get_recent()` ke `enrich_context` agar STM berguna, ATAU hapus STM sepenuhnya (sumber sudah = tabel `messages`). 6 test.
- **A2 (defer):** WS device registry cross-worker (pub/sub).

## Rollback
`STATE_BACKEND=inprocess` (default) → perilaku sekarang. Paket bisa idle tanpa efek.

## Exit criteria
Contract suite hijau di kedua backend; integrasi 2-instance shared; chaos Redis-down
degrade aman; full suite tetap hijau; canary prod 48 jam bersih.
