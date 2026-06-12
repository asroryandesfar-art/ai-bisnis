#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PG_ROOT="${BOTNESIA_PG_ROOT:-$HOME/.local/share/botnesia/postgres-runtime}"
PG_BIN="$PG_ROOT/usr/lib/postgresql/16/bin"
PGDATA="${BOTNESIA_PGDATA:-$HOME/.local/share/botnesia/postgres/data}"
PGSOCKET="${BOTNESIA_PGSOCKET:-$HOME/.local/share/botnesia/postgres/socket}"
PGPORT="${BOTNESIA_PGPORT:-5432}"

bootstrap_runtime() {
  if [ -x "$PG_BIN/postgres" ]; then
    return
  fi
  local packages=(
    "postgresql-common_257build1.1_all.deb"
    "libpq5_16.14-0ubuntu0.24.04.1_amd64.deb"
    "postgresql-client-16_16.14-0ubuntu0.24.04.1_amd64.deb"
    "postgresql-16_16.14-0ubuntu0.24.04.1_amd64.deb"
    "postgresql-16-pgvector_0.6.0-1_amd64.deb"
  )
  mkdir -p "$PG_ROOT"
  for package in "${packages[@]}"; do
    test -f "$PROJECT_DIR/$package" || { echo "Paket PostgreSQL hilang: $package" >&2; exit 1; }
    dpkg-deb -x "$PROJECT_DIR/$package" "$PG_ROOT"
  done
}

bootstrap_runtime
mkdir -p "$PGDATA" "$PGSOCKET"
chmod 700 "$PGDATA"
chmod 700 "$PGSOCKET"
export LD_LIBRARY_PATH="$PG_ROOT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$PG_BIN/postgres" -D "$PGDATA"   -c "unix_socket_directories=$PGSOCKET"   -c "dynamic_library_path=$PG_ROOT/usr/lib/postgresql/16/lib:\$libdir"   -c "port=$PGPORT"
