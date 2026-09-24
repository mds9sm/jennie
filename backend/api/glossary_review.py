"""
Glossary Review API — PR-style workflow for business definitions.

Workflow: draft → in_review → changes_requested → approved → merged (live)
Sources: 'agent' (auto-generated from KB refresh) or 'user' (manually created)
Comments: threaded conversation per entry (like PR review comments)
History: full audit trail of who changed what
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

logger = logging.getLogger("genie.glossary_review")
router = APIRouter()

VALID_STATES = ("draft", "in_review", "changes_requested", "approved", "merged", "rejected")


async def find_existing_entry(pool, term: str, term_key: str = None) -> dict | None:
    """Check if a glossary entry already exists for this term (exact or fuzzy).
    Returns the existing entry dict, or None if no match found.
    Checks: exact term_key, exact term (case-insensitive), and fuzzy term match.
    """
    # 1. Exact term_key match
    if term_key:
        row = await pool.fetchrow(
            "SELECT id, term, term_key, definition, workflow_state, created_by_type FROM glossary_entries WHERE term_key = $1",
            term_key,
        )
        if row:
            return dict(row)

    # 2. Case-insensitive term match
    row = await pool.fetchrow(
        "SELECT id, term, term_key, definition, workflow_state, created_by_type FROM glossary_entries WHERE LOWER(term) = LOWER($1)",
        term,
    )
    if row:
        return dict(row)

    # 3. Fuzzy match — normalized key (underscores, no spaces)
    normalized = term.lower().replace(" ", "_").replace("-", "_")
    row = await pool.fetchrow(
        "SELECT id, term, term_key, definition, workflow_state, created_by_type FROM glossary_entries WHERE term_key = $1",
        normalized,
    )
    if row:
        return dict(row)

    return None


async def find_related_entries(pool, term: str, exclude_id: int = None, limit: int = 10) -> list[dict]:
    """Find glossary entries related to this term.
    Uses: word overlap in term names, shared source tables, and term_key prefix matching.
    Returns list of related entries with relevance reason.
    """
    related = []
    seen_ids = {exclude_id} if exclude_id else set()

    # Extract keywords from term (split on spaces, underscores, strip short words)
    keywords = [w.lower() for w in term.replace("_", " ").replace("-", " ").split() if len(w) > 2]

    if not keywords:
        return []

    # 1. Keyword overlap in term names — most useful
    for kw in keywords:
        rows = await pool.fetch(
            """SELECT id, term, term_key, definition, workflow_state, created_by_type
               FROM glossary_entries
               WHERE (LOWER(term) LIKE $1 OR term_key LIKE $1)
               ORDER BY workflow_state, term
               LIMIT 20""",
            f"%{kw}%",
        )
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                related.append({
                    "id": r["id"],
                    "term": r["term"],
                    "term_key": r["term_key"],
                    "definition": (r["definition"] or "")[:150],
                    "state": r["workflow_state"],
                    "source": r["created_by_type"],
                    "match_reason": f"shares keyword '{kw}'",
                })

    # 2. Same source tables — entries that reference the same data
    # (only check if we have the entry's source tables)
    if exclude_id:
        source_row = await pool.fetchrow(
            "SELECT source_tables FROM glossary_entries WHERE id = $1", exclude_id
        )
        if source_row and source_row["source_tables"]:
            try:
                tables = json.loads(source_row["source_tables"]) if isinstance(source_row["source_tables"], str) else source_row["source_tables"]
                if isinstance(tables, list) and tables:
                    for tbl in tables[:3]:
                        rows = await pool.fetch(
                            """SELECT id, term, term_key, definition, workflow_state, created_by_type
                               FROM glossary_entries
                               WHERE source_tables::text LIKE $1 AND id != $2
                               LIMIT 5""",
                            f"%{tbl}%", exclude_id,
                        )
                        for r in rows:
                            if r["id"] not in seen_ids:
                                seen_ids.add(r["id"])
                                related.append({
                                    "id": r["id"],
                                    "term": r["term"],
                                    "term_key": r["term_key"],
                                    "definition": (r["definition"] or "")[:150],
                                    "state": r["workflow_state"],
                                    "source": r["created_by_type"],
                                    "match_reason": f"shares source table '{tbl}'",
                                })
            except Exception:
                pass

    return related[:limit]


def _row_to_dict(r) -> dict:
    d = dict(r)
    for key in ("source_tables", "dimensions", "sources"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                d[key] = []
        elif d.get(key) is None:
            d[key] = []
    return d


# ---------------------------------------------------------------------------
# Entries CRUD
# ---------------------------------------------------------------------------

def _require_auth(request: Request):
    from api.users import get_current_user
    if not get_current_user(request):
        from fastapi import HTTPException
        raise HTTPException(401, "Authentication required")


@router.get("/entries")
async def list_entries(request: Request, status: Optional[str] = None, created_by_type: Optional[str] = None):
    """List glossary entries with optional filters."""
    _require_auth(request)
    pool = request.app.state.db_pool
    where = []
    params = []
    idx = 1
    if status:
        where.append(f"workflow_state = ${idx}")
        params.append(status)
        idx += 1
    if created_by_type:
        where.append(f"created_by_type = ${idx}")
        params.append(created_by_type)
        idx += 1

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = await pool.fetch(
        f"SELECT * FROM glossary_entries {where_clause} ORDER BY workflow_state, term",
        *params,
    )
    return [_row_to_dict(r) for r in rows]


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: int, request: Request):
    """Get a single entry with its comments and history."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("SELECT * FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404, "Entry not found")

    entry = _row_to_dict(row)

    # Fetch comments
    comments = await pool.fetch(
        "SELECT * FROM glossary_comments WHERE entry_id = $1 ORDER BY created_at",
        entry_id,
    )
    entry["comments"] = [dict(c) for c in comments]

    # Fetch history
    history = await pool.fetch(
        "SELECT * FROM glossary_history WHERE entry_id = $1 ORDER BY created_at",
        entry_id,
    )
    entry["history"] = [dict(h) for h in history]

    # Find related entries (for reviewer context — "these other definitions exist")
    related = await find_related_entries(pool, entry.get("term", ""), exclude_id=entry_id)
    if related:
        entry["related_entries"] = related

    return entry


class CreateEntryRequest(BaseModel):
    term_key: str
    term: str
    definition: str
    formula: Optional[str] = None
    source_tables: list[str] = []
    dimensions: list[str] = []
    created_by: str = "anonymous"


@router.post("/entries")
async def create_entry(body: CreateEntryRequest, request: Request):
    """Create a new glossary entry (user-created, starts as draft).
    If a matching entry already exists, returns the existing entry info
    so the user can decide to update it instead.
    """
    pool = request.app.state.db_pool

    # Check for existing entry (exact + fuzzy)
    existing = await find_existing_entry(pool, body.term, body.term_key)
    if existing:
        # Also find other related entries for context
        related = await find_related_entries(pool, body.term, exclude_id=existing["id"])
        return {
            "status": "exists",
            "existing_id": existing["id"],
            "existing_term": existing["term"],
            "existing_definition": existing["definition"][:200] if existing["definition"] else "",
            "existing_state": existing["workflow_state"],
            "existing_source": existing["created_by_type"],
            "related_entries": related,
            "message": f"Entry '{existing['term']}' already exists (state: {existing['workflow_state']}). You can update the existing entry or create a context-specific variant (e.g., '{body.term} (pillar)' or '{body.term} (subscription)').",
        }

    row = await pool.fetchrow("""
        INSERT INTO glossary_entries (
            term_key, term, definition, formula, source_tables, dimensions,
            status, workflow_state, auto_generated, created_by, created_by_type
        ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, 'draft', 'draft', false, $7, 'user')
        ON CONFLICT (term_key) DO NOTHING
        RETURNING id
    """,
        body.term_key, body.term, body.definition, body.formula,
        json.dumps(body.source_tables), json.dumps(body.dimensions),
        body.created_by,
    )
    if not row:
        raise HTTPException(409, f"Term '{body.term_key}' already exists")

    # Log history
    await pool.execute("""
        INSERT INTO glossary_history (entry_id, action, actor, new_value)
        VALUES ($1, 'created', $2, $3)
    """, row["id"], body.created_by, body.definition[:200])

    return {"status": "created", "id": row["id"]}


class UpdateEntryRequest(BaseModel):
    definition: Optional[str] = None
    formula: Optional[str] = None
    source_tables: Optional[list[str]] = None
    dimensions: Optional[list[str]] = None
    updated_by: str = "anonymous"


@router.put("/entries/{entry_id}")
async def update_entry(entry_id: int, body: UpdateEntryRequest, request: Request):
    """Update an entry's content (only if draft or changes_requested)."""
    pool = request.app.state.db_pool

    row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404, "Entry not found")
    if row["workflow_state"] in ("merged",):
        raise HTTPException(400, "Cannot edit a merged entry. Create a new version instead.")

    updates = ["updated_at = NOW()", "auto_generated = false"]
    params = [entry_id]
    idx = 2
    changes = []

    if body.definition is not None:
        updates.append(f"definition = ${idx}")
        params.append(body.definition)
        idx += 1
        changes.append("definition")
    if body.formula is not None:
        updates.append(f"formula = ${idx}")
        params.append(body.formula)
        idx += 1
        changes.append("formula")
    if body.source_tables is not None:
        updates.append(f"source_tables = ${idx}::jsonb")
        params.append(json.dumps(body.source_tables))
        idx += 1
    if body.dimensions is not None:
        updates.append(f"dimensions = ${idx}::jsonb")
        params.append(json.dumps(body.dimensions))
        idx += 1

    await pool.execute(
        f"UPDATE glossary_entries SET {', '.join(updates)} WHERE id = $1",
        *params,
    )

    await pool.execute("""
        INSERT INTO glossary_history (entry_id, action, actor, new_value)
        VALUES ($1, 'updated', $2, $3)
    """, entry_id, body.updated_by, f"Updated: {', '.join(changes)}")

    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Workflow Actions (PR-style)
# ---------------------------------------------------------------------------

class WorkflowAction(BaseModel):
    actor: str = "anonymous"
    comment: Optional[str] = None


@router.post("/entries/{entry_id}/submit-for-review")
async def submit_for_review(entry_id: int, body: WorkflowAction, request: Request):
    """Submit a draft for review (draft → in_review)."""
    pool = request.app.state.db_pool
    await _transition(pool, entry_id, "draft", "in_review", body.actor, body.comment)
    return {"status": "submitted"}


@router.post("/entries/{entry_id}/approve")
async def approve_entry(entry_id: int, body: WorkflowAction, request: Request):
    """Approve an entry (in_review → approved)."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404)
    if row["workflow_state"] not in ("in_review", "draft", "changes_requested"):
        raise HTTPException(400, f"Cannot approve from state '{row['workflow_state']}'")

    await pool.execute("""
        UPDATE glossary_entries SET workflow_state = 'approved', status = 'approved',
            reviewed_by = $2, reviewed_at = NOW(), updated_at = NOW()
        WHERE id = $1
    """, entry_id, body.actor)

    if body.comment:
        await _add_comment(pool, entry_id, body.actor, body.comment, "approve")

    await _log_history(pool, entry_id, "status_changed", body.actor, row["workflow_state"], "approved")

    # Auto-update linked ticket status
    await _auto_update_linked_ticket(pool, entry_id)

    return {"status": "approved"}


@router.post("/entries/{entry_id}/request-changes")
async def request_changes(entry_id: int, body: WorkflowAction, request: Request):
    """Request changes (in_review → changes_requested). Comment required."""
    pool = request.app.state.db_pool
    if not body.comment:
        raise HTTPException(400, "Comment is required when requesting changes")

    row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404)

    await pool.execute("""
        UPDATE glossary_entries SET workflow_state = 'changes_requested', status = 'needs_review',
            updated_at = NOW()
        WHERE id = $1
    """, entry_id)

    await _add_comment(pool, entry_id, body.actor, body.comment, "request_changes")
    await _log_history(pool, entry_id, "status_changed", body.actor, row["workflow_state"], "changes_requested")
    return {"status": "changes_requested"}


@router.post("/entries/{entry_id}/merge")
async def merge_entry(entry_id: int, body: WorkflowAction, request: Request):
    """Merge an approved entry into the live glossary (approved → merged)."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404)
    if row["workflow_state"] != "approved":
        raise HTTPException(400, "Only approved entries can be merged")

    await pool.execute("""
        UPDATE glossary_entries SET workflow_state = 'merged', status = 'approved', updated_at = NOW()
        WHERE id = $1
    """, entry_id)

    if body.comment:
        await _add_comment(pool, entry_id, body.actor, body.comment, "merge")

    await _log_history(pool, entry_id, "merged", body.actor, "approved", "merged")

    # Notify the original contributor that their entry is now live
    entry = await pool.fetchrow(
        "SELECT term, created_by, created_by_type FROM glossary_entries WHERE id = $1", entry_id
    )
    if entry and entry["created_by"]:
        try:
            from api.notifications import create_notification
            # Find user ID from email/name
            contributor = await pool.fetchrow(
                "SELECT id FROM users WHERE email = $1 OR name = $1", entry["created_by"]
            )
            if contributor:
                await create_notification(
                    pool, str(contributor["id"]), "glossary_merged",
                    f"Your glossary entry '{entry['term']}' is now live!",
                    f"Merged by {body.actor}. Your contribution is now part of the official glossary.",
                    f"/glossary?entry={entry_id}",
                )
        except Exception:
            pass

    # Auto-update linked ticket status
    await _auto_update_linked_ticket(pool, entry_id)

    return {"status": "merged"}


@router.post("/entries/{entry_id}/reject")
async def reject_entry(entry_id: int, body: WorkflowAction, request: Request):
    """Reject an entry."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404)

    await pool.execute("""
        UPDATE glossary_entries SET workflow_state = 'rejected', status = 'rejected', updated_at = NOW()
        WHERE id = $1
    """, entry_id)

    if body.comment:
        await _add_comment(pool, entry_id, body.actor, body.comment, "reject")

    await _log_history(pool, entry_id, "status_changed", body.actor, row["workflow_state"], "rejected")

    # Notify contributor of rejection with reason
    entry = await pool.fetchrow(
        "SELECT term, created_by FROM glossary_entries WHERE id = $1", entry_id
    )
    if entry and entry["created_by"]:
        try:
            from api.notifications import create_notification
            contributor = await pool.fetchrow(
                "SELECT id FROM users WHERE email = $1 OR name = $1", entry["created_by"]
            )
            if contributor:
                reason = body.comment or "No reason provided"
                await create_notification(
                    pool, str(contributor["id"]), "glossary_rejected",
                    f"Glossary entry '{entry['term']}' was not approved",
                    f"Rejected by {body.actor}. Reason: {reason[:200]}",
                    f"/glossary?entry={entry_id}",
                )
        except Exception:
            pass

    # Auto-update linked ticket status
    await _auto_update_linked_ticket(pool, entry_id)

    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class CommentRequest(BaseModel):
    author: str
    comment: str


@router.post("/entries/{entry_id}/comments")
async def add_comment(entry_id: int, body: CommentRequest, request: Request):
    """Add a comment to an entry's conversation thread."""
    pool = request.app.state.db_pool
    await _add_comment(pool, entry_id, body.author, body.comment, "comment")
    return {"status": "added"}


@router.get("/entries/{entry_id}/comments")
async def get_comments(entry_id: int, request: Request):
    """Get all comments for an entry."""
    pool = request.app.state.db_pool
    rows = await pool.fetch(
        "SELECT * FROM glossary_comments WHERE entry_id = $1 ORDER BY created_at",
        entry_id,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

class AssignRequest(BaseModel):
    entry_ids: list[int]
    assigned_to: str


@router.post("/entries/assign")
async def assign_entries(body: AssignRequest, request: Request):
    """Assign entries to a reviewer."""
    pool = request.app.state.db_pool
    await pool.execute("""
        UPDATE glossary_entries
        SET assigned_to = $1, assigned_at = NOW(), updated_at = NOW()
        WHERE id = ANY($2)
    """, body.assigned_to, body.entry_ids)

    for eid in body.entry_ids:
        await _log_history(pool, eid, "assigned", body.assigned_to, None, body.assigned_to)

    # Notify assigned reviewer
    from api.notifications import create_notification
    assigned_user = await pool.fetchrow("SELECT id FROM users WHERE name = $1 OR email = $1", body.assigned_to)
    if assigned_user:
        entry_id_param = str(body.entry_ids[0]) if len(body.entry_ids) == 1 else ""
        await create_notification(pool, str(assigned_user["id"]), "glossary_assigned",
            f"Glossary review assigned: {len(body.entry_ids)} entries", "",
            f"/glossary?entry={entry_id_param}" if entry_id_param else "/glossary?status=draft")

    return {"status": "assigned", "count": len(body.entry_ids)}


# ---------------------------------------------------------------------------
# Stats & Reviewers
# ---------------------------------------------------------------------------

@router.get("/entries/{entry_id}/related")
async def get_related_entries(entry_id: int, request: Request):
    """Get entries related to this one — for reviewer context during approval."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("SELECT term FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404, "Entry not found")
    related = await find_related_entries(pool, row["term"], exclude_id=entry_id)
    return related


@router.get("/stats")
async def glossary_stats(request: Request):
    """Entry counts by workflow state and source type."""
    pool = request.app.state.db_pool
    state_rows = await pool.fetch(
        "SELECT workflow_state, COUNT(*) as count FROM glossary_entries GROUP BY workflow_state"
    )
    type_rows = await pool.fetch(
        "SELECT created_by_type, COUNT(*) as count FROM glossary_entries GROUP BY created_by_type"
    )
    states = {r["workflow_state"]: r["count"] for r in state_rows}
    types = {r["created_by_type"]: r["count"] for r in type_rows}
    return {
        "total": sum(states.values()),
        "by_state": states,
        "by_source": types,
    }


@router.get("/ticket-progress/{ticket_id}")
async def ticket_progress(ticket_id: int, request: Request):
    """Check review progress for a glossary ticket."""
    pool = request.app.state.db_pool
    ticket = await pool.fetchrow("SELECT chat_messages FROM feedback_tickets WHERE id = $1", ticket_id)
    if not ticket or not ticket["chat_messages"]:
        return {"error": "No linked entries"}

    data = json.loads(ticket["chat_messages"]) if isinstance(ticket["chat_messages"], str) else ticket["chat_messages"]
    entry_ids = data.get("linked_entry_ids", [])
    if not entry_ids:
        return {"total": 0, "reviewed": 0, "pending": 0}

    rows = await pool.fetch(
        "SELECT id, workflow_state FROM glossary_entries WHERE id = ANY($1)", entry_ids
    )
    states = [r["workflow_state"] for r in rows]
    reviewed = sum(1 for s in states if s in ("approved", "merged", "rejected"))
    return {
        "total": len(entry_ids),
        "reviewed": reviewed,
        "pending": len(entry_ids) - reviewed,
        "by_state": {s: states.count(s) for s in set(states)},
    }


@router.get("/reviewers")
async def list_reviewers(request: Request):
    """List all users who have been assigned or reviewed entries."""
    pool = request.app.state.db_pool
    rows = await pool.fetch("""
        SELECT DISTINCT name FROM (
            SELECT assigned_to AS name FROM glossary_entries WHERE assigned_to IS NOT NULL
            UNION
            SELECT reviewed_by AS name FROM glossary_entries WHERE reviewed_by IS NOT NULL
            UNION
            SELECT DISTINCT author AS name FROM glossary_comments
        ) sub WHERE name IS NOT NULL
    """)
    return [r["name"] for r in rows]


# ---------------------------------------------------------------------------
# Merge & Bulk Actions
# ---------------------------------------------------------------------------

class MergeRequest(BaseModel):
    primary_id: int
    merge_ids: list[int]
    actor: str = "anonymous"


@router.post("/entries/merge")
async def merge_entries(body: MergeRequest, request: Request):
    """Merge redundant entries into one. Combines source_tables, dimensions, keeps best definition."""
    pool = request.app.state.db_pool

    primary = await pool.fetchrow("SELECT * FROM glossary_entries WHERE id = $1", body.primary_id)
    if not primary:
        raise HTTPException(404, "Primary entry not found")

    merge_rows = await pool.fetch(
        "SELECT * FROM glossary_entries WHERE id = ANY($1)", body.merge_ids
    )
    if not merge_rows:
        raise HTTPException(404, "No entries to merge")

    # Collect combined source_tables and dimensions
    all_sources = set()
    all_dims = set()
    merged_terms = []

    p_sources = primary["source_tables"]
    if isinstance(p_sources, str):
        p_sources = json.loads(p_sources)
    for s in (p_sources or []):
        all_sources.add(s)

    p_dims = primary["dimensions"]
    if isinstance(p_dims, str):
        p_dims = json.loads(p_dims)
    for d in (p_dims or []):
        all_dims.add(d)

    for row in merge_rows:
        merged_terms.append(row["term"])
        src = row["source_tables"]
        if isinstance(src, str):
            src = json.loads(src)
        for s in (src or []):
            all_sources.add(s)
        dims = row["dimensions"]
        if isinstance(dims, str):
            dims = json.loads(dims)
        for d in (dims or []):
            all_dims.add(d)
        # Keep formula if primary doesn't have one
        if not primary["formula"] and row["formula"]:
            await pool.execute(
                "UPDATE glossary_entries SET formula = $1 WHERE id = $2",
                row["formula"], body.primary_id,
            )

    # Update primary with combined data
    await pool.execute("""
        UPDATE glossary_entries
        SET source_tables = $1::jsonb, dimensions = $2::jsonb, updated_at = NOW()
        WHERE id = $3
    """, json.dumps(sorted(all_sources)), json.dumps(sorted(all_dims)), body.primary_id)

    # Reject merged entries
    for row in merge_rows:
        await pool.execute("""
            UPDATE glossary_entries SET workflow_state = 'rejected', updated_at = NOW()
            WHERE id = $1
        """, row["id"])
        await _log_history(pool, row["id"], "merged_into", body.actor, None,
                           f"Merged into #{body.primary_id} ({primary['term']})")

    await _log_history(pool, body.primary_id, "merge", body.actor, None,
                       f"Merged {len(merge_rows)} entries: {', '.join(merged_terms)}")
    await _add_comment(pool, body.primary_id, body.actor,
                       f"Merged {len(merge_rows)} redundant entries: {', '.join(merged_terms)}", "merge")

    return {"status": "merged", "primary_id": body.primary_id, "merged_count": len(merge_rows)}


class BulkActionRequest(BaseModel):
    entry_ids: list[int]
    action: str  # approve, reject, delete, submit-for-review
    actor: str = "anonymous"
    comment: str | None = None


@router.post("/entries/bulk-action")
async def bulk_action(body: BulkActionRequest, request: Request):
    """Apply a workflow action to multiple entries at once."""
    pool = request.app.state.db_pool

    if body.action not in ("approve", "reject", "delete", "submit-for-review"):
        raise HTTPException(400, f"Invalid bulk action: {body.action}")

    count = 0
    errors = []
    for eid in body.entry_ids:
        try:
            if body.action == "delete":
                await pool.execute("DELETE FROM glossary_entries WHERE id = $1", eid)
                count += 1
            elif body.action == "submit-for-review":
                await _transition(pool, eid, "draft", "in_review", body.actor, body.comment)
                count += 1
            elif body.action == "approve":
                row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", eid)
                if row and row["workflow_state"] in ("in_review", "draft", "changes_requested"):
                    await pool.execute("""
                        UPDATE glossary_entries
                        SET workflow_state = 'approved', reviewed_by = $1, updated_at = NOW()
                        WHERE id = $2
                    """, body.actor, eid)
                    await _log_history(pool, eid, "approved", body.actor, None, "approved")
                    count += 1
            elif body.action == "reject":
                row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", eid)
                if row and row["workflow_state"] not in ("merged", "rejected"):
                    await pool.execute("""
                        UPDATE glossary_entries
                        SET workflow_state = 'rejected', updated_at = NOW()
                        WHERE id = $2
                    """, body.actor, eid)
                    await _log_history(pool, eid, "rejected", body.actor, None, body.comment or "bulk rejected")
                    count += 1
        except Exception as e:
            errors.append(f"#{eid}: {str(e)[:80]}")

    return {"status": "done", "processed": count, "errors": errors}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_comment(pool, entry_id: int, author: str, comment: str, action: str):
    await pool.execute("""
        INSERT INTO glossary_comments (entry_id, author, comment, action)
        VALUES ($1, $2, $3, $4)
    """, entry_id, author, comment, action)


# ---------------------------------------------------------------------------
# Document Upload → AI Extract → Draft Glossary Entries
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".pdf", ".docx"}


def _extract_text_from_file(content: bytes, filename: str) -> str:
    """Extract text from uploaded file."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in (".txt", ".md", ".csv", ".yaml", ".yml"):
        return content.decode("utf-8", errors="replace")
    elif ext == ".json":
        return content.decode("utf-8", errors="replace")
    elif ext == ".pdf":
        try:
            import io
            # Try PyPDF2 first, then pdfplumber
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(content))
                return "\n".join(page.extract_text() or "" for page in reader.pages[:30])
            except ImportError:
                pass
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages[:30])
            except ImportError:
                pass
            return content.decode("utf-8", errors="replace")[:10000]
        except Exception:
            return content.decode("utf-8", errors="replace")[:10000]
    elif ext == ".docx":
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return content.decode("utf-8", errors="replace")[:10000]
    else:
        return content.decode("utf-8", errors="replace")[:10000]


@router.post("/upload-document")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    uploaded_by: str = Form("anonymous"),
):
    """
    Upload a document → AI extracts glossary terms → creates draft entries + review ticket.

    Supported: .txt, .md, .csv, .json, .yaml, .pdf, .docx
    AI summarizes the document and extracts business terms, definitions, and metrics.
    Each extracted term becomes a draft glossary entry with source='document'.
    """
    pool = request.app.state.db_pool

    # Validate file
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    content = await file.read()
    if len(content) > 5_000_000:  # 5MB limit
        raise HTTPException(400, "File too large (max 5MB)")

    text = _extract_text_from_file(content, file.filename or "unknown.txt")
    if not text.strip():
        raise HTTPException(400, "Could not extract text from file")

    # Truncate for AI context
    text_for_ai = text[:8000]

    # AI extraction
    from engine.claude_client import ClaudeClient
    client = ClaudeClient()

    system_prompt = """You are a data glossary expert in the organization.
Extract business terms, definitions, and metrics from the document.

Output as JSON array:
[
  {
    "term": "Human-readable term name",
    "term_key": "snake_case_key",
    "definition": "Clear definition of what this means in the organization",
    "formula": "SQL formula if applicable, or empty string",
    "source_tables": ["schema.table_name"],
    "category": "metric|dimension|business_rule|process|other"
  }
]

Rules:
- Extract ALL business terms, metrics, KPIs, definitions found in the document
- Be specific to the organization's domain (the product surface, devices, subscriptions, content, pillars)
- If the document mentions SQL or table references, include them
- term_key should be lowercase with underscores
- Output ONLY valid JSON array, nothing else"""

    try:
        result = await client.quick_completion(
            f"{system_prompt}\n\n---\nDocument: {file.filename}\n\n{text_for_ai}",
            max_tokens=4096,
            use_main_model=True,  # Complex extraction needs Opus, not Haiku
        )

        # Parse AI response — try to extract JSON from response
        result = result.strip()
        # Sometimes AI wraps JSON in markdown code block
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()

        entries = json.loads(result)
        if not isinstance(entries, list):
            entries = [entries]
    except json.JSONDecodeError as e:
        # Try to salvage truncated JSON — find last complete object
        logger.warning("AI returned truncated JSON for %s (%s), attempting salvage...", file.filename, e)
        try:
            # Find the last complete }, then close the array
            last_brace = result.rfind("}")
            if last_brace > 0:
                salvaged = result[:last_brace + 1] + "]"
                entries = json.loads(salvaged)
                if not isinstance(entries, list):
                    entries = [entries]
                logger.info("Salvaged %d entries from truncated JSON", len(entries))
            else:
                raise ValueError("No complete JSON objects found")
        except Exception:
            logger.warning("Could not salvage JSON for %s. Response: %s", file.filename, result[:500])
            raise HTTPException(500, f"AI could not extract structured terms from this document. Try a simpler text file or copy-paste the key content.")
    except Exception as e:
        logger.warning("AI extraction failed for %s: %s", file.filename, e)
        raise HTTPException(500, f"AI extraction failed: {e}")

    # Create draft glossary entries (with dedup check)
    created_ids = []
    updated_ids = []
    skipped = 0
    for entry in entries:
        term_key = entry.get("term_key", "").strip()
        term = entry.get("term", "").strip()
        definition = entry.get("definition", "").strip()

        if not term_key or not term or not definition:
            continue

        sources = json.dumps([{
            "type": "document",
            "label": f"Document: {file.filename}",
            "detail": f"Uploaded by {uploaded_by}",
        }])

        try:
            # Check for existing entry
            existing = await find_existing_entry(pool, term, term_key)

            if existing:
                if existing["workflow_state"] in ("merged", "approved"):
                    # Existing approved entry — flag for review with new source info
                    await pool.execute("""
                        UPDATE glossary_entries
                        SET status = 'needs_review', expert_notes = COALESCE(expert_notes, '') || $2,
                            updated_at = NOW()
                        WHERE id = $1
                    """, existing["id"],
                        f"\n[Document update from {file.filename}]: {definition[:200]}")
                    updated_ids.append(existing["id"])

                    await pool.execute("""
                        INSERT INTO glossary_history (entry_id, action, actor, new_value)
                        VALUES ($1, 'document_update', $2, $3)
                    """, existing["id"], uploaded_by, f"New info from {file.filename}")
                else:
                    # Draft/rejected — skip, don't pile on
                    skipped += 1
                continue

            row = await pool.fetchrow("""
                INSERT INTO glossary_entries (
                    term_key, term, definition, formula, source_tables, dimensions,
                    status, workflow_state, auto_generated, sources,
                    created_by, created_by_type
                ) VALUES ($1, $2, $3, $4, $5::jsonb, '[]'::jsonb,
                          'draft', 'draft', true, $6::jsonb, $7, 'document')
                ON CONFLICT (term_key) DO NOTHING
                RETURNING id
            """,
                term_key, term, definition,
                entry.get("formula", ""),
                json.dumps(entry.get("source_tables", [])),
                sources, uploaded_by,
            )
            if row:
                created_ids.append(row["id"])
                await pool.execute("""
                    INSERT INTO glossary_history (entry_id, action, actor, new_value)
                    VALUES ($1, 'created_from_document', $2, $3)
                """, row["id"], uploaded_by, f"Extracted from {file.filename}")
            else:
                skipped += 1
        except Exception as e:
            logger.warning("Failed to create entry for %s: %s", term_key, e)

    # Create review ticket
    if created_ids:
        try:
            admin_row = await pool.fetchrow(
                "SELECT email FROM users WHERE role = 'admin' AND is_active = true ORDER BY id LIMIT 1"
            )
            assigned = admin_row["email"] if admin_row else None

            description_text = (
                f"AI extracted {len(created_ids)} glossary terms from uploaded document '{file.filename}'.\n\n"
                f"Uploaded by: {uploaded_by}\n"
                f"Terms need review in Glossary page.\n\n"
                f"Original document text (first 500 chars):\n{text[:500]}"
            )

            await pool.execute("""
                INSERT INTO feedback_tickets (title, description, status, priority, category, created_by, assigned_to, chat_messages)
                VALUES ($1, $2, 'open', 'medium', 'glossary', $3, $4, $5::jsonb)
            """,
                f"Document upload: {len(created_ids)} terms from {file.filename}",
                description_text,
                uploaded_by, assigned,
                json.dumps({"linked_entry_ids": created_ids}),
            )
        except Exception as e:
            logger.warning("Failed to create review ticket: %s", e)

    logger.info("Document upload: %s → %d extracted, %d new, %d updated, %d skipped",
                file.filename, len(entries), len(created_ids), len(updated_ids), skipped)

    return {
        "status": "success",
        "filename": file.filename,
        "extracted_count": len(entries),
        "created_count": len(created_ids),
        "updated_count": len(updated_ids),
        "created_ids": created_ids,
        "updated_ids": updated_ids,
        "skipped_count": skipped,
    }


async def _auto_update_linked_ticket(pool, entry_id: int):
    """Auto-update feedback ticket status based on glossary entry progress."""
    try:
        # Find ticket that links to this entry
        tickets = await pool.fetch("""
            SELECT id, chat_messages FROM feedback_tickets
            WHERE category = 'glossary' AND status != 'closed'
        """)
        for ticket in tickets:
            data = json.loads(ticket["chat_messages"]) if isinstance(ticket["chat_messages"], str) else (ticket["chat_messages"] or {})
            entry_ids = data.get("linked_entry_ids", [])
            if entry_id not in entry_ids:
                continue

            # Check progress
            rows = await pool.fetch(
                "SELECT workflow_state FROM glossary_entries WHERE id = ANY($1)", entry_ids
            )
            states = [r["workflow_state"] for r in rows]
            reviewed = sum(1 for s in states if s in ("approved", "merged", "rejected"))

            if reviewed == len(entry_ids):
                # All done -> resolve
                await pool.execute("UPDATE feedback_tickets SET status = 'resolved', updated_at = NOW() WHERE id = $1", ticket["id"])
            elif reviewed > 0:
                # Some done -> in progress
                await pool.execute("UPDATE feedback_tickets SET status = 'in_progress', updated_at = NOW() WHERE id = $1", ticket["id"])
    except Exception as e:
        logger.warning("Auto-update ticket failed: %s", e)


async def _log_history(pool, entry_id: int, action: str, actor: str, old_value: str = None, new_value: str = None):
    await pool.execute("""
        INSERT INTO glossary_history (entry_id, action, actor, old_value, new_value)
        VALUES ($1, $2, $3, $4, $5)
    """, entry_id, action, actor, old_value, new_value)


async def _transition(pool, entry_id: int, from_state: str, to_state: str, actor: str, comment: str = None):
    row = await pool.fetchrow("SELECT workflow_state FROM glossary_entries WHERE id = $1", entry_id)
    if not row:
        raise HTTPException(404, "Entry not found")
    if row["workflow_state"] != from_state:
        raise HTTPException(400, f"Expected state '{from_state}', got '{row['workflow_state']}'")

    await pool.execute("""
        UPDATE glossary_entries SET workflow_state = $2, updated_at = NOW()
        WHERE id = $1
    """, entry_id, to_state)

    if comment:
        await _add_comment(pool, entry_id, actor, comment, to_state)

    await _log_history(pool, entry_id, "status_changed", actor, from_state, to_state)
