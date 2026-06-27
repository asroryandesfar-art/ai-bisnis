from __future__ import annotations

from abc import ABC, abstractmethod

from ai_providers.types import LLMRequest, LLMResponse


class AIProvider(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest, *, model: str | None = None) -> LLMResponse:
        """Non-streaming completion. `model` overrides the provider default."""
        ...

    @abstractmethod
    async def stream(self, request: LLMRequest, *, model: str | None = None):
        """Async generator yielding str chunks."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """True if provider has a usable API key."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def default_model(self) -> str: ...
