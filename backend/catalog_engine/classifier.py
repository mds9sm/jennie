"""
Table and Column Classifier — uses weighted scoring to categorize
tables as fact/dimension and columns as metric/dimension/key/date/flag.

Confidence-based: each signal contributes a weighted score.
Tables: >0.6 = fact, <0.4 = dimension, between = ambiguous
"""

import re
import logging
from typing import Any

logger = logging.getLogger("genie.classifier")

# ---------------------------------------------------------------------------
# Table-level classification
# ---------------------------------------------------------------------------

# Name patterns
FACT_NAME_PATTERNS = re.compile(
    r"(^fact_|^fct_|_fact$|events|transactions|orders|clicks|logs|"
    r"_daily$|_hourly$|_detail$|_enriched$|_raw$|_history$|_master$|"
    r"firehose|session|activity|engagement|kpi|cube|funnel|cohort)",
    re.IGNORECASE,
)

DIM_NAME_PATTERNS = re.compile(
    r"(^dim_|^dim\.|_dim$|lookup|^ref_|_ref$|catalog|"
    r"country|currency|date|machine|image|font|project_type|"
    r"subscription_type|category|status|^lkp_)",
    re.IGNORECASE,
)

# SCD-style column patterns (suggest dimension)
SCD_COLUMNS = re.compile(
    r"(effective_date|expiry_date|is_current|valid_from|valid_to|scd_|row_version)",
    re.IGNORECASE,
)


def classify_table(
    schema_name: str,
    table_name: str,
    row_count: int | None,
    profile_data: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Classify a table as fact or dimension using weighted scoring.

    Returns:
        {
            "classification": "fact" | "dimension" | "ambiguous",
            "fact_score": float (0-1),
            "dim_score": float (0-1),
            "confidence": float (0-1),
            "signals": [list of reasons],
        }
    """
    profile = profile_data or {}
    meta = metadata or {}
    columns = profile.get("columns", {})
    col_count = profile.get("column_count", len(columns))
    rows = row_count or profile.get("row_count", 0) or 0

    signals: list[str] = []

    # --- Name pattern matching (weight: 0.30) ---
    name_fact = 0.0
    name_dim = 0.0
    full_name = f"{schema_name}.{table_name}"

    if schema_name.lower() in ("fact",):
        name_fact = 1.0
        signals.append(f"schema '{schema_name}' = fact")
    elif schema_name.lower() in ("dim",):
        name_dim = 1.0
        signals.append(f"schema '{schema_name}' = dimension")
    elif schema_name.lower() in ("analytics", "events", "stage"):
        name_fact = 0.7
        signals.append(f"schema '{schema_name}' suggests fact")

    if FACT_NAME_PATTERNS.search(table_name):
        name_fact = max(name_fact, 0.8)
        signals.append(f"name pattern matches fact")
    if DIM_NAME_PATTERNS.search(table_name):
        name_dim = max(name_dim, 0.8)
        signals.append(f"name pattern matches dimension")

    name_score_fact = name_fact
    name_score_dim = name_dim

    # --- Row count signal (weight: 0.20) ---
    row_fact = 0.0
    row_dim = 0.0
    if rows > 10_000_000:
        row_fact = 1.0
        signals.append(f"high row count ({rows:,}) = fact")
    elif rows > 1_000_000:
        row_fact = 0.7
        signals.append(f"medium-high row count ({rows:,}) leans fact")
    elif rows > 100_000:
        row_fact = 0.4
        row_dim = 0.3
    elif rows > 0:
        row_dim = 0.8
        signals.append(f"low row count ({rows:,}) = dimension")

    # --- Foreign key column ratio (weight: 0.20) ---
    fk_fact = 0.0
    fk_dim = 0.0
    if columns:
        id_cols = [c for c in columns if c.endswith("_id") or c.endswith("_key") or c.endswith("_code")]
        fk_ratio = len(id_cols) / max(col_count, 1)
        if fk_ratio > 0.3:
            fk_fact = 0.9
            signals.append(f"high FK ratio ({len(id_cols)}/{col_count}) = fact")
        elif fk_ratio > 0.15:
            fk_fact = 0.5
        elif len(id_cols) <= 1 and col_count > 3:
            fk_dim = 0.6
            signals.append(f"single/no FK columns = dimension")

    # --- Numeric column ratio (weight: 0.15) ---
    num_fact = 0.0
    num_dim = 0.0
    if columns:
        numeric_types = ("integer", "bigint", "numeric", "decimal", "float", "double", "real")
        string_types = ("character", "varchar", "text", "char")
        metric_pattern = re.compile(
            r"(amount|total|sum|count|qty|quantity|revenue|cost|price|rate|"
            r"percent|duration|weight|score|rank|value|size|num_|cnt_)",
            re.IGNORECASE,
        )

        numeric_cols = [c for c, info in columns.items()
                       if any(t in (info.get("type", "")).lower() for t in numeric_types)
                       and not c.endswith("_id") and not c.endswith("_key")]
        metric_cols = [c for c in numeric_cols if metric_pattern.search(c)]
        string_cols = [c for c, info in columns.items()
                      if any(t in (info.get("type", "")).lower() for t in string_types)]

        numeric_ratio = len(numeric_cols) / max(col_count, 1)
        string_ratio = len(string_cols) / max(col_count, 1)

        if metric_cols:
            num_fact = 0.9
            signals.append(f"metric columns found: {metric_cols[:3]}")
        elif numeric_ratio > 0.4:
            num_fact = 0.6
            signals.append(f"high numeric ratio ({len(numeric_cols)}/{col_count})")

        if string_ratio > 0.5:
            num_dim = 0.7
            signals.append(f"high string ratio ({len(string_cols)}/{col_count}) = descriptive/dimension")

    # --- Timestamp presence (weight: 0.15) ---
    ts_fact = 0.0
    ts_dim = 0.0
    if columns:
        date_cols = [c for c, info in columns.items()
                    if "date" in (info.get("type", "")).lower()
                    or "timestamp" in (info.get("type", "")).lower()
                    or "date" in c.lower()]
        scd_cols = [c for c in columns if SCD_COLUMNS.search(c)]

        if date_cols and not scd_cols:
            ts_fact = 0.8
            signals.append(f"date columns present: {date_cols[:3]}")
        if scd_cols:
            ts_dim = 0.9
            signals.append(f"SCD columns found: {scd_cols[:3]} = dimension")

    # --- ETL metadata signals (bonus) ---
    if meta.get("delta_load"):
        name_fact = max(name_fact, 0.6)
        signals.append("delta_load = fact pattern")
    if meta.get("refill_days"):
        name_fact = max(name_fact, 0.6)
        signals.append(f"refill_days={meta['refill_days']} = fact pattern")

    # --- Weighted scoring ---
    fact_score = (
        0.30 * name_score_fact +
        0.20 * row_fact +
        0.20 * fk_fact +
        0.15 * num_fact +
        0.15 * ts_fact
    )

    dim_score = (
        0.30 * name_score_dim +
        0.20 * row_dim +
        0.20 * fk_dim +
        0.15 * num_dim +
        0.15 * ts_dim
    )

    # Classification with thresholds
    if fact_score > 0.6:
        classification = "fact"
    elif dim_score > 0.6 or (dim_score > 0.4 and fact_score < 0.3):
        classification = "dimension"
    elif fact_score > dim_score and fact_score > 0.4:
        classification = "fact"
    elif dim_score > fact_score and dim_score > 0.4:
        classification = "dimension"
    else:
        classification = "ambiguous"

    confidence = abs(fact_score - dim_score)

    return {
        "classification": classification,
        "fact_score": round(fact_score, 3),
        "dim_score": round(dim_score, 3),
        "confidence": round(confidence, 3),
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Column-level classification
# ---------------------------------------------------------------------------

METRIC_NAME_PATTERNS = re.compile(
    r"(amount|total|sum|count|qty|quantity|revenue|cost|price|rate|"
    r"percent|duration|weight|score|rank|value|size_mb|num_|cnt_|"
    r"avg_|min_|max_|tbl_rows|pct_|ratio)",
    re.IGNORECASE,
)

KEY_NAME_PATTERNS = re.compile(
    r"(_id$|_key$|_pk$|^id$|_fk$)",
    re.IGNORECASE,
)

CODE_NAME_PATTERNS = re.compile(
    r"(_code$|_type$|_status$|_category$|_class$|_group$|_flag$|_ind$)",
    re.IGNORECASE,
)

DATE_TYPES = ("date", "timestamp", "timestamptz")

BOOLEAN_PATTERNS = re.compile(
    r"(^is_|^has_|^can_|^was_|^should_|_flag$|_ind$|_bool$|^flag_)",
    re.IGNORECASE,
)


def classify_column(
    col_name: str,
    col_type: str,
    distinct_count: int | None = None,
    null_rate: float | None = None,
    cardinality_ratio: float | None = None,
    row_count: int | None = None,
) -> dict:
    """
    Classify a column as: primary_key, foreign_key, metric, dimension, date, flag.

    Returns:
        {
            "category": str,
            "confidence": float (0-1),
            "signals": [list of reasons],
        }
    """
    col_type_lower = (col_type or "").lower()
    signals: list[str] = []

    # --- Date/Time ---
    if any(dt in col_type_lower for dt in DATE_TYPES) or col_name.lower().endswith(("_date", "_at", "_time", "_ts")):
        signals.append(f"date/timestamp type or name")
        return {"category": "date", "confidence": 0.95, "signals": signals}

    # --- Boolean / Flag ---
    if "bool" in col_type_lower or BOOLEAN_PATTERNS.search(col_name):
        signals.append(f"boolean type or is_/has_ pattern")
        return {"category": "flag", "confidence": 0.9, "signals": signals}

    if distinct_count is not None and distinct_count <= 3 and cardinality_ratio is not None and cardinality_ratio < 0.01:
        signals.append(f"very low cardinality ({distinct_count} distinct) = flag")
        return {"category": "flag", "confidence": 0.8, "signals": signals}

    # --- Primary Key ---
    is_key_name = KEY_NAME_PATTERNS.search(col_name)
    is_numeric = any(t in col_type_lower for t in ("int", "bigint", "numeric", "decimal"))

    if is_key_name and cardinality_ratio is not None and cardinality_ratio > 0.95 and (null_rate is None or null_rate == 0):
        signals.append(f"key name + unique + no nulls = primary key")
        return {"category": "primary_key", "confidence": 0.9, "signals": signals}

    if col_name.lower() == "id" or col_name.lower().endswith("_pk"):
        signals.append(f"explicit PK name")
        return {"category": "primary_key", "confidence": 0.85, "signals": signals}

    # --- Foreign Key ---
    if is_key_name and cardinality_ratio is not None and cardinality_ratio < 0.95:
        signals.append(f"key name + non-unique = foreign key")
        return {"category": "foreign_key", "confidence": 0.85, "signals": signals}

    if is_key_name:
        signals.append(f"key name pattern")
        return {"category": "foreign_key", "confidence": 0.7, "signals": signals}

    # --- Metric ---
    is_metric_name = METRIC_NAME_PATTERNS.search(col_name)
    if is_metric_name and is_numeric:
        signals.append(f"metric name + numeric type")
        return {"category": "metric", "confidence": 0.9, "signals": signals}

    if is_numeric and not is_key_name and cardinality_ratio is not None and cardinality_ratio > 0.1:
        signals.append(f"numeric + high cardinality + not a key = likely metric")
        return {"category": "metric", "confidence": 0.6, "signals": signals}

    # --- Dimension (categorical) ---
    if CODE_NAME_PATTERNS.search(col_name):
        signals.append(f"code/type/status/category name pattern")
        return {"category": "dimension", "confidence": 0.85, "signals": signals}

    if "char" in col_type_lower or "text" in col_type_lower or "varchar" in col_type_lower:
        if cardinality_ratio is not None and cardinality_ratio < 0.5:
            signals.append(f"string + low cardinality = categorical dimension")
            return {"category": "dimension", "confidence": 0.8, "signals": signals}
        else:
            signals.append(f"string column")
            return {"category": "dimension", "confidence": 0.5, "signals": signals}

    # --- Fallback ---
    if is_numeric and cardinality_ratio is not None and cardinality_ratio < 0.05:
        signals.append(f"numeric + very low cardinality = categorical")
        return {"category": "dimension", "confidence": 0.5, "signals": signals}

    signals.append("no strong signals")
    return {"category": "unknown", "confidence": 0.2, "signals": signals}


def classify_table_columns(profile_data: dict) -> dict[str, dict]:
    """
    Classify all columns in a profiled table.
    Returns {col_name: {category, confidence, signals}}.
    """
    columns = profile_data.get("columns", {})
    row_count = profile_data.get("row_count", 0)
    result = {}

    for col_name, col_info in columns.items():
        result[col_name] = classify_column(
            col_name=col_name,
            col_type=col_info.get("type", ""),
            distinct_count=col_info.get("distinct_count"),
            null_rate=col_info.get("null_rate"),
            cardinality_ratio=col_info.get("cardinality_ratio"),
            row_count=row_count,
        )

    return result
