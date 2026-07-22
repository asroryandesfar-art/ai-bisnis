"""Server-Sent Events (SSE) streaming chat endpoint: POST /chat/{bot_id}/stream.

Real token streaming (see chat_streaming.stream_answer) with RAG context — a
fast path distinct from the full multi-agent /chat. Emits SSE events:
  start  -> {"session_id"}
  token  -> {"text"}            (one per model chunk)
  done   -> {"answer","session_id"}
  error  -> {"error"}
Dependencies are injected; stream_answer is injectable so tests need no real LLM.
"""
import json
import uuid
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_chat_stream_router(
    *,
    get_pool: Callable[..., Awaitable],
    cfg,
    retrieve_chunks: Callable[..., Awaitable[list]],
    language_middleware,
    ChatReq,
    stream_answer: Callable[..., object],
    any_provider_configured: Callable[..., bool],
) -> APIRouter:
    router = APIRouter()

    @router.post("/chat/{bot_id}/stream")
    async def chat_stream(bot_id: str, body: ChatReq, pool=Depends(get_pool)):
        bot = await pool.fetchrow(
            """SELECT id, org_id, system_prompt, language, computer_agent_enabled
               FROM bots WHERE id=$1 AND status IN ('active','training')""",
            bot_id,
        )
        if not bot:
            raise HTTPException(404, "Bot tidak aktif")
        if not any_provider_configured(cfg):
            raise HTTPException(503, "Tidak ada AI provider yang dikonfigurasi untuk streaming.")
        # Per-message decision: only actual browsing requests need the Computer
        # Agent (which the single-model stream path can't run). Signal the client
        # to fall back to the full /chat pipeline for those; everything else —
        # including normal chat on a Computer-Agent bot — streams on the base model.
        if bot.get("computer_agent_enabled"):
            try:
                from computer_agent import looks_like_computer_agent_request
                if looks_like_computer_agent_request(body.message):
                    raise HTTPException(409, "Computer-agent request — use full pipeline")
            except HTTPException:
                raise
            except Exception:
                pass  # detector unavailable -> just stream (still degrades gracefully)

        conv_id = body.session_id or str(uuid.uuid4())
        # Persist conversation + user message best-effort (never break the stream).
        try:
            await pool.execute(
                """INSERT INTO conversations (id, bot_id, org_id, channel)
                   VALUES ($1,$2,$3,'widget') ON CONFLICT (id) DO NOTHING""",
                conv_id, bot_id, bot["org_id"],
            )
            await pool.execute(
                "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,'user',$3)",
                str(uuid.uuid4()), conv_id, body.message,
            )
        except Exception:
            pass

        relevant_chunks = await retrieve_chunks(pool, str(bot["org_id"]), body.message, bot_id=bot_id)
        effective_lang = language_middleware.resolve_language(
            user_message=body.message, agent_language=bot.get("language"), conversation_language=None,
        )
        system = language_middleware.build_system_prompt(bot["system_prompt"], relevant_chunks, effective_lang)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": body.message},
        ]

        async def gen():
            yield _sse("start", {"session_id": conv_id})
            acc: list[str] = []
            try:
                async for token in stream_answer(messages, cfg, user_message=body.message,
                                                 org_id=str(bot["org_id"])):   # P2-A cost router (flag-gated)
                    acc.append(token)
                    yield _sse("token", {"text": token})
            except Exception:
                yield _sse("error", {"error": "Streaming gagal. Coba lagi."})
                return
            answer = "".join(acc)
            try:
                await pool.execute(
                    """INSERT INTO messages (id, conversation_id, role, content, model)
                       VALUES ($1,$2,'assistant',$3,'stream')""",
                    str(uuid.uuid4()), conv_id, answer,
                )
                await pool.execute(
                    "UPDATE conversations SET msg_count=msg_count+2, last_msg_at=NOW() WHERE id=$1", conv_id,
                )
            except Exception:
                pass
            yield _sse("done", {"answer": answer, "session_id": conv_id})

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
