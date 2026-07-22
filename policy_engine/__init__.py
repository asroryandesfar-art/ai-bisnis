"""policy_engine — governance deklaratif untuk aksi agent (P1-C).

    from policy_engine import PolicyEngine, ALLOW, BLOCK, APPROVAL, MASK
    pe = PolicyEngine({"cost_limit_usd": 0.5, "blacklist_domains": ["bad.example"]})
    if pe.check_tool("run_command").action == APPROVAL: ...   # butuh approval
    masked, found = pe.mask("email saya a@b.com")              # → "email saya [EMAIL]"

Pure & mandiri; konsumen mengadopsi di belakang flag `is_enabled("policy_engine")`.
Lihat ADR-0008.
"""
from policy_engine.engine import (
    PolicyEngine, Decision, DEFAULT_RULES, ALLOW, BLOCK, APPROVAL, MASK,
)
from policy_engine.loader import (
    ensure_policy_schema, load_org_policy, set_org_policy, POLICY_SCHEMA_SQL,
)

__all__ = ["PolicyEngine", "Decision", "DEFAULT_RULES", "ALLOW", "BLOCK", "APPROVAL", "MASK",
           "ensure_policy_schema", "load_org_policy", "set_org_policy", "POLICY_SCHEMA_SQL"]
