"""Real token streaming for chat.

Builds an ai_providers.SmartModelRouter from the app config and streams a single
completion (Gemini → DeepSeek → OpenRouter → Groq fallback, same as the rest of
the app). This is the fast streaming path used by POST /chat/{bot_id}/stream —
distinct from the full multi-agent /chat pipeline, which does not stream.
"""
from ai_providers.deepseek import DeepSeekProvider
from ai_providers.gemini import GeminiProvider
from ai_providers.groq_provider import GroqProvider
from ai_providers.openrouter import OpenRouterProvider
from ai_providers.router import SmartModelRouter
from ai_providers.types import LLMRequest


def build_provider_router(cfg) -> SmartModelRouter:
    """Assemble the provider router from configured API keys (only providers with
    a key are included; the router handles priority + fallback)."""
    gemini = (
        GeminiProvider(api_key=cfg.effective_gemini_api_key, model=cfg.gemini_model, pro_model=cfg.gemini_pro_model)
        if getattr(cfg, "effective_gemini_api_key", "") else None
    )
    groq = (
        GroqProvider(api_key=cfg.groq_api_key, model=cfg.groq_model, base_url=cfg.groq_base_url)
        if cfg.groq_api_key else None
    )
    openrouter = OpenRouterProvider(api_key=cfg.openrouter_api_key) if cfg.openrouter_api_key else None
    deepseek = DeepSeekProvider(api_key=cfg.deepseek_api_key) if cfg.deepseek_api_key else None
    return SmartModelRouter(gemini=gemini, groq=groq, openrouter=openrouter, deepseek=deepseek)


def any_provider_configured(cfg) -> bool:
    return bool(
        getattr(cfg, "effective_gemini_api_key", "") or cfg.groq_api_key
        or cfg.openrouter_api_key or cfg.deepseek_api_key
    )


async def stream_answer(messages: list[dict], cfg, *, temperature: float = 0.4, max_tokens: int = 1024):
    """Async generator yielding answer text chunks for the given chat messages."""
    router = build_provider_router(cfg)
    req = LLMRequest(messages=messages, temperature=temperature, max_tokens=max_tokens, stream=True)
    # NOTE: task_type must NOT be one of deepseek._SKIP_TASKS ('chat','cs','faq'…),
    # else the router resolves NO DeepSeek model and — with Gemini/Groq unconfigured
    # and OpenRouter often out-of-credit — streaming has no provider at all.
    # DeepSeek is the primary brain, so route this generic chat completion to it.
    async for chunk in router.stream(req, tier="standard", task_type="standard"):
        if chunk:
            yield chunk
