"""
Genie Knowledge MCP Server.

Exposes Genie's business knowledge tools to claude.ai via Streamable HTTP transport.
All tool calls delegate to engine/tools_executor.py (no Claude/Bedrock dependencies here).

Integration pattern:
  - `build_mcp()` creates and returns the FastMCP instance (call once at startup)
  - `get_mcp_asgi_handler()` returns the raw ASGI callable for FastAPI `add_route`
  - `start_session_manager()` / `stop_session_manager()` must be called in FastAPI lifespan
    to satisfy the MCP session manager task group requirement

Mounted in main.py via api/mcp_router.py:
    from api.mcp_router import setup_mcp
    setup_mcp(app)   # call at module level after app = FastAPI(...)
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("genie.mcp")

# Module-level KB — set during lifespan startup
_kb = None
_db_pool = None

# The FastMCP instance — created once by build_mcp() / get_mcp()
_mcp: FastMCP | None = None


def set_kb(kb) -> None:
    global _kb
    _kb = kb


def set_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


def _result_to_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, default=str)


def get_mcp() -> FastMCP:
    """Return the module-level FastMCP instance, creating it if needed."""
    global _mcp
    if _mcp is None:
        _mcp = _build_mcp()
    return _mcp


def _build_mcp() -> FastMCP:
    """Create the FastMCP server and register all tools. Called once."""
    mcp = FastMCP(
        "genie-knowledge",
        instructions=(
            "Genie Knowledge MCP: your data platform business knowledge layer. "
            "Provides enriched table catalog, lineage graph, business glossary, "
            "DOMO metrics, ProductApp event schemas, and rendered pipeline SQL "
            "from MWAA task logs. Start with get_data_platform_context for orientation."
        ),
        streamable_http_path="/",   # Effective public path = /mcp (mount prefix + "/")
        stateless_http=True,        # Stateless: no persistent sessions, simpler for remote clients
    )

    # ── Context tool ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_data_platform_context(
        pillar: str = "",
        environment: str = "np",
    ) -> str:
        """
        Get a rich summary of your data platform — top 40 tables with columns,
        top 25 DOMO metrics, top 20 business definitions, active Statsig experiments,
        and common SQL patterns. Call this first to orient yourself before deeper lookups.
        Returns ~6K of inline KB context so you can write SQL on the first attempt.
        """
        if _kb is None:
            return "Knowledge base not loaded yet — try again in a few seconds."
        try:
            from engine.context import build_system_prompt
            dynamic_patterns = None
            if _db_pool:
                try:
                    rows = await _db_pool.fetch(
                        "SELECT name, sql FROM saved_queries ORDER BY run_count DESC LIMIT 5"
                    )
                    if rows:
                        dynamic_patterns = [dict(r) for r in rows]
                except Exception:
                    pass
            return build_system_prompt(
                _kb,
                pillar=pillar or None,
                environment=environment,
                dynamic_sql_patterns=dynamic_patterns,
            )
        except Exception as e:
            logger.error("get_data_platform_context error: %s", e)
            return f"Error building context: {e}"

    # ── Catalog tools ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def search_tables(keyword: str) -> str:
        """Search the data catalog for tables matching a keyword."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("search_tables", {"keyword": keyword}, _kb))

    @mcp.tool()
    async def get_table_detail(table_name: str) -> str:
        """Get full column/key/row-count details for a specific table."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("get_table_detail", {"table_name": table_name}, _kb))

    @mcp.tool()
    async def get_table_lineage(table_name: str, direction: str = "both") -> str:
        """Get upstream/downstream dependencies for a table. direction: upstream|downstream|both."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool(
            "get_table_lineage", {"table_name": table_name, "direction": direction}, _kb
        ))

    @mcp.tool()
    async def search_transforms(keyword: str) -> str:
        """Search for transform pipeline configurations matching a keyword."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("search_transforms", {"keyword": keyword}, _kb))

    @mcp.tool()
    async def get_transform_detail(dag_id: str) -> str:
        """
        Get full details for a DAG including rendered SQL from MWAA task logs
        (actual Jinja-resolved query), task stats, and run history.
        This is Genie's key differentiator — no AWS API exposes rendered SQL directly.
        """
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("get_transform_detail", {"dag_id": dag_id}, _kb))

    @mcp.tool()
    async def get_view_detail(view_name: str) -> str:
        """Get the SQL definition of a Redshift view/metric with DOMO dataset link."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("get_view_detail", {"view_name": view_name}, _kb))

    # ── Glossary ──────────────────────────────────────────────────────────────

    @mcp.tool()
    async def glossary_lookup(term: str) -> str:
        """Look up a business term: definition, formula, source table, DAG, pillar."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("glossary_lookup", {"term": term}, _kb))

    # ── DOMO tools ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def analyze_domo_dataset(metric_name: str, query: str = "", limit: int = 100) -> str:
        """
        Analyze a DOMO S3 dataset with DuckDB — no Redshift load needed.
        Use for metric questions (engagement, activation, etc.) instead of querying Redshift directly.
        """
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        args: dict = {"metric_name": metric_name, "limit": limit}
        if query:
            args["query"] = query
        return _result_to_text(await execute_tool("analyze_domo_dataset", args, _kb))

    @mcp.tool()
    async def domo_search(query: str) -> str:
        """Search DOMO datasets by name."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("domo_search", {"query": query}, _kb))

    @mcp.tool()
    async def domo_dataset_info(dataset_id: str) -> str:
        """Get DOMO dataset metadata, schema, row count, last updated."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("domo_dataset_info", {"dataset_id": dataset_id}, _kb))

    @mcp.tool()
    async def domo_dashboards() -> str:
        """List DOMO dashboards with card counts."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("domo_dashboards", {}, _kb))

    @mcp.tool()
    async def domo_dashboard_detail(page_id: str) -> str:
        """Get cards on a specific DOMO dashboard."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("domo_dashboard_detail", {"page_id": page_id}, _kb))

    # ── Event schemas ─────────────────────────────────────────────────────────

    @mcp.tool()
    async def search_events(keyword: str) -> str:
        """Search ProductApp event types by keyword (558 events from Swagger spec)."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("search_events", {"keyword": keyword}, _kb))

    @mcp.tool()
    async def get_event_schema(event_name: str) -> str:
        """
        Get payload schema for a ProductApp event. Use before querying
        firehose_v3_enriched to know exact SUPER column field names.
        """
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool("get_event_schema", {"event_name": event_name}, _kb))

    # ── Repo / code ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def repo_search(pattern: str, file_pattern: str = "", repo: str = "data_platform") -> str:
        """Grep for patterns in locally cloned repos. repo: data_platform or gitops."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        args = {"pattern": pattern, "repo": repo}
        if file_pattern:
            args["file_pattern"] = file_pattern
        return _result_to_text(await execute_tool("repo_search", args, _kb))

    @mcp.tool()
    async def github_file(repo: str, path: str, branch: str = "main") -> str:
        """Read a file from a cloned repo. Use repo_search first to find it."""
        if _kb is None:
            return json.dumps({"error": "Knowledge base not loaded"})
        from engine.tools_executor import execute_tool
        return _result_to_text(await execute_tool(
            "github_file", {"repo": repo, "path": path, "branch": branch}, _kb
        ))

    return mcp


@asynccontextmanager
async def lifespan_context():
    """
    Async context manager that starts/stops the MCP session manager.
    Must be entered inside FastAPI's lifespan — after KB is loaded — so that
    tools_executor requests succeed.

    Usage in main.py lifespan (after KB wired):
        from mcp_server.server import lifespan_context
        async with lifespan_context():
            yield
    """
    mcp = get_mcp()
    # Calling streamable_http_app() initialises the session manager lazily.
    # We then start it via the async context manager.
    _ = mcp.streamable_http_app()  # ensures _session_manager is created
    logger.info("MCP session manager: starting")
    async with mcp._session_manager.run():
        logger.info("MCP session manager: running")
        yield
    logger.info("MCP session manager: stopped")


def get_mcp_asgi_handler():
    """
    Return the raw ASGI callable that handles /mcp requests.
    Used by mcp_router.py to add the route directly to FastAPI (no sub-app mount).
    """
    mcp = get_mcp()
    starlette_app = mcp.streamable_http_app()
    # The Starlette app itself is the ASGI callable — but it wraps our handler
    # at path "/". We return the whole Starlette app; it will be added as a
    # mounted sub-app so path "/" inside it maps to "/mcp" externally.
    return starlette_app
