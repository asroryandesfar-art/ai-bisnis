"""prompt_registry — Prompt Management untuk BotNesia (P2-B).

Registry versi prompt agen: riwayat versi, rollback (aktifkan versi lama), dan
A/B (>1 varian aktif berbobot, pilih deterministik). Prompt hardcoded kelas agen
tetap fallback → perilaku byte-identik saat registry kosong / flag off.

    from prompt_registry import PromptRegistry
    reg = PromptRegistry(pool)
    await reg.create_version("cs_agent.system", "Kamu ...", activate=True)
    rp = await reg.resolve("cs_agent.system", org_id=org, default=agent.system_prompt)

Konsumen gate `is_enabled("prompt_registry", org_id)`. Lihat ADR-0010.
"""
from prompt_registry.schema import ensure_prompt_schema, PROMPT_SCHEMA_SQL
from prompt_registry.registry import PromptRegistry, ResolvedPrompt
from prompt_registry.factory import get_prompt_registry, set_prompt_registry

__all__ = [
    "ensure_prompt_schema", "PROMPT_SCHEMA_SQL",
    "PromptRegistry", "ResolvedPrompt",
    "get_prompt_registry", "set_prompt_registry",
]
