#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/.local/share/botnesia"
LOG="$BASE/tunnel/cloudflared.log"
URL_FILE="$BASE/public-url"
mkdir -p "$BASE/tunnel"
umask 077
# Tunnel permanen "botnesia" (botnesia.uk/www/app/api) -- ganti dari Quick
# Tunnel (--url, domain trycloudflare.com acak setiap restart) ke named
# tunnel berbasis ~/.cloudflared/config.yml, supaya domain publik stabil.
echo "https://botnesia.uk" > "$URL_FILE"
"$HOME/.local/bin/cloudflared" tunnel --no-autoupdate --config "$HOME/.cloudflared/config.yml" run 2>&1 | while IFS= read -r line; do
  printf '%s\n' "$line" >> "$LOG"
done
