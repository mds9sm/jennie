"""
Task Board API — kanban board for data team task management.

Evolved from feedback tickets. Supports task types: investigation, data_issue,
dag_failure, ai_quality, kb_gap, glossary, request, general.

Backwards-compatible: existing feedback_tickets table gets new columns via ALTER.
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("genie.tasks")
router = APIRouter()

VALID_TASK_TYPES = {
    "investigation", "data_issue", "dag_failure", "ai_quality",
    "kb_gap", "glossary", "request", "general",
}

VALID_PRIORITIES = {"low", "medium", "high", "critical"}

VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}


async def _ensure_table(pool):
    """Create feedback_tickets table if missing, then add new columns."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS feedback_tickets (
            id              BIGSERIAL PRIMARY KEY,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'open',
            priority        TEXT NOT NULL DEFAULT 'medium',
            category        TEXT NOT NULL DEFAULT 'chat',
            created_by      TEXT NOT NULL,
            assigned_to     TEXT,
            chat_session_id TEXT,
            chat_messages   JSONB,
            resolution      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Add new columns for task management (idempotent ALTER)
    for stmt in [
        "ALTER TABLE feedback_tickets ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'general'",
        "ALTER TABLE feedback_tickets ADD COLUMN IF NOT EXISTS due_date DATE",
        "ALTER TABLE feedback_tickets ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'",
    ]:
        try:
            await pool.execute(stmt)
        except Exception as e:
            # Column might already exist on older postgres without IF NOT EXISTS support
            logger.debug("ALTER TABLE skipped: %s", e)


def _get_user_email(request: Request) -> str:
    from api.users import get_current_user
    user = get_current_user(request)
    return user.get("email", "unknown") if user else "unknown"


async def _process_mentions(pool, text: str, ticket_id: int, author: str):
    """Find @mentions in text and notify mentioned users."""
    mentions = re.findall(r'@([\w.]+@example\.com|[\w.]+)', text)
    for mention in mentions:
        # Try to find user by email or name
        user = await pool.fetchrow(
            "SELECT id, email FROM users WHERE email = $1 OR name ILIKE $2 OR email ILIKE $3",
            mention if '@' in mention else f"{mention}@example.com",
            f"%{mention}%",
            f"%{mention}%",
        )
        if user:
            from api.notifications import create_notification
            await create_notification(
                pool, str(user["id"]), "mention",
                f"You were mentioned in task #{ticket_id}",
                f"By {author}",
                "/tasks",
            )


class CreateTicketRequest(BaseModel):
    title: str
    description: str = ""
    category: str = "general"
    priority: str = "medium"  # low, medium, high, critical
    task_type: str = "general"  # investigation, data_issue, dag_failure, ai_quality, kb_gap, glossary, request, general
    chat_session_id: Optional[str] = None
    assigned_to: Optional[str] = None
    due_date: Optional[date] = None  # ISO date string parsed by Pydantic
    tags: list[str] = []  # free-form tags like "pillar:onboard", "dag:cuts_session"


class UpdateTicketRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    resolution: Optional[str] = None
    task_type: Optional[str] = None
    due_date: Optional[date] = None
    tags: Optional[list[str]] = None


@router.get("")
async def list_tickets(
    request: Request,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    task_type: Optional[str] = None,
    tag: Optional[str] = None,
):
    """List tasks. Filterable by status, assignee, task_type, and tag."""
    from api.users import get_current_user
    if not get_current_user(request):
        raise HTTPException(401, "Authentication required")
    pool = request.app.state.db_pool
    await _ensure_table(pool)

    conditions = []
    params = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if assigned_to:
        conditions.append(f"assigned_to = ${idx}")
        params.append(assigned_to)
        idx += 1
    if task_type:
        conditions.append(f"task_type = ${idx}")
        params.append(task_type)
        idx += 1
    if tag:
        conditions.append(f"tags @> ${idx}::jsonb")
        params.append(json.dumps([tag]))
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await pool.fetch(
        f"""
        SELECT id, title, description, status, priority, category, task_type,
               created_by, assigned_to, chat_session_id, resolution,
               due_date, tags, created_at, updated_at
        FROM feedback_tickets
        {where}
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
            END,
            CASE status
                WHEN 'open' THEN 1
                WHEN 'in_progress' THEN 2
                WHEN 'resolved' THEN 3
                WHEN 'closed' THEN 4
            END,
            created_at DESC
        """,
        *params,
    )
    results = []
    for r in rows:
        d = dict(r)
        # Ensure tags is always a list
        if isinstance(d.get("tags"), str):
            d["tags"] = json.loads(d["tags"])
        elif d.get("tags") is None:
            d["tags"] = []
        results.append(d)
    return results


@router.post("")
async def create_ticket(body: CreateTicketRequest, request: Request):
    """Create a task. Auto-assigns to admin if no assignee specified."""
    pool = request.app.state.db_pool
    await _ensure_table(pool)

    user_email = _get_user_email(request)

    # Default assignment: first admin user
    assigned = body.assigned_to
    if not assigned:
        admin_row = await pool.fetchrow(
            "SELECT email FROM users WHERE role = 'admin' AND is_active = true ORDER BY id LIMIT 1"
        )
        assigned = admin_row["email"] if admin_row else None

    # Snapshot chat messages if session provided
    chat_messages = None
    if body.chat_session_id:
        session_row = await pool.fetchrow(
            "SELECT messages FROM chat_sessions WHERE id = $1", body.chat_session_id
        )
        if session_row:
            msgs = session_row["messages"]
            if isinstance(msgs, str):
                msgs = json.loads(msgs)
            # Keep last 10 messages for context
            chat_messages = json.dumps(msgs[-10:]) if msgs else None

    tags_json = json.dumps(body.tags) if body.tags else "[]"

    row = await pool.fetchrow("""
        INSERT INTO feedback_tickets (title, description, status, priority, category, task_type,
                                      created_by, assigned_to, chat_session_id, chat_messages,
                                      due_date, tags)
        VALUES ($1, $2, 'open', $3, $4, $5, $6, $7, $8, $9::jsonb,
                $10::date, $11::jsonb)
        RETURNING id
    """,
        body.title, body.description, body.priority, body.category, body.task_type,
        user_email, assigned, body.chat_session_id, chat_messages,
        body.due_date, tags_json,
    )

    logger.info("Task #%d (%s) created by %s, assigned to %s", row["id"], body.task_type, user_email, assigned)

    # Notify assigned user
    if assigned:
        from api.notifications import create_notification
        assigned_user = await pool.fetchrow("SELECT id FROM users WHERE email = $1", assigned)
        if assigned_user:
            await create_notification(pool, str(assigned_user["id"]), "task_assigned",
                f"Task assigned: {body.title}", "", "/tasks")

    # Process @mentions in description
    if body.description:
        await _process_mentions(pool, body.description, row["id"], user_email)

    return {"id": row["id"], "status": "created", "assigned_to": assigned}


@router.post("/from-chat")
async def create_from_chat(request: Request):
    """Create a task from an ongoing chat investigation. Auto-fills from chat context."""
    pool = request.app.state.db_pool
    await _ensure_table(pool)

    body = await request.json()
    user_email = _get_user_email(request)

    title = body.get("title", "Untitled task")
    description = body.get("description", "")
    task_type = body.get("task_type", "general")
    priority = body.get("priority", "medium")
    chat_session_id = body.get("chat_session_id")
    tags = body.get("tags", [])

    # "task" = self-assigned, "support" = assigned to admin
    is_self_task = task_type == "task"

    if is_self_task:
        assigned = user_email  # self-assigned
    else:
        # Assign to first admin for support requests
        admin_row = await pool.fetchrow(
            "SELECT email FROM users WHERE role = 'admin' AND is_active = true ORDER BY id LIMIT 1"
        )
        assigned = admin_row["email"] if admin_row else None

    # Snapshot chat messages
    chat_messages = None
    if chat_session_id:
        session_row = await pool.fetchrow(
            "SELECT messages FROM chat_sessions WHERE id = $1", chat_session_id
        )
        if session_row:
            msgs = session_row["messages"]
            if isinstance(msgs, str):
                msgs = json.loads(msgs)
            chat_messages = json.dumps(msgs[-10:]) if msgs else None

    # Category mapping from task_type
    category_map = {
        "ai_quality": "chat",
        "investigation": "data",
        "data_issue": "data",
        "dag_failure": "pipeline",
        "kb_gap": "kb_gap",
        "glossary": "glossary",
        "request": "other",
        "general": "other",
    }
    category = category_map.get(task_type, "other")
    tags_json = json.dumps(tags) if tags else "[]"

    row = await pool.fetchrow("""
        INSERT INTO feedback_tickets (title, description, status, priority, category, task_type,
                                      created_by, assigned_to, chat_session_id, chat_messages, tags)
        VALUES ($1, $2, 'open', $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb)
        RETURNING id
    """,
        title, description, priority, category, task_type,
        user_email, assigned, chat_session_id, chat_messages, tags_json,
    )

    logger.info("Task #%d (%s) created from chat by %s", row["id"], task_type, user_email)

    # Notify assigned user
    if assigned:
        from api.notifications import create_notification
        assigned_user = await pool.fetchrow("SELECT id FROM users WHERE email = $1", assigned)
        if assigned_user:
            await create_notification(pool, str(assigned_user["id"]), "task_assigned",
                f"Task assigned from chat: {title}", "", "/tasks")

    # Process @mentions in description
    if description:
        await _process_mentions(pool, description, row["id"], user_email)

    return {"id": row["id"], "status": "created", "assigned_to": assigned}


@router.get("/stats/summary")
async def ticket_stats(request: Request):
    """Get task counts by status and type for board."""
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    rows = await pool.fetch("""
        SELECT status, task_type, count(*) as count
        FROM feedback_tickets
        GROUP BY status, task_type
    """)
    # Return both flat status counts and per-type breakdown
    status_counts: dict = {}
    type_counts: dict = {}
    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + r["count"]
        type_counts[r["task_type"]] = type_counts.get(r["task_type"], 0) + r["count"]
    return {"by_status": status_counts, "by_type": type_counts, "total": sum(status_counts.values())}


# Literal paths must precede the /{ticket_id} catch-all so int validation doesn't 422.
@router.get("/tags/distinct")
async def list_distinct_tags(request: Request):
    """Distinct tag strings across all tasks, alphabetical. Used for tag editor autocomplete."""
    from api.users import get_current_user
    if not get_current_user(request):
        raise HTTPException(401, "Authentication required")
    pool = request.app.state.db_pool
    rows = await pool.fetch("""
        SELECT DISTINCT t AS tag
        FROM feedback_tickets, jsonb_array_elements_text(tags) AS t
        WHERE t <> ''
        ORDER BY t
    """)
    return {"tags": [r["tag"] for r in rows]}


@router.get("/{ticket_id}")
async def get_ticket(ticket_id: int, request: Request):
    """Get a single task with full details including chat context."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow("SELECT * FROM feedback_tickets WHERE id = $1", ticket_id)
    if not row:
        raise HTTPException(404, "Task not found")
    result = dict(row)
    if isinstance(result.get("chat_messages"), str):
        result["chat_messages"] = json.loads(result["chat_messages"])
    if isinstance(result.get("tags"), str):
        result["tags"] = json.loads(result["tags"])
    elif result.get("tags") is None:
        result["tags"] = []
    return result


@router.put("/{ticket_id}")
async def update_ticket(ticket_id: int, body: UpdateTicketRequest, request: Request):
    """Update task status, priority, assignee, resolution, type, due_date, or tags."""
    pool = request.app.state.db_pool

    updates = ["updated_at = NOW()"]
    params = [ticket_id]
    idx = 2
    # fields_set lets us distinguish "omitted" from "explicit null" so the
    # client can clear a due_date / assignee by sending null.
    sent = body.model_fields_set

    for field in ("title", "description", "status", "priority", "assigned_to", "resolution", "task_type"):
        if field not in sent:
            continue
        val = getattr(body, field)
        updates.append(f"{field} = ${idx}")
        params.append(val)
        idx += 1

    if "due_date" in sent:
        updates.append(f"due_date = ${idx}::date")
        params.append(body.due_date)
        idx += 1

    if "tags" in sent and body.tags is not None:
        updates.append(f"tags = ${idx}::jsonb")
        params.append(json.dumps(body.tags))
        idx += 1

    if len(updates) == 1:
        raise HTTPException(400, "No fields to update")

    await pool.execute(
        f"UPDATE feedback_tickets SET {', '.join(updates)} WHERE id = $1",
        *params,
    )
    return {"status": "updated"}


@router.delete("/{ticket_id}")
async def delete_ticket(ticket_id: int, request: Request):
    """Delete a task. Admin only."""
    pool = request.app.state.db_pool

    # Check admin
    from api.users import get_current_user
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Only admins can delete tasks")

    result = await pool.execute("DELETE FROM feedback_tickets WHERE id = $1", ticket_id)
    if result == "DELETE 0":
        raise HTTPException(404, "Task not found")
    return {"status": "deleted"}


# --- Comments ----------------------------------------------------------------


class CommentCreate(BaseModel):
    comment: str


@router.get("/{ticket_id}/comments")
async def list_comments(ticket_id: int, request: Request):
    """List comments for a task, oldest first."""
    from api.users import get_current_user
    if not get_current_user(request):
        raise HTTPException(401, "Authentication required")
    pool = request.app.state.db_pool
    rows = await pool.fetch(
        """
        SELECT c.id, c.ticket_id, c.author, c.comment, c.created_at,
               u.name AS author_name
        FROM feedback_comments c
        LEFT JOIN users u ON u.email = c.author
        WHERE c.ticket_id = $1
        ORDER BY c.created_at
        """,
        ticket_id,
    )
    return [
        {
            "id": r["id"],
            "ticket_id": r["ticket_id"],
            "author": r["author"],
            "author_name": r["author_name"],
            "comment": r["comment"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.post("/{ticket_id}/comments")
async def add_comment(ticket_id: int, body: CommentCreate, request: Request):
    """Add a comment to a task. Author = current user's email."""
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")

    text = (body.comment or "").strip()
    if not text:
        raise HTTPException(400, "Comment is empty")

    pool = request.app.state.db_pool

    ticket = await pool.fetchrow("SELECT id FROM feedback_tickets WHERE id = $1", ticket_id)
    if not ticket:
        raise HTTPException(404, "Task not found")

    author = user.get("email", "unknown")
    row = await pool.fetchrow(
        """
        INSERT INTO feedback_comments (ticket_id, author, comment)
        VALUES ($1, $2, $3)
        RETURNING id, ticket_id, author, comment, created_at
        """,
        ticket_id, author, text,
    )

    # Notify @mentioned users
    await _process_mentions(pool, text, ticket_id, author)

    user_row = await pool.fetchrow("SELECT name FROM users WHERE email = $1", author)
    return {
        "id": row["id"],
        "ticket_id": row["ticket_id"],
        "author": row["author"],
        "author_name": user_row["name"] if user_row else None,
        "comment": row["comment"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
