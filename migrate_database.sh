#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PG_ROOT="${BOTNESIA_PG_ROOT:-$HOME/.local/share/botnesia/postgres-runtime}"
PG_BIN="$PG_ROOT/usr/lib/postgresql/16/bin"
export LD_LIBRARY_PATH="$PG_ROOT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
for _ in $(seq 1 30); do
  "$PG_BIN/pg_isready" -h localhost -p 5432 -U postgres -d botnesia -q && break
  sleep 1
done
"$PG_BIN/psql" -v ON_ERROR_STOP=1 -h localhost -U postgres -d botnesia -f "$PROJECT_DIR/schema.sql" -q
"$PG_BIN/psql" -v ON_ERROR_STOP=1 -h localhost -U postgres -d botnesia -f "$PROJECT_DIR/intelligence/schema_intelligence.sql" -q
"$PG_BIN/psql" -v ON_ERROR_STOP=1 -h localhost -U postgres -d botnesia -f "$PROJECT_DIR/bn_platform/schema_platform.sql" -q
