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

from platform_state import get_state_store   # P0-A C4: shared circuit-breaker state

logger = logging.getLogger("botnesia.router")

_FAIL_THRESHOLD = 3
_RESET_SECS = 60
_SYNC_TTL = 1.0          # throttle baca lintas-worker: maks 1 baca/detik/provider


class _CircuitBreaker:
    """Per-provider circuit breaker HYBRID (P0-A C4).

    Fast-path LOKAL (in-process) supaya `is_open` tak menambah round-trip di
    jalur panas LLM. State 'open' juga di-mirror ke platform_state.StateStore
    (`cb:{name}`, wall-clock `open_until`) sehingga provider yang di-open satu
    worker terlihat worker lain dalam ~_SYNC_TTL detik (bila STATE_BACKEND=redis).
    Default in-process: StateStore = dict lokal → perilaku identik versi lama.
    `is_open/ok/fail` kini async (dipanggil dari _try_*/stream yang sudah async);
    `state()` tetap sync (dipakai status(), tanpa I/O)."""

    def __init__(self):
        self._fails: dict = {}
        self._open_until: dict = {}      # name -> wall-clock epoch
        self._last_sync: dict = {}       # name -> monotonic terakhir baca store

    async def is_open(self, name: str) -> bool:
        now = time.time()
        until = self._open_until.get(name, 0.0)
        if until:
            if now < until:
                return True
            self._fails[name] = 0            # cooldown lokal habis — reset
            self._open_until.pop(name, None)
        # adopsi open dari worker lain (di-throttle agar tak beri beban tiap call)
        if time.monotonic() - self._last_sync.get(name, 0.0) >= _SYNC_TTL:
            self._last_sync[name] = time.monotonic()
            try:
                raw = await get_state_store().get(f"cb:{name}")
            except Exception:
                raw = None
            if raw:
                try:
                    remote_until = float(raw)
                except (TypeError, ValueError):
                    remote_until = 0.0
                if remote_until > now:
                    self._open_until[name] = remote_until
                    return True
        return False

    async def ok(self, name: str) -> None:
        self._fails[name] = 0
        self._open_until.pop(name, None)
        try:
            await get_state_store().delete(f"cb:{name}")
        except Exception:
            pass

    async def fail(self, name: str) -> None:
        n = self._fails.get(name, 0) + 1
        self._fails[name] = n
        if n >= _FAIL_THRESHOLD:
            until = time.time() + _RESET_SECS
            self._open_until[name] = until
            try:
                await get_state_store().set(f"cb:{name}", str(until), ttl_s=_RESET_SECS)
            except Exception:
                pass
            logger.warning("circuit-breaker: %s opened for %ds", name, _RESET_SECS)

    def state(self, name: str) -> dict:
        """Snapshot LOKAL (sync) untuk status() — tanpa I/O."""
        until = self._open_until.get(name, 0.0)
        return {
            "fails": self._fails.get(name, 0),
            "open": bool(until and time.time() < until),
            "open_until": until or None,
        }


# Shared across all SmartModelRouter instances — process-level health view.
_breaker = _CircuitBreaker()


class SmartModelRouter:
    def __init__(
        self,
        gemini: AIProvider | None = None,
        groq: AIProvider | None = None,
        openrouter: AIProvider | None = None,
        deepseek: AIProvider | None = None,
    ):
        self.gemini = gemini
        self.groq = groq
        self.openrouter = openrouter
        self.deepseek = deepseek

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

    def _ds_model(self, task_type: str) -> str | None:
        if not self.deepseek or not self.deepseek.is_available():
            return None
        from ai_providers.deepseek import deepseek_model_for_task
        return deepseek_model_for_task(task_type)

    # ── Try helpers ───────────────────────────────────────────────────────────

    async def _try_gemini(self, req: LLMRequest, model: str) -> LLMResponse | None:
        if not self.gemini or not self.gemini.is_available() or await _breaker.is_open("gemini"):
            return None
        try:
            r = await self.gemini.complete(req, model=model)
            if r.error is None:
                await _breaker.ok("gemini")
                return r
            logger.warning("gemini err model=%s: %s", model, r.error)
        except Exception as exc:
            logger.warning("gemini exc model=%s: %s", model, exc)
        await _breaker.fail("gemini")
        return None

    async def _try_openrouter(self, req: LLMRequest, model: str) -> LLMResponse | None:
        if not self.openrouter or not self.openrouter.is_available() or await _breaker.is_open("openrouter"):
            return None
        try:
            r = await self.openrouter.complete(req, model=model)
            if r.error is None:
                await _breaker.ok("openrouter")
                return r
            logger.warning("openrouter err model=%s: %s", model, r.error)
        except Exception as exc:
            logger.warning("openrouter exc model=%s: %s", model, exc)
        await _breaker.fail("openrouter")
        return None

    async def _try_deepseek(self, req: LLMRequest, model: str) -> LLMResponse | None:
        if not self.deepseek or not self.deepseek.is_available() or await _breaker.is_open("deepseek"):
            return None
        try:
            r = await self.deepseek.complete(req, model=model)
            if r.error is None:
                await _breaker.ok("deepseek")
                return r
            logger.warning("deepseek err model=%s: %s", model, r.error)
        except Exception as exc:
            logger.warning("deepseek exc model=%s: %s", model, exc)
        await _breaker.fail("deepseek")
        return None

    async def _try_groq(self, req: LLMRequest) -> LLMResponse | None:
        if not self.groq or not self.groq.is_available() or await _breaker.is_open("groq"):
            return None
        try:
            r = await self.groq.complete(req)
            if r.error is None:
                await _breaker.ok("groq")
                return r
            logger.warning("groq err: %s", r.error)
        except Exception as exc:
            logger.warning("groq exc: %s", exc)
        await _breaker.fail("groq")
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
          pro/complex  → Gemini Pro → DeepSeek(task) → OpenRouter(task) → Gemini Flash → Groq
          standard     → Gemini Flash → OpenRouter(task) → Groq
        """
        primary = self.select_model(tier, task_type)
        ds_model = self._ds_model(task_type)
        or_model = self._or_model(task_type)
        flash = self._flash_model()

        # 1. Primary Gemini (Pro or Flash depending on tier)
        if primary:
            r = await self._try_gemini(request, primary)
            if r:
                return r

        # 2. DeepSeek direct API — best for coding/reasoning tasks, no markup
        if ds_model:
            r = await self._try_deepseek(request, ds_model)
            if r:
                return r

        # 3. OpenRouter — task-optimal model (covers other models not in DeepSeek)
        if or_model:
            r = await self._try_openrouter(request, or_model)
            if r:
                return r

        # 4. Gemini Flash retry (only if Pro was the primary and failed)
        if flash and flash != primary:
            r = await self._try_gemini(request, flash)
            if r:
                return r

        # 5. Groq fallback
        r = await self._try_groq(request)
        if r:
            return r

        raise RuntimeError(
            "No AI provider available — Gemini, DeepSeek, OpenRouter, and Groq all failed or unconfigured"
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
        ds_model = self._ds_model(task_type)
        or_model = self._or_model(task_type)
        flash = self._flash_model()

        # 1. Gemini primary
        if primary and self.gemini and self.gemini.is_available() and not await _breaker.is_open("gemini"):
            try:
                async for chunk in self.gemini.stream(request, model=primary):
                    yield chunk
                await _breaker.ok("gemini"); return
            except Exception as exc:
                logger.warning("gemini stream err model=%s: %s", primary, exc)
                await _breaker.fail("gemini")

        # 2. DeepSeek direct
        if ds_model and self.deepseek and self.deepseek.is_available() and not await _breaker.is_open("deepseek"):
            try:
                async for chunk in self.deepseek.stream(request, model=ds_model):
                    yield chunk
                await _breaker.ok("deepseek"); return
            except Exception as exc:
                logger.warning("deepseek stream err model=%s: %s", ds_model, exc)
                await _breaker.fail("deepseek")

        # 3. OpenRouter
        if or_model and self.openrouter and self.openrouter.is_available() and not await _breaker.is_open("openrouter"):
            try:
                async for chunk in self.openrouter.stream(request, model=or_model):
                    yield chunk
                await _breaker.ok("openrouter"); return
            except Exception as exc:
                logger.warning("openrouter stream err model=%s: %s", or_model, exc)
                await _breaker.fail("openrouter")

        # 4. Gemini Flash retry
        if flash and flash != primary and self.gemini and self.gemini.is_available() and not await _breaker.is_open("gemini"):
            try:
                async for chunk in self.gemini.stream(request, model=flash):
                    yield chunk
                await _breaker.ok("gemini"); return
            except Exception as exc:
                logger.warning("gemini flash stream err: %s", exc)
                await _breaker.fail("gemini")

        # 5. Groq
        if self.groq and self.groq.is_available() and not await _breaker.is_open("groq"):
            try:
                async for chunk in self.groq.stream(request):
                    yield chunk
                await _breaker.ok("groq"); return
            except Exception as exc:
                logger.warning("groq stream err: %s", exc)
                await _breaker.fail("groq")

        raise RuntimeError("No AI provider available for streaming")

    # ── Cost Router (P2-A): pilih model dari KELAS pesan ────────────────────
    async def route_for_message(self, request: LLMRequest, *, user_message: str,
                                has_image: bool = False, reasoning_mode: str = "standard") -> LLMResponse:
        """Klasifikasi pesan 5-arah (simple/medium/complex/coding/vision) →
        tier+task_type otomatis → route(). Hemat biaya: task ringan tak ke model
        mahal; coding→coding-model, complex→reasoning, vision→vision."""
        from cost_intelligence import classify_task_class, router_params
        p = router_params(classify_task_class(user_message, reasoning_mode=reasoning_mode,
                                              has_image=has_image))
        return await self.route(request, tier=p["tier"], task_type=p["task_type"])

    def stream_for_message(self, request: LLMRequest, *, user_message: str,
                           has_image: bool = False, reasoning_mode: str = "standard"):
        """Versi streaming route_for_message (kembalikan async generator)."""
        from cost_intelligence import classify_task_class, router_params
        p = router_params(classify_task_class(user_message, reasoning_mode=reasoning_mode,
                                              has_image=has_image))
        return self.stream(request, tier=p["tier"], task_type=p["task_type"])

    def status(self) -> dict:
        """Current availability and circuit-breaker state for all providers."""
        return {
            "gemini": {
                "available": bool(self.gemini and self.gemini.is_available()),
                "model": self.select_model("standard", "chat"),
                "pro_model": self.select_model("pro", "reasoning"),
                **_breaker.state("gemini"),
            },
            "deepseek": {
                "available": bool(self.deepseek and self.deepseek.is_available()),
                "model": self.deepseek.default_model if self.deepseek else None,
                **_breaker.state("deepseek"),
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
