"""
Git IDE API — browse, edit, commit, push, and create PRs for the data platform repo.

Uses per-user git worktrees so multiple users can work on different branches
simultaneously without interfering. The shared bare repo lives at REPO_PATH;
each user gets a worktree at /app/data-repo-worktrees/{user_id}/.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

from config import config

logger = logging.getLogger("genie.git_ide")
router = APIRouter()

WORKTREE_BASE = Path("/app/data-repo-worktrees")


def _main_repo() -> Path:
    """The shared main clone (used as the base for worktrees)."""
    return Path(config.REPO_PATH)


# Git subprocesses run in worker threads — network operations (fetch/push) can
# take up to 30s and must never stall the event loop (health probes, all other
# requests share the single uvicorn worker).
async def _run_git(args: list[str], cwd: str = None) -> subprocess.CompletedProcess:
    cmd = ["git"] + args
    return await asyncio.to_thread(
        subprocess.run, cmd, cwd=cwd or str(_main_repo()), capture_output=True, text=True, timeout=30
    )


def _get_user_id(request: Request) -> int | None:
    """Extract user_id from auth token."""
    from api.users import get_current_user
    user = get_current_user(request)
    return user.get("user_id") if user else None


async def _user_worktree(request: Request) -> Path:
    """Get or create a worktree for the authenticated user."""
    user_id = _get_user_id(request)
    if not user_id:
        # Fallback: use main repo (backwards compat for unauthenticated)
        return _main_repo()

    wt_path = WORKTREE_BASE / str(user_id)
    if wt_path.exists() and (wt_path / ".git").exists():
        return wt_path

    # Create worktree from main repo
    main = _main_repo()
    if not (main / ".git").exists():
        raise HTTPException(400, "Main repo not cloned. Clone it first in Settings → Knowledge Base.")

    WORKTREE_BASE.mkdir(parents=True, exist_ok=True)

    # Ensure full branch fetch (shallow clones limit refspec to main only)
    await _run_git(["config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"], cwd=str(main))
    await _run_git(["fetch", "origin", "--prune"], cwd=str(main))

    # Create worktree on main branch (user will switch to feature branch)
    result = await _run_git(
        ["worktree", "add", str(wt_path), "main"],
        cwd=str(main),
    )
    if result.returncode != 0:
        # Worktree might exist in git's list but dir was cleaned up
        await _run_git(["worktree", "prune"], cwd=str(main))
        result = await _run_git(
            ["worktree", "add", str(wt_path), "main"],
            cwd=str(main),
        )
        if result.returncode != 0:
            logger.error("Failed to create worktree for user %s: %s", user_id, result.stderr)
            raise HTTPException(500, f"Failed to create worktree: {result.stderr.strip()}")

    logger.info("Created worktree for user %s at %s", user_id, wt_path)
    return wt_path


async def _wt_git(args: list[str], wt_path: Path) -> subprocess.CompletedProcess:
    """Run git command in a user's worktree."""
    cmd = ["git"] + args
    return await asyncio.to_thread(
        subprocess.run, cmd, cwd=str(wt_path), capture_output=True, text=True, timeout=30
    )


# ---------------------------------------------------------------------------
# File browsing
# ---------------------------------------------------------------------------

@router.get("/files")
async def list_files(request: Request, path: str = ""):
    """List files/dirs at a path in the repo. Returns tree nodes."""
    repo = await _user_worktree(request)
    target = repo / path if path else repo

    if not target.exists() or not str(target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(404, "Path not found")

    if target.is_file():
        return {"type": "file", "path": path, "name": target.name, "size": target.stat().st_size}

    entries = []
    for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if item.name.startswith('.') or item.name == '__pycache__':
            continue
        rel = str(item.relative_to(repo))
        entry = {
            "name": item.name,
            "path": rel,
            "type": "dir" if item.is_dir() else "file",
        }
        if item.is_file():
            entry["size"] = item.stat().st_size
            entry["ext"] = item.suffix
        elif item.is_dir():
            entry["children_count"] = sum(1 for _ in item.iterdir() if not _.name.startswith('.'))
        entries.append(entry)

    return {"path": path, "entries": entries}


@router.get("/file")
async def read_file(request: Request, path: str):
    """Read a file's content."""
    repo = await _user_worktree(request)
    target = repo / path

    if not target.is_file() or not str(target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(404, "File not found")

    if target.stat().st_size > 1_000_000:
        raise HTTPException(400, "File too large (>1MB)")

    try:
        content = target.read_text(errors="replace")
    except Exception as e:
        raise HTTPException(500, str(e))

    return {"path": path, "name": target.name, "content": content, "size": len(content)}


class SaveFileRequest(BaseModel):
    path: str
    content: str


@router.put("/file")
async def save_file(body: SaveFileRequest, request: Request):
    """Save changes to a file. Must be on a feature branch (not main)."""
    repo = await _user_worktree(request)
    target = repo / body.path

    if not str(target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(400, "Invalid path")

    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot save directly to main. Create a feature branch first.")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content)
    logger.info("Saved file: %s on branch %s", body.path, branch)
    return {"status": "saved", "path": body.path, "branch": branch}


# ---------------------------------------------------------------------------
# Branch management
# ---------------------------------------------------------------------------

@router.get("/branches")
async def list_branches(request: Request):
    """List local + recent remote branches."""
    repo = await _user_worktree(request)

    # Fetch latest from remote
    await _wt_git(["fetch", "origin", "--prune"], repo)

    current = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()

    # Local branches (in this worktree + shared)
    local_result = await _wt_git(["branch", "--format=%(refname:short)|%(objectname:short)|%(committerdate:iso)"], repo)
    branches = []
    seen = set()

    for line in local_result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        name = parts[0]
        seen.add(name)
        branches.append({
            "name": name,
            "commit": parts[1] if len(parts) > 1 else "",
            "date": parts[2] if len(parts) > 2 else "",
            "current": name == current,
            "local": True,
        })

    # Remote branches (last 30 days)
    remote_result = await _wt_git([
        "branch", "-r", "--sort=-committerdate",
        "--format=%(refname:short)|%(objectname:short)|%(committerdate:iso)"
    ], repo)
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=365)  # show branches from last year

    for line in remote_result.stdout.strip().split("\n"):
        if not line or "HEAD" in line:
            continue
        parts = line.split("|")
        remote_name = parts[0]
        short_name = remote_name.replace("origin/", "")
        if short_name in seen:
            continue
        date_str = parts[2] if len(parts) > 2 else ""
        try:
            branch_date = datetime.fromisoformat(date_str.strip().replace(" ", "T"))
            if branch_date.tzinfo is None:
                branch_date = branch_date.replace(tzinfo=timezone.utc)
            if branch_date < cutoff:
                continue
        except (ValueError, TypeError):
            pass

        branches.append({
            "name": short_name,
            "commit": parts[1] if len(parts) > 1 else "",
            "date": date_str,
            "current": False,
            "local": False,
            "remote": remote_name,
        })

    return {"branches": branches, "current": current}


class CreateBranchRequest(BaseModel):
    name: str
    from_branch: str = "main"


@router.post("/branches")
async def create_branch(body: CreateBranchRequest, request: Request):
    """Create a new feature branch and switch to it."""
    repo = await _user_worktree(request)
    await _wt_git(["fetch", "origin"], repo)

    result = await _wt_git(["checkout", "-b", body.name, f"origin/{body.from_branch}"], repo)
    if result.returncode != 0:
        raise HTTPException(400, f"Failed to create branch: {result.stderr.strip()}")

    return {"status": "created", "branch": body.name}


@router.post("/branches/switch")
async def switch_branch(request: Request):
    """Switch to an existing branch."""
    body = await request.json()
    branch = body.get("branch", "")
    repo = await _user_worktree(request)

    result = await _wt_git(["checkout", branch], repo)
    if result.returncode != 0:
        result = await _wt_git(["checkout", "-b", branch, f"origin/{branch}"], repo)
        if result.returncode != 0:
            raise HTTPException(400, f"Failed to switch: {result.stderr.strip()}")

    return {"status": "switched", "branch": branch}


# ---------------------------------------------------------------------------
# Git status, diff, commit, push
# ---------------------------------------------------------------------------

@router.get("/status")
async def git_status(request: Request):
    """Get current branch, status of working tree."""
    repo = await _user_worktree(request)
    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    status = await _wt_git(["status", "--porcelain"], repo)

    files = []
    for line in status.stdout.strip().split("\n"):
        if not line:
            continue
        state = line[:2].strip()
        filepath = line[3:].strip()
        files.append({"state": state, "path": filepath})

    ahead_behind = await _wt_git(["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"], repo)
    ahead = 0
    behind = 0
    if ahead_behind.returncode == 0:
        parts = ahead_behind.stdout.strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    return {
        "branch": branch,
        "is_main": branch == "main",
        "changed_files": files,
        "ahead": ahead,
        "behind": behind,
    }


@router.post("/pull")
async def git_pull(request: Request):
    """Pull latest from remote for the current branch."""
    repo = await _user_worktree(request)
    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()

    # Fetch first
    await _wt_git(["fetch", "origin"], repo)

    # Fast-forward merge (safe — no force)
    result = await _wt_git(["merge", "--ff-only", f"origin/{branch}"], repo)
    if result.returncode != 0:
        # If ff-only fails, try rebase
        result = await _wt_git(["pull", "--rebase", "origin", branch], repo)
        if result.returncode != 0:
            raise HTTPException(400, f"Pull failed: {result.stderr.strip()}")

    return {"status": "pulled", "branch": branch}


@router.get("/diff")
async def git_diff(request: Request, path: Optional[str] = None):
    """Get diff of changes."""
    repo = await _user_worktree(request)
    args = ["diff"]
    if path:
        args.append(path)
    result = await _wt_git(args, repo)
    return {"diff": result.stdout}


class CommitRequest(BaseModel):
    message: str
    files: list[str] = []


@router.post("/commit")
async def git_commit(body: CommitRequest, request: Request):
    """Stage and commit changes using the authenticated user's git identity."""
    repo = await _user_worktree(request)
    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot commit to main. Create a feature branch first.")

    # Get user's git config
    user_id = _get_user_id(request)
    git_name = None
    git_email = None
    if user_id:
        pool = request.app.state.db_pool
        row = await pool.fetchrow(
            "SELECT git_name, git_email FROM users WHERE id = $1", user_id
        )
        if row:
            git_name = row["git_name"]
            git_email = row["git_email"]

    if git_name:
        await _wt_git(["config", "user.name", git_name], repo)
    if git_email:
        await _wt_git(["config", "user.email", git_email], repo)

    if body.files:
        for f in body.files:
            await _wt_git(["add", f], repo)
    else:
        await _wt_git(["add", "-A"], repo)

    result = await _wt_git(["commit", "-m", body.message], repo)
    if result.returncode != 0:
        raise HTTPException(400, f"Commit failed: {result.stderr.strip()}")

    commit_sha = (await _wt_git(["rev-parse", "--short", "HEAD"], repo)).stdout.strip()
    return {"status": "committed", "branch": branch, "commit": commit_sha, "message": body.message, "author": git_name or "unknown"}


@router.post("/push")
async def git_push(request: Request):
    """Push current branch using user's GitHub token (or shared fallback)."""
    repo = await _user_worktree(request)
    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot push to main directly.")

    token = config.GITHUB_TOKEN
    user_id = _get_user_id(request)
    if user_id:
        pool = request.app.state.db_pool
        row = await pool.fetchrow("SELECT github_token FROM users WHERE id = $1", user_id)
        if row and row["github_token"]:
            token = row["github_token"]

    if not token:
        raise HTTPException(400, "No GitHub token configured. Set it in Settings > Git.")

    repo_url = config.REPO_URL
    auth_url = repo_url.replace("https://", f"https://{token}@")
    await _wt_git(["remote", "set-url", "origin", auth_url], repo)

    result = await _wt_git(["push", "-u", "origin", branch], repo)
    if result.returncode != 0:
        raise HTTPException(400, f"Push failed: {result.stderr.strip()}")

    return {"status": "pushed", "branch": branch}


# ---------------------------------------------------------------------------
# File operations (create, rename, delete)
# ---------------------------------------------------------------------------

@router.post("/create-file")
async def create_new_file(request: Request):
    """Create a new file in the repo."""
    body = await request.json()
    path = body.get("path", "")
    content = body.get("content", "")

    repo = await _user_worktree(request)
    target = repo / path

    if not str(target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(400, "Invalid path")

    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot create files on main. Create a feature branch first.")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    logger.info("Created file: %s on branch %s", path, branch)
    return {"status": "created", "path": path, "branch": branch}


@router.post("/create-directory")
async def create_directory(request: Request):
    """Create a new directory in the repo."""
    body = await request.json()
    path = body.get("path", "")

    repo = await _user_worktree(request)
    target = repo / path

    if not str(target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(400, "Invalid path")

    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot create directories on main. Create a feature branch first.")

    target.mkdir(parents=True, exist_ok=True)
    (target / ".gitkeep").touch()
    logger.info("Created directory: %s on branch %s", path, branch)
    return {"status": "created", "path": path, "branch": branch}


@router.post("/rename")
async def rename_file(request: Request):
    """Rename/move a file or directory in the repo."""
    body = await request.json()
    old_path = body.get("old_path", "")
    new_path = body.get("new_path", "")

    if not old_path or not new_path:
        raise HTTPException(400, "old_path and new_path required")

    repo = await _user_worktree(request)
    old_target = repo / old_path
    new_target = repo / new_path

    if not str(old_target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(400, "Invalid old path")
    if not str(new_target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(400, "Invalid new path")
    if not old_target.exists():
        raise HTTPException(404, f"Path not found: {old_path}")

    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot rename on main. Use a feature branch.")

    new_target.parent.mkdir(parents=True, exist_ok=True)

    result = await _wt_git(["mv", old_path, new_path], repo)
    if result.returncode != 0:
        import shutil
        try:
            if old_target.is_dir():
                shutil.move(str(old_target), str(new_target))
            else:
                old_target.rename(new_target)
            await _wt_git(["add", new_path], repo)
            await _wt_git(["add", old_path], repo)
        except Exception as e:
            raise HTTPException(500, f"Rename failed: {e}")

    logger.info("Renamed %s → %s on branch %s", old_path, new_path, branch)
    return {"status": "renamed", "old_path": old_path, "new_path": new_path}


@router.post("/delete")
async def delete_file(request: Request):
    """Delete a file or directory from the repo."""
    body = await request.json()
    path = body.get("path", "")

    if not path:
        raise HTTPException(400, "path required")

    repo = await _user_worktree(request)
    target = repo / path

    if not str(target.resolve()).startswith(str(repo.resolve())):
        raise HTTPException(400, "Invalid path")
    if not target.exists():
        raise HTTPException(404, f"Path not found: {path}")

    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot delete on main. Use a feature branch.")

    if target.is_dir():
        result = await _wt_git(["rm", "-rf", path], repo)
        if result.returncode != 0:
            import shutil
            shutil.rmtree(str(target), ignore_errors=True)
    else:
        result = await _wt_git(["rm", path], repo)
        if result.returncode != 0:
            target.unlink(missing_ok=True)

    logger.info("Deleted %s on branch %s", path, branch)
    return {"status": "deleted", "path": path}


# ---------------------------------------------------------------------------
# Pull Request
# ---------------------------------------------------------------------------

class CreatePRRequest(BaseModel):
    title: str
    body: str = ""
    base: str = "main"


@router.post("/pull-request")
async def create_pull_request(body: CreatePRRequest, request: Request):
    """Create a GitHub PR via the API."""
    import requests as http_requests

    repo = await _user_worktree(request)
    branch = (await _wt_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)).stdout.strip()
    if branch == "main":
        raise HTTPException(400, "Cannot create PR from main.")

    token = config.GITHUB_TOKEN
    user_id = _get_user_id(request)
    if user_id:
        pool = request.app.state.db_pool
        row = await pool.fetchrow("SELECT github_token FROM users WHERE id = $1", user_id)
        if row and row["github_token"]:
            token = row["github_token"]

    if not token or not config.REPO_URL:
        raise HTTPException(400, "GitHub token and REPO_URL required")

    repo_url_str = config.REPO_URL.rstrip("/").rstrip(".git")
    parts = repo_url_str.split("/")
    owner_repo = f"{parts[-2]}/{parts[-1]}"

    resp = await asyncio.to_thread(
        http_requests.post,
        f"https://api.github.com/repos/{owner_repo}/pulls",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={
            "title": body.title,
            "body": body.body,
            "head": branch,
            "base": body.base,
        },
        timeout=15,
    )

    if resp.status_code == 201:
        pr = resp.json()
        return {"status": "created", "pr_number": pr["number"], "url": pr["html_url"]}
    else:
        return {"status": "error", "error": resp.json().get("message", resp.text[:200])}
