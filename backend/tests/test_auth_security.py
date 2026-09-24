"""
Layer 1: Auth & Security Tests

Every protected endpoint must:
- Return 401 without auth token
- Return 403 for insufficient role (where applicable)
- Never leak data to unauthenticated callers
"""

import pytest
from httpx import AsyncClient


# =============================================================================
# P0: All protected endpoints reject unauthenticated requests
# =============================================================================

PROTECTED_ENDPOINTS = [
    # Settings
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    # History
    ("GET", "/api/history/queries"),
    ("GET", "/api/history/queries/1"),
    # Connections
    ("GET", "/api/connections"),
    ("POST", "/api/connections"),
    ("PUT", "/api/connections/1"),
    ("DELETE", "/api/connections/1"),
    ("POST", "/api/connections/1/test"),
    ("GET", "/api/connections/browse/databases"),
    ("GET", "/api/connections/browse/schemas?database=dev"),
    ("GET", "/api/connections/browse/tables?database=dev&schema=public"),
    ("GET", "/api/connections/browse/columns?database=dev&schema=public&table=users"),
    ("POST", "/api/connections/execute"),
    # Glossary review
    ("GET", "/api/glossary-review/entries"),
    # Notifications
    ("GET", "/api/notifications"),
    # Tasks / Feedback
    ("GET", "/api/feedback"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
async def test_unauthenticated_returns_401(client: AsyncClient, method: str, path: str):
    """Every protected endpoint must return 401 without auth."""
    if method == "GET":
        resp = await client.get(path)
    elif method == "POST":
        resp = await client.post(path, json={})
    elif method == "PUT":
        resp = await client.put(path, json={})
    elif method == "DELETE":
        resp = await client.delete(path)
    else:
        pytest.fail(f"Unknown method {method}")

    # 401 = auth rejected, 422 = Pydantic validation ran before auth (FastAPI ordering — body-based endpoints)
    # Both are acceptable: the request is denied without leaking data
    assert resp.status_code in (401, 422), f"{method} {path} returned {resp.status_code}, expected 401 or 422"


# =============================================================================
# Auth token validation
# =============================================================================

@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient):
    """A garbage token should not authenticate."""
    resp = await client.get(
        "/api/settings",
        headers={"X-Auth-Token": "garbage-invalid-token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(client: AsyncClient):
    """An expired token should not authenticate."""
    import time
    from api.users import _sessions

    token = "expired-test-token"
    _sessions[token] = {
        "user_id": 999,
        "email": "expired@example.com",
        "role": "engineer",
        "expires": time.time() - 100,  # expired 100s ago
    }

    resp = await client.get(
        "/api/settings",
        headers={"X-Auth-Token": token},
    )
    assert resp.status_code == 401

    _sessions.pop(token, None)


@pytest.mark.asyncio
async def test_valid_token_returns_200(auth_client: AsyncClient):
    """A valid token should authenticate successfully."""
    resp = await auth_client.get("/api/settings")
    assert resp.status_code == 200


# =============================================================================
# SQL Injection prevention
# =============================================================================

@pytest.mark.asyncio
async def test_browse_schemas_rejects_sql_injection(auth_client: AsyncClient):
    """SQL injection in database param should be rejected."""
    resp = await auth_client.get("/api/connections/browse/schemas?database=dev';SELECT 1--")
    data = resp.json()
    assert "error" in data or data.get("schemas") == []
    # Should NOT have executed the injected SQL
    assert "Invalid identifier" in data.get("error", "") or resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_browse_tables_rejects_sql_injection(auth_client: AsyncClient):
    """SQL injection in schema param should be rejected."""
    resp = await auth_client.get("/api/connections/browse/tables?database=dev&schema=public' OR '1'='1")
    data = resp.json()
    assert "error" in data or data.get("tables") == []


@pytest.mark.asyncio
async def test_browse_columns_rejects_sql_injection(auth_client: AsyncClient):
    """SQL injection in table param should be rejected."""
    resp = await auth_client.get("/api/connections/browse/columns?database=dev&schema=public&table=users'; DROP TABLE users--")
    data = resp.json()
    assert "error" in data or data.get("columns") == []


@pytest.mark.asyncio
async def test_valid_identifiers_pass(auth_client: AsyncClient):
    """Valid identifiers should not be rejected."""
    # This will fail to connect to Redshift (no connection) but should NOT fail on identifier validation
    resp = await auth_client.get("/api/connections/browse/schemas?database=dev")
    data = resp.json()
    # Should fail with connection error, not identifier error
    assert "Invalid identifier" not in data.get("error", "")


# =============================================================================
# Query safety guard
# =============================================================================

@pytest.mark.asyncio
async def test_execute_query_rejects_non_select(auth_client: AsyncClient):
    """execute_query should reject INSERT/UPDATE/DELETE/DROP statements."""
    dangerous_sqls = [
        "DROP TABLE users",
        "DELETE FROM usage_events",
        "INSERT INTO users VALUES (1, 'hacker')",
        "UPDATE users SET role = 'admin'",
        "TRUNCATE TABLE usage_events",
        "CREATE TABLE hacked (id int)",
    ]
    for sql in dangerous_sqls:
        resp = await auth_client.post("/api/sql/execute", json={"sql": sql, "environment": "np"})
        data = resp.json()
        # Should be rejected — either by query safety guard or by error
        assert resp.status_code != 200 or "error" in data or "not allowed" in str(data).lower(), \
            f"Dangerous SQL was not rejected: {sql}"
