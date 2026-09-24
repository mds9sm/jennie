"""Weekly Task Digest API — emailable summary of team task activity.

Pulls from feedback_tickets and feedback_comments to produce a structured
digest covering completed, in-progress, newly opened, recently updated, and
overdue tasks, plus discussion activity and active-task counts by owner.

Two endpoints:
- GET /api/task-digest/weekly        -> JSON for in-app preview
- GET /api/task-digest/weekly.html   -> self-contained HTML for download
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger("genie.task_digest")
router = APIRouter()


TASK_COLS = (
    "id, title, description, status, priority, task_type, created_by, "
    "assigned_to, due_date, tags, created_at, updated_at"
)


def _serialize_task(row) -> dict:
    d = dict(row)
    tags = d.get("tags")
    if isinstance(tags, str):
        try:
            d["tags"] = json.loads(tags)
        except json.JSONDecodeError:
            d["tags"] = []
    elif tags is None:
        d["tags"] = []
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    if d.get("due_date"):
        d["due_date"] = d["due_date"].isoformat()
    return d


async def _build_digest(pool, days: int) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    completed = await pool.fetch(
        f"SELECT {TASK_COLS} FROM feedback_tickets "
        "WHERE status IN ('resolved', 'closed') AND updated_at >= $1 "
        "ORDER BY updated_at DESC",
        since,
    )

    in_progress = await pool.fetch(
        f"SELECT {TASK_COLS} FROM feedback_tickets WHERE status = 'in_progress' "
        "ORDER BY CASE priority "
        "WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, updated_at DESC"
    )

    newly_opened = await pool.fetch(
        f"SELECT {TASK_COLS} FROM feedback_tickets "
        "WHERE created_at >= $1 ORDER BY created_at DESC",
        since,
    )

    # Touched in window, but pre-existing and still open — captures status
    # transitions, edits, reassignments without double-counting "newly opened".
    recently_updated = await pool.fetch(
        f"SELECT {TASK_COLS} FROM feedback_tickets "
        "WHERE updated_at >= $1 AND created_at < $1 "
        "AND status NOT IN ('resolved', 'closed') "
        "ORDER BY updated_at DESC",
        since,
    )

    overdue = await pool.fetch(
        f"SELECT {TASK_COLS} FROM feedback_tickets "
        "WHERE due_date IS NOT NULL AND due_date < CURRENT_DATE "
        "AND status NOT IN ('resolved', 'closed') "
        "ORDER BY due_date ASC"
    )

    comments = await pool.fetch(
        """
        SELECT c.id, c.ticket_id, c.author, c.comment, c.created_at,
               t.title AS task_title, t.status AS task_status,
               t.priority AS task_priority
        FROM feedback_comments c
        JOIN feedback_tickets t ON t.id = c.ticket_id
        WHERE c.created_at >= $1
        ORDER BY c.created_at DESC
        LIMIT 50
        """,
        since,
    )

    by_status_rows = await pool.fetch(
        "SELECT status, COUNT(*) AS n FROM feedback_tickets GROUP BY status"
    )
    by_priority_rows = await pool.fetch(
        "SELECT priority, COUNT(*) AS n FROM feedback_tickets "
        "WHERE status NOT IN ('resolved', 'closed') GROUP BY priority"
    )
    by_type_rows = await pool.fetch(
        "SELECT task_type, COUNT(*) AS n FROM feedback_tickets "
        "WHERE status NOT IN ('resolved', 'closed') GROUP BY task_type"
    )
    top_assignees_rows = await pool.fetch(
        """
        SELECT assigned_to, COUNT(*) AS n
        FROM feedback_tickets
        WHERE assigned_to IS NOT NULL
          AND status IN ('open', 'in_progress')
        GROUP BY assigned_to
        ORDER BY n DESC
        LIMIT 10
        """
    )

    return {
        "period_days": days,
        "period_start": since.isoformat(),
        "period_end": now.isoformat(),
        "generated_at": now.isoformat(),
        "summary": {
            "completed_count": len(completed),
            "in_progress_count": len(in_progress),
            "newly_opened_count": len(newly_opened),
            "recently_updated_count": len(recently_updated),
            "overdue_count": len(overdue),
            "comments_count": len(comments),
            "by_status": {r["status"]: r["n"] for r in by_status_rows},
            "by_priority": {r["priority"]: r["n"] for r in by_priority_rows},
            "by_type": {r["task_type"]: r["n"] for r in by_type_rows},
            "top_assignees": [
                {"assignee": r["assigned_to"], "count": r["n"]}
                for r in top_assignees_rows
            ],
        },
        "completed": [_serialize_task(r) for r in completed],
        "in_progress": [_serialize_task(r) for r in in_progress],
        "newly_opened": [_serialize_task(r) for r in newly_opened],
        "recently_updated": [_serialize_task(r) for r in recently_updated],
        "overdue": [_serialize_task(r) for r in overdue],
        "comments": [
            {
                "id": c["id"],
                "ticket_id": c["ticket_id"],
                "task_title": c["task_title"],
                "task_status": c["task_status"],
                "task_priority": c["task_priority"],
                "author": c["author"],
                "comment": c["comment"],
                "created_at": c["created_at"].isoformat() if c["created_at"] else None,
            }
            for c in comments
        ],
    }


@router.get("/weekly")
async def weekly_digest(request: Request, days: int = 7):
    from api.users import get_current_user
    from api.feedback import _ensure_table
    if not get_current_user(request):
        raise HTTPException(401, "Authentication required")
    if days < 1 or days > 90:
        raise HTTPException(400, "days must be between 1 and 90")
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    return await _build_digest(pool, days)


@router.get("/weekly.html", response_class=HTMLResponse)
async def weekly_digest_html(request: Request, days: int = 7):
    from api.users import get_current_user
    from api.feedback import _ensure_table
    if not get_current_user(request):
        raise HTTPException(401, "Authentication required")
    if days < 1 or days > 90:
        raise HTTPException(400, "days must be between 1 and 90")
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    digest = await _build_digest(pool, days)
    html = _render_html(digest)
    filename = f"task-digest-{datetime.now().strftime('%Y-%m-%d')}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- HTML rendering (email-friendly: tables + inline styles) ---------------

PRIORITY_COLOR = {
    "critical": "#dc2626",
    "high": "#ea580c",
    "medium": "#ca8a04",
    "low": "#2563eb",
}

STATUS_COLOR = {
    "open": "#dc2626",
    "in_progress": "#ca8a04",
    "resolved": "#16a34a",
    "closed": "#6b7280",
}


def _badge(text: str, bg: str, fg: str = "#ffffff") -> str:
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
        f'background:{bg};color:{fg};font-size:11px;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.3px;">{escape(text)}</span>'
    )


def _task_row(t: dict) -> str:
    prio = t.get("priority") or "medium"
    status = t.get("status") or "open"
    ttype = t.get("task_type") or "general"
    assignee = t.get("assigned_to") or "Unassigned"
    due = t.get("due_date") or ""
    title = escape(t.get("title") or "")
    tid = t.get("id")
    parts = [
        f'<strong style="color:#111827;">#{tid}</strong> &nbsp;'
        f'<span style="color:#111827;">{title}</span>',
        _badge(prio, PRIORITY_COLOR.get(prio, "#6b7280")),
        _badge(status.replace("_", " "), STATUS_COLOR.get(status, "#6b7280")),
        _badge(ttype.replace("_", " "), "#e5e7eb", "#374151"),
    ]
    if due:
        parts.append(
            f'<span style="color:#6b7280;font-size:12px;">due {escape(due)}</span>'
        )
    parts.append(
        f'<span style="color:#6b7280;font-size:12px;">{escape(assignee)}</span>'
    )
    return (
        '<tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;'
        'font-family:Arial,sans-serif;font-size:13px;">'
        + " &nbsp; ".join(parts)
        + "</td></tr>"
    )


def _section(title: str, tasks: list, empty_msg: str) -> str:
    if not tasks:
        body = (
            '<tr><td style="padding:12px;color:#9ca3af;font-style:italic;'
            f'font-size:13px;font-family:Arial,sans-serif;">{escape(empty_msg)}</td></tr>'
        )
    else:
        body = "".join(_task_row(t) for t in tasks)
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="margin-bottom:20px;border:1px solid #e5e7eb;border-radius:6px;'
        'border-collapse:separate;border-spacing:0;overflow:hidden;">'
        '<tr><td style="background:#f9fafb;padding:10px 12px;'
        'border-bottom:1px solid #e5e7eb;font-family:Arial,sans-serif;'
        'font-size:14px;font-weight:600;color:#111827;">'
        f'{escape(title)} '
        f'<span style="color:#6b7280;font-weight:400;">({len(tasks)})</span>'
        f'</td></tr>{body}</table>'
    )


def _stat_cell(label: str, value: int, color: str) -> str:
    return (
        '<td align="center" valign="middle" '
        'style="padding:14px;border:1px solid #e5e7eb;border-radius:6px;'
        'background:#ffffff;width:25%;">'
        f'<div style="font-size:26px;font-weight:700;color:{color};'
        f'font-family:Arial,sans-serif;line-height:1;">{value}</div>'
        '<div style="font-size:11px;color:#6b7280;font-family:Arial,sans-serif;'
        f'text-transform:uppercase;letter-spacing:0.5px;margin-top:6px;">{escape(label)}</div>'
        '</td>'
    )


def _render_html(d: dict) -> str:
    period_start = d["period_start"][:10]
    period_end = d["period_end"][:10]
    s = d["summary"]

    # Discussion activity
    comments_section = ""
    if d["comments"]:
        rows = "".join(
            '<tr><td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;'
            'font-family:Arial,sans-serif;font-size:13px;">'
            f'<strong style="color:#111827;">#{c["ticket_id"]}</strong> '
            f'<span style="color:#111827;">{escape(c["task_title"])}</span><br>'
            f'<span style="color:#6b7280;font-size:12px;">{escape(c["author"])}: </span>'
            f'<span style="color:#374151;font-size:12px;">'
            f'{escape((c["comment"] or "")[:240])}'
            f'{"..." if c["comment"] and len(c["comment"]) > 240 else ""}'
            '</span></td></tr>'
            for c in d["comments"][:15]
        )
        comments_section = (
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="margin-bottom:20px;border:1px solid #e5e7eb;border-radius:6px;'
            'border-collapse:separate;border-spacing:0;overflow:hidden;">'
            '<tr><td style="background:#f9fafb;padding:10px 12px;'
            'border-bottom:1px solid #e5e7eb;font-family:Arial,sans-serif;'
            'font-size:14px;font-weight:600;color:#111827;">'
            f'Discussion Activity <span style="color:#6b7280;font-weight:400;">'
            f'({len(d["comments"])})</span></td></tr>'
            f'{rows}</table>'
        )

    # Owner workload
    assignees_section = ""
    if s["top_assignees"]:
        rows = "".join(
            '<tr><td style="padding:6px 12px;font-family:Arial,sans-serif;'
            'font-size:13px;border-bottom:1px solid #f3f4f6;">'
            f'<span style="color:#111827;">{escape(a["assignee"])}</span>'
            f'<span style="color:#6b7280;float:right;">{a["count"]} active</span>'
            '</td></tr>'
            for a in s["top_assignees"]
        )
        assignees_section = (
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="margin-bottom:20px;border:1px solid #e5e7eb;border-radius:6px;'
            'border-collapse:separate;border-spacing:0;overflow:hidden;">'
            '<tr><td style="background:#f9fafb;padding:10px 12px;'
            'border-bottom:1px solid #e5e7eb;font-family:Arial,sans-serif;'
            'font-size:14px;font-weight:600;color:#111827;">'
            'Active Tasks by Owner</td></tr>'
            f'{rows}</table>'
        )

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Jennie — Task Digest {period_start} to {period_end}</title>
</head>
<body style="margin:0;padding:24px;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
<table width="720" align="center" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;max-width:720px;">
  <tr><td style="padding:32px;">
    <h1 style="margin:0 0 4px 0;color:#111827;font-size:24px;font-family:Arial,sans-serif;">Data Team — Weekly Task Digest</h1>
    <p style="margin:0 0 24px 0;color:#6b7280;font-size:13px;font-family:Arial,sans-serif;">{period_start} &rarr; {period_end} &nbsp;&middot;&nbsp; Jennie</p>

    <table width="100%" cellpadding="0" cellspacing="6" style="margin-bottom:24px;border-collapse:separate;">
      <tr>
        {_stat_cell("Completed", s["completed_count"], "#16a34a")}
        {_stat_cell("In Progress", s["in_progress_count"], "#ca8a04")}
        {_stat_cell("Newly Opened", s["newly_opened_count"], "#2563eb")}
        {_stat_cell("Overdue", s["overdue_count"], "#dc2626")}
      </tr>
    </table>

    {_section("Completed This Week", d["completed"], "No tasks completed in this window.")}
    {_section("In Progress", d["in_progress"], "No tasks in progress.")}
    {_section("Newly Opened", d["newly_opened"], "No new tasks this week.")}
    {_section("Recently Updated", d["recently_updated"], "No updates this week.")}
    {_section("Overdue", d["overdue"], "No overdue tasks.")}
    {comments_section}
    {assignees_section}

    <p style="margin:24px 0 0 0;color:#9ca3af;font-size:11px;font-family:Arial,sans-serif;text-align:center;">
      Generated by Jennie &middot; {d["generated_at"][:19].replace("T", " ")} UTC
    </p>
  </td></tr>
</table>
</body>
</html>'''
