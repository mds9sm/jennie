"""Scheduled Reports API — recurring AI-generated reports from chat questions."""
import json
import logging
import secrets
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger("genie.scheduled_reports")
router = APIRouter()


async def _ensure_table(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_reports (
            id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
            chat_question TEXT NOT NULL, cron_expression TEXT DEFAULT '0 7 * * *',
            pillar TEXT, environment TEXT DEFAULT 'np', enabled BOOLEAN DEFAULT true,
            last_run_at TIMESTAMPTZ, last_output TEXT, last_status TEXT DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS report_executions (
            id BIGSERIAL PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES scheduled_reports(id) ON DELETE CASCADE,
            status TEXT NOT NULL, output TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _get_user_id(request: Request) -> str:
    from api.users import get_current_user
    user = get_current_user(request)
    if user and user.get("user_id"):
        return str(user["user_id"])
    # Fallback: check if token header exists and try to extract
    return ""


def _get_user_id_or_all(request: Request) -> tuple[str, bool]:
    """Returns (user_id, is_admin). Admins can see all reports."""
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        return "", False
    uid = str(user.get("user_id", ""))
    is_admin = user.get("role", "") == "admin"
    return uid, is_admin


class CreateReportRequest(BaseModel):
    title: str
    chat_question: str
    context: str = ""  # additional instructions/context for the AI
    cron_expression: str = "0 7 * * *"
    pillar: Optional[str] = None
    environment: str = "np"


class UpdateReportRequest(BaseModel):
    title: Optional[str] = None
    chat_question: Optional[str] = None
    context: Optional[str] = None
    cron_expression: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_reports(request: Request):
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    user_id, is_admin = _get_user_id_or_all(request)
    if not user_id:
        # No auth — return all reports (backwards compat)
        rows = await pool.fetch("""
            SELECT id, title, chat_question, context, cron_expression, pillar, environment,
                   enabled, last_run_at, last_status, created_at, user_id
            FROM scheduled_reports ORDER BY enabled DESC, created_at DESC
        """)
    else:
        rows = await pool.fetch("""
            SELECT id, title, chat_question, context, cron_expression, pillar, environment,
                   enabled, last_run_at, last_status, created_at, user_id
            FROM scheduled_reports
            WHERE user_id = $1
            ORDER BY enabled DESC, created_at DESC
        """, user_id)
    return [dict(r) for r in rows]


@router.post("")
async def create_report(body: CreateReportRequest, request: Request):
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(401, "Authentication required")
    row = await pool.fetchrow("""
        INSERT INTO scheduled_reports (user_id, title, chat_question, context, cron_expression, pillar, environment)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
    """, user_id, body.title, body.chat_question, body.context, body.cron_expression, body.pillar, body.environment)
    return {"id": row["id"], "status": "created"}


@router.put("/{report_id}")
async def update_report(report_id: int, body: UpdateReportRequest, request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    updates = ["updated_at = NOW()"]
    params = [report_id, user_id]
    idx = 3
    for field in ("title", "chat_question", "context", "cron_expression", "enabled"):
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1
    await pool.execute(
        f"UPDATE scheduled_reports SET {', '.join(updates)} WHERE id = $1 AND user_id = $2",
        *params
    )
    return {"status": "updated"}


@router.delete("/{report_id}")
async def delete_report(report_id: int, request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    await pool.execute("DELETE FROM scheduled_reports WHERE id = $1 AND user_id = $2", report_id, user_id)
    return {"status": "deleted"}


@router.get("/{report_id}/output")
async def get_report_output(report_id: int, request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    row = await pool.fetchrow(
        "SELECT title, last_output, last_run_at, last_status FROM scheduled_reports WHERE id = $1 AND user_id = $2",
        report_id, user_id
    )
    if not row:
        raise HTTPException(404, "Report not found")
    return dict(row)


@router.get("/{report_id}/history")
async def get_report_history(report_id: int, request: Request):
    """Get last 7 execution history for a report."""
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    # Verify ownership
    owner = await pool.fetchval("SELECT user_id FROM scheduled_reports WHERE id = $1", report_id)
    if owner != user_id:
        raise HTTPException(404, "Report not found")
    await _ensure_table(pool)
    rows = await pool.fetch("""
        SELECT id, status, output, created_at FROM report_executions
        WHERE report_id = $1 ORDER BY created_at DESC LIMIT 7
    """, report_id)
    return [dict(r) for r in rows]


@router.post("/{report_id}/run-now")
async def run_report_now(report_id: int, request: Request):
    """Manually trigger a scheduled report."""
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    row = await pool.fetchrow(
        "SELECT * FROM scheduled_reports WHERE id = $1 AND user_id = $2", report_id, user_id
    )
    if not row:
        raise HTTPException(404, "Report not found")
    # Run asynchronously
    import asyncio
    asyncio.create_task(_execute_report(pool, dict(row)))
    return {"status": "running"}


async def _execute_report(pool, report: dict):
    """Execute a scheduled report — run the chat question through the AI."""
    report_id = report["id"]
    user_id = report["user_id"]
    try:
        await pool.execute(
            "UPDATE scheduled_reports SET last_status = 'running', updated_at = NOW() WHERE id = $1",
            report_id
        )

        # Load user settings for persona/system prompt
        from api.settings import DEFAULT_SYSTEM_PROMPT
        user_settings_row = await pool.fetchrow(
            "SELECT * FROM user_settings WHERE user_id = $1", user_id
        )
        user_settings = dict(user_settings_row) if user_settings_row else None

        # Build system prompt
        from engine.context import build_system_prompt
        from main import app
        kb = app.state.kb if hasattr(app.state, "kb") else None

        system_prompt = build_system_prompt(
            kb=kb,
            pillar=report.get("pillar"),
            environment=report.get("environment", "np"),
            capability="chat",
            user_settings=user_settings,
        )

        # Run through agent
        from engine.claude_client import ClaudeClient
        client = ClaudeClient()
        # Build the question with optional context
        question = report["chat_question"]
        context = report.get("context", "")
        if context:
            question = f"{question}\n\nAdditional context: {context}"
        messages = [{"role": "user", "content": question}]

        output_parts = []
        async for event in client.chat_stream(system_prompt, messages, kb):
            if event["type"] == "text":
                output_parts.append(event["content"])

        output = "".join(output_parts)

        # Save output
        await pool.execute("""
            UPDATE scheduled_reports SET last_output = $2, last_status = 'success',
                last_run_at = NOW(), updated_at = NOW()
            WHERE id = $1
        """, report_id, output)

        # Save to execution history (keep last 7)
        await pool.execute("""
            INSERT INTO report_executions (report_id, status, output) VALUES ($1, 'success', $2)
        """, report_id, output)
        await pool.execute("""
            DELETE FROM report_executions WHERE report_id = $1 AND id NOT IN (
                SELECT id FROM report_executions WHERE report_id = $1 ORDER BY created_at DESC LIMIT 7
            )
        """, report_id)

        # Create notification
        from api.notifications import create_notification
        await create_notification(
            pool, user_id, "scheduled_report",
            f"Report ready: {report['title']}",
            f"Your scheduled report has been generated.",
            f"/reports"
        )

        logger.info("Scheduled report #%d completed: %s", report_id, report["title"])

    except Exception as e:
        logger.error("Scheduled report #%d failed: %s", report_id, e)
        error_msg = f"Error: {str(e)[:500]}"
        await pool.execute("""
            UPDATE scheduled_reports SET last_status = 'error',
                last_output = $2, last_run_at = NOW(), updated_at = NOW()
            WHERE id = $1
        """, report_id, error_msg)
        await pool.execute("""
            INSERT INTO report_executions (report_id, status, output) VALUES ($1, 'error', $2)
        """, report_id, error_msg)

        from api.notifications import create_notification
        await create_notification(
            pool, user_id, "scheduled_report",
            f"Report failed: {report['title']}",
            f"Error: {str(e)[:200]}",
            f"/reports"
        )
