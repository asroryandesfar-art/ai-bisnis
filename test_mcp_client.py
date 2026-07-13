"""Tests for the MCP client (JSON-RPC over Streamable HTTP), using a mock
httpx transport that emulates a real MCP server (JSON + SSE responses)."""
import asyncio
import json

import httpx
import pytest

from mcp_client import MCPClient, McpError


def _make_server(*, sse=False, session_id="sess-abc"):
    """A minimal in-memory MCP server over httpx.MockTransport."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((body.get("method"), body.get("params"), dict(request.headers)))
        method = body.get("method")
        headers = {}

        def rpc_result(result):
            msg = {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
            if sse:
                text = f"event: message\ndata: {json.dumps(msg)}\n\n"
                return httpx.Response(200, headers={**headers, "content-type": "text/event-stream"}, text=text)
            return httpx.Response(200, headers=headers, json=msg)

        if method == "initialize":
            headers["mcp-session-id"] = session_id
            return rpc_result({"protocolVersion": "2025-06-18", "serverInfo": {"name": "mock", "version": "0"}})
        if method == "notifications/initialized":
            return httpx.Response(202, json={})  # notification: no body needed
        if method == "tools/list":
            return rpc_result({"tools": [
                {"name": "add", "description": "Add two numbers",
                 "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}},
                {"name": "echo", "description": "Echo text", "inputSchema": {"type": "object"}},
                {"bad": "no-name"},  # must be filtered out
            ]})
        if method == "tools/call":
            args = body["params"]["arguments"]
            if body["params"]["name"] == "add":
                return rpc_result({"content": [{"type": "text", "text": str(args["a"] + args["b"])}], "isError": False})
            return rpc_result({"content": [{"type": "text", "text": "err"}], "isError": True})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"),
                                         "error": {"code": -32601, "message": "Method not found"}})

    return httpx.MockTransport(handler), calls


def _client(transport):
    return MCPClient("http://mock/mcp", transport=transport)


def test_initialize_and_list_tools_json():
    transport, calls = _make_server()

    async def go():
        async with _client(transport) as c:
            tools = await c.list_tools()
            return tools, c._session_id

    tools, sid = asyncio.run(go())
    names = [t["name"] for t in tools]
    assert names == ["add", "echo"]  # the {"bad":...} entry is filtered
    assert sid == "sess-abc"
    # session id echoed back after initialize
    assert any(m == "tools/list" and h.get("mcp-session-id") == "sess-abc" for m, _, h in calls)


def test_call_tool_returns_result():
    transport, _ = _make_server()

    async def go():
        async with _client(transport) as c:
            return await c.call_tool("add", {"a": 2, "b": 3})

    res = asyncio.run(go())
    assert res["isError"] is False
    assert res["content"][0]["text"] == "5"


def test_sse_response_is_parsed():
    transport, _ = _make_server(sse=True)

    async def go():
        async with _client(transport) as c:
            return await c.list_tools()

    tools = asyncio.run(go())
    assert [t["name"] for t in tools] == ["add", "echo"]


def test_jsonrpc_error_raises_mcperror():
    transport, _ = _make_server()

    async def go():
        async with _client(transport) as c:
            await c._send("nonexistent/method", {})

    with pytest.raises(McpError) as ei:
        asyncio.run(go())
    assert ei.value.code == -32601


def test_transport_failure_raises_mcperror():
    def boom(request):
        raise httpx.ConnectError("refused")

    async def go():
        async with _client(httpx.MockTransport(boom)) as c:
            await c.list_tools()

    with pytest.raises(McpError):
        asyncio.run(go())
