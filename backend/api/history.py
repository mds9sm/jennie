from fastapi import APIRouter, Request, Query, HTTPException

router = APIRouter()


def _require_auth(request: Request) -> dict:
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


@router.get("/queries")
async def list_queries(
    request: Request,
    limit: int = Query(10, le=50),
):
    """Return recent SQL queries for the authenticated user only."""
    user = _require_auth(request)
    user_id = str(user.get("user_id", ""))
    pool = request.app.state.db_pool

    # Always scope to the authenticated user — never expose other users' queries
    rows = await pool.fetch(
        """
        SELECT id, query_text, environment, redshift_query_duration_ms,
               created_at
        FROM usage_events
        WHERE capability = 'sql_execute'
          AND query_text IS NOT NULL
          AND user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )

    return [
        {
            "id": r["id"],
            "query_text": r["query_text"],
            "environment": r["environment"],
            "execution_time_ms": r["redshift_query_duration_ms"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/queries/{query_id}")
async def get_query(query_id: int, request: Request):
    """Get a specific query event by ID — only if owned by the authenticated user."""
    user = _require_auth(request)
    user_id = str(user.get("user_id", ""))
    pool = request.app.state.db_pool

    row = await pool.fetchrow(
        """
        SELECT id, query_text, environment, redshift_query_duration_ms,
               pillar, created_at
        FROM usage_events
        WHERE id = $1 AND capability = 'sql_execute' AND user_id = $2
        """,
        query_id,
        user_id,
    )
    if not row:
        raise HTTPException(404, "Query not found")

    return {
        "id": row["id"],
        "query_text": row["query_text"],
        "environment": row["environment"],
        "execution_time_ms": row["redshift_query_duration_ms"],
        "pillar": row["pillar"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
