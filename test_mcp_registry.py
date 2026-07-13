"""Tests for the MCP registry (discovery -> schemas + dispatch) and the
tool_executor mcp__* routing hook."""
import asyncio
import json

import httpx
import pytest

import mcp_registry
import tool_executor
from mcp_registry import MCPRegistry, parse_servers_env


def _server_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        m = body.get("method")
        if m == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s1"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if m == "notifications/initialized":
            return httpx.Response(202, json={})
        if m == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [
                {"name": "search", "description": "Search docs",
                 "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}},
            ]}})
        if m == "tools/call":
            args = body["params"]["arguments"]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "content": [{"type": "text", "text": f"hits for {args.get('q')}"}], "isError": False}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"),
                                         "error": {"code": -32601, "message": "no"}})
    return httpx.MockTransport(handler)


def _registry():
    reg = MCPRegistry({"docs": {"url": "http://mock/mcp"}})
    # inject the mock transport into every client the registry opens
    transport = _server_transport()
    reg._server_client = lambda name: mcp_registry.MCPClient("http://mock/mcp", transport=transport)
    return reg


def test_discover_builds_namespaced_schemas():
    reg = _registry()
    n = asyncio.run(reg.discover())
    assert n == 1
    schemas = reg.tool_schemas()
    assert schemas[0]["function"]["name"] == "mcp__docs__search"
    assert schemas[0]["function"]["parameters"]["properties"]["q"]["type"] == "string"
    assert reg.owns("mcp__docs__search")


def test_call_routes_and_flattens_text():
    reg = _registry()
    asyncio.run(reg.discover())
    res = asyncio.run(reg.call("mcp__docs__search", {"q": "invoices"}))
    assert res["success"] is True
    assert res["result"] == "hits for invoices"


def test_call_unknown_tool_is_error():
    reg = _registry()
    asyncio.run(reg.discover())
    res = asyncio.run(reg.call("mcp__docs__nope", {}))
    assert res["success"] is False


def test_parse_servers_env():
    assert parse_servers_env(None) == {}
    assert parse_servers_env("not json") == {}
    parsed = parse_servers_env('{"a": {"url": "http://x"}, "bad": {"no_url": 1}}')
    assert "a" in parsed and parsed["a"]["url"] == "http://x"
    assert "bad" not in parsed  # missing url is dropped


def test_tool_executor_routes_mcp_when_configured(monkeypatch):
    reg = _registry()
    asyncio.run(reg.discover())
    monkeypatch.setattr(mcp_registry, "_registry", reg)
    res = asyncio.run(tool_executor.execute_tool("mcp__docs__search", {"q": "x"}, ctx={}))
    assert res["success"] is True
    assert res["result"] == "hits for x"


def test_tool_executor_mcp_without_config_is_graceful(monkeypatch):
    monkeypatch.setattr(mcp_registry, "_registry", None)
    res = asyncio.run(tool_executor.execute_tool("mcp__docs__search", {"q": "x"}, ctx={}))
    assert res["success"] is False
    assert "MCP" in res["error"]


def test_available_tool_schemas_includes_requested_mcp_tool(monkeypatch):
    import asyncio
    reg = _registry()
    asyncio.run(reg.discover())
    monkeypatch.setattr(mcp_registry, "_registry", reg)
    # agent lists a built-in AND an mcp tool; both schemas returned
    got = tool_executor.available_tool_schemas(["calculator", "mcp__docs__search", "mcp__docs__missing"])
    names = [s["function"]["name"] for s in got]
    assert "mcp__docs__search" in names
    assert "mcp__docs__missing" not in names  # not discovered -> omitted


def test_available_tool_schemas_no_mcp_when_unconfigured(monkeypatch):
    monkeypatch.setattr(mcp_registry, "_registry", None)
    got = tool_executor.available_tool_schemas(["mcp__docs__search"])
    assert got == []
