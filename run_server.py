import socket
import urllib.error
import urllib.request
import uvicorn


def _is_botnesia_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _pick_port(host: str, preferred: int, fallbacks: list[int]) -> int:
    for port in [preferred, *fallbacks]:
        try:
            s = socket.socket()
            s.bind((host, port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("Tidak ada port yang tersedia (coba tutup server lain)")


if __name__ == "__main__":
    import sys
    command = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "start"
    if command not in {"start", "restart", "stop"}:
        print("Usage: python run_server.py [start|restart|stop]", flush=True)
        raise SystemExit(2)
    if command == "stop":
        print("Perintah stop belum dikelola oleh runner ini. Hentikan proses uvicorn yang aktif.", flush=True)
        raise SystemExit(0)
    if command == "restart":
        print("Restart diminta. Pastikan proses BotNesia lama sudah dihentikan.", flush=True)
    # Simple runner: tidak pakai --reload (lebih stabil di Windows tertentu)
    host = "127.0.0.1"
    preferred_port = 8000
    preferred_health = f"http://{host}:{preferred_port}/health"
    if _is_botnesia_running(preferred_health):
        print(f"BotNesia API already running on http://{host}:{preferred_port}", flush=True)
        print(f"- Health:    {preferred_health}", flush=True)
        print(f"- Dashboard: http://{host}:{preferred_port}/dashboard", flush=True)
        raise SystemExit(0)

    port = _pick_port(host, preferred_port, [8001, 8002, 8010])
    print(f"Starting BotNesia API on http://{host}:{port}", flush=True)
    print(f"- Health:    http://{host}:{port}/health", flush=True)
    print(f"- Dashboard: http://{host}:{port}/dashboard", flush=True)
    uvicorn.run("main:app", host=host, port=port, reload=False)
