from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import UnifiedMessage


class BaseConnector(ABC):
    def __init__(self, *, tenant_id: str, connection_id: str, credentials: dict[str, Any], config: dict[str, Any] | None = None):
        self.tenant_id = tenant_id
        self.connection_id = connection_id
        self.credentials = credentials
        self.config = config or {}

    @abstractmethod
    async def connect(self) -> dict[str, Any]: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_message(self, user_id: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

    @abstractmethod
    async def receive_message(self, payload: dict[str, Any]) -> list[UnifiedMessage]: ...

    @abstractmethod
    async def validate(self) -> bool: ...

    @abstractmethod
    async def sync(self) -> dict[str, Any]: ...
