"""
MCP Bridge — persistent connections to MCP servers.

Supports multiple servers:
- GitHub MCP (Node.js): @modelcontextprotocol/server-github
- DOMO MCP (Python): domo_mcp — dataset search, metadata, schema, SQL query

Each server gets its own persistent session. Tool names are prefixed to avoid collisions:
- github__<tool> for GitHub tools
- domo__<tool> for DOMO tools
"""

import asyncio
import json
import logging
from typing import Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import config

logger = logging.getLogger("genie.mcp")


class MCPServer:
    """Manages a single MCP server subprocess with persistent session."""

    def __init__(self, name: str, prefix: str, params: StdioServerParameters, tool_filter: list[str] | None = None):
        self.name = name
        self.prefix = prefix  # e.g., "github__" or "domo__"
        self.params = params
        self.tool_filter = tool_filter  # if set, only include these tool names
        self.tools: list[dict] = []
        self.session: ClientSession | None = None
        self.exit_stack: AsyncExitStack | None = None
        self.initialized = False

    async def start(self):
        """Start the MCP server and establish persistent session."""
        if self.initialized:
            return
        try:
            self.exit_stack = AsyncExitStack()
            read, write = await self.exit_stack.enter_async_context(stdio_client(self.params))
            self.session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()

            tools_result = await self.session.list_tools()
            for tool in tools_result.tools:
                # Apply filter if set
                if self.tool_filter and tool.name not in self.tool_filter:
                    continue
                self.tools.append({
                    "name": f"{self.prefix}{tool.name}",
                    "description": f"[{self.name}] {tool.description}",
                    "input_schema": tool.inputSchema,
                    "_mcp_name": tool.name,
                    "_server": self.name,
                })

            logger.info("%s MCP: persistent session started, %d tools: %s",
                        self.name, len(self.tools), [t["name"] for t in self.tools])
            self.initialized = True

        except Exception as e:
            logger.warning("%s MCP initialization failed: %s", self.name, e)
            self.session = None
            if self.exit_stack:
                await self.exit_stack.aclose()
                self.exit_stack = None
            self.initialized = True  # mark as tried

    async def call_tool(self, mcp_name: str, arguments: dict) -> Any:
        """Call a tool on this server."""
        if not self.session:
            return {"error": f"{self.name} MCP session not available"}

        try:
            result = await asyncio.wait_for(
                self.session.call_tool(mcp_name, arguments),
                timeout=30,
            )
            if result.content:
                texts = [c.text for c in result.content if hasattr(c, 'text')]
                combined = "\n".join(texts)
                try:
                    return json.loads(combined)
                except (json.JSONDecodeError, TypeError):
                    if len(combined) > 8000:
                        combined = combined[:8000] + "\n... (truncated)"
                    return {"result": combined}
            return {"result": "No content returned"}

        except asyncio.TimeoutError:
            logger.warning("%s MCP tool call timed out: %s", self.name, mcp_name)
            return {"error": f"Tool call timed out (30s)"}
        except Exception as e:
            logger.error("%s MCP tool call failed (%s): %s", self.name, mcp_name, e)
            self.session = None
            return {"error": f"MCP call failed: {str(e)[:200]}. Session will reconnect on next request."}

    async def shutdown(self):
        if self.exit_stack:
            await self.exit_stack.aclose()
            self.exit_stack = None
        self.session = None


# Global registry
_servers: dict[str, MCPServer] = {}
_all_tools: list[dict] = []
_initialized = False


def _build_servers() -> list[MCPServer]:
    """Build MCP server configs based on available credentials."""
    servers = []

    # GitHub MCP (Node.js)
    if config.GITHUB_TOKEN:
        servers.append(MCPServer(
            name="GitHub",
            prefix="github__",
            params=StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": config.GITHUB_TOKEN},
            ),
            tool_filter=["search_code", "get_file_contents", "list_commits", "search_repositories"],
        ))
    else:
        logger.info("GitHub MCP disabled (no GITHUB_TOKEN)")

    # DOMO uses direct API calls (connectors/domo_client.py), not MCP
    # Token managed via Settings → Connection, loaded from postgres on startup

    return servers


async def initialize():
    """Start all configured MCP servers."""
    global _initialized, _all_tools, _servers
    if _initialized:
        return

    server_list = _build_servers()
    for server in server_list:
        await server.start()
        _servers[server.name] = server
        _all_tools.extend(server.tools)

    if _all_tools:
        logger.info("MCP bridge: %d total tools from %d servers", len(_all_tools), len(_servers))
    _initialized = True


async def shutdown():
    """Cleanup all servers."""
    for server in _servers.values():
        await server.shutdown()
    _servers.clear()


def get_mcp_tools() -> list[dict]:
    """Get all discovered MCP tools for agent registration."""
    return _all_tools


async def call_mcp_tool(tool_name: str, arguments: dict) -> Any:
    """Route a tool call to the correct MCP server."""
    # Find which tool this is
    for tool in _all_tools:
        if tool["name"] == tool_name:
            server_name = tool["_server"]
            server = _servers.get(server_name)
            if not server:
                return {"error": f"MCP server '{server_name}' not available"}
            return await server.call_tool(tool["_mcp_name"], arguments)

    return {"error": f"Unknown MCP tool: {tool_name}"}
