from fastapi import APIRouter, Request, Query

from api.models import GlossaryCorrectionRequest
from catalog.search import search_glossary

router = APIRouter()


@router.get("/search")
async def glossary_search(request: Request, q: str = Query(..., min_length=1)):
    kb = request.app.state.kb
    results = search_glossary(kb, q)
    return {"results": results, "count": len(results)}


@router.get("/all")
async def glossary_all(request: Request):
    """Return all glossary terms from the knowledge base."""
    kb = request.app.state.kb
    return {"results": kb.glossary, "count": len(kb.glossary)}


@router.post("/correct")
async def submit_correction(req: GlossaryCorrectionRequest, request: Request):
    pool = request.app.state.db_pool
    await pool.execute(
        """
        INSERT INTO glossary_feedback (term, correction, submitted_by)
        VALUES ($1, $2, $3)
        """,
        req.term,
        req.correction,
        req.submitted_by,
    )
    return {"status": "submitted", "term": req.term}


@router.get("/feedback")
async def list_feedback(request: Request, status: str = Query("pending")):
    """List glossary feedback entries filtered by status."""
    pool = request.app.state.db_pool
    rows = await pool.fetch(
        """
        SELECT id, term, correction, submitted_by, status, created_at
        FROM glossary_feedback
        WHERE status = $1
        ORDER BY created_at DESC
        """,
        status,
    )
    return [
        {
            "id": r["id"],
            "term": r["term"],
            "correction": r["correction"],
            "submitted_by": r["submitted_by"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.put("/feedback/{feedback_id}")
async def update_feedback(feedback_id: int, request: Request):
    """Approve or reject a glossary feedback entry."""
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("approved", "rejected"):
        return {"error": "status must be 'approved' or 'rejected'"}

    pool = request.app.state.db_pool
    result = await pool.execute(
        """
        UPDATE glossary_feedback SET status = $1 WHERE id = $2
        """,
        new_status,
        feedback_id,
    )
    if result == "UPDATE 0":
        return {"error": "Feedback entry not found"}
    return {"id": feedback_id, "status": new_status}
