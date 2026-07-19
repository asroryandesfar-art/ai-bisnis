"""Realtime observability — push status eksekusi agent ke dashboard via WebSocket.

Dashboard membuka WS /api/observability/ws?token=<jwt>. `observe_agent`
(agent_observability.py) mem-publish event transisi status (running/retrying/
final) ke hub; hub menyiarkan ke semua koneksi dashboard org tsb → status
berubah tanpa reload browser. Single-process (uvicorn 1 worker) → hub in-memory.
"""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ObservabilityHub:
    """Pub/sub in-memory per org untuk event observability realtime."""

    def __init__(self):
        self._conns: dict[str, set[WebSocket]] = {}

    def connect(self, org_id: str, ws: WebSocket) -> None:
        self._conns.setdefault(org_id, set()).add(ws)

    def disconnect(self, org_id: str, ws: WebSocket) -> None:
        conns = self._conns.get(org_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._conns.pop(org_id, None)

    def has(self, org_id: str) -> bool:
        return bool(self._conns.get(org_id))

    async def publish(self, org_id: str, event: dict) -> None:
        """Siarkan event ke semua dashboard org. Koneksi mati dibersihkan."""
        conns = list(self._conns.get(org_id) or ())
        if not conns:
            return
        dead = []
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(org_id, ws)


_hub = ObservabilityHub()


def get_hub() -> ObservabilityHub:
    return _hub


def build_observability_ws_router(*, decode_token) -> APIRouter:
    router = APIRouter()

    @router.websocket("/observability/ws")
    async def observability_ws(websocket: WebSocket, token: str = ""):
        await websocket.accept()
        try:
            payload = decode_token(token)
            org_id = str(payload["org"])
        except Exception:
            await websocket.send_json({"type": "error", "message": "Token tidak valid"})
            await websocket.close(code=4001)
            return

        hub = get_hub()
        hub.connect(org_id, websocket)
        await websocket.send_json({"type": "connected", "message": "Realtime observability aktif"})
        try:
            # Terima ping/keep-alive dari klien; tak butuh payload khusus.
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug("observability_ws org=%s: %s", org_id, exc)
        finally:
            hub.disconnect(org_id, websocket)

    return router
