"""
Jennie Data MCP Server.

Thin MCP service providing direct Redshift access + MWAA log reads.
Deployed in np K8s (in-VPC) — prd tables accessible via Redshift datashare from np.

Tools:
  execute_query   — SELECT against np Redshift (prd data via datashare)
  list_schemas    — available databases and schemas
  list_tables     — tables in a schema with column counts
  list_columns    — column names, types, nullable for a table
  get_mwaa_dag_runs   — recent DAG run status + timestamps
  get_mwaa_task_log   — task execution log (for rendered SQL)

Credentials from environment:
  REDSHIFT_HOST, REDSHIFT_PORT, REDSHIFT_USER, REDSHIFT_PASSWORD, REDSHIFT_DATABASE
  MWAA_ENV_NAME — environment name for boto3 MWAA API calls
"""

import json
import logging
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("data_mcp")

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "your-org",
    instructions=(
        "Jennie NP Data MCP: direct Redshift access for nonprod + prd (via datashare). "
        "Use execute_query for SELECT queries. list_schemas/list_tables/list_columns for schema discovery. "
        "Use get_mwaa_dag_runs / get_mwaa_task_log to inspect pipeline executions. "
        "All queries are read-only (SELECT only). prd tables are available via np datashare prefix prd_*."
    ),
    streamable_http_path="/",
    stateless_http=True,
)

# ---------------------------------------------------------------------------
# Query safety guard (self-contained — no Genie imports)
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS = re.compile(
    r"^\s*(CREATE|DROP|TRUNCATE|DELETE|INSERT|UPDATE|MERGE|ALTER|GRANT|REVOKE|COPY|UNLOAD)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ALLOWED_PATTERNS = re.compile(
    r"^\s*(SELECT|EXPLAIN|ANALYZE|SET|SHOW|WITH)\b",
    re.IGNORECASE,
)


def _validate_query_safety(sql: str) -> None:
    cleaned = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    for stmt in cleaned.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        if _FORBIDDEN_PATTERNS.search(stmt):
            raise ValueError(
                f"BLOCKED: Only SELECT queries are allowed. Detected: {stmt[:80]}"
            )
        if not _ALLOWED_PATTERNS.match(stmt):
            first_word = stmt.split()[0] if stmt.split() else "?"
            raise ValueError(f"BLOCKED: Unknown statement type '{first_word}'. Only SELECT is allowed.")


# ---------------------------------------------------------------------------
# Redshift connection (direct credentials from env)
# ---------------------------------------------------------------------------

def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _connect():
    """Open a synchronous redshift_connector connection using env-var credentials."""
    import redshift_connector

    host = _get_env("REDSHIFT_HOST")
    port = int(_get_env("REDSHIFT_PORT", "5439"))
    user = _get_env("REDSHIFT_USER")
    password = _get_env("REDSHIFT_PASSWORD")
    database = _get_env("REDSHIFT_DATABASE", "dev")

    if not host or not user or not password:
        raise RuntimeError(
            "Redshift credentials not configured. "
            "Set REDSHIFT_HOST, REDSHIFT_USER, REDSHIFT_PASSWORD environment variables."
        )

    return redshift_connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        timeout=120,
    )


def _json_safe(cell: Any) -> Any:
    from datetime import datetime
    from decimal import Decimal
    if cell is None:
        return None
    if isinstance(cell, (int, float, str, bool)):
        return cell
    if isinstance(cell, Decimal):
        return float(cell)
    if isinstance(cell, datetime):
        return cell.isoformat()
    if isinstance(cell, bytes):
        return cell.decode("utf-8", errors="replace")
    return str(cell)


def _run_query(sql: str, max_rows: int = 1000) -> dict:
    """Execute SQL, return dict with columns + rows."""
    import asyncio
    return asyncio.get_event_loop().run_in_executor(None, _run_query_sync, sql, max_rows)


def _run_query_sync(sql: str, max_rows: int = 1000) -> dict:
    import time
    t0 = time.time()
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        raw_rows = cursor.fetchmany(max_rows)
        rows = [[_json_safe(c) for c in row] for row in raw_rows]
        truncated = len(rows) == max_rows
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "execution_time_ms": int((time.time() - t0) * 1000),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Mock mode (REDSHIFT_MODE=mock)
# ---------------------------------------------------------------------------

def _mock_query(sql: str) -> dict:
    sql_lower = sql.lower().strip()
    if "information_schema.schemata" in sql_lower:
        return {
            "columns": ["catalog_name", "schema_name"],
            "rows": [
                ["dev", "public"],
                ["dev", "information_schema"],
                ["prd_dw", "users"],
                ["prd_dw", "events"],
            ],
            "row_count": 4,
            "truncated": False,
            "execution_time_ms": 1,
        }
    if "information_schema.tables" in sql_lower:
        return {
            "columns": ["table_schema", "table_name", "table_type"],
            "rows": [
                ["users", "users", "BASE TABLE"],
                ["users", "user_events", "BASE TABLE"],
                ["public", "orders", "BASE TABLE"],
            ],
            "row_count": 3,
            "truncated": False,
            "execution_time_ms": 1,
        }
    if "information_schema.columns" in sql_lower:
        return {
            "columns": ["column_name", "data_type", "is_nullable", "ordinal_position"],
            "rows": [
                ["user_id", "integer", "NO", 1],
                ["email", "character varying", "YES", 2],
                ["created_at", "timestamp without time zone", "YES", 3],
            ],
            "row_count": 3,
            "truncated": False,
            "execution_time_ms": 1,
        }
    # Generic SELECT mock
    return {
        "columns": ["result"],
        "rows": [["mock_value"]],
        "row_count": 1,
        "truncated": False,
        "execution_time_ms": 1,
    }


async def _execute_sql(sql: str, max_rows: int = 1000) -> dict:
    mode = _get_env("REDSHIFT_MODE", "real")
    if mode == "mock":
        return _mock_query(sql)
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, _run_query_sync, sql, max_rows)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def execute_query(sql: str, database: str = "", max_rows: int = 500) -> str:
    """
    Execute a SELECT query against Redshift.
    prd data is accessible via datashare — use prd_dw.schema.table notation.
    database parameter is ignored (connect to configured database, use qualified names for cross-db).
    Returns JSON with columns, rows, row_count, execution_time_ms.
    """
    try:
        _validate_query_safety(sql)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    try:
        result = await _execute_sql(sql, max_rows=max_rows)
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error("execute_query failed: %s", e)
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_schemas() -> str:
    """
    List available databases and schemas in Redshift.
    Includes both native np schemas and prd datashare databases (prd_*).
    """
    sql = """
        SELECT catalog_name, schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_internal',
                                   'pg_toast', 'pg_temp_1', 'catalog_history')
        ORDER BY catalog_name, schema_name
    """
    try:
        result = await _execute_sql(sql)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_tables(schema: str = "public", database: str = "") -> str:
    """
    List tables in a schema with column counts.
    Use schema like 'users', 'events', or fully qualified 'prd_dw.users'.
    For prd data: specify database='prd_dw' and the schema name.
    """
    # Parse schema to support "prd_dw.users" notation
    if "." in schema and not database:
        parts = schema.split(".", 1)
        database = parts[0]
        schema = parts[1]

    db_filter = f"AND table_catalog = '{database}'" if database else ""
    sql = f"""
        SELECT table_catalog, table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = '{schema}'
          AND table_type IN ('BASE TABLE', 'VIEW')
          {db_filter}
        ORDER BY table_type, table_name
        LIMIT 200
    """
    try:
        result = await _execute_sql(sql)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_columns(table: str, schema: str = "public", database: str = "") -> str:
    """
    Get column names, types, and nullable flags for a table.
    Supports fully qualified names: table='users.users' or table='users', schema='users'.
    """
    # Parse "schema.table" notation in table arg
    if "." in table:
        parts = table.rsplit(".", 1)
        schema = parts[0]
        table = parts[1]

    db_filter = f"AND table_catalog = '{database}'" if database else ""
    sql = f"""
        SELECT column_name, data_type, is_nullable, ordinal_position, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = '{schema}'
          AND table_name = '{table}'
          {db_filter}
        ORDER BY ordinal_position
    """
    try:
        result = await _execute_sql(sql)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_mwaa_dag_runs(dag_id: str, limit: int = 10) -> str:
    """
    Get recent DAG run status and timestamps from MWAA.
    Returns run_id, state (success/failed/running), start/end date, duration.
    Uses IRSA pod identity — no explicit credentials needed.
    """
    mwaa_env = _get_env("MWAA_ENV_NAME")
    if not mwaa_env:
        return json.dumps({"error": "MWAA_ENV_NAME not configured"})

    try:
        import asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_dag_runs_sync, mwaa_env, dag_id, limit
        )
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error("get_mwaa_dag_runs failed: %s", e)
        return json.dumps({"error": str(e)})


def _fetch_dag_runs_sync(mwaa_env: str, dag_id: str, limit: int) -> dict:
    import urllib.request
    import boto3

    client = boto3.client("mwaa")
    token_resp = client.create_web_login_token(Name=mwaa_env)
    web_token = token_resp["WebToken"]
    web_server_url = f"https://{token_resp['WebServerHostname']}"

    # Get Airflow REST API session cookie
    login_url = f"{web_server_url}/aws_mwaa/aws-console-sso?login=true"
    req = urllib.request.Request(login_url, headers={"Authorization": f"Bearer {web_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        cookie = resp.headers.get("Set-Cookie", "")

    # Fetch dag runs
    api_url = f"{web_server_url}/api/v1/dags/{dag_id}/dagRuns?limit={limit}&order_by=-execution_date"
    req2 = urllib.request.Request(api_url, headers={"Cookie": cookie, "Content-Type": "application/json"})
    with urllib.request.urlopen(req2, timeout=30) as resp:
        data = json.loads(resp.read())

    runs = []
    for run in data.get("dag_runs", []):
        runs.append({
            "dag_run_id": run.get("dag_run_id"),
            "state": run.get("state"),
            "execution_date": run.get("execution_date"),
            "start_date": run.get("start_date"),
            "end_date": run.get("end_date"),
        })
    return {"dag_id": dag_id, "dag_runs": runs, "total_entries": data.get("total_entries", len(runs))}


@mcp.tool()
async def get_mwaa_task_log(dag_id: str, dag_run_id: str, task_id: str) -> str:
    """
    Get task execution log from MWAA.
    Use get_mwaa_dag_runs first to find a run_id.
    Task logs contain rendered SQL (Jinja-resolved) for TRANSFORM_DAG__ pipelines.
    task_id is typically 'run_sql' or the last task in the DAG.
    """
    mwaa_env = _get_env("MWAA_ENV_NAME")
    if not mwaa_env:
        return json.dumps({"error": "MWAA_ENV_NAME not configured"})

    try:
        import asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_task_log_sync, mwaa_env, dag_id, dag_run_id, task_id
        )
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error("get_mwaa_task_log failed: %s", e)
        return json.dumps({"error": str(e)})


def _fetch_task_log_sync(mwaa_env: str, dag_id: str, dag_run_id: str, task_id: str) -> dict:
    import urllib.request
    import urllib.parse
    import boto3

    client = boto3.client("mwaa")
    token_resp = client.create_web_login_token(Name=mwaa_env)
    web_token = token_resp["WebToken"]
    web_server_url = f"https://{token_resp['WebServerHostname']}"

    login_url = f"{web_server_url}/aws_mwaa/aws-console-sso?login=true"
    req = urllib.request.Request(login_url, headers={"Authorization": f"Bearer {web_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        cookie = resp.headers.get("Set-Cookie", "")

    encoded_run_id = urllib.parse.quote(dag_run_id, safe="")
    api_url = (
        f"{web_server_url}/api/v1/dags/{dag_id}/dagRuns/{encoded_run_id}"
        f"/taskInstances/{task_id}/logs/1"
    )
    req2 = urllib.request.Request(api_url, headers={"Cookie": cookie, "Accept": "text/plain"})
    with urllib.request.urlopen(req2, timeout=60) as resp:
        log_content = resp.read().decode("utf-8", errors="replace")

    # Trim log to last 8K to avoid token bloat
    if len(log_content) > 8000:
        log_content = "...(truncated)...\n" + log_content[-8000:]

    return {
        "dag_id": dag_id,
        "dag_run_id": dag_run_id,
        "task_id": task_id,
        "log": log_content,
    }
