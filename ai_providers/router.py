"""
ai_providers/router.py — SmartModelRouter (multi-provider).

Routing priority:
  pro / complex task  → Gemini Pro  → OpenRouter (task-optimal) → Gemini Flash → Groq
  standard task       → Gemini Flash → OpenRouter (task-fast)   → Groq

Circuit breaker: after _FAIL_THRESHOLD consecutive failures a provider is
paused for _RESET_SECS before being retried.  The breaker is process-level
(shared across all SmartModelRouter instances) so provider health is tracked
globally, not per-agent.

Providers are all optional; any combination works:
  - Gemini only (no OpenRouter, no Groq) — minimal setup
  - Gemini + Groq                         — original setup
  - Gemini + OpenRouter + Groq            — full multi-provider
  - OpenRouter + Groq                     — no Gemini key
"""
import logging
import time

from ai_providers.base import AIProvider
from ai_providers.types import LLMRequest, LLMResponse, PRO_TASK_TYPES

logger = logging.getLogger("botnesia.router")

_FAIL_THRESHOLD = 3
_RESET_SECS = 60


class _CircuitBreaker:
    """Simple per-provider circuit breaker (in-process, non-persistent)."""

    def __init__(self):
        self._fails: dict = {}
        self._open_until: dict = {}

    def is_open(self, name: str) -> bool:
        until = self._open_until.get(name, 0.0)
        if until and time.monotonic() < until:
            return True
        if until:
            # Cool-down expired — reset
            self._fails[name] = 0
            self._open_until.pop(name, None)
        return False

    def ok(self, name: str) -> None:
        self._fails[name] = 0
        self._open_until.pop(name, None)

    def fail(self, name: str) -> None:
        n = self._fails.get(name, 0) + 1
        self._fails[name] = n
        if n >= _FAIL_THRESHOLD:
            self._open_until[name] = time.monotonic() + _RESET_SECS
            logger.warning("circuit-breaker: %s opened for %ds", name, _RESET_SECS)

    def state(self, name: str) -> dict:
        return {
            "fails": self._fails.get(name, 0),
            "open": self.is_open(name),
            "open_until": self._open_until.get(name),
        }


# Shared across all SmartModelRouter instances — process-level health view.
_breaker = _CircuitBreaker()


class SmartModelRouter:
    def __init__(
        self,
        gemini: AIProvider | None = None,
        groq: AIProvider | None = None,
        openrouter: AIProvider | None = None,
    ):
        self.gemini = gemini
        self.groq = groq
        self.openrouter = openrouter

    # ── Model selection ───────────────────────────────────────────────────────

    def select_model(self, tier: str = "standard", task_type: str = "chat") -> str | None:
        """Gemini model name for this tier/task, or None if Gemini unavailable."""
        if not self.gemini or not self.gemini.is_available():
            return None
        task = (task_type or "chat").lower()
        use_pro = (tier == "pro") or (task in PRO_TASK_TYPES)
        from ai_providers.gemini import GeminiProvider
        if isinstance(self.gemini, GeminiProvider):
            return self.gemini.pro_model if use_pro else self.gemini.model
        return self.gemini.default_model

    def _flash_model(self) -> str | None:
        if not self.gemini or not self.gemini.is_available():
            return None
        from ai_providers.gemini import GeminiProvider
        return self.gemini.model if isinstance(self.gemini, GeminiProvider) else None

    def _or_model(self, task_type: str) -> str | None:
        if not self.openrouter or not self.openrouter.is_available():
            return None
        from ai_providers.openrouter import task_model
        return task_model(task_type)

    # ── Try helpers ───────────────────────────────────────────────────────────

    async def _try_gemini(self, req: LLMRequest, model: str) -> LLMResponse | None:
        if not self.gemini or not self.gemini.is_available() or _breaker.is_open("gemini"):
            return None
        try:
            r = await self.gemini.complete(req, model=model)
            if r.error is None:
                _breaker.ok("gemini")
                return r
            logger.warning("gemini err model=%s: %s", model, r.error)
        except Exception as exc:
            logger.warning("gemini exc model=%s: %s", model, exc)
        _breaker.fail("gemini")
        return None

    async def _try_openrouter(self, req: LLMRequest, model: str) -> LLMResponse | None:
        if not self.openrouter or not self.openrouter.is_available() or _breaker.is_open("openrouter"):
            return None
        try:
            r = await self.openrouter.complete(req, model=model)
            if r.error is None:
                _breaker.ok("openrouter")
                return r
            logger.warning("openrouter err model=%s: %s", model, r.error)
        except Exception as exc:
            logger.warning("openrouter exc model=%s: %s", model, exc)
        _breaker.fail("openrouter")
        return None

    async def _try_groq(self, req: LLMRequest) -> LLMResponse | None:
        if not self.groq or not self.groq.is_available() or _breaker.is_open("groq"):
            return None
        try:
            r = await self.groq.complete(req)
            if r.error is None:
                _breaker.ok("groq")
                return r
            logger.warning("groq err: %s", r.error)
        except Exception as exc:
            logger.warning("groq exc: %s", exc)
        _breaker.fail("groq")
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    async def route(
        self,
        request: LLMRequest,
        *,
        tier: str = "standard",
        task_type: str = "chat",
    ) -> LLMResponse:
        """
        Route to best available provider:
          pro/complex  → Gemini Pro  → OpenRouter(task-optimal) → Gemini Flash → Groq
          standard     → Gemini Flash → OpenRouter(task-fast)   → Groq
        """
        primary = self.select_model(tier, task_type)
        or_model = self._or_model(task_type)
        flash = self._flash_model()

        # 1. Primary Gemini (Pro or Flash depending on tier)
        if primary:
            r = await self._try_gemini(request, primary)
            if r:
                return r

        # 2. OpenRouter — task-optimal model
        if or_model:
            r = await self._try_openrouter(request, or_model)
            if r:
                return r

        # 3. Gemini Flash retry (only if Pro was the primary and failed)
        if flash and flash != primary:
            r = await self._try_gemini(request, flash)
            if r:
                return r

        # 4. Groq fallback
        r = await self._try_groq(request)
        if r:
            return r

        raise RuntimeError(
            "No AI provider available — Gemini, OpenRouter, and Groq all failed or unconfigured"
        )

    async def stream(
        self,
        request: LLMRequest,
        *,
        tier: str = "standard",
        task_type: str = "chat",
    ):
        """Streaming with same provider priority as route()."""
        primary = self.select_model(tier, task_type)
        or_model = self._or_model(task_type)
        flash = self._flash_model()

        # 1. Gemini primary
        if primary and self.gemini and self.gemini.is_available() and not _breaker.is_open("gemini"):
            try:
                async for chunk in self.gemini.stream(request, model=primary):
                    yield chunk
                _breaker.ok("gemini")
                return
            except Exception as exc:
                logger.warning("gemini stream err model=%s: %s", primary, exc)
                _breaker.fail("gemini")

        # 2. OpenRouter
        if or_model and self.openrouter and self.openrouter.is_available() and not _breaker.is_open("openrouter"):
            try:
                async for chunk in self.openrouter.stream(request, model=or_model):
                    yield chunk
                _breaker.ok("openrouter")
                return
            except Exception as exc:
                logger.warning("openrouter stream err model=%s: %s", or_model, exc)
                _breaker.fail("openrouter")

        # 3. Gemini Flash retry
        if flash and flash != primary and self.gemini and self.gemini.is_available() and not _breaker.is_open("gemini"):
            try:
                async for chunk in self.gemini.stream(request, model=flash):
                    yield chunk
                _breaker.ok("gemini")
                return
            except Exception as exc:
                logger.warning("gemini flash stream err: %s", exc)
                _breaker.fail("gemini")

        # 4. Groq
        if self.groq and self.groq.is_available() and not _breaker.is_open("groq"):
            try:
                async for chunk in self.groq.stream(request):
                    yield chunk
                _breaker.ok("groq")
                return
            except Exception as exc:
                logger.warning("groq stream err: %s", exc)
                _breaker.fail("groq")

        raise RuntimeError("No AI provider available for streaming")

    def status(self) -> dict:
        """Current availability and circuit-breaker state for all providers."""
        return {
            "gemini": {
                "available": bool(self.gemini and self.gemini.is_available()),
                "model": self.select_model("standard", "chat"),
                "pro_model": self.select_model("pro", "reasoning"),
                **_breaker.state("gemini"),
            },
            "openrouter": {
                "available": bool(self.openrouter and self.openrouter.is_available()),
                "model": self._or_model("chat"),
                **_breaker.state("openrouter"),
            },
            "groq": {
                "available": bool(self.groq and self.groq.is_available()),
                "model": self.groq.default_model if self.groq else None,
                **_breaker.state("groq"),
            },
        }
