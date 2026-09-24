"""KB Repos API — manage multiple git repos for knowledge base."""
import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("genie.kb_repos")
router = APIRouter()


async def _ensure_table(pool):
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS kb_repos (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
            token TEXT, branch TEXT DEFAULT 'main', clone_path TEXT,
            is_active BOOLEAN DEFAULT true, parse_all BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


class RepoRequest(BaseModel):
    name: str
    url: str
    token: Optional[str] = None
    branch: str = "main"
    parse_all: bool = False


@router.get("")
async def list_repos(request: Request):
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    rows = await pool.fetch("SELECT id, name, url, branch, is_active, parse_all, clone_path, created_at FROM kb_repos ORDER BY name")
    return [dict(r) for r in rows]


@router.post("")
async def add_repo(body: RepoRequest, request: Request):
    pool = request.app.state.db_pool
    await _ensure_table(pool)
    clone_path = f"/app/data-repo-kb/{body.name.replace(' ', '_').lower()}"
    row = await pool.fetchrow("""
        INSERT INTO kb_repos (name, url, token, branch, clone_path, parse_all)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """, body.name, body.url, body.token, body.branch, clone_path, body.parse_all)
    return {"id": row["id"], "status": "added", "clone_path": clone_path}


@router.put("/{repo_id}")
async def update_repo(repo_id: int, body: RepoRequest, request: Request):
    pool = request.app.state.db_pool
    await pool.execute("""
        UPDATE kb_repos SET name=$2, url=$3, branch=$4, parse_all=$5, updated_at=NOW()
        WHERE id=$1
    """, repo_id, body.name, body.url, body.branch, body.parse_all)
    if body.token:
        await pool.execute("UPDATE kb_repos SET token=$2 WHERE id=$1", repo_id, body.token)
    return {"status": "updated"}


@router.delete("/{repo_id}")
async def remove_repo(repo_id: int, request: Request):
    pool = request.app.state.db_pool
    await pool.execute("UPDATE kb_repos SET is_active=false WHERE id=$1", repo_id)
    return {"status": "deactivated"}
