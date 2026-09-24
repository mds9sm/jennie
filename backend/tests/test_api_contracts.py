"""
Layer 3: API Contract Tests

Every major endpoint must return the expected response shape.
Verifies status codes, JSON structure, and key field presence.
"""

import json
import pytest
from httpx import AsyncClient


# =============================================================================
# Health & Meta (no auth required)
# =============================================================================

@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "redshift_mode" in data


@pytest.mark.asyncio
async def test_pillars_returns_list(client: AsyncClient):
    resp = await client.get("/api/pillars")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_environments_returns_np_and_prd(client: AsyncClient):
    resp = await client.get("/api/environments")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = [e["id"] for e in data]
    assert "np" in ids
    assert "prd" in ids


# =============================================================================
# Chat sessions
# =============================================================================

@pytest.mark.asyncio
async def test_chat_post_returns_sse(auth_client: AsyncClient):
    """POST /api/chat should return 200 with SSE content type."""
    resp = await auth_client.post("/api/chat", json={
        "message": "hello",
        "pillar": "Platform",
        "environment": "np",
        "conversation_history": [],
        "attachments": [],
    })
    # SSE responses may be 200 with text/event-stream
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chat_sessions_list_returns_list(auth_client: AsyncClient):
    resp = await auth_client.get("/api/chat/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_chat_session_save_returns_session_id(auth_client: AsyncClient, db_pool):
    resp = await auth_client.post("/api/chat/sessions", json={
        "session_id": "test-contract-session",
        "messages": [{"role": "user", "content": "test"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    # Cleanup
    await db_pool.execute("DELETE FROM chat_sessions WHERE id = 'test-contract-session'")


@pytest.mark.asyncio
async def test_chat_session_get_returns_detail(auth_client: AsyncClient, db_pool):
    # Create first
    await auth_client.post("/api/chat/sessions", json={
        "session_id": "test-contract-get",
        "messages": [{"role": "user", "content": "hello"}],
    })
    resp = await auth_client.get("/api/chat/sessions/test-contract-get")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    # Cleanup
    await db_pool.execute("DELETE FROM chat_sessions WHERE id = 'test-contract-get'")


@pytest.mark.asyncio
async def test_chat_session_get_nonexistent_returns_error(auth_client: AsyncClient):
    resp = await auth_client.get("/api/chat/sessions/nonexistent-session-id-12345")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_chat_session_delete_returns_deleted(auth_client: AsyncClient, db_pool):
    await auth_client.post("/api/chat/sessions", json={
        "session_id": "test-contract-delete",
        "messages": [{"role": "user", "content": "bye"}],
    })
    resp = await auth_client.delete("/api/chat/sessions/test-contract-delete")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deleted"


# =============================================================================
# SQL
# =============================================================================

@pytest.mark.asyncio
async def test_sql_execute_shape(auth_client: AsyncClient):
    """SQL execute should return columns, rows, row_count (or error for mock mode)."""
    resp = await auth_client.post("/api/sql/execute", json={
        "sql": "SELECT 1 AS num",
        "environment": "np",
    })
    # Mock mode returns a result or an error
    data = resp.json()
    if resp.status_code == 200:
        assert "columns" in data or "error" in data
    else:
        # 400 = query rejected, which is acceptable
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sql_execute_rejects_non_select(auth_client: AsyncClient):
    resp = await auth_client.post("/api/sql/execute", json={
        "sql": "DROP TABLE users",
        "environment": "np",
    })
    assert resp.status_code == 400


# =============================================================================
# Glossary
# =============================================================================

@pytest.mark.asyncio
async def test_glossary_search_returns_results_array(client: AsyncClient):
    resp = await client.get("/api/glossary/search?q=test")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_glossary_all_returns_results(client: AsyncClient):
    resp = await client.get("/api/glossary/all")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "count" in data


# =============================================================================
# Glossary Review
# =============================================================================

@pytest.mark.asyncio
async def test_glossary_review_entries_returns_list(auth_client: AsyncClient):
    resp = await auth_client.get("/api/glossary-review/entries")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_glossary_review_stats_shape(client: AsyncClient):
    resp = await client.get("/api/glossary-review/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "by_state" in data
    assert "by_source" in data
    assert "total" in data


# =============================================================================
# Activity
# =============================================================================

@pytest.mark.asyncio
async def test_activity_heatmap_returns_days(client: AsyncClient):
    resp = await client.get("/api/activity/heatmap")
    assert resp.status_code == 200
    data = resp.json()
    assert "days" in data
    assert isinstance(data["days"], list)
    assert "total_interactions" in data
    assert "streak_days" in data


@pytest.mark.asyncio
async def test_activity_cost_explorer_shape(client: AsyncClient):
    resp = await client.get("/api/activity/cost-explorer")
    assert resp.status_code == 200
    data = resp.json()
    assert "timeline" in data
    assert "by_model" in data
    assert "by_user" in data
    assert "totals" in data


@pytest.mark.asyncio
async def test_activity_stats_shape(client: AsyncClient):
    resp = await client.get("/api/activity/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_queries" in data
    assert "total_cost" in data


# =============================================================================
# Notifications
# =============================================================================

@pytest.mark.asyncio
async def test_notifications_list_returns_list(auth_client: AsyncClient):
    resp = await auth_client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_notifications_unread_count_shape(auth_client: AsyncClient):
    resp = await auth_client.get("/api/notifications/unread-count")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert isinstance(data["count"], int)


@pytest.mark.asyncio
async def test_notifications_mark_read_returns_status(auth_client: AsyncClient, db_pool):
    """Mark-read on a non-existent ID should still return 200 with status."""
    resp = await auth_client.post("/api/notifications/99999/read")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "read"


@pytest.mark.asyncio
async def test_notifications_unread_count_without_auth(client: AsyncClient):
    """Unread count without auth returns count: 0 (graceful degradation)."""
    resp = await client.get("/api/notifications/unread-count")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


# =============================================================================
# Feedback / Tasks
# =============================================================================

@pytest.mark.asyncio
async def test_feedback_list_returns_list(auth_client: AsyncClient):
    resp = await auth_client.get("/api/feedback")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_feedback_create_returns_id(auth_client: AsyncClient, db_pool):
    resp = await auth_client.post("/api/feedback", json={
        "title": "Test task from contract test",
        "description": "Automated test",
        "category": "general",
        "priority": "low",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["status"] == "created"
    # Cleanup
    await db_pool.execute("DELETE FROM feedback_tickets WHERE id = $1", data["id"])


@pytest.mark.asyncio
async def test_feedback_stats_summary_shape(auth_client: AsyncClient):
    resp = await auth_client.get("/api/feedback/stats/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "by_status" in data
    assert "by_type" in data
    assert "total" in data


# =============================================================================
# Catalog Engine
# =============================================================================

@pytest.mark.asyncio
async def test_catalog_engine_status_shape(client: AsyncClient):
    resp = await client.get("/api/catalog-engine/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data


@pytest.mark.asyncio
async def test_catalog_engine_kb_explore_shape(client: AsyncClient):
    resp = await client.get("/api/catalog-engine/kb/explore")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "transforms" in data
    assert "profiles" in data
    assert "domo_metrics" in data
    assert "glossary" in data


@pytest.mark.asyncio
async def test_catalog_engine_kb_history_returns_list(client: AsyncClient):
    resp = await client.get("/api/catalog-engine/kb/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# =============================================================================
# Settings / Personas
# =============================================================================

@pytest.mark.asyncio
async def test_settings_personas_returns_list(client: AsyncClient):
    resp = await client.get("/api/settings/personas")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "id" in data[0]
    assert "name" in data[0]


@pytest.mark.asyncio
async def test_settings_get_returns_persona_and_prompt(auth_client: AsyncClient):
    resp = await auth_client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "persona" in data
    assert "system_prompt" in data


@pytest.mark.asyncio
async def test_settings_save_requires_session_id(auth_client: AsyncClient):
    resp = await auth_client.put("/api/settings", json={"persona": "analyst"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_settings_save_returns_saved(auth_client: AsyncClient, db_pool, auth_token):
    from api.users import _sessions
    user_id = str(_sessions[auth_token]["user_id"])
    resp = await auth_client.put("/api/settings", json={
        "session_id": "test-session",
        "persona": "analyst",
        "system_prompt": "test prompt",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "saved"
    # Cleanup
    await db_pool.execute("DELETE FROM user_settings WHERE user_id = $1", user_id)


# =============================================================================
# Agent Prompts
# =============================================================================

@pytest.mark.asyncio
async def test_agent_prompts_list_returns_agents(client: AsyncClient):
    resp = await client.get("/api/agent-prompts")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for agent in data:
        assert "id" in agent
        assert "label" in agent
        assert "prompt" in agent
        assert "char_count" in agent


# =============================================================================
# Auth / DOMO
# =============================================================================

@pytest.mark.asyncio
async def test_auth_domo_status_returns_configured(client: AsyncClient):
    resp = await client.get("/api/auth/domo/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert isinstance(data["configured"], bool)


# =============================================================================
# Catalog search
# =============================================================================

@pytest.mark.asyncio
async def test_catalog_search_returns_results(client: AsyncClient):
    resp = await client.get("/api/catalog/search?q=users")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "count" in data


# =============================================================================
# Connectivity
# =============================================================================

@pytest.mark.asyncio
async def test_connectivity_returns_shape(client: AsyncClient):
    resp = await client.get("/api/connectivity")
    assert resp.status_code == 200
    data = resp.json()
    assert "sso" in data
    assert "redshift" in data
    assert "git" in data


# =============================================================================
# Redshift test endpoint (mock mode)
# =============================================================================

@pytest.mark.asyncio
async def test_redshift_test_mock_mode(client: AsyncClient):
    resp = await client.get("/api/redshift/test/np")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


# =============================================================================
# Chat extract-file (multipart form)
# =============================================================================

@pytest.mark.asyncio
async def test_chat_extract_file_shape(client: AsyncClient):
    """POST /api/chat/extract-file returns filename, content, size."""
    from httpx import AsyncClient as _  # already imported
    resp = await client.post(
        "/api/chat/extract-file",
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "filename" in data
    assert "content" in data
    assert "size" in data


@pytest.mark.asyncio
async def test_chat_extract_file_no_file_returns_400(client: AsyncClient):
    resp = await client.post("/api/chat/extract-file")
    # Should return 400 or 422 for missing file
    assert resp.status_code in (400, 422)


# =============================================================================
# Usage summary
# =============================================================================

@pytest.mark.asyncio
async def test_usage_summary_returns_dict(client: AsyncClient):
    resp = await client.get("/api/usage/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# =============================================================================
# History (requires auth)
# =============================================================================

@pytest.mark.asyncio
async def test_history_queries_returns_list(auth_client: AsyncClient):
    resp = await auth_client.get("/api/history/queries")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# =============================================================================
# Lineage
# =============================================================================

@pytest.mark.asyncio
async def test_lineage_full_returns_dict(client: AsyncClient):
    resp = await client.get("/api/catalog/lineage")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
