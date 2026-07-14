"""Agent Marketplace — publisher layer: authoring + publish lifecycle + monetisasi field.

Menguji create/update/publish/unpublish template milik org (org-owned), ownership
guard, visibilitas (draft tersembunyi dari katalog publik), dan field berbayar
(price_idr>0 => is_paid, revenue_share default 70%).
"""
import asyncio
import uuid

import asyncpg

import bn_platform.marketplace as mp
import main

_UID = str(uuid.uuid4())


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


async def _seed_org(pool):
    org_id = str(uuid.uuid4())
    await pool.execute("INSERT INTO organizations (id,name,slug) VALUES ($1,$2,$3)",
                       org_id, f"Pub {org_id[:8]}", f"pub-{org_id[:8]}")
    return org_id


async def _cleanup(pool, org_id):
    await pool.execute("DELETE FROM marketplace_templates WHERE owner_org_id=$1", org_id)
    await pool.execute("DELETE FROM organizations WHERE id=$1", org_id)


def test_create_draft_hidden_then_publish_shows():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            created = await mp.create_template(
                pool, org_id=org, user_id=str(uuid.uuid4()),
                data={"name": "Agen Kopi Saya", "category": "Ecommerce",
                      "system_prompt": "Kamu asisten toko kopi."},
            )
            key = created["key"]
            assert created["status"] == "draft"
            # draft TIDAK muncul di katalog publik
            pub = await mp.get_template(pool, key)
            assert pub is None
            # tapi muncul di my-templates
            mine = await mp.list_my_templates(pool, org)
            assert any(t["key"] == key for t in mine)
            # publish → muncul publik
            await mp.set_template_status(pool, org_id=org, user_id=_UID, key=key, publish=True)
            pub2 = await mp.get_template(pool, key)
            assert pub2 is not None and pub2["name"] == "Agen Kopi Saya"
            # unpublish → hilang lagi
            await mp.set_template_status(pool, org_id=org, user_id=_UID, key=key, publish=False)
            assert await mp.get_template(pool, key) is None
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_paid_template_sets_is_paid_and_revenue_share():
    async def body(pool):
        org = await _seed_org(pool)
        try:
            created = await mp.create_template(
                pool, org_id=org, user_id=_UID,
                data={"name": "Agen Premium", "category": "Finance & Accounting",
                      "system_prompt": "x", "price_idr": 150000},
            )
            assert created["is_paid"] is True
            assert created["price_idr"] == 150000
            assert float(created["revenue_share_pct"]) == 70.0  # default publisher share
        finally:
            await _cleanup(pool, org)
    _run(body)


def test_update_only_by_owner():
    async def body(pool):
        org_a = await _seed_org(pool)
        org_b = await _seed_org(pool)
        try:
            created = await mp.create_template(
                pool, org_id=org_a, user_id=_UID,
                data={"name": "Punya A", "category": "Education", "system_prompt": "x"},
            )
            key = created["key"]
            # pemilik bisa update
            upd = await mp.update_template(pool, org_id=org_a, user_id=_UID, key=key,
                                           data={"description": "deskripsi baru"})
            assert upd["key"] == key
            # org lain TIDAK bisa (ownership guard → 404)
            import pytest
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await mp.update_template(pool, org_id=org_b, user_id=_UID, key=key,
                                         data={"description": "hack"})
            assert exc.value.status_code == 404
        finally:
            await _cleanup(pool, org_a)
            await _cleanup(pool, org_b)
    _run(body)
