"""
stdio shim for local Claude Desktop testing.

Runs the Genie MCP server over stdio so Claude Desktop can connect to it
without needing the full FastAPI app or K8s.

Usage — add to ~/.config/claude/claude_desktop_config.json:

{
  "mcpServers": {
    "genie-local": {
      "command": "python",
      "args": ["-m", "mcp_server.stdio_shim"],
      "cwd": "/path/to/Jennie/backend",
      "env": {
        "PYTHONPATH": ".",
        "DATABASE_URL": "postgresql+asyncpg://genie:genie@localhost:5434/genie",
        "KNOWLEDGE_DIR": "./knowledge",
        "REDSHIFT_MODE": "mock"
      }
    }
  }
}

Then restart Claude Desktop. The "genie-local" connector should appear
in the MCP tools list with all Genie knowledge tools.
"""

import asyncio
import logging
import os
import sys

# Silence noisy loggers on stdio (would corrupt the JSON-RPC stream)
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)


async def main():
    # Bootstrap minimal app state (KB + db_pool) without the full FastAPI lifespan
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from config import config

    # Connect to postgres
    import asyncpg
    dsn = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    db_pool = await asyncpg.create_pool(dsn, min_size=0, max_size=3, command_timeout=60)

    # Download KB from S3 if configured
    try:
        kb_s3_row = await db_pool.fetchrow("""
            SELECT data->>'bucket' as bucket, data->>'prefix' as prefix
            FROM credential_cache WHERE cred_type = 'kb_s3_storage' AND expires_at > NOW() LIMIT 1
        """)
        if kb_s3_row and kb_s3_row["bucket"]:
            from connectors.kb_storage import configure as cfg_s3, download_kb_from_s3
            cfg_s3(kb_s3_row["bucket"], kb_s3_row["prefix"] or "knowledge/")
            download_kb_from_s3(config.KNOWLEDGE_DIR)
    except Exception as e:
        print(f"[genie-stdio] KB S3 skip: {e}", file=sys.stderr)

    # Load KB
    from catalog.loader import KnowledgeBase
    kb = KnowledgeBase(config.KNOWLEDGE_DIR)
    kb.load()
    try:
        await kb.load_glossary_from_db(db_pool)
        await kb.load_table_profiles(db_pool)
        if not kb.lineage:
            await kb.load_lineage_from_db(db_pool)
    except Exception as e:
        print(f"[genie-stdio] Postgres KB partial: {e}", file=sys.stderr)

    print(
        f"[genie-stdio] KB loaded: {len(kb.catalog.get('tables', []))} tables, "
        f"{len(kb.glossary)} glossary, {len(kb.lineage)} lineage",
        file=sys.stderr,
    )

    # Restore credentials
    from connectors.credential_store import set_db_pool, restore_credentials_from_db, credential_store
    set_db_pool(db_pool)
    await restore_credentials_from_db(credential_store)

    # Wire KB into MCP server module
    from mcp_server.server import set_kb, set_db_pool as mcp_set_pool
    set_kb(kb)
    mcp_set_pool(db_pool)

    # Run the MCP server over stdio
    from mcp.server.fastmcp import FastMCP
    from mcp_server import server as _srv

    # Re-create the FastMCP instance configured for stdio
    import mcp_server.server as _server_mod

    # Build a stdio-capable FastMCP by re-using all tool registrations.
    # The simplest approach: run the ASGI app wrapped in stdio transport.
    # FastMCP supports stdio via `mcp.run()`.

    # Reconstruct an MCP server instance that we can run over stdio
    from mcp.server.fastmcp import FastMCP as _FastMCP
    mcp_stdio = _FastMCP(
        "genie-knowledge",
        instructions="Genie Knowledge MCP: the organization data platform business knowledge.",
    )

    # Import and re-register all tools by delegating to the same execute_tool dispatcher
    from engine.tools_executor import execute_tool
    import json

    TOOLS = [
        ("get_data_platform_context", "Get rich KB context: top tables, DOMO metrics, glossary, SQL patterns."),
        ("search_tables", "Search the data catalog for tables matching a keyword."),
        ("get_table_detail", "Get full column/key/row-count details for a table."),
        ("get_table_lineage", "Get upstream/downstream dependencies for a table."),
        ("search_transforms", "Search transform pipeline configurations."),
        ("get_transform_detail", "Get rendered SQL and run history for a DAG."),
        ("get_view_detail", "Get the SQL definition of a metric view."),
        ("glossary_lookup", "Look up a business term in the glossary."),
        ("analyze_domo_dataset", "Analyze a DOMO S3 dataset with DuckDB."),
        ("domo_search", "Search DOMO datasets by name."),
        ("domo_dataset_info", "Get DOMO dataset metadata and schema."),
        ("domo_dashboards", "List DOMO dashboards."),
        ("domo_dashboard_detail", "Get cards on a DOMO dashboard."),
        ("search_events", "Search ProductApp event types."),
        ("get_event_schema", "Get payload schema for a ProductApp event."),
        ("repo_search", "Grep for patterns in locally cloned repos."),
        ("github_file", "Read a file from a cloned repo."),
    ]

    def _make_tool_fn(tool_name: str):
        async def _tool_fn(**kwargs):
            result = await execute_tool(tool_name, kwargs, kb)
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2, default=str)
        _tool_fn.__name__ = tool_name
        return _tool_fn

    for name, desc in TOOLS:
        fn = _make_tool_fn(name)
        fn.__doc__ = desc
        mcp_stdio.tool()(fn)

    # Special handling for get_data_platform_context (needs kb directly)
    @mcp_stdio.tool()
    async def get_data_platform_context(pillar: str = "", environment: str = "np") -> str:
        """Get rich KB context: top 40 tables, DOMO metrics, glossary, SQL patterns."""
        try:
            from engine.context import build_system_prompt
            return build_system_prompt(kb, pillar=pillar or None, environment=environment)
        except Exception as e:
            return f"Error: {e}"

    # Run over stdio
    print("[genie-stdio] Starting MCP server over stdio...", file=sys.stderr)
    mcp_stdio.run(transport="stdio")


if __name__ == "__main__":
    asyncio.run(main())
