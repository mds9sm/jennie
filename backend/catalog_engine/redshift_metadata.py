"""
Redshift Metadata Fetcher — queries Redshift system tables to build
table metadata in the catalog.json format used by Genie.

organization-specific: targets schemas analytics, fact, dim, data_lake, personalize
across np_dw / np_data_lake / np_personalize (or prd_ equivalents).
"""

import logging
import time
from typing import Any

from config import config
from connectors.redshift import _get_connection, _json_safe

logger = logging.getLogger("genie.catalog_engine.redshift")

# Schemas we care about in your data warehouse
TARGET_SCHEMAS = ("analytics", "fact", "dim", "data_lake", "personalize", "stage", "events", "kafka", "public")

# Environment prefix for database discovery
ENV_DB_PREFIX = {"np": "np_", "prd": "prd_"}

# Excluded databases (system, temp, etc.)
EXCLUDED_DATABASES = {"dev", "padb_harvest", "template0", "template1"}


def _discover_databases(conn, environment: str) -> tuple[str, ...]:
    """Discover all databases matching the environment prefix (e.g., all prd_* databases)."""
    prefix = ENV_DB_PREFIX.get(environment, "prd_")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT database_name FROM svv_all_tables ORDER BY database_name")
    all_dbs = [r[0] for r in cursor.fetchall()]
    cursor.close()
    matched = [db for db in all_dbs if db.startswith(prefix) and db not in EXCLUDED_DATABASES]
    if not matched:
        # Fallback to hardcoded
        matched = [f"{prefix}dw", f"{prefix}data_lake", f"{prefix}personalize"]
    logger.info("Discovered %d databases for %s: %s", len(matched), environment, matched)
    return tuple(matched)


def _get_short_name(database: str) -> str:
    """Map a database name to a canonical short name for catalog.json."""
    # Strip environment prefix: prd_dw → dw, prd_board_kpi → board_kpi, np_data_lake → data_lake
    for prefix in ("prd_", "np_"):
        if database.startswith(prefix):
            return database[len(prefix):]
    return database


def _build_schema_filter(schemas: tuple[str, ...]) -> str:
    """Build a SQL IN clause for schema names."""
    quoted = ", ".join(f"'{s}'" for s in schemas)
    return f"({quoted})"


def _build_db_filter(databases: tuple[str, ...]) -> str:
    """Build a SQL IN clause for database names."""
    quoted = ", ".join(f"'{d}'" for d in databases)
    return f"({quoted})"


def _fetch_all_tables(conn, databases: tuple[str, ...], schemas: tuple[str, ...]) -> list[dict]:
    """Query SVV_ALL_TABLES for table list."""
    sql = f"""
    SELECT
        database_name,
        schema_name,
        table_name,
        table_type,
        COALESCE(remarks, '') AS description
    FROM svv_all_tables
    WHERE schema_name IN {_build_schema_filter(schemas)}
      AND database_name IN {_build_db_filter(databases)}
      AND table_type IN ('TABLE', 'VIEW')
    ORDER BY database_name, schema_name, table_name
    """
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    cursor.close()
    return [dict(zip(columns, [_json_safe(c) for c in row])) for row in rows]


def _fetch_all_columns(conn, databases: tuple[str, ...], schemas: tuple[str, ...]) -> list[dict]:
    """Query SVV_ALL_COLUMNS for column metadata."""
    sql = f"""
    SELECT
        database_name,
        schema_name,
        table_name,
        column_name,
        data_type,
        ordinal_position,
        COALESCE(remarks, '') AS description,
        is_nullable,
        character_maximum_length,
        numeric_precision
    FROM svv_all_columns
    WHERE schema_name IN {_build_schema_filter(schemas)}
      AND database_name IN {_build_db_filter(databases)}
    ORDER BY database_name, schema_name, table_name, ordinal_position
    """
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    cursor.close()
    return [dict(zip(columns, [_json_safe(c) for c in row])) for row in rows]


def _fetch_table_info(conn) -> dict[str, dict]:
    """
    Query SVV_TABLE_INFO for dist/sort keys, row counts, and size.
    Returns a dict keyed by (schema, table_name).
    """
    sql = """
    SELECT
        "schema" AS schema_name,
        "table" AS table_name,
        diststyle,
        sortkey1,
        tbl_rows,
        size AS size_mb,
        sortkey_num
    FROM svv_table_info
    ORDER BY schema_name, table_name
    """
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    cursor.close()

    result: dict[str, dict] = {}
    for row in rows:
        record = dict(zip(columns, [_json_safe(c) for c in row]))
        key = f"{record['schema_name']}.{record['table_name']}"
        result[key] = record
    return result


def _fetch_pg_table_def_keys(conn, schemas: tuple[str, ...]) -> dict[str, dict]:
    """
    Fallback: query PG_TABLE_DEF for distkey / sortkey info
    when SVV_TABLE_INFO doesn't have it (e.g., datashared tables).
    """
    sql = f"""
    SELECT
        schemaname AS schema_name,
        tablename AS table_name,
        "column" AS column_name,
        distkey,
        sortkey
    FROM pg_table_def
    WHERE schemaname IN {_build_schema_filter(schemas)}
      AND (distkey = true OR sortkey > 0)
    ORDER BY schemaname, tablename, sortkey
    """
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    cursor.close()

    result: dict[str, dict] = {}
    for row in rows:
        record = dict(zip(columns, [_json_safe(c) for c in row]))
        key = f"{record['schema_name']}.{record['table_name']}"
        if key not in result:
            result[key] = {"distkey": None, "sortkeys": []}
        if record.get("distkey"):
            result[key]["distkey"] = record["column_name"]
        if record.get("sortkey") and record["sortkey"] > 0:
            result[key]["sortkeys"].append(record["column_name"])
    return result


def _format_column_type(col: dict) -> str:
    """Build a human-readable column type string from SVV_ALL_COLUMNS metadata."""
    dtype = col.get("data_type", "").upper()
    max_len = col.get("character_maximum_length")
    precision = col.get("numeric_precision")

    if max_len and "CHAR" in dtype:
        return f"{dtype}({max_len})"
    if precision and dtype in ("NUMERIC", "DECIMAL"):
        return f"{dtype}({precision})"
    return dtype


def _assemble_catalog(
    tables_raw: list[dict],
    columns_raw: list[dict],
    table_info: dict[str, dict],
    pg_keys: dict[str, dict],
    environment: str,
) -> list[dict]:
    """
    Assemble the final catalog entries in the same format as catalog.json "tables".
    """
    # databases param passed from caller

    # Index columns by (db, schema, table)
    col_index: dict[str, list[dict]] = {}
    for col in columns_raw:
        key = f"{col['database_name']}.{col['schema_name']}.{col['table_name']}"
        col_index.setdefault(key, []).append(col)

    catalog_tables: list[dict] = []

    for tbl in tables_raw:
        db_name = tbl["database_name"]
        schema = tbl["schema_name"]
        table_name = tbl["table_name"]
        full_key = f"{db_name}.{schema}.{table_name}"
        short_key = f"{schema}.{table_name}"

        # Map database to canonical short name (strip env prefix)
        db_short = _get_short_name(db_name)

        # Gather columns
        raw_cols = col_index.get(full_key, [])
        formatted_columns = [
            {
                "name": c["column_name"],
                "type": _format_column_type(c),
                "description": c.get("description", ""),
            }
            for c in sorted(raw_cols, key=lambda x: x.get("ordinal_position", 0))
        ]

        # Dist/sort keys from SVV_TABLE_INFO
        info = table_info.get(short_key, {})
        distkey = None
        sortkey = None
        row_count_estimate = None
        size_mb = None

        if info:
            diststyle = info.get("diststyle", "")
            if diststyle and "KEY" in str(diststyle).upper():
                # Extract key column — SVV_TABLE_INFO gives diststyle like "KEY(user_id)"
                if "(" in str(diststyle):
                    distkey = str(diststyle).split("(")[1].rstrip(")")
                else:
                    distkey = info.get("sortkey1")  # sometimes stored here
            elif diststyle and "ALL" in str(diststyle).upper():
                distkey = "ALL"

            sk1 = info.get("sortkey1")
            if sk1:
                sortkey = sk1

            row_count_estimate = info.get("tbl_rows")
            if row_count_estimate is not None:
                row_count_estimate = int(row_count_estimate)
            size_mb = info.get("size_mb")

        # Fallback to PG_TABLE_DEF if we didn't get keys
        if not distkey or not sortkey:
            pg_info = pg_keys.get(short_key, {})
            if not distkey and pg_info.get("distkey"):
                distkey = pg_info["distkey"]
            if not sortkey and pg_info.get("sortkeys"):
                sortkey = pg_info["sortkeys"][0]

        entry: dict[str, Any] = {
            "name": table_name,
            "schema": schema,
            "database": db_short,
            "description": tbl.get("description", ""),
            "columns": formatted_columns,
        }
        if distkey:
            entry["distkey"] = distkey
        if sortkey:
            entry["sortkey"] = sortkey
        if row_count_estimate is not None:
            entry["row_count_estimate"] = row_count_estimate
        if size_mb is not None:
            entry["size_mb"] = size_mb

        catalog_tables.append(entry)

    return catalog_tables


async def fetch_redshift_metadata(
    environment: str = "prd",
    session_id: str | None = None,
    profile_tables: bool = True,
    db_pool=None,
) -> list[dict]:
    """
    Fetch Redshift metadata for your data warehouse and return
    a list of table entries matching the catalog.json "tables" format.

    Args:
        environment: "np" for nonprod, "prd" for prod
        session_id: Optional session ID for per-user Redshift auth

    Returns:
        List of table dicts compatible with catalog.json
    """
    schemas = TARGET_SCHEMAS

    start = time.time()
    conn = _get_connection(environment, session_id)

    # Discover all databases for this environment dynamically
    databases = _discover_databases(conn, environment)

    logger.info(
        "Fetching Redshift metadata: env=%s, databases=%s, schemas=%s",
        environment, databases, schemas,
    )

    try:
        # 1. Get table list
        tables_raw = _fetch_all_tables(conn, databases, schemas)
        logger.info("Found %d tables", len(tables_raw))

        # 2. Get column metadata
        columns_raw = _fetch_all_columns(conn, databases, schemas)
        logger.info("Found %d columns", len(columns_raw))

        # 3. Get table info (distkey, sortkey, row counts) — requires elevated permissions
        table_info = {}
        try:
            table_info = _fetch_table_info(conn)
            logger.info("Got table info for %d tables", len(table_info))
        except Exception as e:
            logger.warning("svv_table_info not accessible (permission denied?) — skipping table stats: %s", str(e)[:100])

        # 4. Fallback key info from PG_TABLE_DEF
        pg_keys = {}
        try:
            pg_keys = _fetch_pg_table_def_keys(conn, schemas)
            logger.info("Got pg_table_def keys for %d tables", len(pg_keys))
        except Exception as e:
            logger.warning("pg_table_def not accessible — skipping key info: %s", str(e)[:100])

    finally:
        conn.close()

    # Assemble into catalog format
    catalog_tables = _assemble_catalog(tables_raw, columns_raw, table_info, pg_keys, environment)

    elapsed = time.time() - start
    logger.info(
        "Redshift metadata fetch complete: %d tables in %.1fs",
        len(catalog_tables), elapsed,
    )

    # Profile tables using nonprod connection (via datashare)
    if profile_tables and catalog_tables:
        try:
            np_conn = _get_connection("np", session_id)
            profiled_count = 0
            from catalog_engine.table_ops import _run_profile, auto_classify_table
            import json as _json

            for tbl in catalog_tables:
                schema = tbl.get("schema", "")
                name = tbl.get("name", "")
                db = f"prd_{tbl.get('database', 'dw')}"
                if not schema or not name:
                    continue
                try:
                    profile_data = _run_profile(np_conn, schema, name, database=db)
                    if profile_data and "error" not in profile_data:
                        tbl["profile"] = profile_data
                        tbl["row_count_estimate"] = profile_data.get("row_count")
                        tbl["table_type_auto"] = auto_classify_table(profile_data, tbl)
                        profiled_count += 1

                        # Collect for batch postgres save after profiling
                        pass
                except Exception as e:
                    if profiled_count == 0:
                        # Log first failure at warning level to diagnose
                        logger.warning("Profile failed for %s.%s.%s: %s", db, schema, name, str(e)[:150])
                    else:
                        logger.debug("Profile failed for %s.%s: %s", schema, name, str(e)[:80])

            np_conn.close()
            logger.info("Profiled %d/%d tables via nonprod datashare", profiled_count, len(catalog_tables))

            # Batch save profiles to postgres
            if db_pool and profiled_count > 0:
                saved = 0
                for tbl in catalog_tables:
                    if not tbl.get("profile"):
                        continue
                    try:
                        await db_pool.execute("""
                            INSERT INTO table_registry (schema_name, table_name, database, row_count,
                                table_type_auto, profile_data, last_profiled_at, updated_at)
                            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW(), NOW())
                            ON CONFLICT (schema_name, table_name) DO UPDATE SET
                                database = $3, row_count = $4, table_type_auto = $5,
                                profile_data = $6::jsonb, last_profiled_at = NOW(), updated_at = NOW()
                        """,
                            tbl["schema"], tbl["name"], f"prd_{tbl.get('database', 'dw')}",
                            tbl["profile"].get("row_count"),
                            tbl.get("table_type_auto"),
                            _json.dumps(tbl["profile"], default=str),
                        )
                        saved += 1
                    except Exception:
                        pass
                logger.info("Saved %d table profiles to postgres", saved)

        except Exception as e:
            logger.warning("Table profiling skipped: %s", str(e)[:100])

    return catalog_tables
