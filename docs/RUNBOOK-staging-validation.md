# Runbook — Validasi Fondasi P0 di Staging (Redis + Celery NYATA)

Fondasi P0 (shared-state, feature-flags, event-bus, durable-runtime) sudah
diimplementasi & diuji vs Postgres nyata + fakeredis. Sebelum canary produksi,
lakukan validasi berikut dengan **Redis + Celery worker asli** (tak bisa di CI
tanpa server). Semua langkah reversible (matikan flag/env → perilaku lama).

## 0. Prasyarat
```bash
# Redis (broker + shared-state). Contoh:
sudo apt-get install -y redis-server && sudo systemctl start redis
redis-cli ping   # → PONG
pip install -r requirements-dev.txt   # (opsional, untuk skrip uji)
```

## 1. Aktifkan shared-state Redis (P0-A)
```bash
export STATE_BACKEND=redis
export REDIS_URL=redis://127.0.0.1:6379/0
```
Jalankan **2 instance** web di port berbeda (simulasi multi-worker):
```bash
uvicorn main:app --port 8000 &
uvicorn main:app --port 8001 &
```
**Cek log:** `Shared-state backend: Redis (...)` di kedua instance.

### Validasi
- **Rate-limit lintas-worker:** tembak endpoint ber-rate-limit (mis. `POST /api/research/run`, limit 5/menit) via port 8000 sebanyak 3× lalu port 8001 sebanyak 3× dengan token org yang sama → total ke-6 harus **429** (limit global, bukan ×2). Bila masih lolos 10×, `STATE_BACKEND` belum aktif.
- **Circuit-breaker lintas-worker:** matikan sementara satu provider LLM (mis. set key salah) → setelah 3 gagal di satu instance, instance lain harus ikut skip provider itu dalam ≤1 dtk.
- **Fail-open:** matikan Redis (`systemctl stop redis`) → app tetap melayani (rate-limit fail-open, breaker jatuh ke lokal). Nyalakan lagi → normal.

## 2. Durable Task Runtime (P0-D)
```bash
# worker + beat (proses terpisah). Pastikan env LLM (.env) ter-load di proses ini.
celery -A celery_app worker -l info -Q intelligence &
celery -A celery_app beat   -l info &
```
Aktifkan flag durable untuk 1 org canary:
```bash
export FEATURE_DURABLE_RUNTIME="canary:<ORG_ID_CANARY>"   # atau "on" utk semua
```

### Validasi end-to-end
1. **Enqueue → jalan → selesai:**
   ```bash
   curl -XPOST /api/jobs -H "Authorization: Bearer <JWT>" \
     -d '{"agent":"finance_agent","goal":"buat ringkasan penjualan"}'
   # → {job_id, status:"queued"}
   curl /api/jobs/<job_id>            # → status berpindah queued→running→completed
   curl -N /api/jobs/<job_id>/stream  # SSE progress realtime
   ```
   Cek: baris final tertulis ke `agent_task_executions` (backward-compat).
2. **Integrasi domain (opt-in):** `POST /api/finance/run-task?async=true` untuk org canary → balas `{"mode":"durable","job_id":...}`. Org non-canary → tetap inline (jalur lama).
3. **Chaos kill-worker→resume:** enqueue job panjang; saat `running`, `kill -9` worker. Beat `task_runtime.run_pending` (tiap 30 dtk) me-reclaim lease kadaluarsa → worker lain **resume dari checkpoint** (step selesai tak diulang). Cek `agent_job_steps`.
4. **Cancel/Pause/Resume:** `POST /api/jobs/<id>/cancel|pause|resume` saat running → status berubah di boundary step.
5. **DLQ replay:** paksa job gagal sampai `dead_letter` (mis. goal invalid + `max_attempts` kecil) → `POST /api/jobs/<id>/retry` → antre ulang.

## 3. SQL verifikasi cepat
```sql
SELECT status, count(*) FROM agent_jobs GROUP BY status;
SELECT job_id, seq, kind, status FROM agent_job_steps ORDER BY job_id, seq;
```

## 4. Beban (opsional, target skala)
- k6/Locust: 1.000 enqueue → pantau kedalaman antrean, throughput worker, p95 latency, lease-timeout.
- Skala worker: `celery ... --concurrency=N`; skala web: tambah instance (stateless krn shared-state di Redis).

## 5. Rollback
- `STATE_BACKEND=inprocess` + restart → shared-state kembali per-proses (perilaku lama).
- `FEATURE_DURABLE_RUNTIME` unset/`off` → semua run-task inline lagi.
- Matikan worker/beat → job mengendap di `queued` (tak ada efek ke jalur lama).

## Exit criteria (lolos → boleh canary prod)
Rate-limit & breaker terbukti shared lintas-instance; enqueue→worker→completed;
kill-worker→resume tanpa mengulang step; cancel/pause/DLQ-replay bekerja; fail-open
saat Redis mati; full suite tetap hijau; tak ada Critical/High baru.
