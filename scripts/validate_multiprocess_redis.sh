#!/usr/bin/env bash
# Validasi MULTI-PROSES fondasi P0 terhadap Redis NYATA (via redislite, tanpa sudo).
#
# Membuktikan shared-state benar-benar konsisten LINTAS-PROSES: 2 instance uvicorn
# (STATE_BACKEND=redis) berbagi rate-limit lewat satu Redis → hit ke-6 (limit 5)
# balas 429 meski disebar 3+3 ke instance berbeda. Kalau state per-proses, takkan
# pernah 429. Idempoten & self-cleaning (trap). Butuh: pip install redislite.
#
# Jalankan: bash scripts/validate_multiprocess_redis.sh
set -u
cd "$(dirname "$0")/.."

KEEPER="" ; U1="" ; U2="" ; PREV=""
cleanup() {
  set +e
  [ -n "$U1" ] && kill "$U1" 2>/dev/null
  [ -n "$U2" ] && kill "$U2" 2>/dev/null
  [ -n "$KEEPER" ] && kill "$KEEPER" 2>/dev/null
  sleep 2
  # kembalikan 1 uvicorn normal (inprocess) di :8000
  nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 >/tmp/bn_uvicorn.log 2>&1 &
}
trap cleanup EXIT

# 1) redis-server ASLI (redislite) di TCP 6399
nohup python3 -c "import redislite,time; r=redislite.Redis(serverconfig={'port':'6399'}); time.sleep(900)" >/tmp/rediskeeper.log 2>&1 &
KEEPER=$!
for i in $(seq 1 40); do (echo > /dev/tcp/127.0.0.1/6399) 2>/dev/null && break; sleep 0.5; done
echo "redislite 6399 UP"

# 2) matikan uvicorn :8000 lama, start 2 instance mode REDIS
PID=$(ss -ltnp 2>/dev/null | grep ':8000' | grep -oP 'pid=\K[0-9]+' | head -1); [ -n "$PID" ] && kill "$PID"; sleep 1
STATE_BACKEND=redis REDIS_URL=redis://127.0.0.1:6399/0 nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 >/tmp/u1.log 2>&1 & U1=$!
STATE_BACKEND=redis REDIS_URL=redis://127.0.0.1:6399/0 nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8001 >/tmp/u2.log 2>&1 & U2=$!
for p in 8000 8001; do for i in $(seq 1 40); do sleep 1; curl -sf "http://127.0.0.1:$p/health" >/dev/null 2>&1 && break; done; done
echo "kedua instance HEALTHY (fallback-count harus 0):"
grep -cih "fallback inprocess" /tmp/u1.log /tmp/u2.log

# 3) uji rate-limit shared (limit 5/menit per-IP; 3×:8000 + 3×:8001)
codes=""
for port in 8000 8000 8000 8001 8001 8001; do
  c=$(curl -s -o /dev/null -w "%{http_code}" -m 20 -X POST "http://127.0.0.1:$port/api/public/investor-demo" -H 'Content-Type: application/json' -d '{}')
  echo "  hit :$port -> $c"; codes="$codes $c"
done
last=$(echo "$codes" | awk '{print $NF}')
echo "urutan:$codes"
if [ "$last" = "429" ]; then echo "PASS ✅ shared rate-limit lintas-proses (hit ke-6 = 429)"; exit 0
else echo "FAIL ❌ hit ke-6 = $last (harus 429) — state TIDAK shared"; exit 1; fi
