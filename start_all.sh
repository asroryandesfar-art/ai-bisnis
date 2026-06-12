#!/usr/bin/env bash
set -euo pipefail
units=(botnesia-postgres.service botnesia-api.service)
case "${1:-start}" in
  start)
    systemctl --user daemon-reload
    systemctl --user start "${units[@]}"
    ;;
  stop)
    systemctl --user stop botnesia-api.service botnesia-postgres.service
    ;;
  restart)
    systemctl --user daemon-reload
    systemctl --user stop botnesia-api.service
    systemctl --user restart botnesia-postgres.service
    systemctl --user start botnesia-api.service
    ;;
  status)
    systemctl --user --no-pager --full status "${units[@]}" || true
    ;;
  backup)
    exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backup_database.sh"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|backup}" >&2
    exit 2
    ;;
esac
