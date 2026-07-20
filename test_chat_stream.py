"""Tests for the SSE streaming chat endpoint (POST /chat/{bot_id}/stream)."""
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

import language_middleware
from bn_platform.chat_stream import build_chat_stream_router

_BOT = {
    "id": "11111111-1111-1111-1111-111111111111",
    "org_id": "22222222-2222-2222-2222-222222222222",
    "system_prompt": "Kamu asisten.", "language": "id",
}


class FakePool:
    def __init__(self, bot=_BOT):
        self._bot = bot
        self.executed = []

    async def fetchrow(self, sql, *a):
        return self._bot if "FROM bots" in sql else None

    async def execute(self, sql, *a):
        self.executed.append(sql)
        return "OK"


async def _fake_retrieve(*a, **k):
    return []


def _app(*, bot=_BOT, tokens=("Ha", "lo", "!"), provider=True, boom=False):
    async def _stream(messages, cfg, **k):
        if boom:
            raise RuntimeError("provider down")
        for t in tokens:
            yield t

    # Use the real ChatReq so FastAPI validates the body.
    import main
    app = FastAPI()
    app.include_router(build_chat_stream_router(
        get_pool=lambda: FakePool(bot),
        cfg=types.SimpleNamespace(),
        retrieve_chunks=_fake_retrieve,
        language_middleware=language_middleware,
        ChatReq=main.ChatReq,
        stream_answer=_stream,
        any_provider_configured=lambda cfg: provider,
    ))
    return app


def _events(text):
    """Parse SSE text into [(event, data_str), ...]."""
    out = []
    ev = None
    for line in text.splitlines():
        if line.startswith("event:"):
            ev = line[len("event:"):].strip()
        elif line.startswith("data:"):
            out.append((ev, line[len("data:"):].strip()))
    return out


def test_streams_tokens_then_done():
    c = TestClient(_app(tokens=("Ha", "lo", "!")))
    r = c.post("/chat/bot-1/stream", json={"message": "halo"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = _events(r.text)
    kinds = [e for e, _ in evs]
    assert kinds[0] == "start"
    assert kinds.count("token") == 3
    assert kinds[-1] == "done"
    assert '"answer": "Halo!"' in r.text


def test_unknown_bot_404():
    c = TestClient(_app(bot=None))
    r = c.post("/chat/nope/stream", json={"message": "halo"})
    assert r.status_code == 404


def test_no_provider_503():
    c = TestClient(_app(provider=False))
    r = c.post("/chat/bot-1/stream", json={"message": "halo"})
    assert r.status_code == 503


_CA_BOT = {**_BOT, "computer_agent_enabled": True}


def test_computer_agent_bot_streams_normal_message():
    # Normal chat on a Computer-Agent bot must still stream on the base model.
    c = TestClient(_app(bot=_CA_BOT, tokens=("Ha", "i")))
    r = c.post("/chat/bot-1/stream", json={"message": "halo apa kabar"})
    assert r.status_code == 200
    assert "event: token" in r.text


def test_computer_agent_bot_409_on_browsing_request():
    # A real browsing request signals the client to fall back to the full /chat
    # pipeline (which runs the Computer Agent) instead of streaming single-model.
    c = TestClient(_app(bot=_CA_BOT))
    r = c.post("/chat/bot-1/stream", json={"message": "tolong buka website tokopedia lalu screenshot"})
    assert r.status_code == 409


def test_stream_error_emits_error_event():
    c = TestClient(_app(boom=True))
    r = c.post("/chat/bot-1/stream", json={"message": "halo"})
    assert r.status_code == 200
    kinds = [e for e, _ in _events(r.text)]
    assert "error" in kinds
    assert "done" not in kinds


def test_persists_user_and_assistant_messages():
    import main
    shared = FakePool()  # one pool instance so we can inspect what was executed

    async def _stream(messages, cfg, **k):
        yield "hi"

    app = FastAPI()
    app.include_router(build_chat_stream_router(
        get_pool=lambda: shared, cfg=types.SimpleNamespace(),
        retrieve_chunks=_fake_retrieve, language_middleware=language_middleware,
        ChatReq=main.ChatReq, stream_answer=_stream, any_provider_configured=lambda cfg: True,
    ))
    TestClient(app).post("/chat/bot-1/stream", json={"message": "halo"})
    assert any("INSERT INTO messages" in s and "'user'" in s for s in shared.executed)
    assert any("INSERT INTO messages" in s and "'assistant'" in s for s in shared.executed)
