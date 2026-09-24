"""
MWAA Rendered SQL Fetcher — authenticates to Amazon MWAA (Managed Workflows
for Apache Airflow), fetches active TRANSFORM_DAG__ DAGs, retrieves rendered
template fields (Jinja2-resolved SQL), and builds enriched transform entries
with real lineage derived from the actual executed queries.

This solves the problem that repo_parser.py can only see raw SQL with
Jinja2 placeholders like {{ params.database }} — this module gets the
*actually executed* SQL from the last successful DAG run.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote as url_quote

import boto3
import requests

logger = logging.getLogger("genie.catalog_engine.mwaa_fetcher")

# ---------------------------------------------------------------------------
# Table reference extraction from rendered SQL
# ---------------------------------------------------------------------------

_TABLE_REF_PATTERN = re.compile(
    r"""
    (?:FROM|JOIN)\s+
    (?:(\w+)\.)?           # optional database prefix
    (\w+)\.(\w+)           # schema.table
    """,
    re.IGNORECASE | re.VERBOSE,
)

# SQL keywords that may appear after FROM/JOIN but are not table names
_SQL_KEYWORDS = frozenset({
    "SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION",
    "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "OUTER", "ON", "AS",
    "SET", "VALUES", "INSERT", "UPDATE", "DELETE", "INTO", "WITH",
    "CASE", "WHEN", "THEN", "ELSE", "END", "AND", "OR", "NOT", "IN",
    "EXISTS", "BETWEEN", "LIKE", "IS", "NULL", "TRUE", "FALSE",
    "LATERAL", "UNNEST", "TABLE", "TEMP", "TEMPORARY",
})


def _is_valid_identifier(name: str) -> bool:
    """Check if a name looks like a real table/schema identifier, not an alias."""
    if not name:
        return False
    # Single or double letter — likely a table alias (a, b, aa, ab)
    if len(name) <= 2 and name.isalpha():
        return False
    # Pure numbers or starts with number
    if name[0].isdigit():
        return False
    # Common alias patterns
    if name.lower() in ("t1", "t2", "t3", "s1", "s2", "src", "dst", "tmp", "cte", "sub"):
        return False
    return True


def _extract_table_references(sql_text: str) -> list[str]:
    """
    Extract fully-qualified table references from rendered SQL.
    Returns list of "database.schema.table" or "schema.table" strings.
    Filters out SQL aliases, column references, and numeric patterns.
    """
    refs: list[str] = []
    for match in _TABLE_REF_PATTERN.finditer(sql_text):
        db, schema, table = match.groups()
        if not schema or not table:
            continue
        if schema.upper() in _SQL_KEYWORDS or table.upper() in _SQL_KEYWORDS:
            continue
        # Filter out aliases and non-table patterns
        if not _is_valid_identifier(schema) or not _is_valid_identifier(table):
            continue
        if db and not _is_valid_identifier(db):
            continue
        if db:
            refs.append(f"{db}.{schema}.{table}".lower())
        else:
            refs.append(f"{schema}.{table}".lower())
    return list(set(refs))


def _extract_column_references(sql_text: str) -> list[str]:
    """
    Best-effort extraction of column-level references from rendered SQL.
    Looks for schema.table.column patterns in SELECT and WHERE clauses.
    """
    col_pattern = re.compile(
        r"(\w+)\.(\w+)\.(\w+)",  # schema.table.column or table.alias.column
        re.IGNORECASE,
    )
    cols: list[str] = []
    for match in col_pattern.finditer(sql_text):
        a, b, c = match.groups()
        # Skip things that look like database.schema.table (already captured)
        if a.upper() in _SQL_KEYWORDS or b.upper() in _SQL_KEYWORDS:
            continue
        cols.append(f"{a}.{b}.{c}")
    return list(set(cols))


# ---------------------------------------------------------------------------
# MWAA authentication (mirrors airflow_api_logs_v0.py)
# ---------------------------------------------------------------------------

def _get_boto3_session(
    environment: str,
    session_id: str | None = None,
) -> boto3.Session:
    """
    Build a boto3 session using per-user credentials from the credential
    store, falling back to the AWS SSO profile from config.
    """
    # Try per-user credentials first
    if session_id:
        try:
            from connectors.credential_store import credential_store
            creds = credential_store.get_credentials(session_id, environment)
            if creds:
                logger.info(
                    "Using per-user credentials for %s/%s (%d min remaining)",
                    session_id, environment, creds.minutes_remaining,
                )
                return boto3.Session(
                    aws_access_key_id=creds.access_key_id,
                    aws_secret_access_key=creds.secret_access_key,
                    aws_session_token=creds.session_token,
                    region_name="us-west-2",
                )
        except Exception as e:
            logger.warning("Could not load per-user credentials: %s", e)

    # Try any session in the credential store (not just the given session_id)
    try:
        from connectors.credential_store import credential_store
        for sid, session in credential_store._sessions.items():
            creds = session.get_credentials(environment)
            if creds and creds.minutes_remaining > 2:
                logger.info("Using SSO credentials from session %s for %s (%d min remaining)", sid, environment, creds.minutes_remaining)
                return boto3.Session(
                    aws_access_key_id=creds.access_key_id,
                    aws_secret_access_key=creds.secret_access_key,
                    aws_session_token=creds.session_token,
                    region_name="us-west-2",
                )
    except Exception:
        pass

    # Fall back to AWS SSO profile from config
    try:
        from config import config as app_config
        profile = (
            app_config.AWS_PROFILE_NP if environment == "np"
            else app_config.AWS_PROFILE_PRD
        )
        logger.info("Using AWS profile '%s' for MWAA %s", profile, environment)
        return boto3.Session(profile_name=profile, region_name="us-west-2")
    except Exception as e:
        logger.warning("Could not create profile session: %s — using default", e)
        return boto3.Session(region_name="us-west-2")


def _get_mwaa_env_name(environment: str) -> str:
    """Return the MWAA environment name from config."""
    try:
        from config import config as app_config
        if environment == "np":
            return getattr(app_config, "MWAA_NP_ENV_NAME", "nonprod-airflow-mwaa")
        else:
            return getattr(app_config, "MWAA_PRD_ENV_NAME", "prod-airflow-mwaa")
    except Exception:
        if environment == "np":
            return "nonprod-airflow-mwaa"
        return "prod-airflow-mwaa"


def _get_environment_metadata(
    boto_session: boto3.Session,
    env_name: str,
) -> dict:
    """Fetch MWAA environment metadata — class, config overrides, status, versions."""
    try:
        mwaa = boto_session.client("mwaa", region_name="us-west-2")
        resp = mwaa.get_environment(Name=env_name)
        env = resp.get("Environment", {})
        return {
            "name": env.get("Name", ""),
            "status": env.get("Status", ""),
            "environment_class": env.get("EnvironmentClass", ""),
            "airflow_version": env.get("AirflowVersion", ""),
            "max_workers": env.get("MaxWorkers"),
            "min_workers": env.get("MinWorkers"),
            "schedulers": env.get("Schedulers"),
            "webserver_access_mode": env.get("WebserverAccessMode", ""),
            "weekly_maintenance_window": env.get("WeeklyMaintenanceWindowStart", ""),
            "airflow_config_options": env.get("AirflowConfigurationOptions", {}),
            "logging_config": {
                k: v.get("LogLevel", "") for k, v in env.get("LoggingConfiguration", {}).items()
                if isinstance(v, dict)
            },
            "source_bucket": env.get("SourceBucketArn", ""),
            "execution_role": env.get("ExecutionRoleArn", ""),
            "created_at": str(env.get("CreatedAt", "")),
            "service_role": env.get("ServiceRoleArn", ""),
            "dag_s3_path": env.get("DagS3Path", ""),
            "requirements_s3_path": env.get("RequirementsS3Path", ""),
            "plugins_s3_path": env.get("PluginsS3Path", ""),
        }
    except Exception as e:
        logger.warning("Could not fetch MWAA environment metadata for %s: %s", env_name, e)
        return {"name": env_name, "error": str(e)}


def _get_session_info(
    boto_session: boto3.Session,
    env_name: str,
) -> tuple[str | None, str | None]:
    """
    Authenticate to MWAA using create_web_login_token and return
    (web_server_hostname, session_cookie).
    """
    try:
        mwaa = boto_session.client("mwaa", region_name="us-west-2")
        response = mwaa.create_web_login_token(Name=env_name)
        web_server_host_name = response["WebServerHostname"]
        web_token = response["WebToken"]

        login_url = f"https://{web_server_host_name}/aws_mwaa/login"
        login_payload = {"token": web_token}

        resp = requests.post(login_url, data=login_payload, timeout=10)
        if resp.status_code == 200:
            return web_server_host_name, resp.cookies["session"]
        else:
            logger.error("MWAA login failed: HTTP %d", resp.status_code)
            return None, None
    except requests.RequestException as e:
        logger.error("MWAA login request failed: %s", e)
        return None, None
    except Exception as e:
        logger.error("MWAA login unexpected error: %s", e)
        return None, None


# ---------------------------------------------------------------------------
# Airflow REST API helpers
# ---------------------------------------------------------------------------

def _call_api_sync(host: str, session_cookie: str, url: str) -> dict | None:
    """Synchronous version of the API call."""
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"session={session_cookie}",
    }
    try:
        start_time = time.time()
        resp = requests.get(url, headers=headers, timeout=30)
        elapsed = time.time() - start_time
        if resp.status_code == 200:
            logger.debug("API OK (%0.2fs): %s", elapsed, url)
            return resp.json()
        else:
            logger.warning(
                "API %d (%0.2fs): %s — %s",
                resp.status_code, elapsed, url, resp.text[:200],
            )
            return None
    except requests.RequestException as e:
        logger.error("API request failed: %s", e)
        return None


def _call_api(host: str, session_cookie: str, url: str) -> dict | None:
    """Call API - same as sync version (used by non-async callers)."""
    return _call_api_sync(host, session_cookie, url)


async def _call_api_async(host: str, session_cookie: str, url: str) -> dict | None:
    """Non-blocking version — runs the HTTP call in a thread."""
    return await asyncio.to_thread(_call_api_sync, host, session_cookie, url)


def _get_all_active_dags(host: str, session: str) -> list[dict]:
    """Fetch ALL active DAGs with pagination."""
    all_dags: list[dict] = []
    offset = 0
    limit = 100

    while True:
        url = (
            f"https://{host}/api/v1/dags"
            f"?only_active=true&limit={limit}&offset={offset}"
        )
        logger.info("Fetching DAGs: offset=%d", offset)
        resp = _call_api(host, session, url)
        if not resp:
            break

        dags = resp.get("dags", [])
        all_dags.extend(dags)
        logger.info("Fetched %d DAGs (total: %d)", len(dags), len(all_dags))

        if len(dags) < limit:
            break
        offset += limit
        if offset > 10000:
            logger.warning("Hit safety limit of 10000 DAGs")
            break

    return all_dags


def _get_recent_runs(
    host: str, session: str, dag_id: str, limit: int = 10,
) -> list[dict]:
    """Fetch recent DAG runs (any state) for run history."""
    encoded_dag_id = url_quote(dag_id, safe="")
    url = (
        f"https://{host}/api/v1/dags/{encoded_dag_id}/dagRuns"
        f"?order_by=-execution_date&limit={limit}"
    )
    resp = _call_api(host, session, url)
    if not resp:
        return []
    return resp.get("dag_runs", [])


def _get_last_successful_run(
    host: str, session: str, dag_id: str,
) -> dict | None:
    """Fetch the last successful DAG run for a given dag_id."""
    encoded_dag_id = url_quote(dag_id, safe="")
    url = (
        f"https://{host}/api/v1/dags/{encoded_dag_id}/dagRuns"
        f"?order_by=-execution_date&limit=5&state=success"
    )
    resp = _call_api(host, session, url)
    if not resp:
        return None
    runs = resp.get("dag_runs", [])
    return runs[0] if runs else None


def _parse_run_duration(run: dict) -> float | None:
    """Extract duration in seconds from a DAG run dict."""
    duration = run.get("duration")
    if duration is not None:
        return float(duration)
    start_date = run.get("start_date")
    end_date = run.get("end_date")
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            return (end_dt - start_dt).total_seconds()
        except (ValueError, TypeError):
            pass
    return None


def _build_run_history(runs: list[dict]) -> dict:
    """
    Build run history stats from recent DAG runs.
    Returns success rate, avg duration, failure streak, etc.
    """
    if not runs:
        return {}

    states = [r.get("state", "unknown") for r in runs]
    durations = [_parse_run_duration(r) for r in runs]
    valid_durations = [d for d in durations if d is not None]

    success_count = states.count("success")
    failed_count = states.count("failed")

    # Consecutive failures from most recent
    failure_streak = 0
    for s in states:
        if s == "failed":
            failure_streak += 1
        else:
            break

    history: dict[str, Any] = {
        "recent_runs": len(runs),
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate": round(success_count / len(runs), 2) if runs else 0,
        "current_failure_streak": failure_streak,
    }

    if valid_durations:
        history["avg_duration_seconds"] = round(sum(valid_durations) / len(valid_durations), 1)
        history["min_duration_seconds"] = round(min(valid_durations), 1)
        history["max_duration_seconds"] = round(max(valid_durations), 1)

    # Last run (any state)
    latest = runs[0]
    history["last_run_state"] = latest.get("state", "unknown")
    history["last_run_date"] = latest.get("execution_date", "")

    return history


def _build_task_stats(tasks: list[dict]) -> list[dict]:
    """
    Extract per-task execution stats from task instances.
    Airflow returns: task_id, state, duration, start_date, end_date,
    try_number, operator, etc.
    """
    task_stats: list[dict] = []
    for task in tasks:
        task_id = task.get("task_id", "")
        duration = task.get("duration")
        start_date = task.get("start_date")
        end_date = task.get("end_date")

        if duration is None and start_date and end_date:
            try:
                s = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                e = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                duration = (e - s).total_seconds()
            except (ValueError, TypeError):
                duration = None

        stat: dict[str, Any] = {
            "task_id": task_id,
            "state": task.get("state", "unknown"),
            "operator": task.get("operator", ""),
            "try_number": task.get("try_number"),
        }
        if duration is not None:
            stat["duration_seconds"] = round(duration, 2)
        if start_date:
            stat["start_date"] = start_date
        if end_date:
            stat["end_date"] = end_date

        task_stats.append(stat)

    return task_stats


def _get_task_instances(
    host: str, session: str, dag_id: str, dag_run_id: str,
) -> list[dict]:
    """Fetch task instances for a DAG run."""
    encoded_dag_id = url_quote(dag_id, safe="")
    encoded_run_id = url_quote(dag_run_id, safe="")
    url = (
        f"https://{host}/api/v1/dags/{encoded_dag_id}"
        f"/dagRuns/{encoded_run_id}/taskInstances"
    )
    resp = _call_api(host, session, url)
    if not resp:
        return []
    return resp.get("task_instances", [])


def _get_rendered_template(
    host: str,
    session: str,
    dag_id: str,
    dag_run_id: str,
    task_id: str,
) -> dict | None:
    """
    Fetch the rendered template fields for a specific task instance.
    Returns the rendered_fields dict which contains the Jinja2-resolved SQL.

    Airflow API:
      GET /api/v1/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}/renderedTemplateFields
    """
    encoded_dag_id = url_quote(dag_id, safe="")
    encoded_run_id = url_quote(dag_run_id, safe="")
    encoded_task_id = url_quote(task_id, safe="")
    url = (
        f"https://{host}/api/v1/dags/{encoded_dag_id}"
        f"/dagRuns/{encoded_run_id}"
        f"/taskInstances/{encoded_task_id}/renderedTemplateFields"
    )
    resp = _call_api(host, session, url)
    return resp


def _get_task_logs(
    host: str,
    session: str,
    dag_id: str,
    dag_run_id: str,
    task_id: str,
    try_number: int = 1,
) -> str | None:
    """Fetch task execution logs — contains the actual SQL that was run."""
    encoded_dag_id = url_quote(dag_id, safe="")
    encoded_run_id = url_quote(dag_run_id, safe="")
    encoded_task_id = url_quote(task_id, safe="")
    url = (
        f"https://{host}/api/v1/dags/{encoded_dag_id}"
        f"/dagRuns/{encoded_run_id}"
        f"/taskInstances/{encoded_task_id}/logs/{try_number}"
    )
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"session={session}",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


def _extract_sql_from_logs(log_text: str) -> str | None:
    """
    Extract SQL from Airflow task logs.

    Common patterns in logs:
    - "Running statement: SELECT ..."
    - "Executing: SELECT ..."
    - "Running query: ..."
    - Raw SQL blocks between known markers
    """
    if not log_text:
        return None

    sql_parts: list[str] = []

    # Pattern 1: "Running statement: SQL"
    for marker in ("Running statement:", "Executing:", "Running query:", "Running command:"):
        idx = 0
        while True:
            pos = log_text.find(marker, idx)
            if pos == -1:
                break
            start = pos + len(marker)
            # Find the end — usually a log line starting with [timestamp] or INFO
            end = len(log_text)
            for end_marker in ("\n[", "\nINFO", "\n{", "\nDEBUG", "\nWARNING", "\nERROR"):
                em_pos = log_text.find(end_marker, start + 10)
                if em_pos != -1 and em_pos < end:
                    end = em_pos
            sql = log_text[start:end].strip()
            if sql and len(sql) > 20 and any(kw in sql.upper() for kw in ("SELECT", "CREATE", "INSERT", "WITH", "DROP", "TRUNCATE", "COPY", "UNLOAD")):
                sql_parts.append(sql)
            idx = start

    # Pattern 2: Look for SQL blocks — multiline starting with common SQL keywords
    if not sql_parts:
        import re
        sql_block_pattern = re.compile(
            r'(?:^|\n)((?:SELECT|CREATE|INSERT|WITH|DROP|TRUNCATE|COPY|UNLOAD)\b.+?)(?=\n\[\d{4}|\nINFO|\nDEBUG|\nWARNING|\nERROR|\Z)',
            re.IGNORECASE | re.DOTALL,
        )
        for match in sql_block_pattern.finditer(log_text):
            sql = match.group(1).strip()
            if len(sql) > 20:
                sql_parts.append(sql)

    if sql_parts:
        return "\n;\n".join(sql_parts)
    return None


def _extract_sql_from_rendered(rendered: dict) -> str | None:
    """
    Extract SQL from the rendered template fields response.

    The SQL might be in:
      - rendered_fields.sql (for PostgresOperator / RedshiftSQLOperator)
      - rendered_fields.query (for some custom operators)
      - rendered_fields.params containing SQL text
      - rendered_fields.templates_dict.transform_sql
      - rendered_fields.templates_dict.sql
    """
    fields = rendered.get("rendered_fields", {})
    if not fields:
        return None

    # Direct SQL field
    if isinstance(fields.get("sql"), str) and fields["sql"].strip():
        return fields["sql"]

    # SQL as a list (multiple statements)
    if isinstance(fields.get("sql"), list):
        return "\n;\n".join(str(s) for s in fields["sql"] if s)

    # Query field
    if isinstance(fields.get("query"), str) and fields["query"].strip():
        return fields["query"]

    # templates_dict (used by TransformDAGTemplate)
    tdict = fields.get("templates_dict", {})
    if isinstance(tdict, dict):
        for key in ("transform_sql", "sql", "transform.sql", "query"):
            if isinstance(tdict.get(key), str) and tdict[key].strip():
                return tdict[key]

    # params dict may contain SQL
    params = fields.get("params", {})
    if isinstance(params, dict):
        for key in ("sql", "transform_sql", "query"):
            if isinstance(params.get(key), str) and params[key].strip():
                return params[key]

    return None


# ---------------------------------------------------------------------------
# Target table extraction from DAG ID
# ---------------------------------------------------------------------------

def _extract_target_from_dag_id(dag_id: str) -> str | None:
    """
    Extract the target table name from a TRANSFORM_DAG__ dag_id.
    Pattern: TRANSFORM_DAG__{transform_name}__{domain_key}
    The transform_name usually matches the target table name.
    """
    if not dag_id.startswith("TRANSFORM_DAG__"):
        return None
    parts = dag_id.split("__", 2)
    if len(parts) >= 2:
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

DAG_TYPE_PREFIXES = {
    "transform": ["TRANSFORM_DAG__"],
    "domo": ["DOMO__", "DOMO_REFRESH_DAG__", "domo_refresh__"],
    "dq_sync": ["DQ_SYNC__"],
    "ingest_s3": ["ingest_s3__"],
    "ingest_sqs": ["ingest_sqs__"],
    "events": ["events_v3__"],
    "personalization": ["personalization__"],
    "statsig": ["statsig__"],
    "braze": ["braze__"],
    "extract": ["extract__"],
    "ingestion_pipelines": ["ingestion_pipelines__"],
    "glue": ["glue__", "GLUE__"],
}


def _categorize_dags(dags: list[dict]) -> dict[str, list[dict]]:
    """Categorize DAGs by their prefix/framework type."""
    categories: dict[str, list[dict]] = {}
    for dag in dags:
        dag_id = dag.get("dag_id", "")
        matched = False
        for cat, prefixes in DAG_TYPE_PREFIXES.items():
            if any(dag_id.startswith(p) for p in prefixes):
                categories.setdefault(cat, []).append(dag)
                matched = True
                break
        if not matched:
            categories.setdefault("other", []).append(dag)
    return categories


def _extract_dag_metadata(dag: dict, tasks: list[dict] = None, run_history: list = None) -> dict:
    """Extract metadata for any DAG type (no SQL extraction needed)."""
    dag_id = dag.get("dag_id", "")
    return {
        "dag_id": dag_id,
        "description": dag.get("description") or "",
        "schedule": dag.get("schedule_interval") or dag.get("timetable_description", ""),
        "owner": dag.get("owners", []),
        "tags": [t.get("name", "") for t in dag.get("tags", [])],
        "is_paused": dag.get("is_paused", False),
        "file_token": dag.get("file_token", ""),
        "task_count": len(tasks) if tasks else 0,
        "operator_types": list(set(t.get("operator", "") for t in (tasks or []))),
        "task_ids": [t.get("task_id", "") for t in (tasks or [])],
        "run_history": run_history or [],
    }


async def fetch_mwaa_metadata(
    environment: str = "np",
    session_id: str | None = None,
    progress: dict | None = None,
) -> dict:
    """
    Fetch rendered SQL and run metadata from MWAA for all TRANSFORM_DAG__ DAGs.

    Authenticates to MWAA, fetches active DAGs, retrieves the last successful
    run for each TRANSFORM_DAG__ DAG, fetches rendered template fields to get
    the actual executed SQL (with Jinja2 resolved), and parses that SQL for
    real table references.

    Args:
        environment: "np" for nonprod or "prd" for prod
        session_id: Optional session ID for per-user AWS credentials

    Returns:
        {
            "transforms": [...],   # enriched transform entries
            "lineage": {...},      # lineage from rendered SQL (real table names)
            "dag_runs": {...},     # dag_id -> {last_run_date, duration, state}
        }
    """
    result: dict[str, Any] = {
        "transforms": [],
        "lineage": {},
        "dag_runs": {},
    }

    # 1. Authenticate to MWAA
    env_name = _get_mwaa_env_name(environment)
    boto_session = _get_boto3_session(environment, session_id)

    # 1a. Fetch environment metadata (class, config, versions)
    env_metadata = await asyncio.to_thread(_get_environment_metadata, boto_session, env_name)
    result["environment"] = env_metadata
    if env_metadata.get("environment_class"):
        logger.info("MWAA %s: class=%s, airflow=%s, workers=%s-%s",
                    env_name, env_metadata["environment_class"],
                    env_metadata.get("airflow_version", ""),
                    env_metadata.get("min_workers", ""), env_metadata.get("max_workers", ""))

    logger.info("Authenticating to MWAA environment: %s", env_name)
    host, session_cookie = _get_session_info(boto_session, env_name)
    if not host or not session_cookie:
        logger.error("Failed to authenticate to MWAA %s", env_name)
        return result

    logger.info("Authenticated to MWAA: %s", host)

    # 2. Fetch all active DAGs
    all_dags = _get_all_active_dags(host, session_cookie)
    logger.info("Found %d active DAGs", len(all_dags))

    # For nonprod: filter to only recently-run DAGs (skip stale test DAGs)
    if environment == "np":
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        active_dags = []
        for d in all_dags:
            # Keep if it has a recent run or is a known framework DAG
            dag_id = d.get("dag_id", "")
            last_parsed = d.get("last_parsed_time") or d.get("last_pickled")
            is_framework = any(dag_id.startswith(p) for p in (
                "TRANSFORM_DAG__", "DOMO", "DQ_SYNC__", "ingest_s3__", "ingest_sqs__",
                "events_v3__", "personalization__", "statsig__", "braze__", "extract__",
                "ingestion_pipelines__",
            ))
            if is_framework:
                active_dags.append(d)
            elif last_parsed:
                try:
                    parsed_dt = datetime.fromisoformat(str(last_parsed).replace("Z", "+00:00"))
                    if parsed_dt > cutoff:
                        active_dags.append(d)
                except (ValueError, TypeError):
                    active_dags.append(d)
            else:
                active_dags.append(d)
        logger.info("Nonprod: filtered %d → %d active DAGs (last 30 days + frameworks)", len(all_dags), len(active_dags))
        all_dags = active_dags

    # 3. Categorize DAGs by type
    dag_categories = _categorize_dags(all_dags)
    for cat, dags in dag_categories.items():
        logger.info("  %s: %d DAGs", cat, len(dags))

    # SQL-extractable DAG prefixes (have SQL in task logs)
    SQL_DAG_PREFIXES = ("TRANSFORM_DAG__", "DOMO", "DQ_SYNC__")
    sql_dags = [d for d in all_dags if any(d.get("dag_id", "").startswith(p) for p in SQL_DAG_PREFIXES)]
    metadata_only_dags = [d for d in all_dags if not any(d.get("dag_id", "").startswith(p) for p in SQL_DAG_PREFIXES)]
    logger.info("SQL extraction: %d DAGs | Metadata only: %d DAGs", len(sql_dags), len(metadata_only_dags))

    transforms: list[dict] = []
    lineage: dict[str, dict[str, list[str]]] = {}
    dag_runs: dict[str, dict] = {}

    def _process_dag(dag_id: str, dag: dict) -> dict | None:
        """Process a single DAG — runs in thread pool to avoid blocking event loop."""
        recent_runs = _get_recent_runs(host, session_cookie, dag_id, limit=10)
        run_history = _build_run_history(recent_runs)

        last_run = _get_last_successful_run(host, session_cookie, dag_id)
        if not last_run:
            logger.info("No successful run found for %s", dag_id)
            return {
                "_type": "no_run",
                "dag_id": dag_id,
                "name": _extract_target_from_dag_id(dag_id) or dag_id,
                "target_table": _extract_target_from_dag_id(dag_id) or "",
                "schedule": dag.get("schedule_interval") or dag.get("timetable_description", ""),
                "run_state": "no_successful_run",
                "run_history": run_history,
            }
        return {"_type": "has_run", "last_run": last_run, "run_history": run_history, "dag": dag}

    total_dags = len(sql_dags) + len(metadata_only_dags)

    # ── Phase A: SQL DAGs (extract rendered SQL from task logs) ──────
    for i, dag in enumerate(sql_dags):
        dag_id = dag["dag_id"]
        logger.info("SQL %d/%d: %s", i + 1, len(sql_dags), dag_id)
        if progress is not None:
            progress["mwaa_detail"] = f"{environment} SQL {i+1}/{len(sql_dags)}: {dag_id}"

        # Run I/O-heavy DAG fetch in thread pool
        dag_result = await asyncio.to_thread(_process_dag, dag_id, dag)

        if dag_result and dag_result["_type"] == "no_run":
            del dag_result["_type"]
            transforms.append(dag_result)
            continue
        elif not dag_result or dag_result["_type"] != "has_run":
            continue

        last_run = dag_result["last_run"]
        run_history = dag_result["run_history"]

        dag_run_id = last_run["dag_run_id"]
        execution_date = last_run.get("execution_date", "")
        duration = _parse_run_duration(last_run)
        state = last_run.get("state", "unknown")

        dag_runs[dag_id] = {
            "last_run_date": execution_date,
            "duration_seconds": round(duration, 2) if duration is not None else None,
            "state": state,
            "dag_run_id": dag_run_id,
        }

        # 3b. Fetch task instances for this run (in thread to avoid blocking)
        tasks = await asyncio.to_thread(_get_task_instances, host, session_cookie, dag_id, dag_run_id)
        logger.info("  Found %d task instances for %s", len(tasks), dag_id)

        # 3b-ii. Extract per-task execution stats
        task_stats = _build_task_stats(tasks)

        # 3c. Fetch rendered SQL from each task
        rendered_sql_parts: list[str] = []
        all_source_tables: list[str] = []
        all_column_refs: list[str] = []

        def _fetch_task_sql(task):
            """Fetch SQL for a single task — runs in thread."""
            task_id = task.get("task_id", "")
            operator = task.get("operator", "")
            try_number = task.get("try_number", 1)

            if operator in ("EmptyOperator", "TriggerDagRunOperator", "ExternalTaskSensor", "TimeDeltaSensor"):
                return None

            sql = None
            # Go straight to task logs (rendered template API returns 404 for most tasks)
            log_text = _get_task_logs(host, session_cookie, dag_id, dag_run_id, task_id, try_number=try_number or 1)
            if log_text:
                sql = _extract_sql_from_logs(log_text)
                if sql:
                    logger.info("  Extracted SQL from task logs: %s (%d chars)", task_id, len(sql))

            if not sql:
                return None

            table_refs = _extract_table_references(sql)
            col_refs = _extract_column_references(sql)
            return {"sql": sql, "tables": table_refs, "cols": col_refs}

        for task in tasks:
            task_result = await asyncio.to_thread(_fetch_task_sql, task)
            if not task_result:
                continue
            rendered_sql_parts.append(task_result["sql"])
            all_source_tables.extend(task_result["tables"])
            all_column_refs.extend(task_result["cols"])

        # Deduplicate
        all_source_tables = list(set(all_source_tables))
        all_column_refs = list(set(all_column_refs))

        full_rendered_sql = "\n\n-- ===== NEXT TASK =====\n\n".join(rendered_sql_parts)
        target_table = _extract_target_from_dag_id(dag_id) or ""

        resolved_sources = [
            s for s in all_source_tables
            if not s.endswith(f".{target_table}") and s != target_table
        ]

        # Build enriched transform entry
        transform_entry: dict[str, Any] = {
            "dag_id": dag_id,
            "name": _extract_target_from_dag_id(dag_id) or dag_id,
            "target_table": target_table,
            "schedule": dag.get("schedule_interval") or dag.get("timetable_description", ""),
            "rendered_sql": full_rendered_sql if full_rendered_sql else None,
            "last_run_date": execution_date,
            "last_run_duration_seconds": round(duration, 2) if duration is not None else None,
            "run_state": state,
            "resolved_sources": resolved_sources,
            "resolved_target": target_table,
            "column_references": all_column_refs if all_column_refs else None,
            "source": "mwaa",
            # Enriched fields
            "run_history": run_history,
            "task_stats": task_stats,
        }

        transforms.append(transform_entry)

        # Build lineage from rendered SQL (real table names, no Jinja2)
        if target_table and resolved_sources:
            # Lineage for the target
            if target_table not in lineage:
                lineage[target_table] = {"upstream": [], "downstream": []}
            lineage[target_table]["upstream"] = list(
                set(lineage[target_table]["upstream"] + resolved_sources)
            )

            # Lineage for each source (add downstream reference)
            for src in resolved_sources:
                if src not in lineage:
                    lineage[src] = {"upstream": [], "downstream": []}
                if target_table not in lineage[src]["downstream"]:
                    lineage[src]["downstream"].append(target_table)

    # ── Phase B: Metadata-only DAGs (no SQL extraction) ───────────────
    metadata_entries: list[dict] = []
    for i, dag in enumerate(metadata_only_dags):
        dag_id = dag.get("dag_id", "")
        if progress is not None:
            progress["mwaa_detail"] = f"{environment} meta {i+1}/{len(metadata_only_dags)}: {dag_id}"

        def _fetch_metadata(d_id, d):
            runs = _get_recent_runs(host, session_cookie, d_id, limit=5)
            history = _build_run_history(runs)
            last = _get_last_successful_run(host, session_cookie, d_id)
            tasks = []
            if last:
                tasks = _get_task_instances(host, session_cookie, d_id, last["dag_run_id"])
            return _extract_dag_metadata(d, tasks, history), last

        meta, last_run = await asyncio.to_thread(_fetch_metadata, dag_id, dag)

        if last_run:
            meta["last_run_date"] = last_run.get("execution_date", "")
            meta["last_run_state"] = last_run.get("state", "")
            meta["last_run_duration"] = _parse_run_duration(last_run)
            dag_runs[dag_id] = {
                "last_run_date": last_run.get("execution_date", ""),
                "duration_seconds": round(_parse_run_duration(last_run) or 0, 2),
                "state": last_run.get("state", "unknown"),
            }

        metadata_entries.append(meta)

    logger.info(
        "MWAA fetch complete: %d SQL transforms, %d metadata DAGs, %d lineage, %d dag_runs",
        len(transforms), len(metadata_entries), len(lineage), len(dag_runs),
    )

    # ── Build coverage report ───────────────────────────────────────
    coverage = {
        "total_active_dags": len(all_dags),
        "sql_extracted": len(transforms),
        "metadata_only": len(metadata_entries),
        "by_type": {cat: len(dags) for cat, dags in dag_categories.items()},
        "environment": environment,
    }

    result["transforms"] = transforms
    result["metadata_dags"] = metadata_entries
    result["lineage"] = lineage
    result["dag_runs"] = dag_runs
    result["coverage"] = coverage
    return result
