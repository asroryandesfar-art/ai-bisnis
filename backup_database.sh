#!/usr/bin/env bash
set -euo pipefail
umask 077
BASE="${BOTNESIA_DATA_HOME:-$HOME/.local/share/botnesia}"
PG_ROOT="${BOTNESIA_PG_ROOT:-$BASE/postgres-runtime}"
PG_BIN="$PG_ROOT/usr/lib/postgresql/16/bin"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$BASE/backups/$STAMP"
mkdir -p "$TARGET"
chmod 700 "$BASE/backups" "$TARGET"
export LD_LIBRARY_PATH="$PG_ROOT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$PG_BIN/pg_dump" -h localhost -U postgres -d botnesia -Fc -f "$TARGET/botnesia.dump"
"$PG_BIN/pg_dumpall" -h localhost -U postgres --globals-only -f "$TARGET/globals.sql"
"$PG_BIN/psql" -h localhost -U postgres -d botnesia -Atc   "SELECT (SELECT count(*) FROM organizations),(SELECT count(*) FROM users),(SELECT count(*) FROM conversations),(SELECT count(*) FROM messages);"   > "$TARGET/counts.txt"
printf '%s\n' "$TARGET" > "$BASE/latest-backup-path"
find "$BASE/backups" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf -- {} +
echo "Backup selesai: $TARGET"
