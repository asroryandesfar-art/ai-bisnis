"""Health/readiness probes, extracted verbatim from main.py.

/health does a shallow DB + schema check and reports AI-provider config;
/ready is a no-DB liveness probe. Both are DB/auth-light, so they are a safe,
test-covered slice of the main.py strangler split. Dependencies are injected
(factory-DI convention) to avoid an import cycle with main.
"""
from typing import Awaitable, Callable

from fastapi import APIRouter


def build_health_router(*, get_pool_safe: Callable[..., Awaitable], ensure_schema: Callable[..., Awaitable], cfg) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health():
        pool = await get_pool_safe()
        db_ok = False
        schema_ok = False
        if pool:
            try:
                await pool.fetchval("SELECT 1")
                db_ok = True
                schema_ok = await ensure_schema(pool)
            except Exception:
                pass
        return {
            "status":  "ok" if db_ok and schema_ok and bool(
                cfg.groq_api_key or cfg.deepseek_api_key or cfg.openrouter_api_key or cfg.effective_gemini_api_key
            ) else "degraded",
            "db":      db_ok,
            "schema":  schema_ok if db_ok else False,
            "ai": {
                "configured": bool(cfg.effective_gemini_api_key or cfg.groq_api_key or cfg.openrouter_api_key),
                "providers": {
                    "gemini": {
                        "active": bool(cfg.effective_gemini_api_key),
                        "model": cfg.gemini_model,
                        "pro_model": cfg.gemini_pro_model,
                    },
                    "deepseek": {
                        "active": bool(cfg.deepseek_api_key),
                        "models": ["deepseek-chat", "deepseek-reasoner"],
                    },
                    "openrouter": {
                        "active": bool(cfg.openrouter_api_key),
                        "note": "GPT-4o, DeepSeek, Qwen, and 200+ models",
                    },
                    "groq": {
                        "active": bool(cfg.groq_api_key),
                        "model": cfg.groq_model,
                    },
                },
                "routing": "gemini→openrouter→groq" if cfg.effective_gemini_api_key else (
                    "openrouter→groq" if cfg.openrouter_api_key else "groq"
                ),
            },
            "model": f"gemini:{cfg.gemini_model}" if cfg.effective_gemini_api_key else f"groq:{cfg.groq_model}",
            "version": "1.0.0",
        }

    @router.get("/ready")
    async def ready():
        """Liveness probe — process is running. Does not touch the DB."""
        return {"status": "ok"}

    return router
