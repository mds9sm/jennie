import re


PROD_ONLY_OPERATIONS = {"profiling", "explain", "table_info", "row_count"}


def get_env_prefix(environment: str) -> str:
    return "prd_" if environment == "prd" else "np_"


def should_route_to_prod(sql: str) -> bool:
    """Check if a query requires prod (EXPLAIN, profiling queries)."""
    normalized = sql.strip().upper()
    if normalized.startswith("EXPLAIN"):
        return True
    # Profiling patterns: SVV_TABLE_INFO, STL_QUERY, row count estimates
    profiling_patterns = [
        r"SVV_TABLE_INFO",
        r"STL_QUERY",
        r"STL_SCAN",
        r"STV_BLOCKLIST",
        r"PG_TABLE_DEF",
    ]
    for pattern in profiling_patterns:
        if re.search(pattern, sql, re.IGNORECASE):
            return True
    return False


def validate_read_only(sql: str) -> tuple[bool, str]:
    """Validate that SQL is read-only (SELECT or EXPLAIN only)."""
    normalized = sql.strip().upper()

    # Remove comments
    normalized = re.sub(r"--.*$", "", normalized, flags=re.MULTILINE)
    normalized = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL)
    normalized = normalized.strip()

    allowed_prefixes = ("SELECT", "EXPLAIN", "SHOW", "WITH")
    if not normalized.startswith(allowed_prefixes):
        return False, f"Only SELECT, EXPLAIN, SHOW, and WITH statements are allowed. Got: {normalized[:50]}..."

    # Check for DML/DDL keywords that might be injected
    forbidden = [
        r"\bINSERT\b",
        r"\bUPDATE\b",
        r"\bDELETE\b",
        r"\bDROP\b",
        r"\bCREATE\b",
        r"\bALTER\b",
        r"\bTRUNCATE\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
        r"\bUNLOAD\b",
        r"\bCOPY\b",
    ]
    for pattern in forbidden:
        if re.search(pattern, normalized):
            return False, f"Forbidden operation detected: {pattern.strip(chr(92)).replace('b', '')}"

    return True, ""


def inject_env_prefix(sql: str, environment: str) -> str:
    """Replace generic database references with environment-prefixed ones."""
    prefix = get_env_prefix(environment)
    # Replace common patterns: dw. -> np_dw. or prd_dw.
    sql = re.sub(r"\bdw\.", f"{prefix}dw.", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bdata_lake\.", f"{prefix}data_lake.", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bpersonalize\.", f"{prefix}personalize.", sql, flags=re.IGNORECASE)
    return sql
