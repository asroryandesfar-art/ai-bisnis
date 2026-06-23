"""test_tool_executor.py — tool_executor.py: skema valid + eksekutor nyata
dengan pool/dependency palsu (no network/DB sungguhan di test)."""
import asyncio

import tool_executor as te


def test_all_seven_required_tools_have_schema_and_executor():
    required = {"knowledge_search", "memory_lookup", "file_reader", "database_query",
                "web_search", "browser_open", "browser_extract"}
    assert required <= set(te.TOOL_SCHEMAS)
    assert required <= set(te._EXECUTORS)
    for name in required:
        schema = te.TOOL_SCHEMAS[name]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == name
        assert "parameters" in schema["function"]


def test_available_tool_schemas_filters_by_name():
    schemas = te.available_tool_schemas(["knowledge_search", "not_a_real_tool"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "knowledge_search"


def test_execute_tool_unknown_name_returns_honest_error():
    result = asyncio.run(te.execute_tool("does_not_exist", {}, ctx={}))
    assert result["success"] is False
    assert "tidak dikenal" in result["error"]


def test_execute_tool_catches_exception_as_honest_error():
    async def _boom(args, ctx):
        raise RuntimeError("simulated failure")
    te._EXECUTORS["_test_boom"] = _boom
    try:
        result = asyncio.run(te.execute_tool("_test_boom", {}, ctx={}))
        assert result == {"success": False, "error": "simulated failure"}
    finally:
        del te._EXECUTORS["_test_boom"]


def test_database_query_rejects_table_outside_allowlist():
    class FakePool:
        async def fetch(self, *a, **k):
            raise AssertionError("tidak boleh sampai query -- harus ditolak sebelum itu")
    result = asyncio.run(te.execute_tool(
        "database_query", {"table": "users"}, ctx={"pool": FakePool(), "org_id": "org-1"}
    ))
    assert result["success"] is False
    assert "tidak diizinkan" in result["error"]


def test_database_query_always_scopes_by_org_id_from_ctx_not_args():
    captured = {}

    class FakePool:
        async def fetch(self, sql, *args):
            captured["sql"] = sql
            captured["args"] = args
            return [{"id": "row-1", "status": "paid"}]

    result = asyncio.run(te.execute_tool(
        "database_query",
        {"table": "finance_invoices", "filter_value": "paid", "org_id": "attacker-org"},
        ctx={"pool": FakePool(), "org_id": "real-org-from-ctx"},
    ))
    assert result["success"] is True
    assert captured["args"][0] == "real-org-from-ctx"
    assert "WHERE org_id=$1" in captured["sql"]


def test_file_reader_returns_honest_error_when_document_not_found():
    class FakePool:
        async def fetchrow(self, *a, **k):
            return None
    result = asyncio.run(te.execute_tool(
        "file_reader", {"document_id": "missing"}, ctx={"pool": FakePool(), "org_id": "org-1"}
    ))
    assert result["success"] is False
    assert "tidak ditemukan" in result["error"]


def test_parse_tool_call_args_never_raises_on_bad_json():
    assert te.parse_tool_call_args("not json") == {}
    assert te.parse_tool_call_args('{"a": 1}') == {"a": 1}
    assert te.parse_tool_call_args("") == {}
