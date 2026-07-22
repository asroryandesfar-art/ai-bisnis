"""prompt_registry.registry — versi, rollback & A/B prompt agen (P2-B).

`PromptRegistry(pool)` operasi async atas tabel `agent_prompts`:
  - create_version : simpan versi baru (auto-increment), opsional langsung aktif.
  - activate       : aktifkan satu versi. exclusive=True → rollback (hanya 1 aktif);
                     exclusive=False → A/B (varian lain tetap aktif).
  - resolve        : pilih prompt aktif untuk (name, org). Banyak varian aktif →
                     pilih berbobot DETERMINISTIK (hash bucket_key) agar org/sesi
                     yang sama selalu dapat varian sama. Tak ada → fallback `default`.

Resolusi org: baris ber-org menang atas global (org_id NULL). Fallback default =
prompt hardcoded kelas agen → perilaku byte-identik saat registry kosong.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedPrompt:
    content: str
    version: int | None      # None bila dari fallback default
    variant: str
    source: str              # "registry" | "default"


def _bucket(name: str, key: str | None, modulo: int) -> int:
    h = hashlib.sha256(f"{name}:{key or ''}".encode("utf-8")).hexdigest()
    return int(h, 16) % max(1, modulo)


class PromptRegistry:
    def __init__(self, pool):
        self.pool = pool

    async def create_version(
        self, name: str, content: str, *, org_id: str | None = None,
        variant: str = "default", activate: bool = False, weight: int = 100,
        created_by: str | None = None,
    ) -> dict:
        """Simpan versi baru (versi = MAX+1 per name+org+variant). activate=True →
        langsung aktifkan (exclusive: rollback ke versi baru ini)."""
        weight = max(1, min(1_000_000, int(weight)))
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                next_ver = await conn.fetchval(
                    """SELECT COALESCE(MAX(version), 0) + 1 FROM agent_prompts
                       WHERE name=$1 AND org_id IS NOT DISTINCT FROM $2 AND variant=$3""",
                    name, org_id, variant,
                )
                row = await conn.fetchrow(
                    """INSERT INTO agent_prompts (name, org_id, variant, version, content, weight, active, created_by)
                       VALUES ($1,$2,$3,$4,$5,$6,FALSE,$7) RETURNING *""",
                    name, org_id, variant, next_ver, content, weight, created_by,
                )
                if activate:
                    await self._activate(conn, name, next_ver, org_id=org_id,
                                         variant=variant, exclusive=True)
                    row = await conn.fetchrow("SELECT * FROM agent_prompts WHERE id=$1", row["id"])
        return dict(row)

    async def activate(self, name: str, version: int, *, org_id: str | None = None,
                       variant: str = "default", exclusive: bool = True) -> dict | None:
        """Aktifkan versi. exclusive=True → nonaktifkan semua versi/varian lain
        (rollback: tepat 1 aktif). exclusive=False → biarkan varian lain (A/B)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await self._activate(conn, name, version, org_id=org_id,
                                           variant=variant, exclusive=exclusive)
        return dict(row) if row else None

    @staticmethod
    async def _activate(conn, name, version, *, org_id, variant, exclusive):
        if exclusive:
            await conn.execute(
                "UPDATE agent_prompts SET active=FALSE WHERE name=$1 AND org_id IS NOT DISTINCT FROM $2",
                name, org_id,
            )
        return await conn.fetchrow(
            """UPDATE agent_prompts SET active=TRUE
               WHERE name=$1 AND org_id IS NOT DISTINCT FROM $2 AND variant=$3 AND version=$4
               RETURNING *""",
            name, org_id, variant, version,
        )

    async def deactivate(self, name: str, *, org_id: str | None = None,
                         variant: str | None = None) -> int:
        """Nonaktifkan varian tertentu (atau semua bila variant None)."""
        if variant is None:
            res = await self.pool.execute(
                "UPDATE agent_prompts SET active=FALSE WHERE name=$1 AND org_id IS NOT DISTINCT FROM $2 AND active",
                name, org_id,
            )
        else:
            res = await self.pool.execute(
                """UPDATE agent_prompts SET active=FALSE
                   WHERE name=$1 AND org_id IS NOT DISTINCT FROM $2 AND variant=$3 AND active""",
                name, org_id, variant,
            )
        return int(res.split()[-1]) if res else 0

    async def list_versions(self, name: str, *, org_id: str | None = None) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT * FROM agent_prompts WHERE name=$1 AND org_id IS NOT DISTINCT FROM $2
               ORDER BY variant, version DESC""",
            name, org_id,
        )
        return [dict(r) for r in rows]

    async def _active_rows(self, name: str, *, org_id: str | None) -> list[dict]:
        """Baris aktif untuk (name, org). Ber-org menang; kosong → global (NULL)."""
        if org_id is not None:
            rows = await self.pool.fetch(
                "SELECT * FROM agent_prompts WHERE name=$1 AND org_id=$2 AND active ORDER BY variant",
                name, org_id,
            )
            if rows:
                return [dict(r) for r in rows]
        rows = await self.pool.fetch(
            "SELECT * FROM agent_prompts WHERE name=$1 AND org_id IS NULL AND active ORDER BY variant",
            name,
        )
        return [dict(r) for r in rows]

    async def resolve(self, name: str, *, org_id: str | None = None,
                      bucket_key: str | None = None, default: str | None = None) -> ResolvedPrompt:
        """Prompt aktif untuk (name, org); >1 varian → pilih berbobot deterministik.
        Tak ada baris aktif → fallback `default` (prompt hardcoded)."""
        rows = await self._active_rows(name, org_id=org_id)
        if not rows:
            return ResolvedPrompt(content=default or "", version=None,
                                  variant="default", source="default")
        if len(rows) == 1:
            r = rows[0]
            return ResolvedPrompt(r["content"], r["version"], r["variant"], "registry")
        total = sum(max(1, int(r["weight"])) for r in rows)
        pick = _bucket(name, bucket_key, total)
        acc = 0
        for r in rows:                                  # rows sudah ORDER BY variant (stabil)
            acc += max(1, int(r["weight"]))
            if pick < acc:
                return ResolvedPrompt(r["content"], r["version"], r["variant"], "registry")
        r = rows[-1]
        return ResolvedPrompt(r["content"], r["version"], r["variant"], "registry")
