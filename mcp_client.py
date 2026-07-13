"""Minimal but real MCP (Model Context Protocol) client over Streamable HTTP.

Speaks JSON-RPC 2.0 to a remote MCP server: the `initialize` handshake, then
`tools/list` and `tools/call`. Handles both `application/json` and
`text/event-stream` responses and carries the `Mcp-Session-Id` header across
requests, per the MCP spec (https://modelcontextprotocol.io).

This is intentionally dependency-light (httpx only, already a project dep) and
transport-focused; higher-level concerns (server config, schema conversion,
tool dispatch) live in mcp_registry.py.
"""
import json
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"
_CLIENT_INFO = {"name": "botnesia", "version": "1.0.0"}


class McpError(Exception):
    """A JSON-RPC error returned by an MCP server, or a transport failure."""

    def __init__(self, message: str, *, code: int | None = None):
        super().__init__(message)
        self.code = code


def _parse_response(resp: httpx.Response) -> dict:
    """Extract the single JSON-RPC message from a JSON or SSE response body."""
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype == "text/event-stream":
        # Server-Sent Events: take the last `data:` payload that parses as a
        # JSON-RPC message carrying our result/error.
        message: dict | None = None
        for line in resp.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                message = obj
        if message is None:
            raise McpError("MCP SSE response contained no JSON-RPC message")
        return message
    # Default: plain JSON body.
    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise McpError(f"MCP response was not valid JSON: {exc}") from exc


class MCPClient:
    """One connection to a single MCP server (Streamable HTTP transport)."""

    def __init__(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        self._base_headers = {
            "Content-Type": "application/json",
            # MCP Streamable HTTP clients must accept both response encodings.
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._timeout = timeout
        self._transport = transport  # inject a custom/mock transport (tests)
        self._session_id: str | None = None
        self._id = 0
        self._client: httpx.AsyncClient | None = None
        self._initialized = False

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def __aenter__(self) -> "MCPClient":
        self._client = self._new_client()
        await self.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        h = dict(self._base_headers)
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    async def _send(self, method: str, params: dict | None, *, is_notification: bool = False) -> Any:
        if self._client is None:
            self._client = self._new_client()
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not is_notification:
            self._id += 1
            body["id"] = self._id
        try:
            resp = await self._client.post(self.url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise McpError(f"MCP transport error calling {method}: {exc}") from exc
        # The server assigns a session id on the initialize response.
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        if is_notification:
            return None
        if resp.status_code >= 400:
            raise McpError(f"MCP HTTP {resp.status_code} calling {method}: {resp.text[:300]}")
        msg = _parse_response(resp)
        if "error" in msg and msg["error"]:
            err = msg["error"]
            raise McpError(str(err.get("message") or err), code=err.get("code"))
        return msg.get("result")

    async def initialize(self) -> dict:
        """Perform the MCP handshake; returns the server's initialize result."""
        result = await self._send("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": _CLIENT_INFO,
        })
        # Per spec, the client confirms with an `initialized` notification.
        await self._send("notifications/initialized", None, is_notification=True)
        self._initialized = True
        return result or {}

    async def list_tools(self) -> list[dict]:
        """Return the server's tools as raw MCP tool descriptors."""
        result = await self._send("tools/list", {})
        tools = (result or {}).get("tools") or []
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Invoke a tool; returns the raw MCP tool result ({content, isError})."""
        return await self._send("tools/call", {"name": name, "arguments": arguments or {}}) or {}
