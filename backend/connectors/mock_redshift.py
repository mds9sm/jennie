import json
import random
import time
import uuid
from pathlib import Path


MOCK_FIXTURES_DIR = Path("knowledge/fixtures")


def load_mock_results() -> dict:
    path = MOCK_FIXTURES_DIR / "mock_results.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


async def execute_mock_query(
    sql: str, environment: str = "np", max_rows: int = 1000
) -> dict:
    """Execute a mock query returning fixture data."""
    start = time.time()
    fixtures = load_mock_results()

    sql_upper = sql.strip().upper()

    # Try to match against fixture patterns
    for pattern, result in fixtures.items():
        if pattern.upper() in sql_upper:
            rows = result["rows"][:max_rows]
            return {
                "columns": result["columns"],
                "rows": rows,
                "row_count": len(rows),
                "execution_time_ms": int((time.time() - start) * 1000) + random.randint(50, 300),
                "environment": environment,
                "truncated": len(result["rows"]) > max_rows,
                "query_id": f"mock-{uuid.uuid4().hex[:8]}",
            }

    # No mock data available — return error indicating mock mode
    return {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "execution_time_ms": 0,
        "environment": environment,
        "truncated": False,
        "query_id": f"mock-{uuid.uuid4().hex[:8]}",
        "error": "MOCK MODE: No real Redshift connection. Add credentials in Admin Console > Connection.",
    }
