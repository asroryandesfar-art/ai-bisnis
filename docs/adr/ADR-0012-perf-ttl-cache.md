# ADR-0012 — Performance: TTL cache untuk hot-path poll (P2-D)

- **Status:** Accepted — `perf_cache.TTLCache` + wiring `RuntimeMonitor` (opt-in) selesai
- **Tanggal:** 2026-07-23
- **Konteks fase:** Fase 3 (Efisiensi & Operabilitas), item **P2-D**
- **Terkait:** ADR-0011 (Runtime Observability — sumber hot-path), ADR-0010 (Prompt Registry — calon adopter)

## Konteks
P2-C menambah SSE `/api/runtime/stream` yang mem-poll `RuntimeMonitor.health_snapshot`
tiap `interval_s` **per koneksi**. Banyak operator streaming dashboard org yang sama
→ N× agregasi DB IDENTIK (tiap snapshot = 4 query: status, derived, workers, eval).
Ini hot-path read-heavy yang **toleran basi beberapa detik** (angka dashboard tak
harus real-time-per-milidetik) — kandidat sempurna cache TTL pendek. YAGNI: tak
membangun framework cache besar; cukup utilitas minimal untuk kasus nyata ini.

## Keputusan
Modul mandiri **`perf_cache`**: `TTLCache` (dict + expiry monotonic, `maxsize` +
evict expired→FIFO, `hits/misses/stats`) + helper `get_or_compute(cache, key, ttl,
factory)`. `ttl<=0` → **BYPASS** total (identik tanpa-cache).

Wiring **`RuntimeMonitor(cache_ttl_s=0.0)`**: `health_snapshot`/`evaluation_trends`
di-cache per `(org, window)` bila `cache_ttl_s>0`. Router memakai instance monitor
**tunggal** (dibuat sekali saat mount) → cache dibagi lintas koneksi/permintaan;
TTL default **2s** (env `RUNTIME_OBS_CACHE_TTL_S`, 0=nonaktif). Default kelas
`cache_ttl_s=0.0` → tanpa cache, byte-identik (dipakai test langsung & pemakai lain).

**Benchmark (50 poll snapshot org sama):** cache OFF = 200 DB-call; cache ON (2s) =
**4 DB-call (−98%)**, hit_rate 0.98.

## Alternatif
1. **Single-flight lock (in-proc).** Ditolak untuk gate awal: nambah kompleksitas; TTL sudah mengumpulkan poll sekuensial lintas koneksi (poll SSE ter-stagger, bukan serempak). Bisa ditambah bila profil menunjukkan thundering-herd.
2. **Redis cache lintas-worker.** Berlebihan: snapshot per-worker cukup segar; TTL 2s per-worker → beban DB turun drastis tanpa dependensi baru. Redis-cache bisa menyusul bila banyak worker.
3. **TTLCache in-proc opt-in (DIPILIH).** Minimal, additive, reversible, default off byte-identik, hasil terukur.

## Konsekuensi
**Positif:** beban DB observability turun ~98% saat banyak stream; utilitas reusable
untuk hot-path lain (mis. `PromptRegistry.resolve` saat diadopsi agen). **Batasan:**
angka dashboard bisa basi hingga `cache_ttl_s` detik (disengaja & wajar untuk ops);
cache per-proses (tiap uvicorn worker punya sendiri) → total DB-call = jumlah worker
× (poll/TTL), bukan global 1 — tetap turun drastis; tanpa single-flight, miss
serempak boleh compute ganda (jarang, aman).

## Rencana
- **P2-D (selesai):** `perf_cache` + wiring RuntimeMonitor (opt-in, default 2s di router) + 6 test + benchmark.
- **P2-D.2:** adopsi `perf_cache` di `PromptRegistry.resolve` (TTL pendek + invalidasi pada create/activate) saat prompt registry dipakai di hot-path agen; single-flight bila profil butuh; metrik cache di `/api/runtime/health`.

## Rollback
Set `RUNTIME_OBS_CACHE_TTL_S=0` (atau `cache_ttl_s=0`) → tanpa cache, perilaku
lama byte-identik. Modul `perf_cache` additive/idle bila tak dipakai.
