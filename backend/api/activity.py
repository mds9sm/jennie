import logging
from datetime import datetime

from fastapi import APIRouter, Request, Query

logger = logging.getLogger("genie.activity")

router = APIRouter()


@router.get("/day-detail")
async def day_detail(request: Request, date: str = Query(...)):
    """Return detailed activity for a specific day."""
    pool = request.app.state.db_pool

    rows = await pool.fetch(
        """
        SELECT capability, model, input_tokens, output_tokens, estimated_cost, created_at
        FROM usage_events
        WHERE created_at::date = $1::date
        ORDER BY created_at DESC
        LIMIT 50
        """,
        date,
    )

    summary = await pool.fetchrow(
        """
        SELECT COUNT(*) as count,
               COALESCE(SUM(input_tokens), 0) as total_input,
               COALESCE(SUM(output_tokens), 0) as total_output,
               COALESCE(SUM(estimated_cost), 0) as total_cost
        FROM usage_events
        WHERE created_at::date = $1::date
        """,
        date,
    )

    def serialize_row(r):
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    return {
        "date": date,
        "summary": serialize_row(summary) if summary else {},
        "events": [serialize_row(r) for r in rows],
    }


@router.get("/cost-explorer")
async def cost_explorer(
    request: Request,
    period: str = Query("daily"),
    days: int = Query(30, ge=1, le=365),
    user_id: str = Query(None),
):
    """Admin cost analytics — timeline, user breakdown, model breakdown."""
    pool = request.app.state.db_pool

    if period not in ("daily", "weekly", "monthly"):
        period = "daily"

    trunc = {"daily": "day", "weekly": "week", "monthly": "month"}[period]

    user_filter = ""
    params: list = [str(days)]
    if user_id:
        user_filter = "AND user_id = $2"
        params.append(user_id)

    rows = await pool.fetch(
        f"""
        SELECT
            date_trunc('{trunc}', created_at) as period,
            COUNT(*) as call_count,
            COALESCE(SUM(input_tokens), 0) as input_tokens,
            COALESCE(SUM(output_tokens), 0) as output_tokens,
            COALESCE(SUM(estimated_cost), 0) as total_cost,
            COUNT(DISTINCT user_id) as unique_users
        FROM usage_events
        WHERE created_at > NOW() - ($1 || ' days')::interval
        {user_filter}
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )

    user_rows = await pool.fetch(
        """
        SELECT e.user_id, COALESCE(u.name, u.email, e.user_id) as user_name,
               COUNT(*) as calls,
               COALESCE(SUM(e.estimated_cost), 0) as cost,
               COALESCE(SUM(e.input_tokens + e.output_tokens), 0) as tokens
        FROM usage_events e
        LEFT JOIN users u ON e.user_id = u.id::text
        WHERE e.created_at > NOW() - ($1 || ' days')::interval
        GROUP BY e.user_id, u.name, u.email ORDER BY cost DESC
        """,
        str(days),
    )

    model_rows = await pool.fetch(
        """
        SELECT model, COUNT(*) as calls,
               COALESCE(SUM(estimated_cost), 0) as cost,
               COALESCE(SUM(input_tokens), 0) as input_tokens,
               COALESCE(SUM(output_tokens), 0) as output_tokens
        FROM usage_events
        WHERE created_at > NOW() - ($1 || ' days')::interval
        GROUP BY model ORDER BY cost DESC
        """,
        str(days),
    )

    # Per-model-per-period breakdown for stacked chart
    model_timeline_rows = await pool.fetch(
        f"""
        SELECT
            date_trunc('{trunc}', created_at) as period,
            CASE
                WHEN model ILIKE '%opus%' THEN 'opus'
                WHEN model ILIKE '%haiku%' THEN 'haiku'
                ELSE 'sonnet'
            END as model_family,
            COALESCE(SUM(estimated_cost), 0) as cost,
            COUNT(*) as calls
        FROM usage_events
        WHERE created_at > NOW() - ($1 || ' days')::interval
        {user_filter}
        GROUP BY 1, 2
        ORDER BY 1
        """,
        *params,
    )

    total = await pool.fetchrow(
        """
        SELECT COUNT(*) as total_calls,
               COALESCE(SUM(input_tokens), 0) as total_input,
               COALESCE(SUM(output_tokens), 0) as total_output,
               COALESCE(SUM(estimated_cost), 0) as total_cost
        FROM usage_events
        WHERE created_at > NOW() - ($1 || ' days')::interval
        """,
        str(days),
    )

    def serialize_row(r):
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    # Pivot model_timeline into {period: {opus: cost, sonnet: cost, haiku: cost}}
    model_timeline: dict[str, dict] = {}
    for r in model_timeline_rows:
        p = r["period"].isoformat() if hasattr(r["period"], "isoformat") else str(r["period"])
        if p not in model_timeline:
            model_timeline[p] = {"period": p, "opus": 0, "sonnet": 0, "haiku": 0,
                                 "opus_calls": 0, "sonnet_calls": 0, "haiku_calls": 0}
        fam = r["model_family"]
        model_timeline[p][fam] = float(r["cost"])
        model_timeline[p][f"{fam}_calls"] = r["calls"]

    return {
        "period": period,
        "days": days,
        "timeline": [serialize_row(r) for r in rows],
        "model_timeline": sorted(model_timeline.values(), key=lambda x: x["period"]),
        "by_user": [serialize_row(r) for r in user_rows],
        "by_model": [serialize_row(r) for r in model_rows],
        "totals": serialize_row(total) if total else {},
    }


@router.get("/heatmap")
async def activity_heatmap(
    request: Request,
    session_id: str = Query(None),
    days: int = Query(90, ge=1, le=365),
):
    """Return daily activity counts for the last N days from usage_events."""
    pool = request.app.state.db_pool

    # Try to get actual user_id from auth, fall back to session_id or show all
    from api.users import get_current_user
    auth_user = get_current_user(request)
    user_id = str(auth_user["user_id"]) if auth_user and auth_user.get("user_id") else session_id

    # If still no user_id, show all events (backwards compat)
    if not user_id:
        rows = await pool.fetch("""
            SELECT created_at::date AS day, capability, COUNT(*) AS cnt
            FROM usage_events
            WHERE created_at >= CURRENT_DATE - ($1 || ' days')::interval
            GROUP BY day, capability
        """, str(days))
    else:
        # Match by user_id OR 'local-dev' (old events)
        rows = await pool.fetch("""
            SELECT created_at::date AS day, capability, COUNT(*) AS cnt
            FROM usage_events
            WHERE user_id IN ($1, 'local-dev')
              AND created_at >= CURRENT_DATE - ($2 || ' days')::interval
            GROUP BY day, capability
        ORDER BY day DESC
        """,
        user_id,
        str(days),
    )

    # Aggregate into per-day buckets
    day_map: dict[str, dict] = {}
    for r in rows:
        d = r["day"].isoformat()
        if d not in day_map:
            day_map[d] = {"date": d, "count": 0, "capabilities": {}}
        day_map[d]["count"] += r["cnt"]
        day_map[d]["capabilities"][r["capability"]] = r["cnt"]

    day_list = sorted(day_map.values(), key=lambda x: x["date"], reverse=True)

    # Compute summary stats
    total_interactions = sum(d["count"] for d in day_list)
    active_days = len(day_list)

    # Streak: consecutive days ending today (or yesterday)
    from datetime import date, timedelta

    today = date.today()
    active_dates = {d["date"] for d in day_list}
    streak = 0
    check_date = today
    # Allow streak to start from today or yesterday
    if check_date.isoformat() not in active_dates:
        check_date = today - timedelta(days=1)
    while check_date.isoformat() in active_dates:
        streak += 1
        check_date -= timedelta(days=1)

    # Most active capability
    cap_totals: dict[str, int] = {}
    for d in day_list:
        for cap, cnt in d["capabilities"].items():
            cap_totals[cap] = cap_totals.get(cap, 0) + cnt
    most_active_capability = max(cap_totals, key=cap_totals.get) if cap_totals else None

    return {
        "days": day_list,
        "total_interactions": total_interactions,
        "streak_days": streak,
        "most_active_capability": most_active_capability,
        "active_days": active_days,
    }


@router.get("/stats")
async def activity_stats(
    request: Request,
    session_id: str = Query(None),
):
    """Summary stats for a user."""
    pool = request.app.state.db_pool
    from api.users import get_current_user
    auth_user = get_current_user(request)
    user_id = str(auth_user["user_id"]) if auth_user and auth_user.get("user_id") else session_id or "local-dev"

    totals = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS total_queries,
            COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens_used,
            COALESCE(SUM(estimated_cost), 0) AS total_cost,
            MIN(created_at) AS member_since
        FROM usage_events
        WHERE user_id IN ($1, 'local-dev')
        """,
        user_id,
    )

    # Top capabilities
    cap_rows = await pool.fetch(
        """
        SELECT capability, COUNT(*) AS cnt
        FROM usage_events
        WHERE user_id IN ($1, 'local-dev')
        GROUP BY capability
        ORDER BY cnt DESC
        """,
        user_id,
    )

    top_capabilities = [
        {"capability": r["capability"], "count": r["cnt"]}
        for r in cap_rows
    ]

    # Favorite pillar
    pillar_row = await pool.fetchrow(
        """
        SELECT pillar, COUNT(*) AS cnt
        FROM usage_events
        WHERE user_id IN ($1, 'local-dev') AND pillar IS NOT NULL
        GROUP BY pillar
        ORDER BY cnt DESC
        LIMIT 1
        """,
        user_id,
    )

    return {
        "total_queries": totals["total_queries"] if totals else 0,
        "total_tokens_used": totals["total_tokens_used"] if totals else 0,
        "total_cost": float(totals["total_cost"]) if totals and totals["total_cost"] else 0,
        "favorite_pillar": pillar_row["pillar"] if pillar_row else None,
        "top_capabilities": top_capabilities,
        "member_since": totals["member_since"].isoformat() if totals and totals["member_since"] else None,
    }
