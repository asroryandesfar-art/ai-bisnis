# platform_state — Shared State (P0-A)

Abstraksi shared-state lintas-worker untuk BotNesia. Satu kontrak `StateStore`,
dua backend berkontrak identik. Bagian dari **Fase 1 Fondasi Platform** (lihat
`docs/adr/ADR-0001-shared-state.md`).

## Kenapa
State kritis (rate-limit, circuit-breaker, working-memory STM, distributed-lock)
saat ini in-process per-worker → tak konsisten di multi-worker. Modul ini
memindahkannya ke belakang satu interface sehingga bisa dipindah ke Redis
**tanpa mengubah pemanggil** dan **reversible** (default tetap in-process).

## Status
- ✅ **C1** — interface + `InProcessStateStore` + 12 contract test (`test_platform_state.py`). Zero wiring, zero-behavior-change.
- ✅ **C2** — `RedisStateStore` (Lua atomik) + `STATE_BACKEND=redis`/`REDIS_URL` + wiring startup fail-open (`main._init_shared_state`). Parity via fakeredis+lupa (`test_platform_state_redis.py`) + wiring (`test_shared_state_wiring.py`). Default tetap inprocess.
- ⏳ C3–C5 — migrasi konsumen (rate-limiter, circuit-breaker, STM) ke `StateStore`.

### Mengaktifkan Redis (opsional)
```
STATE_BACKEND=redis
REDIS_URL=redis://host:6379/0
```
Bila init/healthcheck Redis gagal → **fallback otomatis ke inprocess** (fail-open, boot tak crash). Test Redis butuh dev-deps: `pip install -r requirements-dev.txt`.

## Pemakaian
```python
from platform_state import get_state_store

store = get_state_store()                       # singleton; default in-process
allowed, count = await store.rate_incr("rl:research:org123", window_s=60, limit=5)
if not allowed:
    ...  # tolak (429)

got = await store.acquire_lock("lock:job:42", ttl_s=30, token="worker-a")
```

## Kontrak `StateStore`
`get/set/delete/incr` · `hset/hget/hgetall` · `lpush_trim/lrange` ·
`rate_incr(window_s, limit) -> (allowed, count)` · `acquire_lock/release_lock` ·
`healthcheck`. Semua async; `incr/rate_incr/acquire_lock` wajib atomik.

`rate_incr` meniru **persis** `bn_platform.security._check_rate_limit` (sliding-window
log; slot tak dikonsumsi saat ditolak) → migrasi rate-limiter aman.

## Backend
| Backend | Kapan | Sifat |
|---|---|---|
| `InProcessStateStore` | default (`STATE_BACKEND=inprocess`) | per-proses; dev/test/single-worker; tak persisten |
| `RedisStateStore` (C2) | `STATE_BACKEND=redis` + `REDIS_URL` | lintas-worker; produksi multi-instance |

## Test
```bash
python3 -m pytest test_platform_state.py -q
```
Contract suite deterministik (clock di-mock, tanpa `sleep`). Suite yang sama akan
dijalankan ulang untuk `RedisStateStore` di C2 untuk menjamin parity.

## Rollback
`STATE_BACKEND=inprocess` → perilaku sekarang. Modul boleh tetap terpasang (idle).
