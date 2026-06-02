from __future__ import annotations

import json
import sys
from urllib.request import urlopen


def main() -> int:
    try:
        with urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"ngrok API not reachable on http://127.0.0.1:4040: {e}")
        return 2

    tunnels = data.get("tunnels") or []
    https = None
    for t in tunnels:
        url = (t.get("public_url") or "").strip()
        if url.startswith("https://"):
            https = url
            break
    if not https and tunnels:
        https = (tunnels[0].get("public_url") or "").strip()

    if not https:
        print("No tunnels found. Is `ngrok http 8000` running?")
        return 3

    print(https)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

