#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/.local/share/botnesia"
LOG="$BASE/tunnel/cloudflared.log"
URL_FILE="$BASE/public-url"
mkdir -p "$BASE/tunnel"
umask 077
"$HOME/.local/bin/cloudflared" tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8000 2>&1 | while IFS= read -r line; do
  printf '%s\n' "$line" >> "$LOG"
  if [[ "$line" =~ (https://[a-z0-9-]+\.trycloudflare\.com) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}" > "$URL_FILE"
  fi
done
