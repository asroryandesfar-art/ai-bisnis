"""policy_engine.loader — ruleset policy per-org dari DB (P1-C.2).

Tabel `org_policy_rules` (opsional, additive): override rules per-org di atas
DEFAULT_RULES. `load_org_policy` mem-build `PolicyEngine` untuk org; hasil di-cache
singkat (perf_cache) agar hook execute_tool tak query DB tiap panggilan tool.
Tak ada baris → DEFAULT_RULES. Fail-open: error DB → PolicyEngine default.
"""
from __future__ import annotations

import json

import asyncpg

from perf_cache import TTLCache, get_or_compute
from policy_engine.engine import PolicyEngine

POLICY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS org_policy_rules (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    rules       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Cache rules per-org (bukan objek PolicyEngine — kecil & stateless) 5 detik.
_RULES_TTL_S = 5.0
_cache = TTLCache(maxsize=4096)


async def ensure_policy_schema(pool: asyncpg.Pool) -> None:
    await pool.execute(POLICY_SCHEMA_SQL)


def _coerce_rules(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, str):                       # main pool tanpa jsonb codec → string
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


async def _fetch_rules(pool, org_id: str) -> dict:
    try:
        row = await pool.fetchrow("SELECT rules FROM org_policy_rules WHERE org_id=$1", org_id)
        return _coerce_rules(row["rules"]) if row else {}
    except Exception:
        return {}


async def load_org_policy(pool, org_id: str) -> PolicyEngine:
    """PolicyEngine untuk org (rules DB di-merge atas default). Cache 5s."""
    rules = await get_or_compute(_cache, ("policy", str(org_id)), _RULES_TTL_S,
                                 lambda: _fetch_rules(pool, str(org_id)))
    return PolicyEngine(rules)


async def set_org_policy(pool, org_id: str, rules: dict) -> dict:
    """Simpan/replace ruleset org. Invalidasi cache. Return baris tersimpan."""
    row = await pool.fetchrow(
        """INSERT INTO org_policy_rules (org_id, rules, updated_at)
           VALUES ($1, $2::jsonb, NOW())
           ON CONFLICT (org_id) DO UPDATE SET rules=EXCLUDED.rules, updated_at=NOW()
           RETURNING org_id, rules, updated_at""",
        str(org_id), json.dumps(rules or {}),
    )
    _cache.clear()                                 # rules berubah → buang cache
    return dict(row)
