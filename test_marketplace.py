import asyncio
from pathlib import Path

import pytest

from bn_platform.agent_marketplace_catalog import MARKETPLACE_CATEGORIES, PROFESSIONAL_AGENT_TEMPLATES
from bn_platform.marketplace import (
    install_template,
    list_installs,
    list_templates,
    uninstall_install,
    update_install,
)


class FakePool:
    def __init__(self, fetch_rows=None, fetchrow_map=None):
        self.fetch_rows = list(fetch_rows or [])
        self.fetchrow_map = {key: list(value) for key, value in (fetchrow_map or {}).items()}
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return list(self.fetch_rows)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        for key, values in self.fetchrow_map.items():
            if key in sql and values:
                return values.pop(0)
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


def test_phase4_catalog_has_100_plus_professional_templates():
    names = {item["name"] for item in PROFESSIONAL_AGENT_TEMPLATES}
    categories = {item["category"] for item in PROFESSIONAL_AGENT_TEMPLATES}
    assert len(PROFESSIONAL_AGENT_TEMPLATES) >= 100
    assert len(MARKETPLACE_CATEGORIES) == 22
    assert len(categories) == 22
    assert "General AI Agent" in names
    assert "Supervisor Agent" in names
    assert all(item.get("tools") and item.get("starter_questions") and item.get("knowledge_sources") for item in PROFESSIONAL_AGENT_TEMPLATES)


@pytest.mark.parametrize("status", ["active", "inactive"])
def test_list_templates_and_contract_status(status):
    pool = FakePool(fetch_rows=[{"id": "1", "key": "sales", "category": "Business", "name": "Sales Agent", "description": "x", "preview_image": None, "primary_color": "#fff", "install_count": 3, "version": "1.0.0", "sample_faqs": [], "status": status}])
    result = asyncio.run(list_templates(pool))
    assert result[0]["status"] == status
    assert result[0]["version"] == "1.0.0"


def test_install_template_creates_bot_and_records_audit():
    pool = FakePool(fetchrow_map={
        "SELECT id, key, category, name, description, preview_image, system_prompt": [
            {"id": "template-1", "key": "sales", "category": "Business", "name": "Sales Agent", "description": "x", "preview_image": None, "system_prompt": "prompt", "greeting": "hi", "primary_color": "#111", "sample_faqs": [], "install_count": 0, "version": "1.0.0", "status": "active", "is_active": True},
        ],
        "FROM tenant_template_installs": [None],
        "INSERT INTO bots": [{"id": "bot-1", "name": "Sales Agent (dari Marketplace)", "primary_color": "#111", "greeting": "hi", "system_prompt": "prompt", "status": "active", "created_at": "2026-01-01"}],
        "INSERT INTO tenant_template_installs": [{"id": "install-1", "installed_at": "2026-01-01"}],
    })
    result = asyncio.run(install_template(pool, org_id="org-1", user_id="user-1", template_key="sales"))
    assert result["install_id"] == "install-1"
    assert result["status"] == "active"
    assert any("INSERT INTO tenant_template_installs" in sql for kind, sql, _ in pool.calls if kind == "fetchrow")
    assert any("UPDATE marketplace_templates SET install_count" in sql for kind, sql, _ in pool.calls if kind == "execute")


def test_update_and_uninstall_use_existing_install():
    install_row = {"id": "install-1", "org_id": "org-1", "template_id": "template-1", "bot_id": "bot-1", "installed_by": "user-1", "installed_at": "2026-01-01", "template_key": "sales", "template_category": "Business", "template_name": "Sales Agent", "template_description": "x", "template_version": "1.0.0", "template_primary_color": "#111", "template_status": "active", "bot_name": "Sales Agent", "bot_status": "active", "bot_primary_color": "#111"}
    update_pool = FakePool(fetchrow_map={
        "FROM tenant_template_installs": [install_row],
        "SELECT id, key, category, name, description, preview_image, system_prompt": [
            {"id": "template-1", "key": "sales", "category": "Business", "name": "Sales Agent", "description": "x", "preview_image": None, "system_prompt": "prompt", "greeting": "hi", "primary_color": "#222", "sample_faqs": [], "install_count": 0, "version": "1.0.1", "status": "active", "is_active": True},
        ],
        "SELECT name FROM bots": [{"name": "Sales Agent"}],
        "UPDATE bots": [{"id": "bot-1", "name": "Sales Agent", "status": "active", "primary_color": "#222", "greeting": "hi", "system_prompt": "prompt", "created_at": "2026-01-01"}],
    })
    updated = asyncio.run(update_install(update_pool, org_id="org-1", user_id="user-1", install_id="install-1", bot_name=None))
    assert updated["template_version"] == "1.0.1"
    update_bot_calls = [(sql, args) for kind, sql, args in update_pool.calls if kind == "fetchrow" and "UPDATE bots" in sql]
    assert update_bot_calls
    # Defense-in-depth: _sync_bot_from_template's UPDATE bots must be scoped
    # by org_id too, not just rely on install_id ownership having been
    # checked earlier (_fetch_install) -- "org-1" must appear in the params.
    assert "org-1" in update_bot_calls[0][1]
    assert "AND org_id=" in update_bot_calls[0][0]

    uninstall_pool = FakePool(fetchrow_map={
        "FROM tenant_template_installs": [install_row],
        "UPDATE bots": [{"id": "bot-1", "name": "Sales Agent", "status": "inactive", "primary_color": "#111", "greeting": "hi", "system_prompt": "prompt", "created_at": "2026-01-01"}],
    })
    result = asyncio.run(uninstall_install(uninstall_pool, org_id="org-1", user_id="user-1", install_id="install-1"))
    assert result["status"] == "inactive"
    uninstall_bot_calls = [(sql, args) for kind, sql, args in uninstall_pool.calls if kind == "fetchrow" and "status='inactive'" in sql]
    assert uninstall_bot_calls
    assert "AND org_id=" in uninstall_bot_calls[0][0]
    assert "org-1" in uninstall_bot_calls[0][1]


def test_marketplace_routes_and_schema_contract_are_present():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/marketplace/templates" in paths
    assert "/api/marketplace/templates/{key}" in paths
    assert "/api/marketplace/install" in paths
    assert "/api/marketplace/installs" in paths
    assert "/api/marketplace/installs/{install_id}/update" in paths
    assert "/api/marketplace/installs/{install_id}/uninstall" in paths
    assert "/api/marketplace/categories" in paths
    assert "/api/marketplace/analytics" in paths
    assert "/api/marketplace/recommended" in paths
    assert "/api/marketplace/supervisor/route" in paths

    schema = Path(__file__).resolve().parent / "schema.sql"
    text = schema.read_text()
    assert "CREATE VIEW agent_templates AS" in text or "CREATE OR REPLACE VIEW agent_templates AS" in text
    for field in ("id", "name", "description", "category", "version", "status"):
        assert field in text
    for table in ("agents", "agent_versions", "agent_installs", "agent_ratings", "agent_categories", "agent_knowledge_sources"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text
