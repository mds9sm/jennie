"""
DOMO & View Parser — extracts metric/KPI definitions from:

1. Transform YAML "views" sections → SQL file paths → CREATE OR REPLACE VIEW (the metric definition)
2. Transform YAML "downstream_dags" → links transforms to DOMO refresh DAGs and other transforms
3. dags/domo_refresh/conf/*.yaml → maps views to DOMO dataset IDs, S3 paths, schemas

Builds the complete chain: transform → view (metric SQL) → DOMO dataset → dashboard
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("genie.catalog_engine.domo_parser")

# Regex for table references in view SQL
_TABLE_REF_PATTERN = re.compile(
    r"(?:FROM|JOIN)\s+(?:(\w+)\.)?(\w+)\.(\w+)",
    re.IGNORECASE,
)

_SQL_KEYWORDS = frozenset({
    "SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION",
    "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "OUTER", "ON", "AS",
    "SET", "VALUES", "INSERT", "UPDATE", "DELETE", "INTO", "WITH",
    "CASE", "WHEN", "THEN", "ELSE", "END", "AND", "OR", "NOT", "IN",
})


def _is_valid_identifier(name: str) -> bool:
    if not name or len(name) <= 2 and name.isalpha() or name[0].isdigit():
        return False
    return True


def _extract_table_refs(sql: str) -> list[str]:
    refs = []
    for match in _TABLE_REF_PATTERN.finditer(sql):
        db, schema, table = match.groups()
        if not schema or not table:
            continue
        if schema.upper() in _SQL_KEYWORDS or table.upper() in _SQL_KEYWORDS:
            continue
        if not _is_valid_identifier(schema) or not _is_valid_identifier(table):
            continue
        if db and _is_valid_identifier(db):
            refs.append(f"{db}.{schema}.{table}".lower())
        else:
            refs.append(f"{schema}.{table}".lower())
    return list(set(refs))


def parse_domo_refresh_configs(repo_path: str) -> list[dict]:
    """
    Parse dags/domo_refresh/conf/*.yaml to extract DOMO dataset mappings.

    Returns list of:
    {
        "dag_name": str,
        "view_name": str,
        "schema": str,
        "domo_dataset_id": str,
        "s3_unload_path": str,
        "s3_bucket": str,
        "email": list[str],
        "tags": list[str],
    }
    """
    domo_dir = Path(repo_path) / "dags" / "domo_refresh" / "conf"
    if not domo_dir.is_dir():
        logger.warning("No domo_refresh/conf directory found")
        return []

    results: list[dict] = []
    yaml_files = list(domo_dir.glob("*.yaml")) + list(domo_dir.glob("*.yml"))
    logger.info("Scanning %d DOMO refresh configs", len(yaml_files))

    for yaml_path in yaml_files:
        try:
            with open(yaml_path) as f:
                content = yaml.safe_load(f)
        except Exception as e:
            logger.debug("Skipping %s: %s", yaml_path, e)
            continue

        if not content or not isinstance(content, dict):
            continue

        for dag_name, dag_cfg in content.items():
            if not isinstance(dag_cfg, dict):
                continue

            email = dag_cfg.get("email_id", dag_cfg.get("email", []))
            if isinstance(email, str):
                email = [email]
            tags = dag_cfg.get("tags", [])

            # Get S3 bucket from environment config
            env_cfg = dag_cfg.get("environment", {})
            prd_cfg = env_cfg.get("prd", env_cfg.get("prod", {}))
            s3_bucket = ""
            if isinstance(prd_cfg, dict):
                s3_url = prd_cfg.get("s3_unload_url", "")
                if s3_url.startswith("s3://"):
                    s3_bucket = s3_url.replace("s3://", "").rstrip("/")

            # Parse objects (each object = one view → one DOMO dataset)
            objects = dag_cfg.get("objects", {})
            if not isinstance(objects, dict):
                continue

            for view_name, obj_cfg in objects.items():
                if not isinstance(obj_cfg, dict):
                    continue

                results.append({
                    "dag_name": dag_name,
                    "view_name": view_name,
                    "schema": obj_cfg.get("schema", ""),
                    "domo_dataset_id": obj_cfg.get("domo_dataset_id", ""),
                    "s3_unload_path": obj_cfg.get("s3_unload_path", ""),
                    "s3_bucket": s3_bucket,
                    "columns": obj_cfg.get("columns", "*"),
                    "email": email,
                    "tags": tags,
                    "yaml_file": str(yaml_path),
                })

    logger.info("Parsed %d DOMO dataset mappings from %d configs", len(results), len(yaml_files))
    return results


def parse_transform_views(repo_path: str) -> list[dict]:
    """
    Parse transform/conf/*.yaml "views" sections to extract view definitions.

    Returns list of:
    {
        "dag_name": str,
        "view_name": str,          # task name (e.g. REFRESH_ENGAGEMENT_DEPTH_VIEW)
        "view_table": str,         # the actual view being created (from params)
        "view_schema": str,
        "sql_file": str,           # relative path to SQL file
        "sql_content": str,        # raw SQL content
        "source_tables": list[str], # tables referenced in the view SQL
        "conn_id": str,
    }
    """
    conf_dir = Path(repo_path) / "dags" / "transform" / "conf"
    if not conf_dir.is_dir():
        return []

    results: list[dict] = []
    transform_dir = Path(repo_path) / "dags" / "transform"

    for yaml_path in list(conf_dir.glob("*.yaml")) + list(conf_dir.glob("*.yml")):
        if "_deprecated" in yaml_path.name:
            continue
        try:
            with open(yaml_path) as f:
                content = yaml.safe_load(f)
        except Exception:
            continue

        if not content or not isinstance(content, dict):
            continue

        for dag_name, dag_cfg in content.items():
            if not isinstance(dag_cfg, dict):
                continue

            views = dag_cfg.get("views", {})
            if not isinstance(views, dict):
                continue

            for view_task_name, view_cfg in views.items():
                if not isinstance(view_cfg, dict):
                    continue

                sql_path = view_cfg.get("sql", "")
                params = view_cfg.get("params", {})
                conn_id = view_cfg.get("conn_id", "")

                # Extract view name from params
                view_schema = ""
                view_table = ""
                if isinstance(params, dict):
                    for k, v in params.items():
                        if "schema" in k.lower():
                            view_schema = str(v)
                        if "view" in k.lower() or "table" in k.lower():
                            view_table = str(v)

                # Read the SQL file
                sql_content = ""
                source_tables = []
                if sql_path:
                    full_sql_path = transform_dir / sql_path
                    if full_sql_path.exists():
                        try:
                            sql_content = full_sql_path.read_text(errors="replace")
                            source_tables = _extract_table_refs(sql_content)
                        except Exception:
                            pass

                results.append({
                    "dag_name": dag_name,
                    "view_task_name": view_task_name,
                    "view_table": view_table,
                    "view_schema": view_schema,
                    "sql_file": sql_path,
                    "sql_content": sql_content,
                    "source_tables": source_tables,
                    "conn_id": conn_id,
                    "yaml_file": str(yaml_path),
                })

    logger.info("Parsed %d view definitions from transform configs", len(results))
    return results


def parse_downstream_dags(repo_path: str) -> dict[str, list[str]]:
    """
    Parse downstream_dags from all transform configs.

    Returns: {dag_name: [downstream_dag_1, downstream_dag_2, ...]}
    """
    conf_dir = Path(repo_path) / "dags" / "transform" / "conf"
    if not conf_dir.is_dir():
        return {}

    result: dict[str, list[str]] = {}

    for yaml_path in list(conf_dir.glob("*.yaml")) + list(conf_dir.glob("*.yml")):
        if "_deprecated" in yaml_path.name:
            continue
        try:
            with open(yaml_path) as f:
                content = yaml.safe_load(f)
        except Exception:
            continue

        if not content or not isinstance(content, dict):
            continue

        for dag_name, dag_cfg in content.items():
            if not isinstance(dag_cfg, dict):
                continue
            downstream = dag_cfg.get("downstream_dags", [])
            if isinstance(downstream, list) and downstream:
                result[dag_name] = [str(d) for d in downstream]

    logger.info("Parsed downstream_dags for %d transforms", len(result))
    return result


def parse_all(repo_path: str) -> dict:
    """
    Parse all DOMO + view + downstream data from the repo.

    Returns:
    {
        "domo_datasets": [...],      # DOMO dataset mappings
        "views": [...],              # view definitions with SQL
        "downstream_dags": {...},    # DAG → downstream DAGs
        "metrics": [...],            # combined: view + DOMO dataset linked
        "stats": {...},
    }
    """
    domo_datasets = parse_domo_refresh_configs(repo_path)
    views = parse_transform_views(repo_path)
    downstream = parse_downstream_dags(repo_path)

    # Link views to DOMO datasets by view name
    domo_index: dict[str, dict] = {}
    for d in domo_datasets:
        domo_index[d["view_name"].lower()] = d

    metrics: list[dict] = []
    for view in views:
        view_table = view.get("view_table", "").lower()
        domo = domo_index.get(view_table)

        metric: dict[str, Any] = {
            "name": view["view_table"] or view["view_task_name"],
            "schema": view["view_schema"],
            "dag_name": view["dag_name"],
            "view_task": view["view_task_name"],
            "sql_file": view["sql_file"],
            "source_tables": view["source_tables"],
            "has_sql": bool(view["sql_content"]),
        }

        if domo:
            metric["domo_dataset_id"] = domo["domo_dataset_id"]
            metric["domo_dag"] = domo["dag_name"]
            metric["s3_path"] = f"s3://{domo['s3_bucket']}/{domo['s3_unload_path']}" if domo["s3_bucket"] else ""
            metric["domo_tags"] = domo.get("tags", [])

        metrics.append(metric)

    # Also add DOMO datasets that don't have a matching view (direct table unloads)
    view_tables = {v["view_table"].lower() for v in views if v.get("view_table")}
    for d in domo_datasets:
        if d["view_name"].lower() not in view_tables:
            metrics.append({
                "name": d["view_name"],
                "schema": d["schema"],
                "dag_name": d["dag_name"],
                "view_task": None,
                "sql_file": None,
                "source_tables": [],
                "has_sql": False,
                "domo_dataset_id": d["domo_dataset_id"],
                "domo_dag": d["dag_name"],
                "s3_path": f"s3://{d['s3_bucket']}/{d['s3_unload_path']}" if d["s3_bucket"] else "",
                "domo_tags": d.get("tags", []),
                "type": "direct_unload",  # no view, direct table → DOMO
            })

    logger.info(
        "Built %d metrics (%d with DOMO links, %d with SQL)",
        len(metrics),
        sum(1 for m in metrics if m.get("domo_dataset_id")),
        sum(1 for m in metrics if m.get("has_sql")),
    )

    return {
        "domo_datasets": domo_datasets,
        "views": views,
        "downstream_dags": downstream,
        "metrics": metrics,
        "stats": {
            "domo_datasets": len(domo_datasets),
            "views": len(views),
            "downstream_dags": len(downstream),
            "metrics": len(metrics),
        },
    }
