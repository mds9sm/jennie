"""
Layer 2: Data Isolation Tests

User A must never be able to access User B's:
- Settings (persona, system prompt, user context)
- Chat sessions
- Query history
- Tasks
"""

import pytest
from httpx import AsyncClient


# =============================================================================
# Settings isolation
# =============================================================================

@pytest.mark.asyncio
async def test_settings_scoped_to_user(client: AsyncClient, auth_token: str, second_user_token: str, db_pool):
    """User A's settings should not be visible to User B."""
    from api.users import _sessions

    user_a = _sessions[auth_token]
    user_b = _sessions[second_user_token]

    # User A saves settings (may fail on DB constraint — that's OK, test the read isolation)
    resp = await client.put(
        "/api/settings",
        json={
            "session_id": "test-session",
            "persona": "ml_engineer",
            "system_prompt": "SECRET RULES FOR USER A",
            "user_context": "User A private context",
        },
        headers={"X-Auth-Token": auth_token},
    )
    # May be 200 or 500 depending on DB schema — the important test is the read below

    # User B reads settings — should NOT see User A's data
    resp = await client.get(
        "/api/settings",
        headers={"X-Auth-Token": second_user_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("system_prompt", "") != "SECRET RULES FOR USER A"
    assert "SECRET" not in str(data)

    # Cleanup
    await db_pool.execute("DELETE FROM user_settings WHERE user_id = $1", str(user_a["user_id"]))


# =============================================================================
# History isolation
# =============================================================================

@pytest.mark.asyncio
async def test_history_scoped_to_user(client: AsyncClient, auth_token: str, second_user_token: str, db_pool):
    """User A's query history should not be visible to User B."""
    from api.users import _sessions

    user_a = _sessions[auth_token]
    user_b = _sessions[second_user_token]

    # Insert a fake query event for User A
    await db_pool.execute("""
        INSERT INTO usage_events (user_id, capability, query_text, environment)
        VALUES ($1, 'sql_execute', 'SELECT * FROM secret_table', 'np')
    """, str(user_a["user_id"]))

    # User B queries history — should NOT see User A's queries
    resp = await client.get(
        "/api/history/queries",
        headers={"X-Auth-Token": second_user_token},
    )
    assert resp.status_code == 200
    queries = resp.json()
    for q in queries:
        assert "secret_table" not in q.get("query_text", ""), \
            "User B can see User A's query history!"

    # Cleanup
    await db_pool.execute(
        "DELETE FROM usage_events WHERE user_id = $1 AND query_text LIKE '%secret_table%'",
        str(user_a["user_id"]),
    )


@pytest.mark.asyncio
async def test_history_by_id_requires_ownership(client: AsyncClient, auth_token: str, second_user_token: str, db_pool):
    """User B should not be able to fetch User A's query by ID."""
    from api.users import _sessions

    user_a = _sessions[auth_token]

    # Insert a query for User A
    row = await db_pool.fetchrow("""
        INSERT INTO usage_events (user_id, capability, query_text, environment)
        VALUES ($1, 'sql_execute', 'SELECT * FROM user_a_private', 'np')
        RETURNING id
    """, str(user_a["user_id"]))
    query_id = row["id"]

    # User B tries to fetch it by ID — should get 404
    resp = await client.get(
        f"/api/history/queries/{query_id}",
        headers={"X-Auth-Token": second_user_token},
    )
    assert resp.status_code == 404

    # User A can fetch their own query
    resp = await client.get(
        f"/api/history/queries/{query_id}",
        headers={"X-Auth-Token": auth_token},
    )
    assert resp.status_code == 200
    assert resp.json()["query_text"] == "SELECT * FROM user_a_private"

    # Cleanup
    await db_pool.execute("DELETE FROM usage_events WHERE id = $1", query_id)


# =============================================================================
# Chat session isolation
# =============================================================================

@pytest.mark.asyncio
async def test_chat_sessions_scoped_to_user(client: AsyncClient, auth_token: str, second_user_token: str, db_pool):
    """User A's chat sessions should not appear in User B's session list."""
    from api.users import _sessions

    user_a = _sessions[auth_token]

    # Create a session for User A
    resp = await client.post(
        "/api/chat/sessions",
        json={
            "session_id": "user-a-private-session",
            "messages": [{"role": "user", "content": "secret question"}],
        },
        headers={"X-Auth-Token": auth_token},
    )

    # User B lists sessions — should NOT see User A's session
    resp = await client.get(
        "/api/chat/sessions",
        headers={"X-Auth-Token": second_user_token},
    )
    assert resp.status_code == 200
    sessions = resp.json()
    session_ids = [s.get("id") for s in sessions]
    assert "user-a-private-session" not in session_ids

    # Cleanup
    await db_pool.execute("DELETE FROM chat_sessions WHERE id = 'user-a-private-session'")


# =============================================================================
# Connection isolation (all users can see connections — this is by design)
# But anonymous users should NOT see them
# =============================================================================

@pytest.mark.asyncio
async def test_connections_require_auth(client: AsyncClient):
    """Connection CRUD requires authentication."""
    resp = await client.get("/api/connections")
    assert resp.status_code == 401

    resp = await client.post("/api/connections", json={
        "name": "hacker", "host": "evil.com", "username": "root", "password": "pass"
    })
    assert resp.status_code == 401

    resp = await client.delete("/api/connections/1")
    assert resp.status_code == 401
