"""
FastAPI router for Table Operations — discovery, ANALYZE, PROFILE, classification, job queue.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from catalog_engine.table_ops import (
    start_job_runner,
    kill_current_job,
    get_runner_status,
    auto_classify_table,
)

logger = logging.getLogger("genie.table_ops")
router = APIRouter()

_discover_task: asyncio.Task | None = None
_discover_progress: dict = {}


# ---------------------------------------------------------------------------
# Table Registry
# ---------------------------------------------------------------------------

@router.get("/capabilities")
async def get_capabilities():
    """Return what operations are available based on stored credentials."""
    from connectors.redshift import _direct_creds
    has_np = "np" in _direct_creds
    has_prd = "prd" in _direct_creds
    return {
        "can_discover_np": has_np,
        "can_discover_prd": has_prd,
        "can_profile": has_np,      # PROFILE runs on nonprod via datashare
        "can_analyze": has_prd,     # ANALYZE runs on prod directly
        "np_creds": has_np,
        "prd_creds": has_prd,
    }


@router.get("/tables")
async def list_tables(request: Request):
    """List all tables in the registry with their status."""
    pool = request.app.state.db_pool
    rows = await pool.fetch("""
        SELECT id, schema_name, table_name, database, table_type,
               table_type_auto, table_type_manual,
               row_count, size_mb,
               last_analyzed_at, last_profiled_at,
               analyze_enabled, profile_enabled,
               profile_data, metadata, updated_at
        FROM table_registry
        ORDER BY schema_name, table_name
    """)
    result = []
    for r in rows:
        d = dict(r)
        # Ensure JSONB fields are parsed
        for key in ("profile_data", "metadata"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        result.append(d)
    return result


class DiscoverRequest(BaseModel):
    session_id: Optional[str] = None
    environment: str = "np"            # which Redshift to query
    databases: list[str] = []          # empty = all
    schemas: list[str] = []            # empty = all
    object_types: list[str] = ["TABLE", "VIEW"]
    include_lineage_score: bool = True


@router.post("/tables/discover")
async def discover_tables(body: DiscoverRequest, request: Request):
    """
    Discover tables/views from prod Redshift SVV_ALL_TABLES + enrich with lineage scores.
    Runs as background task — poll /tables/discover/status.
    """
    global _discover_task, _discover_progress

    if _discover_task and not _discover_task.done():
        return {"status": "already_running"}

    pool = request.app.state.db_pool
    kb = request.app.state.kb

    _discover_progress = {"status": "running", "phase": "connecting", "found": 0}

    async def _run():
        global _discover_progress
        try:
            from connectors.redshift import _get_connection

            _discover_progress["phase"] = f"querying {body.environment} SVV_ALL_TABLES"

            # Build filters
            where_parts = ["table_type IN ('TABLE', 'VIEW')"]
            if body.object_types:
                types = ", ".join(f"'{t}'" for t in body.object_types)
                where_parts[0] = f"table_type IN ({types})"
            if body.databases:
                dbs = ", ".join(f"'{d}'" for d in body.databases)
                where_parts.append(f"database_name IN ({dbs})")
            if body.schemas:
                schemas = ", ".join(f"'{s}'" for s in body.schemas)
                where_parts.append(f"schema_name IN ({schemas})")
            else:
                # Exclude system schemas
                where_parts.append("schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_internal')")

            where_clause = " AND ".join(where_parts)

            sql = f"""
                SELECT database_name, schema_name, table_name, table_type,
                       COALESCE(remarks, '') AS description
                FROM svv_all_tables
                WHERE {where_clause}
                ORDER BY database_name, schema_name, table_name
            """

            def _query():
                conn = _get_connection(body.environment, body.session_id)
                try:
                    cursor = conn.cursor()
                    cursor.execute(sql)
                    result = cursor.fetchall()
                    cursor.close()
                    return result
                finally:
                    conn.close()

            rows = await asyncio.to_thread(_query)

            _discover_progress["phase"] = f"inserting {len(rows)} objects"
            _discover_progress["found"] = len(rows)

            # Compute lineage value scores
            lineage_scores: dict[str, int] = {}
            if body.include_lineage_score and kb.lineage:
                for table_key, deps in kb.lineage.items():
                    upstream_count = len(deps.get("upstream", []))
                    downstream_count = len(deps.get("downstream", []))
                    lineage_scores[table_key.lower()] = upstream_count + downstream_count

                # Also count references from transform sources
                for t in kb.transforms_index:
                    for src in t.get("resolved_sources", []):
                        key = src.lower()
                        lineage_scores[key] = lineage_scores.get(key, 0) + 1

            # Insert into registry
            inserted = 0
            for row in rows:
                db_name, schema, table_name, table_type, description = row
                db_short = db_name  # keep original database name (prd_dw, np_dw, etc.)

                # Compute lineage score for this table
                score = 0
                for pattern in [
                    f"{schema}.{table_name}",
                    f"{db_name}.{schema}.{table_name}",
                    f"{db_short}.{schema}.{table_name}",
                ]:
                    score = max(score, lineage_scores.get(pattern.lower(), 0))

                meta = {
                    "object_type": table_type,
                    "description": description,
                    "lineage_score": score,
                    "source_database": db_name,
                }

                await pool.execute("""
                    INSERT INTO table_registry (schema_name, table_name, database, table_type, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (schema_name, table_name, database) DO UPDATE SET
                        table_type = COALESCE(table_registry.table_type_manual, $4),
                        metadata = table_registry.metadata || $5::jsonb,
                        updated_at = NOW()
                """, schema, table_name, db_short,
                    table_type.lower() if table_type else None,
                    json.dumps(meta))
                inserted += 1

                if inserted % 100 == 0:
                    _discover_progress["phase"] = f"inserted {inserted}/{len(rows)}"

            total = await pool.fetchval("SELECT COUNT(*) FROM table_registry")
            _discover_progress = {
                "status": "success",
                "phase": "complete",
                "found": len(rows),
                "total_in_registry": total,
            }

        except Exception as e:
            logger.exception("Table discovery failed")
            _discover_progress = {"status": "error", "phase": "failed", "error": str(e)}

    _discover_task = asyncio.create_task(_run())
    return {"status": "started"}


@router.get("/tables/discover/status")
async def discover_status():
    """Poll discovery progress."""
    global _discover_task, _discover_progress
    running = _discover_task is not None and not _discover_task.done()
    return {**_discover_progress, "running": running}


@router.post("/tables/discover/local")
async def discover_from_knowledge_base(request: Request):
    """Fallback: discover tables from catalog.json only (no lineage junk)."""
    pool = request.app.state.db_pool
    kb = request.app.state.kb

    for t in kb.catalog.get("tables", []):
        schema = t.get("schema", "")
        name = t.get("name", "")
        if not schema or not name:
            continue
        await pool.execute("""
            INSERT INTO table_registry (schema_name, table_name, database, row_count, size_mb, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (schema_name, table_name, database) DO NOTHING
        """, schema, name, t.get("database", "dw"),
            t.get("row_count_estimate"), t.get("size_mb"),
            json.dumps({"description": t.get("description", ""), "columns": len(t.get("columns", []))}))

    total = await pool.fetchval("SELECT COUNT(*) FROM table_registry")
    return {"status": "ok", "tables_in_registry": total}


class UpdateTableRequest(BaseModel):
    analyze_enabled: Optional[bool] = None
    profile_enabled: Optional[bool] = None
    table_type_manual: Optional[str] = None


@router.put("/tables/{table_id}")
async def update_table(table_id: int, body: UpdateTableRequest, request: Request):
    """Update table settings (enable/disable analyze/profile, manual classification)."""
    pool = request.app.state.db_pool
    updates = []
    params = []
    idx = 1

    if body.analyze_enabled is not None:
        updates.append(f"analyze_enabled = ${idx}")
        params.append(body.analyze_enabled)
        idx += 1
    if body.profile_enabled is not None:
        updates.append(f"profile_enabled = ${idx}")
        params.append(body.profile_enabled)
        idx += 1
    if body.table_type_manual is not None:
        updates.append(f"table_type_manual = ${idx}")
        params.append(body.table_type_manual if body.table_type_manual != "" else None)
        idx += 1
        # Update derived table_type
        updates.append(f"table_type = COALESCE(${idx - 1}, table_type_auto)")

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = NOW()")
    params.append(table_id)
    await pool.execute(
        f"UPDATE table_registry SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Job Queue
# ---------------------------------------------------------------------------

class QueueJobRequest(BaseModel):
    operation: str  # 'analyze' or 'profile'
    table_ids: list[int] = []
    schema_name: Optional[str] = None  # queue all tables in schema
    timeout_seconds: int = 120


@router.post("/jobs/queue")
async def queue_jobs(body: QueueJobRequest, request: Request):
    """Queue ANALYZE or PROFILE jobs for selected tables."""
    pool = request.app.state.db_pool

    if body.operation not in ("analyze", "profile"):
        raise HTTPException(400, "operation must be 'analyze' or 'profile'")

    # Check if required credentials exist
    from connectors.redshift import _direct_creds
    if body.operation == "analyze" and "prd" not in _direct_creds:
        raise HTTPException(400, "ANALYZE requires prod Redshift credentials. Add them in Settings > Connection.")
    if body.operation == "profile" and "np" not in _direct_creds:
        raise HTTPException(400, "PROFILE requires nonprod Redshift credentials (queries prd_dw via datashare). Add them in Settings > Connection.")

    # Get tables to queue
    if body.table_ids:
        rows = await pool.fetch(
            "SELECT schema_name, table_name, database FROM table_registry WHERE id = ANY($1)",
            body.table_ids,
        )
    elif body.schema_name:
        flag_col = "analyze_enabled" if body.operation == "analyze" else "profile_enabled"
        rows = await pool.fetch(
            f"SELECT schema_name, table_name, database FROM table_registry WHERE schema_name = $1 AND {flag_col} = true",
            body.schema_name,
        )
    else:
        flag_col = "analyze_enabled" if body.operation == "analyze" else "profile_enabled"
        rows = await pool.fetch(
            f"SELECT schema_name, table_name, database FROM table_registry WHERE {flag_col} = true",
        )

    # ANALYZE runs on prod (direct access), PROFILE runs on nonprod (via datashare)
    env = "prd" if body.operation == "analyze" else "np"

    queued = 0
    for r in rows:
        await pool.execute("""
            INSERT INTO table_ops_jobs (operation, schema_name, table_name, database, environment, timeout_seconds)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, body.operation, r["schema_name"], r["table_name"], r["database"], env, body.timeout_seconds)
        queued += 1

    return {"status": "queued", "jobs_queued": queued}


@router.post("/jobs/start")
async def start_runner(request: Request):
    """Start processing the job queue sequentially."""
    pool = request.app.state.db_pool

    # Get session_id from auth context for Redshift connection
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    session_id = body.get("session_id")

    result = await start_job_runner(pool, session_id)
    return result


@router.post("/jobs/kill")
async def kill_job(request: Request):
    """Kill the currently running job."""
    pool = request.app.state.db_pool
    result = await kill_current_job(pool)
    return result


@router.get("/jobs/status")
async def job_status(request: Request):
    """Get runner status and recent jobs."""
    pool = request.app.state.db_pool
    runner = get_runner_status()

    # Get recent jobs
    rows = await pool.fetch("""
        SELECT id, operation, schema_name, table_name, database, environment, status,
               timeout_seconds, started_at, completed_at, duration_seconds, error
        FROM table_ops_jobs
        ORDER BY
            CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
            CASE WHEN status IN ('running', 'queued') THEN created_at END ASC,
            CASE WHEN status NOT IN ('running', 'queued') THEN completed_at END DESC
        LIMIT 50
    """)

    # Queue depth
    queue_depth = await pool.fetchval(
        "SELECT COUNT(*) FROM table_ops_jobs WHERE status = 'queued'"
    )

    return {
        **runner,
        "queue_depth": queue_depth,
        "recent_jobs": [dict(r) for r in rows],
    }


@router.delete("/jobs/clear")
async def clear_queue(request: Request):
    """Clear all queued (not running) jobs."""
    pool = request.app.state.db_pool
    await pool.execute("DELETE FROM table_ops_jobs WHERE status = 'queued'")
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    operation: str  # 'analyze' or 'profile'
    cron_expression: str  # e.g. '0 2 * * 0'
    schema_name: Optional[str] = None
    table_name: Optional[str] = None
    timeout_seconds: int = 120
    enabled: bool = True


@router.get("/schedules")
async def list_schedules(request: Request):
    """List all schedules."""
    pool = request.app.state.db_pool
    rows = await pool.fetch("SELECT * FROM table_ops_schedules ORDER BY created_at")
    return [dict(r) for r in rows]


@router.post("/schedules")
async def create_schedule(body: ScheduleRequest, request: Request):
    """Create a new schedule."""
    pool = request.app.state.db_pool
    if body.operation not in ("analyze", "profile"):
        raise HTTPException(400, "operation must be 'analyze' or 'profile'")

    row = await pool.fetchrow("""
        INSERT INTO table_ops_schedules (operation, schema_name, table_name, cron_expression, timeout_seconds, enabled)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """, body.operation, body.schema_name, body.table_name,
        body.cron_expression, body.timeout_seconds, body.enabled)
    return {"status": "created", "id": row["id"]}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request):
    """Delete a schedule."""
    pool = request.app.state.db_pool
    await pool.execute("DELETE FROM table_ops_schedules WHERE id = $1", schedule_id)
    return {"status": "deleted"}


@router.put("/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int, request: Request):
    """Enable/disable a schedule."""
    pool = request.app.state.db_pool
    await pool.execute(
        "UPDATE table_ops_schedules SET enabled = NOT enabled WHERE id = $1", schedule_id
    )
    return {"status": "toggled"}


# ---------------------------------------------------------------------------
# Redshift database/schema listing (for UI dropdowns)
# ---------------------------------------------------------------------------

@router.get("/schedule-runner/status")
async def schedule_runner_status(request: Request):
    """Get schedule runner active/inactive status."""
    pool = request.app.state.db_pool
    from catalog_engine.schedule_runner import is_runner_active
    active = await is_runner_active(pool)
    return {"active": active}


@router.post("/schedule-runner/toggle")
async def toggle_schedule_runner(request: Request):
    """Toggle schedule runner active/inactive."""
    pool = request.app.state.db_pool
    from catalog_engine.schedule_runner import is_runner_active, set_runner_active
    current = await is_runner_active(pool)
    await set_runner_active(pool, not current)
    new_state = not current
    logger.info("Schedule runner toggled to %s", "active" if new_state else "inactive")
    return {"active": new_state}


@router.get("/redshift/databases")
async def list_redshift_databases(request: Request, session_id: Optional[str] = None):
    """List databases from prod Redshift."""
    try:
        from connectors.redshift import _get_connection

        def _query():
            conn = _get_connection("prd", session_id)
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT database_name
                    FROM svv_all_tables
                    WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_internal')
                    ORDER BY database_name
                """)
                result = cursor.fetchall()
                cursor.close()
                return result
            finally:
                conn.close()

        rows = await asyncio.wait_for(asyncio.to_thread(_query), timeout=75)
        return {"databases": [r[0] for r in rows]}
    except Exception as e:
        return {"databases": [], "error": str(e)}


@router.get("/redshift/schemas")
async def list_redshift_schemas(request: Request, database: Optional[str] = None, session_id: Optional[str] = None):
    """List schemas from prod Redshift, optionally filtered by database."""
    try:
        from connectors.redshift import _get_connection
        where = "WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_internal')"
        if database:
            where += f" AND database_name = '{database}'"

        def _query():
            conn = _get_connection("prd", session_id)
            try:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT DISTINCT database_name, schema_name, COUNT(*) as table_count
                    FROM svv_all_tables
                    {where}
                    GROUP BY database_name, schema_name
                    ORDER BY database_name, schema_name
                """)
                result = cursor.fetchall()
                cursor.close()
                return result
            finally:
                conn.close()

        rows = await asyncio.wait_for(asyncio.to_thread(_query), timeout=75)
        return {"schemas": [{"database": r[0], "schema": r[1], "table_count": r[2]} for r in rows]}
    except Exception as e:
        return {"schemas": [], "error": str(e)}
