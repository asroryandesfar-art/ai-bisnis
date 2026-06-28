"""
ai_providers/router.py — SmartModelRouter.

STANDARD tier + flash task types → Gemini Flash
PRO tier OR complex task types   → Gemini Pro → retry Flash → Groq fallback
Gemini unavailable               → Groq fallback
"""

import logging

from ai_providers.base import AIProvider
from ai_providers.types import LLMRequest, LLMResponse, PRO_TASK_TYPES, FLASH_TASK_TYPES

logger = logging.getLogger("botnesia.router")


class SmartModelRouter:
    def __init__(
        self,
        gemini: AIProvider | None = None,
        groq: AIProvider | None = None,
    ):
        self.gemini = gemini
        self.groq = groq

    def select_model(self, tier: str = "standard", task_type: str = "chat") -> str | None:
        """
        Returns the Gemini model name to use, or None if Gemini unavailable.
        Callers that get None should use Groq directly.
        """
        if not self.gemini or not self.gemini.is_available():
            return None

        task = (task_type or "chat").lower()
        use_pro = (tier == "pro") or (task in PRO_TASK_TYPES)

        from ai_providers.gemini import GeminiProvider
        if isinstance(self.gemini, GeminiProvider):
            return self.gemini.pro_model if use_pro else self.gemini.model

        return self.gemini.default_model

    def _flash_model(self) -> str | None:
        """Return the Gemini Flash model name, or None if unavailable."""
        if not self.gemini or not self.gemini.is_available():
            return None
        from ai_providers.gemini import GeminiProvider
        if isinstance(self.gemini, GeminiProvider):
            return self.gemini.model
        return None

    async def route(
        self,
        request: LLMRequest,
        *,
        tier: str = "standard",
        task_type: str = "chat",
    ) -> LLMResponse:
        """
        Route a request to the best available provider.
        Tries Gemini (Pro or Flash by tier) first.
        On failure, retries with Gemini Flash before falling back to Groq.
        """
        model = self.select_model(tier, task_type)

        if model and self.gemini and self.gemini.is_available():
            try:
                result = await self.gemini.complete(request, model=model)
                if result.error is None:
                    return result
                logger.warning("gemini error model=%s err=%s — retrying with flash", model, result.error)
            except Exception as exc:
                logger.warning("gemini exception model=%s %s — retrying with flash", model, exc)

            # Retry with Flash before going to Groq
            flash = self._flash_model()
            if flash and flash != model:
                try:
                    result = await self.gemini.complete(request, model=flash)
                    if result.error is None:
                        return result
                    logger.warning("gemini flash error err=%s — falling back to groq", result.error)
                except Exception as exc:
                    logger.warning("gemini flash exception %s — falling back to groq", exc)

        if self.groq and self.groq.is_available():
            return await self.groq.complete(request)

        raise RuntimeError("No AI provider available (Gemini and Groq both unavailable/failed)")

    async def stream(
        self,
        request: LLMRequest,
        *,
        tier: str = "standard",
        task_type: str = "chat",
    ):
        """Async generator streaming from the best available provider."""
        model = self.select_model(tier, task_type)

        if model and self.gemini and self.gemini.is_available():
            try:
                async for chunk in self.gemini.stream(request, model=model):
                    yield chunk
                return
            except Exception as exc:
                logger.warning("gemini stream error model=%s %s — retrying flash", model, exc)

            # Retry stream with Flash
            flash = self._flash_model()
            if flash and flash != model:
                try:
                    async for chunk in self.gemini.stream(request, model=flash):
                        yield chunk
                    return
                except Exception as exc:
                    logger.warning("gemini flash stream error %s — falling back to groq", exc)

        if self.groq and self.groq.is_available():
            async for chunk in self.groq.stream(request):
                yield chunk
            return

        raise RuntimeError("No AI provider available for streaming")
