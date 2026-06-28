from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator


class ProviderType(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"
    OPENROUTER = "openrouter"


class TaskType(str, Enum):
    CHAT = "chat"
    CS = "cs"
    FAQ = "faq"
    SALES = "sales"
    MARKETING = "marketing"
    HR = "hr"
    KNOWLEDGE = "knowledge"
    DOCUMENT = "document"
    REASONING = "reasoning"
    PLANNING = "planning"
    CODING = "coding"
    WORKFLOW = "workflow"


# Tasks that need the heavier Pro model
PRO_TASK_TYPES: frozenset[str] = frozenset({
    TaskType.DOCUMENT, TaskType.REASONING, TaskType.PLANNING,
    TaskType.CODING, TaskType.WORKFLOW,
    "document_analysis", "deep_reasoning", "business_planning",
    "advanced_coding", "complex_workflow",
})

# Tasks that run fine on Flash
FLASH_TASK_TYPES: frozenset[str] = frozenset({
    TaskType.CHAT, TaskType.CS, TaskType.FAQ, TaskType.SALES,
    TaskType.MARKETING, TaskType.HR, TaskType.KNOWLEDGE,
    "customer_service", "knowledge_search", "internal",
})


@dataclass
class LLMRequest:
    messages: list[dict]
    temperature: float = 0.3
    max_tokens: int = 1024
    response_format: dict | None = None
    stream: bool = False
    tools: list[dict] | None = None
    images: list[bytes | str] | None = None  # base64 str or raw bytes
    pdfs: list[bytes | str] | None = None    # base64 str or raw bytes


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    retries: int = 0
    error: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    stream_gen: Any = None  # AsyncGenerator[str, None] when streaming

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
