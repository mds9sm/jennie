"""
Table Operations Engine — sequential job queue for ANALYZE and PROFILE operations.

- ANALYZE runs on prod Redshift (updates planner stats)
- PROFILE runs on nonprod against prd_dw.* datashare tables (min/max/null/cardinality)
- Jobs execute sequentially, never in parallel
- Auto-kill on configurable timeout
- Results stored in postgres for the UI checklist
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("genie.catalog_engine.table_ops")

# Global job runner state
_runner_task: asyncio.Task | None = None
_current_job: dict | None = None


# ---------------------------------------------------------------------------
# ANALYZE operation (runs on PROD Redshift)
# ---------------------------------------------------------------------------

def _run_analyze(conn, schema_name: str, table_name: str) -> dict:
    """Run ANALYZE on a specific table. Returns stats.
    ANALYZE is a safe read-like operation — it updates internal planner
    statistics but does not modify data."""
    fq_table = f"{schema_name}.{table_name}"
    cursor = conn.cursor()

    # ANALYZE only — no other write operations ever
    logger.info("Running ANALYZE on %s", fq_table)
    cursor.execute(f"ANALYZE {fq_table}")

    # Fetch updated stats (SELECT only)
    cursor.execute(f"""
        SELECT tbl_rows, size AS size_mb, diststyle, sortkey1, sortkey_num
        FROM svv_table_info
        WHERE "schema" = '{schema_name}' AND "table" = '{table_name}'
    """)
    row = cursor.fetchone()
    cursor.close()

    if row:
        return {
            "row_count": int(row[0]) if row[0] else None,
            "size_mb": float(row[1]) if row[1] else None,
            "diststyle": str(row[2]) if row[2] else None,
            "sortkey1": str(row[3]) if row[3] else None,
            "sortkey_num": int(row[4]) if row[4] else None,
        }
    return {"row_count": None, "size_mb": None}


# ---------------------------------------------------------------------------
# PROFILE operation (runs on NONPROD via datashare)
# ---------------------------------------------------------------------------

def _run_profile(conn, schema_name: str, table_name: str, database: str = "dw") -> dict:
    """
    Profile a table — get min/max, cardinality, null rates per column.
    Runs on nonprod against prd_dw.* datashare tables.
    Uses TABLESAMPLE for large tables to keep it fast.
    """
    # Use database name as-is (already includes prd_ or np_ prefix from discovery)
    fq_table = f"{database}.{schema_name}.{table_name}"

    cursor = conn.cursor()

    # Get row count first to decide if we need sampling
    cursor.execute(f"SELECT COUNT(*) FROM {fq_table}")
    total_rows = cursor.fetchone()[0]

    # Get column list
    cursor.execute(f"""
        SELECT column_name, data_type
        FROM svv_all_columns
        WHERE schema_name = '{schema_name}'
          AND table_name = '{table_name}'
          AND database_name = '{database}'
        ORDER BY ordinal_position
    """)
    columns = [(r[0], r[1]) for r in cursor.fetchall()]

    if not columns:
        cursor.close()
        return {"error": f"No columns found for {fq_table}", "row_count": total_rows}

    # For large tables, wrap in a subquery with LIMIT to avoid full scan
    # Redshift does not support TABLESAMPLE
    use_sampling = total_rows > 10_000_000
    if use_sampling:
        sample_size = 1_000_000
        logger.info("Sampling %d rows from %s (%d total)", sample_size, fq_table, total_rows)

    # Profile each column — batch into one query for efficiency
    select_parts = []
    for col_name, col_type in columns[:50]:  # cap at 50 columns
        safe_col = f'"{col_name}"'
        select_parts.extend([
            f"COUNT(DISTINCT {safe_col}) AS \"{col_name}__distinct\"",
            f"SUM(CASE WHEN {safe_col} IS NULL THEN 1 ELSE 0 END) AS \"{col_name}__nulls\"",
        ])
        # Min/max only for numeric and date types
        upper_type = col_type.upper() if col_type else ""
        if any(t in upper_type for t in ("INT", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "REAL", "DATE", "TIMESTAMP")):
            select_parts.extend([
                f"MIN({safe_col}) AS \"{col_name}__min\"",
                f"MAX({safe_col}) AS \"{col_name}__max\"",
            ])

    if not select_parts:
        cursor.close()
        return {"row_count": total_rows, "columns": {}}

    if use_sampling:
        profile_sql = f"SELECT COUNT(*) AS sample_rows, {', '.join(select_parts)} FROM (SELECT * FROM {fq_table} LIMIT {sample_size})"
    else:
        profile_sql = f"SELECT COUNT(*) AS sample_rows, {', '.join(select_parts)} FROM {fq_table}"

    # Safety: verify profile SQL is SELECT only
    from connectors.redshift import validate_query_safety
    validate_query_safety(profile_sql)

    logger.info("Profiling %s (%d columns)", fq_table, len(columns))
    cursor.execute(profile_sql)

    result_row = cursor.fetchone()
    col_names = [desc[0] for desc in cursor.description]
    result_dict = dict(zip(col_names, result_row))
    cursor.close()

    sample_rows = result_dict.get("sample_rows", total_rows)

    # Parse into per-column profile
    column_profiles: dict[str, dict] = {}
    for col_name, col_type in columns[:50]:
        profile: dict[str, Any] = {"type": col_type}
        distinct = result_dict.get(f"{col_name}__distinct")
        nulls = result_dict.get(f"{col_name}__nulls")

        if distinct is not None:
            profile["distinct_count"] = int(distinct)
            if sample_rows:
                profile["cardinality_ratio"] = round(int(distinct) / sample_rows, 4)
        if nulls is not None:
            profile["null_count"] = int(nulls)
            if sample_rows:
                profile["null_rate"] = round(int(nulls) / sample_rows, 4)

        min_val = result_dict.get(f"{col_name}__min")
        max_val = result_dict.get(f"{col_name}__max")
        if min_val is not None:
            profile["min"] = str(min_val)
        if max_val is not None:
            profile["max"] = str(max_val)

        column_profiles[col_name] = profile

    return {
        "row_count": total_rows,
        "sample_rows": sample_rows,
        "sampled": use_sampling,
        "column_count": len(columns),
        "columns": column_profiles,
    }


# ---------------------------------------------------------------------------
# Auto-classification: fact vs dimension
# ---------------------------------------------------------------------------

def auto_classify_table(profile_data: dict, metadata: dict = {}) -> str:
    """
    Auto-classify a table as fact or dimension based on profile data.

    Heuristics:
    - High row count + date column + many foreign keys → fact
    - Low cardinality + few columns + stable row count → dimension
    - Has refill_days or delta_load → fact (ETL pattern)
    """
    if not profile_data:
        return "unknown"

    row_count = profile_data.get("row_count", 0) or 0
    columns = profile_data.get("columns", {})
    col_count = profile_data.get("column_count", len(columns))

    # Check for date columns (facts usually have date partitions)
    has_date_col = any(
        "date" in col_name.lower() or "timestamp" in (col_info.get("type", "")).lower()
        for col_name, col_info in columns.items()
    )

    # Check for high-cardinality ID columns (facts have many unique keys)
    high_card_cols = sum(
        1 for col_info in columns.values()
        if (col_info.get("cardinality_ratio", 0) or 0) > 0.5
    )

    # ETL patterns that indicate fact tables
    has_delta_load = metadata.get("delta_load", False)
    has_refill_days = metadata.get("refill_days") is not None

    # Dimension indicators: low row count, low cardinality, few columns
    low_rows = row_count < 100_000
    few_columns = col_count < 15
    low_cardinality = all(
        (col_info.get("cardinality_ratio", 1) or 1) < 0.1
        for col_info in columns.values()
    )

    # Score-based classification
    fact_score = 0
    dim_score = 0

    if row_count > 1_000_000:
        fact_score += 3
    elif row_count > 100_000:
        fact_score += 1
    else:
        dim_score += 2

    if has_date_col:
        fact_score += 2
    if high_card_cols > 2:
        fact_score += 1
    if has_delta_load or has_refill_days:
        fact_score += 2
    if few_columns:
        dim_score += 1
    if low_cardinality and low_rows:
        dim_score += 2

    if fact_score > dim_score:
        return "fact"
    elif dim_score > fact_score:
        return "dimension"
    return "unknown"


# ---------------------------------------------------------------------------
# Job queue runner
# ---------------------------------------------------------------------------

async def _process_next_job(db_pool, session_id: str | None = None):
    """Process the next queued job. Called in a loop by the runner."""
    global _current_job

    # Get next queued job
    row = await db_pool.fetchrow("""
        SELECT id, operation, schema_name, table_name, database, environment, timeout_seconds
        FROM table_ops_jobs
        WHERE status = 'queued'
        ORDER BY created_at ASC
        LIMIT 1
    """)

    if not row:
        return False  # No jobs

    job_id = row["id"]
    operation = row["operation"]
    schema_name = row["schema_name"]
    table_name = row["table_name"]
    database = row["database"]
    environment = row["environment"]
    timeout = row["timeout_seconds"]

    _current_job = {
        "id": job_id,
        "operation": operation,
        "table": f"{schema_name}.{table_name}",
        "environment": environment,
    }

    # Mark as running
    await db_pool.execute("""
        UPDATE table_ops_jobs SET status = 'running', started_at = NOW()
        WHERE id = $1
    """, job_id)

    logger.info("Starting job %d: %s %s.%s on %s (timeout %ds)",
                job_id, operation, schema_name, table_name, environment, timeout)

    start = time.time()
    try:
        from connectors.redshift import _get_connection

        def _run_op():
            conn = _get_connection(environment, session_id)
            try:
                # Set statement timeout on the connection
                cursor = conn.cursor()
                cursor.execute(f"SET statement_timeout = {timeout * 1000}")
                cursor.close()

                if operation == "analyze":
                    return _run_analyze(conn, schema_name, table_name)
                elif operation == "profile":
                    return _run_profile(conn, schema_name, table_name, database)
                else:
                    raise ValueError(f"Unknown operation: {operation}. Only 'analyze' and 'profile' are allowed.")
            finally:
                conn.close()

        # Blocking Redshift work runs in a worker thread; wait_for bounds it
        # even if the connection hangs mid-operation.
        result = await asyncio.wait_for(asyncio.to_thread(_run_op), timeout=timeout + 90)

        elapsed = round(time.time() - start, 2)

        # Update job as completed
        await db_pool.execute("""
            UPDATE table_ops_jobs
            SET status = 'completed', completed_at = NOW(),
                duration_seconds = $2, result = $3::jsonb
            WHERE id = $1
        """, job_id, elapsed, json.dumps(result, default=str))

        # Update table registry
        if operation == "analyze":
            await db_pool.execute("""
                INSERT INTO table_registry (schema_name, table_name, database, row_count, size_mb,
                    last_analyzed_at, metadata, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW(), $6::jsonb, NOW())
                ON CONFLICT (schema_name, table_name, database) DO UPDATE SET
                    row_count = $4, size_mb = $5, last_analyzed_at = NOW(),
                    metadata = table_registry.metadata || $6::jsonb, updated_at = NOW()
            """, schema_name, table_name, database,
                result.get("row_count"), result.get("size_mb"),
                json.dumps({k: v for k, v in result.items() if k not in ("row_count", "size_mb")}, default=str))

        elif operation == "profile":
            # Classify table and columns using weighted scoring
            from catalog_engine.classifier import classify_table, classify_table_columns

            table_class = classify_table(
                schema_name, table_name,
                row_count=result.get("row_count"),
                profile_data=result,
            )
            col_classes = classify_table_columns(result)

            # Add classifications to result
            result["table_classification"] = table_class
            result["column_classifications"] = col_classes

            profile_json = json.dumps(result, default=str)
            auto_type = table_class["classification"]

            await db_pool.execute("""
                INSERT INTO table_registry (schema_name, table_name, database,
                    row_count, last_profiled_at, profile_data, table_type_auto, updated_at)
                VALUES ($1, $2, $3, $4, NOW(), $5::jsonb, $6, NOW())
                ON CONFLICT (schema_name, table_name, database) DO UPDATE SET
                    row_count = $4, last_profiled_at = NOW(),
                    profile_data = $5::jsonb, table_type_auto = $6, updated_at = NOW()
            """, schema_name, table_name, database,
                result.get("row_count"), profile_json, auto_type)

        logger.info("Job %d completed in %.1fs: %s %s.%s",
                    job_id, elapsed, operation, schema_name, table_name)

    except Exception as e:
        elapsed = round(time.time() - start, 2)
        error_str = str(e)

        status = "failed"
        if "statement timeout" in error_str.lower() or "cancel" in error_str.lower():
            status = "timeout"

        await db_pool.execute("""
            UPDATE table_ops_jobs
            SET status = $2, completed_at = NOW(), duration_seconds = $3, error = $4
            WHERE id = $1
        """, job_id, status, elapsed, error_str)

        logger.error("Job %d %s in %.1fs: %s", job_id, status, elapsed, error_str)

    finally:
        _current_job = None

    return True  # Processed a job


async def start_job_runner(db_pool, session_id: str | None = None):
    """Start the sequential job runner. Processes jobs one at a time until queue is empty."""
    global _runner_task

    if _runner_task and not _runner_task.done():
        return {"status": "already_running"}

    async def _run():
        logger.info("Job runner started")
        while True:
            try:
                had_job = await _process_next_job(db_pool, session_id)
                if not had_job:
                    break
            except Exception as e:
                logger.error("Job runner error (continuing): %s", e)
                # Don't break — try the next job
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(0.5)
        logger.info("Job runner finished — queue empty")

    _runner_task = asyncio.create_task(_run())
    return {"status": "started"}


async def kill_current_job(db_pool):
    """Kill the currently running job."""
    global _current_job
    if not _current_job:
        return {"status": "no_running_job"}

    job_id = _current_job["id"]
    await db_pool.execute("""
        UPDATE table_ops_jobs SET status = 'killed', completed_at = NOW()
        WHERE id = $1 AND status = 'running'
    """, job_id)

    # Cancel the runner task
    global _runner_task
    if _runner_task and not _runner_task.done():
        _runner_task.cancel()
        _runner_task = None

    _current_job = None
    return {"status": "killed", "job_id": job_id}


def get_runner_status() -> dict:
    """Get current runner and job status."""
    running = _runner_task is not None and not _runner_task.done()
    return {
        "running": running,
        "current_job": _current_job,
    }
