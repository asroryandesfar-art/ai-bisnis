"""
agent_api.py — FastAPI server untuk BotNesia Multi-Agent System

Cara sambungkan ke BotNesia:
  1. Jalankan server ini: uvicorn agent_api:app --reload --port 8001
  2. Di BotNesia (.env), tambahkan: AGENT_URL=http://localhost:8001
  3. Di main.py BotNesia, panggil agent pipeline setelah generate jawaban bot

Endpoints:
  POST /process     ← dipanggil BotNesia per pesan
  POST /webhook     ← menerima event dari BotNesia (conversation ended, dll)
  GET  /insights/{bot_id} ← dashboard analytics
  GET  /training/{bot_id} ← rekomendasi training terbaru
  GET  /health
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import vendor_bootstrap  # noqa: F401

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from supervisor import SupervisorAgent

# ─── INTELLIGENCE PLATFORM ────────────────────────────────────
# Conversation Memory, FAQ Engine, Sales Intelligence, Knowledge Graph,
# Customer Intelligence — lihat intelligence/ARCHITECTURE.md
from intelligence.routes_intelligence import intel_router
from intelligence.pipeline import persist_intelligence
from intelligence.db import get_pool as get_intelligence_pool

logger = logging.getLogger("agent_api.intelligence")


# ─── CONFIG ───────────────────────────────────────────────────

class Settings(BaseSettings):
    groq_api_key:        str = ""
    groq_model:          str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_cheap_model:    str = "llama-3.1-8b-instant"
    groq_base_url:       str = "https://api.groq.com/openai/v1"
    app_url:             str = "https://botnesia.id"
    botnesia_url:        str = "http://localhost:8000"   # URL server BotNesia utama
    agent_secret: str = os.environ.get('AGENT_SECRET', '')  # shared secret dengan BotNesia
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

cfg = Settings()


# ─── APP ──────────────────────────────────────────────────────

app = FastAPI(title="BotNesia Multi-Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoint /intel/* — Conversation Memory, FAQ, Sales Intelligence, Knowledge
# Graph, Analytics Dashboard, Auto-Learning reports, Customer Intelligence.
app.include_router(intel_router)

# In-memory store untuk insights (ganti Redis/DB di production)
_insights_store:  dict[str, list] = defaultdict(list)
_training_store:  dict[str, list] = defaultdict(list)
_analytics_store: dict[str, list] = defaultdict(list)


# ─── SUPERVISOR SINGLETON ─────────────────────────────────────

_supervisor: SupervisorAgent | None = None

def get_supervisor() -> SupervisorAgent:
    global _supervisor
    if _supervisor is None:
        if not cfg.groq_api_key:
            raise RuntimeError("GROQ_API_KEY belum diisi.")
        _supervisor = SupervisorAgent(
            api_key = cfg.groq_api_key,
            model   = cfg.groq_model,
            base_url = cfg.groq_base_url,
            app_url = cfg.app_url,
        )
    return _supervisor


# ─── MODELS ───────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    """Dikirim BotNesia setiap ada pesan masuk."""
    bot_id:          str
    org_id:          str
    conversation_id: str
    user_message:    str
    messages:        list[dict]        # riwayat percakapan
    knowledge_base_context: str = ""   # hasil RAG dari BotNesia
    resolved:        bool = False
    metadata:        dict = {}

class WebhookEvent(BaseModel):
    """Event dari BotNesia (conversation.ended, handoff.needed, dll)."""
    event:     str           # e.g. "conversation.ended"
    bot_id:    str
    org_id:    str
    conv_id:   str
    payload:   dict = {}
    timestamp: str  = ""


# ─── ROUTES ───────────────────────────────────────────────────

@app.post("/process")
async def process_message(
    req: ProcessRequest,
    x_agent_secret: str = Header(default=""),
) -> dict:
    if not req.bot_id or not req.org_id or not req.conversation_id or not req.user_message:
        raise HTTPException(400, "Input tidak lengkap")
    """
    Endpoint utama — dipanggil BotNesia setiap pesan masuk.
    Return: jawaban final + semua metadata agent untuk disimpan.

    Cara integrasi di main.py BotNesia:
      # Di chat() endpoint, SEBELUM return:
      import httpx
      agent_res = await httpx.AsyncClient().post(
          "http://localhost:8001/process",
          json={...},
          headers={"x-agent-secret": AGENT_SECRET},
      )
      agent_data = agent_res.json()
      # Pakai agent_data["final_answer"] sebagai jawaban
      # Simpan agent_data["analytics"] ke DB
      # Jika agent_data["should_escalate"], trigger webhook
    """
    if x_agent_secret != cfg.agent_secret:
        raise HTTPException(401, "Secret tidak valid")

    supervisor = get_supervisor()

    try:
        observability_pool = await get_intelligence_pool()
    except Exception:
        observability_pool = None

    context = {
        "bot_id":                req.bot_id,
        "org_id":                req.org_id,
        "conversation_id":       req.conversation_id,
        "user_message":          req.user_message,
        "messages":              req.messages,
        "knowledge_base_context": req.knowledge_base_context,
        "resolved":              req.resolved,
        "metadata":              req.metadata,
        "_observability_pool": observability_pool,
        "_cheap_model": cfg.groq_cheap_model,
        "_strong_model": cfg.groq_model,
    }

    result = await supervisor.process(context)

    # ── Intelligence Platform: persist setelah jawaban siap, TANPA menunggu ──
    # (fire-and-forget — lihat _persist_intelligence; kegagalan tidak boleh
    # mempengaruhi response /process)
    asyncio.create_task(persist_intelligence(dict(context), result))

    # Simpan insights ke store
    ts = datetime.now(timezone.utc).isoformat()

    _analytics_store[req.bot_id].append({
        "timestamp":        ts,
        "conversation_id":  req.conversation_id,
        "sentiment":        result.sentiment,
        "intent":           result.intent,
        "topics":           result.topics,
        "quality_score":    result.bot_quality_score,
        "friction_points":  result.friction_points,
        "product_insights": result.product_insights,
        "summary":          result.conversation_summary,
        "should_escalate":  result.should_escalate,
    })

    if result.training_examples or result.prompt_suggestions:
        _training_store[req.bot_id].append({
            "timestamp":        ts,
            "conversation_id":  req.conversation_id,
            "trainer_score":    result.trainer_score,
            "issues":           [],
            "improved_response": result.improved_response,
            "training_examples": result.training_examples,
            "prompt_suggestions": result.prompt_suggestions,
        })

    # Batas 500 record per bot (in-memory)
    if len(_analytics_store[req.bot_id]) > 500:
        _analytics_store[req.bot_id] = _analytics_store[req.bot_id][-500:]
    if len(_training_store[req.bot_id]) > 200:
        _training_store[req.bot_id] = _training_store[req.bot_id][-200:]

    # Response dipersempit: agent_api tidak mengembalikan meta "confidence/topics/suggested_followup"
    # agar konsisten dengan endpoint chat utama.
    return {
        "final_answer": result.final_answer,
        "latency_ms": result.total_latency_ms,
        "errors": result.errors,
    }


@app.post("/webhook")
async def receive_webhook(
    event: WebhookEvent,
    x_agent_secret: str = Header(default=""),
):
    """
    Terima event dari BotNesia.
    BotNesia kirim event ini dari dispatch_webhook() di main.py.
    """
    if x_agent_secret != cfg.agent_secret:
        raise HTTPException(401, "Secret tidak valid")

    # Event yang sudah dihandle
    handlers = {
        "conversation.ended":  _handle_conv_ended,
        "handoff.needed":      _handle_handoff,
        "rating.submitted":    _handle_rating,
    }

    handler = handlers.get(event.event)
    if handler:
        await handler(event)

    return {"received": True, "event": event.event}


async def _handle_conv_ended(event: WebhookEvent):
    """Tandai percakapan selesai di store."""
    _insights_store[event.bot_id].append({
        "type":    "conversation_ended",
        "conv_id": event.conv_id,
        "payload": event.payload,
        "ts":      datetime.now(timezone.utc).isoformat(),
    })


async def _handle_handoff(event: WebhookEvent):
    """Log handoff event."""
    _insights_store[event.bot_id].append({
        "type":    "handoff",
        "conv_id": event.conv_id,
        "payload": event.payload,
        "ts":      datetime.now(timezone.utc).isoformat(),
    })


async def _handle_rating(event: WebhookEvent):
    """Log rating dari pelanggan."""
    _insights_store[event.bot_id].append({
        "type":    "rating",
        "conv_id": event.conv_id,
        "rating":  event.payload.get("rating"),
        "ts":      datetime.now(timezone.utc).isoformat(),
    })


@app.get("/insights/{bot_id}")
async def get_insights(
    bot_id: str,
    limit: int = 50,
    x_agent_secret: str = Header(default=""),
):
    """
    Ambil analytics insights untuk satu bot.
    Dipanggil dari dashboard BotNesia halaman Statistik.
    """
    if x_agent_secret != cfg.agent_secret:
        raise HTTPException(401, "Secret tidak valid")

    records = _analytics_store.get(bot_id, [])[-limit:]

    if not records:
        return {"bot_id": bot_id, "total": 0, "insights": [], "aggregated": {}}

    # Agregasi cepat
    sentiments    = [r["sentiment"]["score"] for r in records if "sentiment" in r]
    quality_scores = [r["quality_score"] for r in records if "quality_score" in r]
    all_topics    = []
    all_friction  = []
    all_insights  = []
    escalated     = sum(1 for r in records if r.get("should_escalate"))

    for r in records:
        all_topics.extend(r.get("topics", []))
        all_friction.extend(r.get("friction_points", []))
        all_insights.extend(r.get("product_insights", []))

    # Hitung top topics
    topic_counts: dict[str, int] = {}
    for t in all_topics:
        topic_counts[t] = topic_counts.get(t, 0) + 1
    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "bot_id":  bot_id,
        "total":   len(records),
        "insights": records,
        "aggregated": {
            "avg_sentiment_score":  round(sum(sentiments) / len(sentiments), 3) if sentiments else 0,
            "avg_quality_score":    round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else 0,
            "escalation_rate":      round(escalated / len(records), 3) if records else 0,
            "top_topics":           [{"topic": t, "count": c} for t, c in top_topics],
            "common_friction":      list(set(all_friction))[:10],
            "product_insights":     list(set(all_insights))[:10],
        },
    }


@app.get("/training/{bot_id}")
async def get_training(
    bot_id: str,
    min_score: float = 0.0,
    limit: int = 20,
    x_agent_secret: str = Header(default=""),
):
    """
    Ambil rekomendasi training untuk satu bot.
    Filter berdasarkan minimum trainer score (default ambil semua).
    """
    if x_agent_secret != cfg.agent_secret:
        raise HTTPException(401, "Secret tidak valid")

    records = _training_store.get(bot_id, [])
    filtered = [r for r in records if r.get("trainer_score", 10) >= min_score][-limit:]

    # Kumpulkan semua prompt suggestions unik
    all_suggestions = []
    for r in filtered:
        all_suggestions.extend(r.get("prompt_suggestions", []))
    unique_suggestions = list(dict.fromkeys(all_suggestions))[:10]

    return {
        "bot_id":             bot_id,
        "total":              len(filtered),
        "records":            filtered,
        "top_suggestions":    unique_suggestions,
    }


@app.get("/health")
async def health():
    return {
        "status":  "ok" if cfg.groq_api_key else "degraded",
        "ai": {
            "configured": bool(cfg.groq_api_key),
            "provider": "groq" if cfg.groq_api_key else None,
            "model": cfg.groq_model if cfg.groq_api_key else None,
        },
        "model":   f"groq:{cfg.groq_model}" if cfg.groq_api_key else None,
        "agents":  [
            "supervisor", "cs_agent", "escalation_agent", "analytics_agent", "trainer_agent", "memory_agent",
            "faq_agent", "sales_agent", "knowledge_agent",
        ],
        "intelligence_routes": "/intel/* (dashboard, faq, sales, knowledge-graph, reports, customers)",
        "version": "1.0.0",
    }
