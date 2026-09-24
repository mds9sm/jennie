"""Notifications API — bell icon notifications for users."""
import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("genie.notifications")
router = APIRouter()


async def _ensure_table(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, type TEXT NOT NULL,
            title TEXT NOT NULL, message TEXT, link TEXT, is_read BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _get_user_id(request: Request) -> str:
    from api.users import get_current_user
    user = get_current_user(request)
    return str(user.get("user_id", "")) if user else ""


async def create_notification(pool, user_id: str, type: str, title: str, message: str = "", link: str = ""):
    """Create a notification for a user. Called from other modules."""
    await _ensure_table(pool)
    await pool.execute("""
        INSERT INTO notifications (user_id, type, title, message, link)
        VALUES ($1, $2, $3, $4, $5)
    """, user_id, type, title, message, link)


async def notify_all_admins(pool, type: str, title: str, message: str = "", link: str = ""):
    """Send notification to all active admins."""
    await _ensure_table(pool)
    rows = await pool.fetch("SELECT id FROM users WHERE role = 'admin' AND is_active = true")
    for r in rows:
        await create_notification(pool, str(r["id"]), type, title, message, link)


@router.get("")
async def list_notifications(request: Request, unread_only: bool = False):
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(401, "Authentication required")
    where = "WHERE user_id = $1" + (" AND is_read = false" if unread_only else "")
    rows = await pool.fetch(f"""
        SELECT id, type, title, message, link, is_read, created_at
        FROM notifications {where}
        ORDER BY created_at DESC LIMIT 50
    """, user_id)
    return [dict(r) for r in rows]


@router.get("/unread-count")
async def unread_count(request: Request):
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    user_id = _get_user_id(request)
    if not user_id:
        return {"count": 0}
    count = await pool.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND is_read = false", user_id
    )
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    await pool.execute(
        "UPDATE notifications SET is_read = true WHERE id = $1 AND user_id = $2",
        notification_id, user_id
    )
    return {"status": "read"}


@router.post("/read-all")
async def mark_all_read(request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    await pool.execute(
        "UPDATE notifications SET is_read = true WHERE user_id = $1 AND is_read = false", user_id
    )
    return {"status": "all_read"}
