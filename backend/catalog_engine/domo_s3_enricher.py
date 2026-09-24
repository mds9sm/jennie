"""
DOMO S3 Metadata Enricher — samples S3 unload data to enrich metrics with:
- Column names and types (from CSV/TSV headers)
- Row count estimate (from file sizes)
- Date range (from sample data)
- Last refresh timestamp (from S3 LastModified)
- File count and total size

Runs during KB build using prod SSO credentials.
Does NOT load full data — only lists objects + reads first few lines per dataset.
"""

import csv
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("genie.catalog_engine.domo_s3")

# S3 bucket and prefix for DOMO unloads
DOMO_BUCKET = "prod-bi-export"
DOMO_PREFIX = "prd_dw/analytics/"
# Also check the /dw/analytics/ prefix (some configs use this)
DOMO_PREFIXES = ["prd_dw/analytics/", "dw/analytics/"]

# Max files to sample per metric (don't need all partitions)
MAX_FILES_PER_METRIC = 5
# Max bytes to read for header sampling
SAMPLE_BYTES = 8192  # 8KB — enough for headers + a few rows


def _get_s3_client(environment: str = "prd"):
    """Get S3 client using prod SSO credentials."""
    try:
        from connectors.credential_store import credential_store
        import boto3

        for sid, session in credential_store._sessions.items():
            creds = session.get_credentials(environment)
            if creds:
                return boto3.client(
                    "s3",
                    aws_access_key_id=creds.access_key_id,
                    aws_secret_access_key=creds.secret_access_key,
                    aws_session_token=creds.session_token,
                    region_name="us-west-2",
                )
        logger.warning("No %s SSO credentials available for S3", environment)
        return None
    except Exception as e:
        logger.error("Failed to create S3 client: %s", e)
        return None


def _parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse s3://bucket/prefix into (bucket, prefix)."""
    if not s3_path or not s3_path.startswith("s3://"):
        return "", ""
    path = s3_path[5:]  # strip s3://
    parts = path.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix


def _sample_csv_header(s3_client, bucket: str, key: str) -> dict:
    """Read first few KB of an S3 object to extract CSV header and sample rows."""
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{SAMPLE_BYTES}")
        raw = resp["Body"].read()

        # Handle gzip compressed files
        if key.endswith(".gz") or raw[:2] == b'\x1f\x8b':
            import gzip
            try:
                raw = gzip.decompress(raw)
            except Exception:
                # Partial gzip (we only read 8KB) — try reading full file if small
                try:
                    full_resp = s3_client.get_object(Bucket=bucket, Key=key)
                    full_raw = full_resp["Body"].read()
                    if len(full_raw) < 5 * 1024 * 1024:  # only decompress if < 5MB
                        raw = gzip.decompress(full_raw)
                    else:
                        return {}
                except Exception:
                    return {}

        # Check if binary/parquet (not text)
        if raw[:4] == b'PAR1' or raw[:4] == b'\x00\x00\x00\x00':
            return {"format": "parquet", "note": "Parquet file — use DuckDB to read"}

        body = raw.decode("utf-8", errors="replace")
        lines = body.strip().split("\n")

        if not lines:
            return {}

        # Try to detect delimiter
        first_line = lines[0]
        delimiter = "\t" if "\t" in first_line else "|" if "|" in first_line else ","

        reader = csv.reader(io.StringIO("\n".join(lines[:10])), delimiter=delimiter)
        rows = list(reader)

        if not rows:
            return {}

        columns = rows[0]
        sample_rows = rows[1:6]  # up to 5 sample rows

        # Try to detect date columns from sample data
        date_columns = []
        date_ranges = {}
        for col_idx, col_name in enumerate(columns):
            for row in sample_rows:
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    # Check if it looks like a date (YYYY-MM-DD pattern)
                    if len(val) >= 10 and val[:4].isdigit() and val[4] == "-":
                        if col_name not in date_columns:
                            date_columns.append(col_name)
                        if col_name not in date_ranges:
                            date_ranges[col_name] = {"min": val[:10], "max": val[:10]}
                        else:
                            if val[:10] < date_ranges[col_name]["min"]:
                                date_ranges[col_name]["min"] = val[:10]
                            if val[:10] > date_ranges[col_name]["max"]:
                                date_ranges[col_name]["max"] = val[:10]

        return {
            "columns": columns,
            "column_count": len(columns),
            "delimiter": delimiter,
            "sample_row_count": len(sample_rows),
            "date_columns": date_columns,
            "date_ranges": date_ranges,
            "sample_values": {
                col: [r[i] for r in sample_rows if i < len(r)][:3]
                for i, col in enumerate(columns[:20])  # first 20 columns only
            },
        }
    except Exception as e:
        logger.debug("Failed to sample %s/%s: %s", bucket, key, str(e)[:100])
        return {}


def enrich_metrics_from_s3(
    metrics: list[dict],
    progress_callback=None,
) -> list[dict]:
    """
    Enrich metrics with S3 metadata. For each metric that has an s3_path:
    1. List objects at that path
    2. Get file count, total size, last modified
    3. Sample headers for column names
    4. Add metadata to metric record

    Returns enriched metrics list (modified in place).
    """
    s3 = _get_s3_client("prd")
    if not s3:
        logger.warning("No S3 client — skipping DOMO S3 enrichment")
        return metrics

    metrics_with_s3 = [m for m in metrics if m.get("s3_path")]
    logger.info("Enriching %d metrics with S3 metadata (out of %d total)",
                len(metrics_with_s3), len(metrics))

    enriched_count = 0
    for idx, metric in enumerate(metrics_with_s3):
        s3_path = metric["s3_path"]
        bucket, prefix = _parse_s3_path(s3_path)

        if not bucket or not prefix:
            continue

        if progress_callback:
            progress_callback(f"S3 metadata: {metric['name']} ({idx+1}/{len(metrics_with_s3)})")

        try:
            # List objects at the metric's S3 path
            resp = s3.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=100,
            )
            objects = resp.get("Contents", [])

            if not objects:
                metric["s3_metadata"] = {"status": "no_files", "checked_at": datetime.utcnow().isoformat()}
                continue

            # Compute stats
            total_size = sum(o["Size"] for o in objects)
            file_count = len(objects)
            last_modified = max(o["LastModified"] for o in objects)
            oldest = min(o["LastModified"] for o in objects)

            # Estimate row count from file size (rough: ~200 bytes per row for typical analytics data)
            estimated_rows = total_size // 200 if total_size > 0 else 0

            s3_meta: dict[str, Any] = {
                "file_count": file_count,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 1),
                "last_modified": last_modified.isoformat(),
                "oldest_file": oldest.isoformat(),
                "estimated_rows": estimated_rows,
                "bucket": bucket,
                "prefix": prefix,
                "checked_at": datetime.utcnow().isoformat(),
            }

            # Sample the most recent file for column headers
            # Sort by LastModified desc, pick the largest recent file
            recent_files = sorted(objects, key=lambda o: o["LastModified"], reverse=True)
            sampled = False
            for obj in recent_files[:MAX_FILES_PER_METRIC]:
                if obj["Size"] < 100:  # skip tiny files
                    continue
                header_info = _sample_csv_header(s3, bucket, obj["Key"])
                if header_info and header_info.get("columns"):
                    s3_meta["columns"] = header_info["columns"]
                    s3_meta["column_count"] = header_info["column_count"]
                    s3_meta["delimiter"] = header_info["delimiter"]
                    s3_meta["date_columns"] = header_info.get("date_columns", [])
                    s3_meta["date_ranges"] = header_info.get("date_ranges", {})
                    s3_meta["sample_values"] = header_info.get("sample_values", {})
                    sampled = True
                    break

            if not sampled:
                s3_meta["columns"] = []
                s3_meta["column_count"] = 0

            metric["s3_metadata"] = s3_meta
            enriched_count += 1

        except Exception as e:
            logger.warning("Failed to enrich %s from S3: %s", metric["name"], str(e)[:200])
            metric["s3_metadata"] = {"status": "error", "error": str(e)[:200]}

    logger.info("Enriched %d/%d metrics with S3 metadata", enriched_count, len(metrics_with_s3))
    return metrics


def build_domo_catalog(metrics: list[dict], knowledge_dir: str | Path) -> dict:
    """
    Build a unified DOMO catalog linking:
    - DOMO refresh DAG (schedule, status)
    - View definition (SQL, source tables)
    - S3 metadata (columns, freshness, size)
    - Business context (pillar, tags)

    Writes domo_catalog.json to knowledge directory.
    Returns summary stats.
    """
    knowledge_dir = Path(knowledge_dir)
    catalog = []

    for m in metrics:
        entry: dict[str, Any] = {
            "name": m["name"],
            "schema": m.get("schema", ""),
            # Pipeline link
            "transform_dag": m.get("dag_name", ""),
            "domo_refresh_dag": m.get("domo_dag", ""),
            "view_task": m.get("view_task", ""),
            # DOMO link
            "domo_dataset_id": m.get("domo_dataset_id", ""),
            "s3_path": m.get("s3_path", ""),
            "domo_tags": m.get("domo_tags", []),
            # SQL definition
            "has_view_sql": m.get("has_sql", False),
            "sql_file": m.get("sql_file", ""),
            "source_tables": m.get("source_tables", []),
            # S3 freshness (if enriched)
            "s3_metadata": m.get("s3_metadata"),
        }

        # Derive business context from tags, names, and source tables
        pillar = _infer_pillar(m)
        if pillar:
            entry["pillar"] = pillar

        # Derive metric type
        entry["metric_type"] = _infer_metric_type(m)

        catalog.append(entry)

    # Write catalog
    catalog_path = knowledge_dir / "domo_catalog.json"
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2, default=str)

    # Summary
    stats = {
        "total_metrics": len(catalog),
        "with_domo_link": sum(1 for c in catalog if c.get("domo_dataset_id")),
        "with_view_sql": sum(1 for c in catalog if c.get("has_view_sql")),
        "with_s3_metadata": sum(1 for c in catalog if c.get("s3_metadata") and c["s3_metadata"].get("columns")),
        "with_pillar": sum(1 for c in catalog if c.get("pillar")),
        "total_s3_size_mb": sum(
            c.get("s3_metadata", {}).get("total_size_mb", 0)
            for c in catalog if c.get("s3_metadata")
        ),
        "pillar_breakdown": {},
    }

    # Pillar breakdown
    for c in catalog:
        p = c.get("pillar", "unknown")
        stats["pillar_breakdown"][p] = stats["pillar_breakdown"].get(p, 0) + 1

    logger.info("Built DOMO catalog: %d metrics, %d with S3 data, %.1f MB total",
                stats["total_metrics"], stats["with_s3_metadata"], stats["total_s3_size_mb"])

    return stats


def _infer_pillar(metric: dict) -> str:
    """Infer pillar from metric name, tags, and source tables."""
    name = (metric.get("name", "") + " " + metric.get("dag_name", "")).lower()
    tags = " ".join(metric.get("domo_tags", [])).lower()
    combined = name + " " + tags

    if any(k in combined for k in ["onboard", "activation", "first_cut", "registration"]):
        return "Onboard"
    if any(k in combined for k in ["pillar_2", "pillar2", "return", "retention", "dau", "wau", "mau"]):
        return "Trigger Return"
    if any(k in combined for k in ["pillar_3", "pillar3", "makeable", "content_availability"]):
        return "Makeable Content"
    if any(k in combined for k in ["pillar_4", "pillar4", "content_matching", "search", "recommendation"]):
        return "Content Matching"
    if any(k in combined for k in ["pillar_5", "pillar5", "canvas_to_cut", "design_make", "cut_session", "engagement"]):
        return "Design & Make"
    if any(k in combined for k in ["guided", "template"]):
        return "Guided Flows"
    if any(k in combined for k in ["braze", "marketing", "subscription", "churn"]):
        return "Marketing"
    if any(k in combined for k in ["platform", "pipeline", "data_quality", "dq_sync"]):
        return "Platform"
    return ""


def _infer_metric_type(metric: dict) -> str:
    """Infer metric type from name and structure."""
    name = metric.get("name", "").lower()
    if metric.get("type") == "direct_unload":
        return "direct_unload"
    if any(k in name for k in ["north_star", "kpi", "board"]):
        return "north_star"
    if any(k in name for k in ["daily", "weekly", "monthly"]):
        return "time_series"
    if any(k in name for k in ["funnel", "conversion"]):
        return "funnel"
    if any(k in name for k in ["cohort", "segment"]):
        return "cohort"
    if any(k in name for k in ["user_level", "user_attribute"]):
        return "user_level"
    return "metric"
