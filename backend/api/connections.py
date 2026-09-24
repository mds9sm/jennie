"""
Redshift Connection Manager — CRUD for named connections.
Passwords stored in postgres, never logged, never in Claude context.
"""

import asyncio
import json
import logging
from typing import Optional

import redshift_connector
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("genie.connections")
router = APIRouter()

# Upper bound for any blocking Redshift work done in a worker thread.
_BROWSE_TIMEOUT_SECONDS = 75


async def _named_conn_kwargs(request: Request, connection_id: int) -> dict:
    """Look up a named connection's connect kwargs from postgres."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT host, port, database, username, password FROM redshift_connections WHERE id = $1",
        connection_id,
    )
    if not row:
        raise HTTPException(404, "Connection not found")
    return dict(
        host=row["host"], port=row["port"], database=row["database"],
        user=row["username"], password=row["password"], timeout=15,
    )


async def _browse_query(
    request: Request,
    environment: str,
    connection_id: int,
    session_id: str,
    sql: str,
    params: tuple | None = None,
):
    """
    Run a read-only metadata query in a worker thread so blocking Redshift
    I/O (connect + execute) can never stall the event loop.
    """
    conn_kwargs = await _named_conn_kwargs(request, connection_id) if connection_id else None

    def _run():
        if conn_kwargs:
            conn = redshift_connector.connect(**conn_kwargs)
        else:
            from connectors.redshift import _get_connection
            conn = _get_connection(environment, session_id)
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()
            return rows
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return await asyncio.wait_for(asyncio.to_thread(_run), timeout=_BROWSE_TIMEOUT_SECONDS)


def _require_auth(request: Request):
    """Require authentication for all connection endpoints."""
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


class ConnectionCreate(BaseModel):
    name: str
    host: str
    port: int = 5439
    database: str = "dev"
    username: str
    password: str
    environment: str = "np"
    is_default: bool = False


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    environment: Optional[str] = None
    is_default: Optional[bool] = None


@router.get("")
async def list_connections(request: Request):
    """List all connections (passwords masked)."""
    _require_auth(request)
    pool = request.app.state.db_pool
    rows = await pool.fetch(
        "SELECT id, name, host, port, database, username, environment, is_default, created_at, updated_at "
        "FROM redshift_connections ORDER BY is_default DESC, name"
    )
    return [dict(r) for r in rows]


@router.post("")
async def create_connection(body: ConnectionCreate, request: Request):
    """Create a new named connection."""
    _require_auth(request)
    pool = request.app.state.db_pool
    try:
        row = await pool.fetchrow("""
            INSERT INTO redshift_connections (name, host, port, database, username, password, environment, is_default)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """, body.name, body.host, body.port, body.database,
            body.username, body.password, body.environment, body.is_default)

        if body.is_default:
            await pool.execute(
                "UPDATE redshift_connections SET is_default = false WHERE id != $1", row["id"]
            )

        logger.info("Created connection '%s' (user=%s, env=%s)", body.name, body.username, body.environment)
        return {"status": "created", "id": row["id"]}
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(409, f"Connection '{body.name}' already exists")
        raise HTTPException(500, str(e))


@router.put("/{conn_id}")
async def update_connection(conn_id: int, body: ConnectionUpdate, request: Request):
    """Update a connection."""
    _require_auth(request)
    pool = request.app.state.db_pool
    updates = ["updated_at = NOW()"]
    params = [conn_id]
    idx = 2

    for field in ("name", "host", "port", "database", "username", "password", "environment", "is_default"):
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1

    await pool.execute(
        f"UPDATE redshift_connections SET {', '.join(updates)} WHERE id = $1",
        *params,
    )

    if body.is_default:
        await pool.execute(
            "UPDATE redshift_connections SET is_default = false WHERE id != $1", conn_id
        )

    return {"status": "updated"}


@router.delete("/{conn_id}")
async def delete_connection(conn_id: int, request: Request):
    """Delete a connection."""
    _require_auth(request)
    pool = request.app.state.db_pool
    await pool.execute("DELETE FROM redshift_connections WHERE id = $1", conn_id)
    return {"status": "deleted"}


@router.post("/{conn_id}/test")
async def test_connection(conn_id: int, request: Request):
    """Test a connection by running SELECT 1."""
    _require_auth(request)
    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT host, port, database, username, password FROM redshift_connections WHERE id = $1",
        conn_id,
    )
    if not row:
        raise HTTPException(404, "Connection not found")

    def _test():
        conn = redshift_connector.connect(
            host=row["host"], port=row["port"], database=row["database"],
            user=row["username"], password=row["password"], timeout=15,
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT CURRENT_USER, CURRENT_DATABASE()")
            result = cursor.fetchone()
            cursor.close()
            return {"status": "connected", "user": result[0], "database": result[1]}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        return await asyncio.wait_for(asyncio.to_thread(_test), timeout=30)
    except asyncio.TimeoutError:
        return {"status": "error", "error": "Connection test timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/browse/databases")
async def browse_databases(request: Request, environment: str = "np", connection_id: int = 0, session_id: str = ""):
    """List databases from Redshift."""
    _require_auth(request)
    try:
        rows = await _browse_query(request, environment, connection_id, session_id, """
            SELECT DISTINCT database_name FROM svv_all_tables
            WHERE schema_name NOT IN ('information_schema','pg_catalog','pg_internal')
            ORDER BY database_name
        """)
        return {"databases": [r[0] for r in rows]}
    except Exception as e:
        return {"databases": [], "error": str(e)}


def _validate_identifier(name: str) -> str:
    """Sanitize SQL identifiers to prevent injection. Only allows alphanumeric + underscore."""
    import re
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid identifier: {name}")
    return name


@router.get("/browse/schemas")
async def browse_schemas(request: Request, database: str, environment: str = "np", connection_id: int = 0, session_id: str = ""):
    """List schemas in a database."""
    _require_auth(request)
    try:
        db = _validate_identifier(database)
        rows = await _browse_query(request, environment, connection_id, session_id, """
            SELECT DISTINCT schema_name, COUNT(*) as table_count
            FROM svv_all_tables
            WHERE database_name = %s
              AND schema_name NOT IN ('information_schema','pg_catalog','pg_internal')
            GROUP BY schema_name ORDER BY schema_name
        """, (db,))
        return {"schemas": [{"name": r[0], "table_count": r[1]} for r in rows]}
    except ValueError as e:
        return {"schemas": [], "error": str(e)}
    except Exception as e:
        return {"schemas": [], "error": str(e)}


@router.get("/browse/tables")
async def browse_tables(request: Request, database: str, schema: str, environment: str = "np", connection_id: int = 0, session_id: str = ""):
    """List tables/views in a schema."""
    _require_auth(request)
    try:
        db = _validate_identifier(database)
        sch = _validate_identifier(schema)
        rows = await _browse_query(request, environment, connection_id, session_id, """
            SELECT table_name, table_type FROM svv_all_tables
            WHERE database_name = %s AND schema_name = %s
            ORDER BY table_name
        """, (db, sch))
        return {"tables": [{"name": r[0], "type": r[1]} for r in rows]}
    except ValueError as e:
        return {"tables": [], "error": str(e)}
    except Exception as e:
        return {"tables": [], "error": str(e)}


@router.get("/browse/columns")
async def browse_columns(request: Request, database: str, schema: str, table: str, environment: str = "np", connection_id: int = 0, session_id: str = ""):
    """List columns of a table."""
    _require_auth(request)
    try:
        db = _validate_identifier(database)
        sch = _validate_identifier(schema)
        tbl = _validate_identifier(table)
        rows = await _browse_query(request, environment, connection_id, session_id, """
            SELECT column_name, data_type, ordinal_position, is_nullable
            FROM svv_all_columns
            WHERE database_name = %s AND schema_name = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (db, sch, tbl))
        return {"columns": [{"name": r[0], "type": r[1], "position": r[2], "nullable": r[3]} for r in rows]}
    except ValueError as e:
        return {"columns": [], "error": str(e)}
    except Exception as e:
        return {"columns": [], "error": str(e)}


@router.get("/browse/prd-dw-catalog")
async def browse_prd_dw_catalog(request: Request, environment: str = "np", connection_id: int = 0, session_id: str = ""):
    """
    List all tables and views in prd_dw across schemas dim, fact, analytics — joined
    with ownership records from postgres. Backs the Catalog page.
    Fetched via the nonprod SSO connection (np cluster has datashare to prd_dw).
    """
    _require_auth(request)
    try:
        rows = await _browse_query(request, environment, connection_id, session_id, """
            SELECT database_name, schema_name, table_name, table_type,
                   COALESCE(remarks, '') AS description
            FROM svv_all_tables
            WHERE database_name = 'prd_dw'
              AND schema_name IN ('dim', 'fact', 'analytics')
              AND table_type IN ('TABLE', 'VIEW')
            ORDER BY schema_name, table_name
        """)
    except Exception as e:
        logger.warning("browse_prd_dw_catalog redshift query failed: %s", e)
        return {"tables": [], "error": str(e)}

    tables = [
        {
            "database": r[0],
            "schema": r[1],
            "name": r[2],
            "type": r[3],
            "description": r[4],
            "primary_owner": None,
            "secondary_owner": None,
            "business_area": None,
            "updated_at": None,
            "updated_by": None,
        }
        for r in rows
    ]

    pool = request.app.state.db_pool
    try:
        own_rows = await pool.fetch("""
            SELECT o.database, o.schema_name, o.table_name,
                   o.primary_owner, o.secondary_owner, o.business_area,
                   o.updated_at, u.name AS updated_by_name
            FROM table_ownership o
            LEFT JOIN users u ON u.id = o.updated_by_user_id
            WHERE o.database = 'prd_dw' AND o.schema_name IN ('dim', 'fact', 'analytics')
        """)
        own_map = {(r["database"], r["schema_name"], r["table_name"]): r for r in own_rows}
        for t in tables:
            row = own_map.get((t["database"], t["schema"], t["name"]))
            if row:
                t["primary_owner"] = row["primary_owner"]
                t["secondary_owner"] = row["secondary_owner"]
                t["business_area"] = row["business_area"]
                t["updated_at"] = row["updated_at"].isoformat() if row["updated_at"] else None
                t["updated_by"] = row["updated_by_name"]
    except Exception as e:
        logger.warning("browse_prd_dw_catalog ownership join failed: %s", e)

    return {"tables": tables}


@router.post("/execute")
async def execute_with_connection(request: Request):
    """Execute a query using a specific named connection."""
    _require_auth(request)
    body = await request.json()
    conn_id = body.get("connection_id")
    sql = body.get("sql", "")

    if not conn_id or not sql:
        raise HTTPException(400, "connection_id and sql required")

    # Safety check
    from connectors.redshift import validate_query_safety
    validate_query_safety(sql)

    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT host, port, database, username, password, environment FROM redshift_connections WHERE id = $1",
        conn_id,
    )
    if not row:
        raise HTTPException(404, "Connection not found")

    import time
    start = time.time()

    def _execute():
        conn = redshift_connector.connect(
            host=row["host"], port=row["port"], database=row["database"],
            user=row["username"], password=row["password"], timeout=60,
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SET statement_timeout = 60000")
            cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(1001)
            truncated = len(rows) > 1000
            rows = rows[:1000]

            from connectors.redshift import _json_safe
            safe_rows = [[_json_safe(cell) for cell in r] for r in rows]
            elapsed_ms = int((time.time() - start) * 1000)

            cursor.close()

            return {
                "columns": columns,
                "rows": safe_rows,
                "row_count": len(safe_rows),
                "execution_time_ms": elapsed_ms,
                "environment": row["environment"],
                "truncated": truncated,
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

    try:
        return await asyncio.wait_for(asyncio.to_thread(_execute), timeout=150)
    except asyncio.TimeoutError:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "columns": [], "rows": [], "row_count": 0,
            "execution_time_ms": elapsed_ms,
            "environment": row["environment"],
            "truncated": False,
            "error": "Query timed out (connection or network stall)",
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "columns": [], "rows": [], "row_count": 0,
            "execution_time_ms": elapsed_ms,
            "environment": row["environment"],
            "truncated": False,
            "error": str(e),
        }
