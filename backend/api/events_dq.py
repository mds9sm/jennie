import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from connectors.redshift import execute_real_query

logger = logging.getLogger("genie.events_dq")

router = APIRouter()


def _row_to_dict(columns: list[str], row: list) -> dict:
    out = {}
    for col, val in zip(columns, row):
        if isinstance(val, datetime):
            val = val.isoformat()
        out[col] = val
    return out


@router.get("/heatmap")
async def events_dq_heatmap(
    request: Request,
    days: int = Query(91, ge=7, le=365),
):
    """Per-day finding counts grouped by max severity for the last N days."""
    sql = f"""
        SELECT
            event_date::DATE AS event_date,
            SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) AS critical_count,
            SUM(CASE WHEN severity = 'warning'  THEN 1 ELSE 0 END) AS warning_count,
            SUM(CASE WHEN severity = 'info'     THEN 1 ELSE 0 END) AS info_count,
            COUNT(*) AS total_count
        FROM np_dw.analytics.events_dq_findings
        WHERE event_date >= CURRENT_DATE - {days}
        GROUP BY 1
        ORDER BY 1
    """

    result = await execute_real_query(sql, environment="np", max_rows=400)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    days_data = [_row_to_dict(result["columns"], r) for r in result["rows"]]

    summary = {
        "total_findings": sum(d.get("total_count", 0) or 0 for d in days_data),
        "critical_findings": sum(d.get("critical_count", 0) or 0 for d in days_data),
        "warning_findings": sum(d.get("warning_count", 0) or 0 for d in days_data),
        "info_findings": sum(d.get("info_count", 0) or 0 for d in days_data),
        "active_days": len(days_data),
    }

    return {"days": days_data, "summary": summary, "lookback_days": days}


@router.get("/day-detail")
async def events_dq_day_detail(
    request: Request,
    date: str = Query(...),
):
    """All findings for a specific day, grouped by kind."""
    sql = f"""
        SELECT finding_id, event_date, severity, kind, stage, event_name, platform,
               client_version, observed_value, expected_low, expected_high, z_score,
               narrative, created_at
        FROM np_dw.analytics.events_dq_findings
        WHERE event_date = DATE '{date}'
        ORDER BY
            CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            kind,
            event_name
    """

    result = await execute_real_query(sql, environment="np", max_rows=500)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    findings = [_row_to_dict(result["columns"], r) for r in result["rows"]]

    by_kind: dict[str, list] = {}
    for f in findings:
        by_kind.setdefault(f.get("kind") or "unknown", []).append(f)

    return {
        "date": date,
        "findings": findings,
        "by_kind": by_kind,
        "total": len(findings),
    }


@router.get("/findings")
async def events_dq_findings(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    severity: str = Query(None),
    kind: str = Query(None),
    platform: str = Query(None),
    event_name: str = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """Filterable list of recent findings."""
    where_clauses = [f"event_date >= CURRENT_DATE - {days}"]
    if severity in ("critical", "warning", "info"):
        where_clauses.append(f"severity = '{severity}'")
    if kind:
        safe_kind = kind.replace("'", "")
        where_clauses.append(f"kind = '{safe_kind}'")
    if platform:
        safe_platform = platform.replace("'", "")
        where_clauses.append(f"platform = '{safe_platform}'")
    if event_name:
        safe_event = event_name.replace("'", "")
        where_clauses.append(f"event_name = '{safe_event}'")

    where_sql = " AND ".join(where_clauses)
    sql = f"""
        SELECT finding_id, event_date, severity, kind, stage, event_name, platform,
               client_version, observed_value, expected_low, expected_high, z_score,
               narrative, created_at
        FROM np_dw.analytics.events_dq_findings
        WHERE {where_sql}
        ORDER BY
            event_date DESC,
            CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            kind
        LIMIT {limit}
    """

    result = await execute_real_query(sql, environment="np", max_rows=limit)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    return {
        "findings": [_row_to_dict(result["columns"], r) for r in result["rows"]],
        "filters": {
            "days": days,
            "severity": severity,
            "kind": kind,
            "platform": platform,
            "event_name": event_name,
        },
    }


@router.get("/stage-counts")
async def events_dq_stage_counts(
    request: Request,
    days: int = Query(14, ge=1, le=90),
):
    """Recent per-stage row counts for the events pipeline (drift visualization)."""
    sql = f"""
        SELECT event_date::DATE AS event_date, stage, source_table, row_count, unique_users,
               path_name, s3_file_count, s3_total_bytes
        FROM np_dw.analytics.events_dq_stage_counts
        WHERE event_date >= CURRENT_DATE - {days}
        ORDER BY event_date DESC, stage
    """

    result = await execute_real_query(sql, environment="np", max_rows=2000)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    return {
        "rows": [_row_to_dict(result["columns"], r) for r in result["rows"]],
        "lookback_days": days,
    }


@router.get("/chain-flow")
async def events_dq_chain_flow(
    request: Request,
    date: str = Query(...),
):
    """Per-path stage counts + drift status for a given date.

    Returns one entry per path in the chain registry with stages in order,
    each annotated with row_count / s3_file_count and any drift findings
    that pertain to that stage.
    """
    counts_sql = f"""
        SELECT path_name, stage, row_count, s3_file_count, s3_total_bytes, source_table
        FROM np_dw.analytics.events_dq_stage_counts
        WHERE event_date = DATE '{date}'
          AND path_name IS NOT NULL
        ORDER BY path_name, stage
    """
    findings_sql = f"""
        SELECT stage, severity, kind, narrative, observed_value, z_score
        FROM np_dw.analytics.events_dq_findings
        WHERE event_date = DATE '{date}'
          AND kind = 'stage_drift'
        ORDER BY severity, stage
    """

    counts_res = await execute_real_query(counts_sql, environment="np", max_rows=500)
    if "error" in counts_res:
        raise HTTPException(status_code=502, detail=counts_res["error"])
    findings_res = await execute_real_query(findings_sql, environment="np", max_rows=200)
    if "error" in findings_res:
        raise HTTPException(status_code=502, detail=findings_res["error"])

    paths: dict[str, list] = {}
    for r in counts_res["rows"]:
        d = _row_to_dict(counts_res["columns"], r)
        paths.setdefault(d["path_name"] or "unknown", []).append(d)

    findings_by_stage: dict[str, list] = {}
    for r in findings_res["rows"]:
        d = _row_to_dict(findings_res["columns"], r)
        findings_by_stage.setdefault(d["stage"] or "", []).append(d)

    return {"date": date, "paths": paths, "findings_by_stage": findings_by_stage}


@router.get("/dq-sync-status")
async def events_dq_dq_sync_status(
    request: Request,
    days: int = Query(7, ge=1, le=30),
):
    """Recent dq_sync DAG run state — for the dq_sync status panel."""
    sql = f"""
        SELECT run_date::DATE AS run_date, dag_id, task_id, state,
               start_date, end_date, duration_seconds, try_number, log_url
        FROM np_dw.analytics.events_dq_dq_sync_runs
        WHERE run_date >= CURRENT_DATE - {days}
        ORDER BY run_date DESC, dag_id, task_id
    """

    result = await execute_real_query(sql, environment="np", max_rows=2000)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    rows = [_row_to_dict(result["columns"], r) for r in result["rows"]]
    by_dag: dict[str, list] = {}
    for r in rows:
        by_dag.setdefault(r.get("dag_id") or "unknown", []).append(r)

    summary = {
        "total_runs": len(rows),
        "failed_runs": sum(1 for r in rows if r.get("state") == "failed"),
        "unique_dags": len(by_dag),
    }

    return {"days": days, "summary": summary, "by_dag": by_dag, "rows": rows}


@router.get("/dim-health")
async def events_dq_dim_health(
    request: Request,
    days: int = Query(14, ge=1, le=90),
):
    """Dim table snapshots — freshness lag, row counts, null rates over time."""
    sql = f"""
        SELECT snapshot_date::DATE AS snapshot_date, schema_name, table_name,
               row_count, max_updated_at, freshness_lag_hours,
               null_rate_pk, null_rate_natural_key
        FROM np_dw.analytics.events_dq_dim_health
        WHERE snapshot_date >= CURRENT_DATE - {days}
        ORDER BY snapshot_date DESC, schema_name, table_name
    """

    result = await execute_real_query(sql, environment="np", max_rows=1000)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    return {
        "rows": [_row_to_dict(result["columns"], r) for r in result["rows"]],
        "lookback_days": days,
    }
