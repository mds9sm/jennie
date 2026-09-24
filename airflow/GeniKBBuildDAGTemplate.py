"""
Genie KB Build DAG Template

Builds the Genie knowledge base. Two instances (np, prd) from YAML configs.
Each task is a self-contained step that writes results to S3 + Genie postgres.

Requires:
- Airflow Variable: GITHUB_TOKEN (for private repo clone)
- Airflow Connection: genie_postgres (Genie RDS)
- IAM: bedrock:InvokeModel on MWAA worker role (for AI enrichment)
- S3: write access to the configured bucket
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import boto3
import yaml
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

logger = logging.getLogger("genie.kb_build")

# Load YAML configs
CONF_DIR = Path(__file__).parent / "conf"
CONFIGS = {}
for p in CONF_DIR.glob("genie_kb_build_*.yaml"):
    with open(p) as f:
        c = yaml.safe_load(f)
    CONFIGS[c["dag_id"]] = c


def _s3():
    return boto3.client("s3", region_name="us-west-2")


# ── Tasks ─────────────────────────────────────────────────────────────────────

def start_build(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    pg = PostgresHook(postgres_conn_id=cfg["postgres_conn_id"])
    row = pg.get_first(
        "INSERT INTO kb_builds (status, triggered_by, sources) VALUES ('running', 'airflow', %s::jsonb) RETURNING id",
        (json.dumps(cfg.get("sources", {})),),
    )
    ctx["ti"].xcom_push(key="build_id", value=row[0])
    ctx["ti"].xcom_push(key="t0", value=time.time())
    logger.info("KB build #%d started (env=%s)", row[0], cfg["environment"])


def git_clone(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    url = cfg.get("repo_url", "")
    branch = cfg.get("repo_branch", "main")
    if not url:
        return

    from airflow.models import Variable
    token = Variable.get("GITHUB_TOKEN", default_var="")
    if token:
        url = url.replace("https://", f"https://{token}@")

    dest = "/tmp/genie-kb-repo"
    if Path(dest, ".git").exists():
        subprocess.run(["git", "-C", dest, "fetch", "origin"], check=True, timeout=120)
        subprocess.run(["git", "-C", dest, "reset", "--hard", f"origin/{branch}"], check=True)
    else:
        subprocess.run(["git", "clone", "--depth", "1", "-b", branch, url, dest], check=True, timeout=300)

    ctx["ti"].xcom_push(key="repo_path", value=dest)


def repo_parse(**ctx):
    repo = ctx["ti"].xcom_pull(key="repo_path") or "/tmp/genie-kb-repo"
    if not Path(repo).exists():
        ctx["ti"].xcom_push(key="repo_json", value="{}")
        return

    # Use the same parser as the Genie backend
    # The catalog_engine package is installed in the MWAA requirements
    # or copied to the DAGs folder
    from genie_catalog.repo_parser import parse_repo
    result = parse_repo(repo)
    path = "/tmp/genie-kb-repo.json"
    with open(path, "w") as f:
        json.dump(result, f, default=str)
    ctx["ti"].xcom_push(key="repo_json", value=path)
    logger.info("Repo: %d transforms", len(result.get("transforms", [])))


def mwaa_fetch(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    if not cfg.get("sources", {}).get("mwaa"):
        ctx["ti"].xcom_push(key="mwaa_json", value="")
        return

    from genie_catalog.mwaa_fetcher import fetch_mwaa_metadata
    import asyncio
    result = asyncio.run(fetch_mwaa_metadata(
        environment=cfg["environment"],
        session_id=None,  # MWAA worker has native IAM access
    ))
    path = f"/tmp/genie-kb-mwaa-{cfg['environment']}.json"
    with open(path, "w") as f:
        json.dump(result, f, default=str)
    ctx["ti"].xcom_push(key="mwaa_json", value=path)
    logger.info("MWAA: %d transforms", len(result.get("transforms", [])))


def redshift_metadata(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    if not cfg.get("sources", {}).get("redshift"):
        ctx["ti"].xcom_push(key="redshift_json", value="")
        return

    from genie_catalog.redshift_metadata import fetch_redshift_metadata
    import asyncio
    result = asyncio.run(fetch_redshift_metadata(
        config=None,  # Use Airflow connection instead
        db_pool=None,
        airflow_conn_id=cfg.get("redshift", {}).get("conn_id", "prd_redshift"),
        databases=cfg.get("redshift", {}).get("databases", ["prd_dw"]),
    ))
    path = "/tmp/genie-kb-redshift.json"
    with open(path, "w") as f:
        json.dump(result, f, default=str)
    ctx["ti"].xcom_push(key="redshift_json", value=path)


def swagger_fetch(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    if not cfg.get("sources", {}).get("swagger"):
        return

    from genie_catalog.swagger_parser import fetch_and_parse, write_event_schemas
    result = fetch_and_parse(url=cfg.get("swagger_url"))
    path = "/tmp/genie-kb-swagger.json"
    with open(path, "w") as f:
        json.dump(result, f, default=str)
    ctx["ti"].xcom_push(key="swagger_json", value=path)
    logger.info("Swagger: %d events", result.get("event_count", 0))


def domo_parse(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    repo = ctx["ti"].xcom_pull(key="repo_path") or "/tmp/genie-kb-repo"
    if not cfg.get("sources", {}).get("domo_parse") or not Path(repo).exists():
        ctx["ti"].xcom_push(key="domo_json", value="")
        return

    from genie_catalog.domo_parser import parse_all
    result = parse_all(repo)
    path = "/tmp/genie-kb-domo.json"
    with open(path, "w") as f:
        json.dump(result, f, default=str)
    ctx["ti"].xcom_push(key="domo_json", value=path)
    logger.info("DOMO: %d metrics, %d views", len(result.get("metrics", [])), len(result.get("views", [])))


def merge_and_write_s3(**ctx):
    """Merge all sources, build lineage, write KB files to S3."""
    cfg = CONFIGS[ctx["dag"].dag_id]
    bucket = cfg["s3_bucket"]
    prefix = cfg["s3_prefix"]
    build_id = ctx["ti"].xcom_pull(key="build_id")

    def _load(key):
        p = ctx["ti"].xcom_pull(key=key)
        if p and Path(p).exists():
            with open(p) as f:
                return json.load(f)
        return {}

    repo = _load("repo_json") or {"transforms": [], "lineage": {}}
    mwaa = _load("mwaa_json") or {"transforms": [], "metadata_dags": []}
    redshift = _load("redshift_json") or {"tables": []}
    swagger = _load("swagger_json") or {"events": [], "event_count": 0}
    domo = _load("domo_json") or {"metrics": [], "views": [], "domo_datasets": []}

    # Use the existing builder merge logic
    from genie_catalog.builder import merge_tables, enrich_with_repo, merge_lineage
    # ... or do a simple merge inline:

    # Merge transforms (MWAA primary + repo enrichment)
    repo_index = {t["dag_id"]: t for t in repo.get("transforms", []) if t.get("dag_id")}
    merged = []
    seen = set()
    for t in mwaa.get("transforms", []):
        did = t.get("dag_id", "")
        seen.add(did)
        rt = repo_index.get(did, {})
        for k in ("git_blame", "last_commit", "schedule", "tags", "owner", "yaml_path"):
            if rt.get(k) and not t.get(k):
                t[k] = rt[k]
        merged.append(t)
    for did, t in repo_index.items():
        if did not in seen:
            merged.append(t)

    # Build lineage from SQL
    import re
    lineage = {}
    for t in merged:
        did = t.get("dag_id", "")
        for task in t.get("tasks", []):
            sql = task.get("rendered_sql", "") or task.get("sql", "")
            for tbl in set(re.findall(r'(?:FROM|JOIN)\s+(\w+\.\w+)', sql, re.I)):
                lineage.setdefault(tbl, {"upstream": [], "downstream": []})
                if did not in lineage[tbl]["downstream"]:
                    lineage[tbl]["downstream"].append(did)

    # Write to S3
    s3 = _s3()
    files = {
        "catalog.json": {"tables": redshift.get("tables", [])},
        "transforms_index.json": [{"dag_id": t.get("dag_id"), "name": t.get("name", t.get("dag_id")),
                                    "schedule": t.get("schedule"), "owner": t.get("owner"),
                                    "tags": t.get("tags", []), "type": t.get("type")}
                                   for t in merged],
        "lineage.json": lineage,
        "metrics.json": domo.get("metrics", []),
        "event_schemas.json": swagger,
        "metadata_dags.json": mwaa.get("metadata_dags", []),
    }
    for fname, data in files.items():
        s3.put_object(Bucket=bucket, Key=f"{prefix}/{fname}",
                      Body=json.dumps(data, indent=2, default=str).encode())

    # Per-transform details
    for t in merged:
        did = t.get("dag_id", "")
        if did:
            s3.put_object(Bucket=bucket, Key=f"{prefix}/transforms/{did}.json",
                          Body=json.dumps(t, indent=2, default=str).encode())

    # Per-view details
    for v in domo.get("views", []):
        vn = v.get("view_name", "")
        if vn:
            s3.put_object(Bucket=bucket, Key=f"{prefix}/views/{vn}.json",
                          Body=json.dumps(v, indent=2, default=str).encode())

    # Manifest
    stats = {
        "environment": cfg["environment"],
        "build_id": build_id,
        "table_count": len(redshift.get("tables", [])),
        "transform_count": len(merged),
        "lineage_count": len(lineage),
        "domo_metrics": len(domo.get("metrics", [])),
        "event_schemas": swagger.get("event_count", 0),
        "metadata_dags": len(mwaa.get("metadata_dags", [])),
    }
    s3.put_object(Bucket=bucket, Key=f"{prefix}/manifest.json",
                  Body=json.dumps(stats, indent=2, default=str).encode())

    logger.info("Uploaded KB to s3://%s/%s/ — %d transforms, %d lineage", bucket, prefix, len(merged), len(lineage))
    ctx["ti"].xcom_push(key="stats", value=json.dumps(stats, default=str))


def complete_build(**ctx):
    cfg = CONFIGS[ctx["dag"].dag_id]
    pg = PostgresHook(postgres_conn_id=cfg["postgres_conn_id"])
    bid = ctx["ti"].xcom_pull(key="build_id")
    t0 = ctx["ti"].xcom_pull(key="t0") or time.time()
    stats = ctx["ti"].xcom_pull(key="stats") or "{}"
    dur = round(time.time() - t0, 2)
    pg.run("UPDATE kb_builds SET status='success', duration_seconds=%s, stats=%s::jsonb WHERE id=%s",
           parameters=(dur, stats, bid))
    logger.info("KB build #%d done in %.0fs", bid, dur)


def fail_build(**ctx):
    cfg = CONFIGS.get(ctx["dag"].dag_id, {})
    conn_id = cfg.get("postgres_conn_id", "genie_postgres")
    try:
        pg = PostgresHook(postgres_conn_id=conn_id)
        bid = ctx["ti"].xcom_pull(key="build_id")
        if bid:
            err = str(ctx.get("exception", "Unknown"))[:500]
            pg.run("UPDATE kb_builds SET status='failed', error=%s WHERE id=%s AND status='running'",
                   parameters=(err, bid))
    except Exception:
        pass


# ── DAG creation ──────────────────────────────────────────────────────────────

for dag_id, cfg in CONFIGS.items():
    dag = DAG(
        dag_id=dag_id,
        description=cfg.get("description", ""),
        schedule_interval=cfg.get("schedule_interval", "@daily"),
        start_date=datetime(2026, 4, 1),
        catchup=False,
        tags=cfg.get("tags", []),
        max_active_runs=1,
        default_args={
            "owner": cfg.get("owner", "data-engineering"),
            "retries": cfg.get("retries", 1),
            "retry_delay": timedelta(minutes=cfg.get("retry_delay_minutes", 5)),
            "on_failure_callback": fail_build,
        },
    )

    with dag:
        t0 = PythonOperator(task_id="start_build", python_callable=start_build)
        t1 = PythonOperator(task_id="git_clone", python_callable=git_clone)
        t2 = PythonOperator(task_id="mwaa_fetch", python_callable=mwaa_fetch)
        t3 = PythonOperator(task_id="redshift_metadata", python_callable=redshift_metadata)
        t4 = PythonOperator(task_id="swagger_fetch", python_callable=swagger_fetch)
        t5 = PythonOperator(task_id="repo_parse", python_callable=repo_parse)
        t6 = PythonOperator(task_id="domo_parse", python_callable=domo_parse)
        t7 = PythonOperator(task_id="merge_and_write_s3", python_callable=merge_and_write_s3)
        t8 = PythonOperator(task_id="complete_build", python_callable=complete_build, trigger_rule="all_success")

        t0 >> t1 >> [t2, t3, t4]
        t1 >> t5 >> t6
        [t2, t3, t4, t5, t6] >> t7 >> t8

    globals()[dag_id] = dag
