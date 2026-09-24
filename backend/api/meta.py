import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request

from config import config
from engine.pillar import get_all_pillars
from tracking.logger import get_usage_summary

router = APIRouter()

# Read version once at import time — check multiple locations
_version = "0.0.0"
for _vpath in [
    Path(__file__).parent.parent / "VERSION",          # /app/VERSION (copied into backend)
    Path(__file__).parent.parent.parent / "VERSION",   # repo root (local dev with volume mount)
]:
    if _vpath.exists():
        _version = _vpath.read_text().strip()
        break
try:
    _git_hash = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=5,
        cwd=str(Path(__file__).parent.parent),
    ).stdout.strip()
except Exception:
    _git_hash = ""
APP_VERSION = f"{_version}+{_git_hash}" if _git_hash else _version


@router.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION, "redshift_mode": config.REDSHIFT_MODE,
            "kb_build_mode": os.environ.get("KB_BUILD_MODE", "local")}


@router.get("/version")
async def version():
    return {"version": APP_VERSION, "semver": _version, "git_hash": _git_hash,
            "kb_build_mode": os.environ.get("KB_BUILD_MODE", "local")}


@router.get("/pillars")
async def pillars():
    return get_all_pillars()


@router.get("/environments")
async def environments():
    envs = [
        {
            "id": "np",
            "name": "Nonprod",
            "prefix": "np_",
            "default": True,
            "description": "Development and testing. Datashare provides full schema + data access.",
            "cluster": config.REDSHIFT_NP_HOST,
            "database": config.REDSHIFT_NP_DATABASE,
            "aws_profile": config.AWS_PROFILE_NP,
        },
        {
            "id": "prd",
            "name": "Prod",
            "prefix": "prd_",
            "default": False,
            "description": "Production. Use only for profiling, EXPLAIN plans, and S3 data access.",
            "cluster": config.REDSHIFT_PRD_HOST,
            "database": config.REDSHIFT_PRD_DATABASE,
            "aws_profile": config.AWS_PROFILE_PRD,
        },
    ]
    return envs


@router.get("/redshift/test/{environment}")
async def test_redshift(environment: str, session_id: str | None = None):
    """Test Redshift connectivity for an environment."""
    if config.REDSHIFT_MODE == "mock":
        return {"status": "mock", "environment": environment, "message": "Running in mock mode. Set REDSHIFT_MODE=real to connect."}
    from connectors.redshift import test_connection
    return await test_connection(environment, session_id=session_id)


@router.get("/usage/summary")
async def usage_summary(request: Request):
    return await get_usage_summary(request.app.state.db_pool)


@router.get("/connectivity")
async def connectivity(session_id: str = "", request: Request = None):
    """Single endpoint returning all connection statuses for header icons."""
    from connectors.credential_store import credential_store
    from connectors.redshift import _direct_creds
    from pathlib import Path

    # AWS SSO
    sso = {}
    if session_id:
        session = credential_store.get_session(session_id)
        for env in ("np", "prd"):
            creds = session.get_credentials(env)
            sso[env] = {
                "connected": creds is not None,
                "minutes_remaining": creds.minutes_remaining if creds else 0,
            }
    else:
        sso = {"np": {"connected": False}, "prd": {"connected": False}}

    # Redshift (direct creds or SSO-based)
    rs = {}
    for env in ("np", "prd"):
        has_direct = env in _direct_creds
        has_sso = sso.get(env, {}).get("connected", False)
        rs[env] = {"connected": has_direct or has_sso, "method": "direct" if has_direct else ("sso" if has_sso else None)}

    # Git repo
    repo_path = Path(config.REPO_PATH)
    git_cloned = (repo_path / ".git").exists()
    git_branch = ""
    if git_cloned:
        def _branch():
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo_path), capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""

        try:
            # Polled every 30s per browser tab — keep the subprocess off the loop
            import asyncio
            git_branch = await asyncio.to_thread(_branch)
        except Exception:
            pass

    return {
        "sso": sso,
        "redshift": rs,
        "git": {"cloned": git_cloned, "branch": git_branch},
    }
