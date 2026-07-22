"""prompt_registry.factory — singleton PromptRegistry (P2-B).

Di-set saat startup dengan pool global; dipakai BaseAgent.resolved_system_prompt
(agen tak memegang pool). Pola sama seperti platform_state.get_state_store.
"""
from __future__ import annotations

from prompt_registry.registry import PromptRegistry

_registry: PromptRegistry | None = None


def set_prompt_registry(reg: PromptRegistry | None) -> None:
    global _registry
    _registry = reg


def get_prompt_registry() -> PromptRegistry | None:
    return _registry
