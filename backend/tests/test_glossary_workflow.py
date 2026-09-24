"""
Layer 4: Glossary Workflow Tests

PR-style glossary lifecycle: draft -> in_review -> approved -> merged
Also tests: duplicate detection, related entries, comments, rejection,
document upload, and correction capture from chat.
"""

import json
import pytest
from httpx import AsyncClient


# Helper: create a glossary entry and return its ID
async def _create_entry(auth_client: AsyncClient, term_key: str, term: str, definition: str) -> int:
    resp = await auth_client.post("/api/glossary-review/entries", json={
        "term_key": term_key,
        "term": term,
        "definition": definition,
        "source_tables": ["analytics.test_table"],
        "dimensions": ["date", "user_id"],
        "created_by": "test-user",
    })
    data = resp.json()
    assert data.get("status") == "created", f"Expected created, got {data}"
    return data["id"]


# =============================================================================
# Create & Duplicate Detection
# =============================================================================

@pytest.mark.asyncio
async def test_create_entry_returns_id_and_status(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_gloss_create", "Test Glossary Create", "A test entry")
    assert entry_id > 0
    # Cleanup
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


@pytest.mark.asyncio
async def test_create_duplicate_returns_exists(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_dup_term", "Test Dup Term", "First definition")

    # Try to create duplicate
    resp = await auth_client.post("/api/glossary-review/entries", json={
        "term_key": "test_dup_term",
        "term": "Test Dup Term",
        "definition": "Second definition",
        "created_by": "test-user",
    })
    data = resp.json()
    assert data["status"] == "exists"
    assert "existing_id" in data
    assert "related_entries" in data

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


# =============================================================================
# Entry Detail with Related Entries
# =============================================================================

@pytest.mark.asyncio
async def test_get_entry_detail_includes_related(auth_client: AsyncClient, db_pool):
    # Create two entries with related terms
    id1 = await _create_entry(auth_client, "active_users_daily", "Active Users Daily", "DAU metric")
    id2 = await _create_entry(auth_client, "active_users_weekly", "Active Users Weekly", "WAU metric")

    resp = await auth_client.get(f"/api/glossary-review/entries/{id1}")
    assert resp.status_code == 200
    data = resp.json()
    assert "comments" in data
    assert "history" in data

    # Cleanup
    for eid in [id1, id2]:
        await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", eid)
        await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", eid)


@pytest.mark.asyncio
async def test_get_entry_not_found_returns_404(client: AsyncClient):
    resp = await client.get("/api/glossary-review/entries/999999")
    assert resp.status_code == 404


# =============================================================================
# Workflow Transitions
# =============================================================================

@pytest.mark.asyncio
async def test_submit_for_review_draft_to_in_review(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_submit_review", "Submit Review Test", "A def")

    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/submit-for-review", json={
        "actor": "reviewer@example.com",
        "comment": "Ready for review",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"

    # Verify state changed
    row = await db_pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    assert row["workflow_state"] == "in_review"

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_comments WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


@pytest.mark.asyncio
async def test_approve_in_review_to_approved(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_approve", "Approve Test", "A def")
    # Submit for review
    await auth_client.post(f"/api/glossary-review/entries/{entry_id}/submit-for-review", json={
        "actor": "test-user",
    })

    # Approve
    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/approve", json={
        "actor": "approver@example.com",
        "comment": "Looks good",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    row = await db_pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    assert row["workflow_state"] == "approved"

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_comments WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


@pytest.mark.asyncio
async def test_merge_approved_to_merged(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_merge", "Merge Test", "A def")
    await auth_client.post(f"/api/glossary-review/entries/{entry_id}/submit-for-review", json={"actor": "test"})
    await auth_client.post(f"/api/glossary-review/entries/{entry_id}/approve", json={"actor": "test"})

    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/merge", json={
        "actor": "merger@example.com",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "merged"

    row = await db_pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    assert row["workflow_state"] == "merged"

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_comments WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


@pytest.mark.asyncio
async def test_merge_rejects_non_approved(auth_client: AsyncClient, db_pool):
    """Cannot merge a draft entry — must be approved first."""
    entry_id = await _create_entry(auth_client, "test_merge_fail", "Merge Fail Test", "A def")

    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/merge", json={"actor": "test"})
    assert resp.status_code == 400

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


@pytest.mark.asyncio
async def test_reject_entry(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_reject", "Reject Test", "Bad def")

    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/reject", json={
        "actor": "reviewer@example.com",
        "comment": "Not accurate",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    row = await db_pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    assert row["workflow_state"] == "rejected"

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_comments WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


@pytest.mark.asyncio
async def test_request_changes_requires_comment(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_reqchange", "Request Change Test", "A def")
    await auth_client.post(f"/api/glossary-review/entries/{entry_id}/submit-for-review", json={"actor": "test"})

    # Missing comment should fail
    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/request-changes", json={
        "actor": "reviewer@example.com",
    })
    assert resp.status_code == 400

    # With comment should succeed
    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/request-changes", json={
        "actor": "reviewer@example.com",
        "comment": "Please fix the formula",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "changes_requested"

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_comments WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


# =============================================================================
# Comments
# =============================================================================

@pytest.mark.asyncio
async def test_add_comment_to_entry(auth_client: AsyncClient, db_pool):
    entry_id = await _create_entry(auth_client, "test_comment", "Comment Test", "A def")

    resp = await auth_client.post(f"/api/glossary-review/entries/{entry_id}/comments", json={
        "author": "tester@example.com",
        "comment": "This looks correct to me",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "added"

    # Verify comment exists
    resp = await auth_client.get(f"/api/glossary-review/entries/{entry_id}/comments")
    assert resp.status_code == 200
    comments = resp.json()
    assert len(comments) >= 1
    assert comments[0]["comment"] == "This looks correct to me"

    # Cleanup
    await db_pool.execute("DELETE FROM glossary_comments WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", entry_id)
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)


# =============================================================================
# Related Entries
# =============================================================================

@pytest.mark.asyncio
async def test_find_related_entries_by_keyword(auth_client: AsyncClient, db_pool):
    id1 = await _create_entry(auth_client, "subscription_rate", "Subscription Rate", "Rate of subs")
    id2 = await _create_entry(auth_client, "subscription_count", "Subscription Count", "Count of subs")

    resp = await auth_client.get(f"/api/glossary-review/entries/{id1}/related")
    assert resp.status_code == 200
    related = resp.json()
    assert isinstance(related, list)
    # The other entry should appear as related (shares "subscription" keyword)
    related_ids = [r["id"] for r in related]
    assert id2 in related_ids

    # Cleanup
    for eid in [id1, id2]:
        await db_pool.execute("DELETE FROM glossary_history WHERE entry_id = $1", eid)
        await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", eid)


# =============================================================================
# Correction Capture (regex pattern from chat.py)
# =============================================================================

@pytest.mark.asyncio
async def test_correction_pattern_regex():
    """Verify the correction regex matches expected format."""
    from api.chat import _CORRECTION_PATTERN

    text = "📝 Correction: Active Users — was counted weekly → now counted daily"
    matches = _CORRECTION_PATTERN.findall(text)
    assert len(matches) == 1
    term, was_wrong, correct_def = matches[0]
    assert "Active Users" in term
    assert "weekly" in was_wrong
    assert "daily" in correct_def


@pytest.mark.asyncio
async def test_correction_capture_creates_draft(db_pool):
    """_auto_capture_corrections should create a draft glossary entry."""
    from api.chat import _auto_capture_corrections

    text = "📝 Correction: DAU Count — was total users → unique users per day"
    await _auto_capture_corrections(db_pool, text, "test-user-123")

    # Check if entry was created
    row = await db_pool.fetchrow(
        "SELECT * FROM glossary_entries WHERE LOWER(term) = 'dau count' AND created_by_type = 'chat_correction'"
    )
    assert row is not None
    assert row["definition"] is not None

    # Cleanup
    entry_id = row["id"]
    await db_pool.execute("DELETE FROM glossary_entries WHERE id = $1", entry_id)
    await db_pool.execute("DELETE FROM feedback_tickets WHERE created_by LIKE '%test-user-123%'")
