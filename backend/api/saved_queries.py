"""
Saved/Shared Queries API — team query library.

Users save SQL queries with name, description, and tags.
Queries are shared across the team (visible to all authenticated users).
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("genie.saved_queries")
router = APIRouter()


async def _ensure_table(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS saved_queries (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            sql TEXT NOT NULL,
            environment TEXT DEFAULT 'np',
            tags TEXT[] DEFAULT '{}',
            pillar TEXT,
            created_by TEXT NOT NULL,
            created_by_name TEXT,
            is_public BOOLEAN DEFAULT true,
            use_count INTEGER DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _require_auth(request: Request) -> dict:
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


class SaveQueryRequest(BaseModel):
    name: str
    sql: str
    description: str = ""
    environment: str = "np"
    tags: list[str] = []
    pillar: Optional[str] = None


class UpdateQueryRequest(BaseModel):
    name: Optional[str] = None
    sql: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    pillar: Optional[str] = None


@router.get("")
async def list_queries(request: Request, tag: Optional[str] = None, search: Optional[str] = None):
    """List saved queries (all public + user's private)."""
    user = _require_auth(request)
    pool = request.app.state.db_pool
    await _ensure_table(pool)

    user_id = str(user.get("user_id", ""))

    if search:
        rows = await pool.fetch("""
            SELECT id, name, description, sql, environment, tags, pillar,
                   created_by, created_by_name, is_public, use_count, last_used_at, created_at
            FROM saved_queries
            WHERE (is_public = true OR created_by = $1)
              AND (LOWER(name) LIKE $2 OR LOWER(description) LIKE $2 OR LOWER(sql) LIKE $2)
            ORDER BY use_count DESC, updated_at DESC
        """, user_id, f"%{search.lower()}%")
    elif tag:
        rows = await pool.fetch("""
            SELECT id, name, description, sql, environment, tags, pillar,
                   created_by, created_by_name, is_public, use_count, last_used_at, created_at
            FROM saved_queries
            WHERE (is_public = true OR created_by = $1)
              AND $2 = ANY(tags)
            ORDER BY use_count DESC, updated_at DESC
        """, user_id, tag)
    else:
        rows = await pool.fetch("""
            SELECT id, name, description, sql, environment, tags, pillar,
                   created_by, created_by_name, is_public, use_count, last_used_at, created_at
            FROM saved_queries
            WHERE is_public = true OR created_by = $1
            ORDER BY use_count DESC, updated_at DESC
        """, user_id)

    return [dict(r) for r in rows]


@router.post("")
async def save_query(body: SaveQueryRequest, request: Request):
    """Save a new query to the shared library."""
    user = _require_auth(request)
    pool = request.app.state.db_pool
    await _ensure_table(pool)

    user_id = str(user.get("user_id", ""))
    user_name = user.get("email", user_id)

    row = await pool.fetchrow("""
        INSERT INTO saved_queries (name, description, sql, environment, tags, pillar, created_by, created_by_name)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
    """, body.name, body.description, body.sql, body.environment,
        body.tags, body.pillar, user_id, user_name)

    return {"status": "saved", "id": row["id"]}


@router.put("/{query_id}")
async def update_query(query_id: int, body: UpdateQueryRequest, request: Request):
    """Update a saved query (owner only)."""
    user = _require_auth(request)
    pool = request.app.state.db_pool
    user_id = str(user.get("user_id", ""))

    # Check ownership
    row = await pool.fetchrow("SELECT created_by FROM saved_queries WHERE id = $1", query_id)
    if not row:
        raise HTTPException(404, "Query not found")
    if row["created_by"] != user_id:
        raise HTTPException(403, "Only the owner can edit this query")

    updates = ["updated_at = NOW()"]
    params = [query_id]
    idx = 2

    for field in ("name", "sql", "description", "pillar"):
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1
    if body.tags is not None:
        updates.append(f"tags = ${idx}")
        params.append(body.tags)
        idx += 1

    await pool.execute(f"UPDATE saved_queries SET {', '.join(updates)} WHERE id = $1", *params)
    return {"status": "updated"}


@router.delete("/{query_id}")
async def delete_query(query_id: int, request: Request):
    """Delete a saved query (owner only)."""
    user = _require_auth(request)
    pool = request.app.state.db_pool
    user_id = str(user.get("user_id", ""))

    row = await pool.fetchrow("SELECT created_by FROM saved_queries WHERE id = $1", query_id)
    if not row:
        raise HTTPException(404, "Query not found")
    if row["created_by"] != user_id:
        raise HTTPException(403, "Only the owner can delete this query")

    await pool.execute("DELETE FROM saved_queries WHERE id = $1", query_id)
    return {"status": "deleted"}


@router.post("/{query_id}/use")
async def record_use(query_id: int, request: Request):
    """Record that a query was used (increment counter)."""
    _require_auth(request)
    pool = request.app.state.db_pool
    await pool.execute("""
        UPDATE saved_queries SET use_count = use_count + 1, last_used_at = NOW() WHERE id = $1
    """, query_id)
    return {"status": "recorded"}


@router.get("/tags")
async def list_tags(request: Request):
    """List all unique tags across saved queries."""
    _require_auth(request)
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    rows = await pool.fetch("""
        SELECT DISTINCT unnest(tags) as tag FROM saved_queries WHERE is_public = true ORDER BY tag
    """)
    return [r["tag"] for r in rows]
