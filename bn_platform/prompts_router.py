"""bn_platform/prompts_router.py — HTTP API Prompt Management (P2-B).

CRUD versi prompt agen per-tenant: list riwayat, buat versi, aktifkan (rollback/
A-B), nonaktifkan, dan preview resolve. RBAC-gated (workforce.read/write),
rate-limited. Pola factory-DI seperti jobs_router (tanpa import dari main).
JANGAN `from __future__ import annotations` (merusak Depends closure FastAPI).

Semua operasi DILINGKUP org pemanggil (org_id = user["org_id"]) → tak bisa
menyentuh prompt tenant lain. Default global (org_id NULL) dikelola di luar API ini.
Endpoint TAMBAHAN & opsional — jalur agen lama tak berubah.
"""
from typing import Annotated, Awaitable, Callable, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from prompt_registry import PromptRegistry
from .security import _check_rate_limit

GetPool = Callable[..., Awaitable[asyncpg.Pool]]


class CreateVersionRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)
    variant: str = Field("default", min_length=1, max_length=40)
    activate: bool = False
    weight: int = Field(100, ge=1, le=1_000_000)


class ActivateRequest(BaseModel):
    version: int = Field(..., ge=1)
    variant: str = Field("default", min_length=1, max_length=40)
    exclusive: bool = True          # True → rollback (1 aktif); False → A/B


def build_prompts_router(*, get_pool: GetPool, require_permission) -> APIRouter:
    router = APIRouter(prefix="/prompts", tags=["prompt-management"])

    @router.get("/{name}")
    async def list_versions(
        name: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        reg = PromptRegistry(pool)
        return await reg.list_versions(name, org_id=str(user["org_id"]))

    @router.post("/{name}")
    async def create_version(
        name: str, body: CreateVersionRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        await _check_rate_limit(f"prompts-write:{user['org_id']}", 60)
        reg = PromptRegistry(pool)
        row = await reg.create_version(
            name, body.content, org_id=str(user["org_id"]), variant=body.variant,
            activate=body.activate, weight=body.weight,
            created_by=str(user.get("id") or user.get("email") or ""),
        )
        return row

    @router.post("/{name}/activate")
    async def activate_version(
        name: str, body: ActivateRequest,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
    ):
        await _check_rate_limit(f"prompts-write:{user['org_id']}", 60)
        reg = PromptRegistry(pool)
        row = await reg.activate(name, body.version, org_id=str(user["org_id"]),
                                 variant=body.variant, exclusive=body.exclusive)
        if row is None:
            raise HTTPException(status_code=404,
                                detail="Versi/varian tak ditemukan untuk org ini.")
        return row

    @router.post("/{name}/deactivate")
    async def deactivate(
        name: str,
        user: Annotated[dict, Depends(require_permission("workforce.write"))],
        pool: asyncpg.Pool = Depends(get_pool),
        variant: Optional[str] = None,
    ):
        await _check_rate_limit(f"prompts-write:{user['org_id']}", 60)
        reg = PromptRegistry(pool)
        n = await reg.deactivate(name, org_id=str(user["org_id"]), variant=variant)
        return {"deactivated": n}

    @router.get("/{name}/resolve")
    async def resolve(
        name: str,
        user: Annotated[dict, Depends(require_permission("workforce.read"))],
        pool: asyncpg.Pool = Depends(get_pool),
        bucket_key: Optional[str] = None,
    ):
        """Preview prompt aktif yang akan dipilih (deterministik untuk bucket_key)."""
        reg = PromptRegistry(pool)
        rp = await reg.resolve(name, org_id=str(user["org_id"]),
                               bucket_key=bucket_key, default=None)
        return {"content": rp.content, "version": rp.version,
                "variant": rp.variant, "source": rp.source}

    return router
