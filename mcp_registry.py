"""MCP server registry: discover tools from configured MCP servers, expose them
as OpenAI/Groq function schemas, and dispatch tool calls.

Bridges the MCP client (mcp_client.py) into BotNesia's existing tool-calling
framework (tool_executor.py / base.py `_call_llm_with_tools`). Discovered tools
are namespaced `mcp__<server>__<tool>` so they never collide with built-in
tools, and dispatch is an exact lookup (no fragile name parsing).

Servers are configured via the MCP_SERVERS env var, a JSON object:
    {"github": {"url": "https://mcp.example/github", "headers": {"Authorization": "Bearer .."}}}
"""
import json
import logging
import os
import re

from mcp_client import MCPClient, McpError

logger = logging.getLogger("botnesia.mcp")

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _fq_name(server: str, tool: str) -> str:
    """Namespaced, OpenAI-safe function name for an MCP tool (<=64 chars)."""
    raw = f"mcp__{server}__{tool}"
    return _NAME_RE.sub("_", raw)[:64]


def _content_to_text(result: dict) -> str:
    """Flatten an MCP tool result's content blocks into plain text."""
    parts = []
    for block in (result or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, dict):
            parts.append(json.dumps(block))
    return "\n".join(p for p in parts if p)


class MCPRegistry:
    def __init__(self, servers: dict[str, dict]):
        # servers: name -> {"url": str, "headers": dict|None, "timeout": float|None}
        self._servers = servers
        # fq_name -> (server_name, mcp_tool_name)
        self._tools: dict[str, tuple[str, str]] = {}
        # OpenAI/Groq function schemas for discovered tools
        self._schemas: list[dict] = []
        self._discovered = False

    def _server_client(self, name: str) -> MCPClient:
        cfg = self._servers[name]
        return MCPClient(cfg["url"], headers=cfg.get("headers"), timeout=cfg.get("timeout", 30.0))

    async def discover(self) -> int:
        """Connect to every configured server and cache their tool schemas.
        Returns the number of tools discovered. A failing server is skipped
        (logged) so one bad server can't disable all MCP tools."""
        self._tools.clear()
        self._schemas.clear()
        for name in self._servers:
            try:
                async with self._server_client(name) as client:
                    tools = await client.list_tools()
            except (McpError, Exception) as exc:  # noqa: BLE001
                logger.warning("MCP discover failed for server %s: %s", name, exc)
                continue
            for t in tools:
                tool_name = t["name"]
                fq = _fq_name(name, tool_name)
                self._tools[fq] = (name, tool_name)
                self._schemas.append({
                    "type": "function",
                    "function": {
                        "name": fq,
                        "description": t.get("description") or f"MCP tool {tool_name} from {name}",
                        "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                    },
                })
        self._discovered = True
        return len(self._tools)

    def tool_schemas(self) -> list[dict]:
        """OpenAI/Groq function schemas for all discovered MCP tools."""
        return list(self._schemas)

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def owns(self, name: str) -> bool:
        return name in self._tools or name.startswith("mcp__")

    async def call(self, name: str, args: dict) -> dict:
        """Dispatch an mcp__* tool call. Returns the tool_executor result shape
        ({"success": bool, ...})."""
        entry = self._tools.get(name)
        if entry is None:
            return {"success": False, "error": f"Unknown MCP tool '{name}'"}
        server, tool_name = entry
        try:
            async with self._server_client(server) as client:
                result = await client.call_tool(tool_name, args or {})
        except McpError as exc:
            return {"success": False, "error": f"MCP call failed: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"MCP call error: {exc}"}
        text = _content_to_text(result)
        if result.get("isError"):
            return {"success": False, "error": text or "MCP tool reported an error"}
        return {"success": True, "result": text, "raw": result}


def parse_servers_env(raw: str | None) -> dict[str, dict]:
    """Parse the MCP_SERVERS env JSON into a validated servers dict (safe)."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("MCP_SERVERS is not valid JSON; ignoring")
        return {}
    servers: dict[str, dict] = {}
    if isinstance(data, dict):
        for name, spec in data.items():
            if isinstance(spec, dict) and isinstance(spec.get("url"), str):
                servers[str(name)] = {
                    "url": spec["url"],
                    "headers": spec.get("headers") if isinstance(spec.get("headers"), dict) else None,
                    "timeout": float(spec["timeout"]) if isinstance(spec.get("timeout"), (int, float)) else 30.0,
                }
    return servers


# ── Process-wide singleton (opt-in; empty until configured) ──────
_registry: MCPRegistry | None = None


def get_registry() -> MCPRegistry | None:
    """The active MCP registry, or None if no MCP servers are configured."""
    return _registry


def configure_from_env() -> MCPRegistry | None:
    """Build the singleton from MCP_SERVERS. Call discover() separately (async)."""
    global _registry
    servers = parse_servers_env(os.environ.get("MCP_SERVERS"))
    _registry = MCPRegistry(servers) if servers else None
    return _registry
