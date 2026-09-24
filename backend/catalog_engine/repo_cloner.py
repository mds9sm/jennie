"""
Repo Cloner — clones or pulls a Git repository inside the container
using subprocess git. Supports GitHub token auth for private repos.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("genie.catalog_engine.repo_cloner")


def _build_auth_url(repo_url: str, token: str) -> str:
    """Inject GitHub token into HTTPS URL for private repo auth."""
    if not token:
        return repo_url
    # https://github.com/org/repo → https://<token>@github.com/org/repo
    if repo_url.startswith("https://"):
        return repo_url.replace("https://", f"https://{token}@", 1)
    return repo_url


def _run_git(args: list[str], cwd: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git"] + args
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        logger.error("git %s failed: %s", args[0], result.stderr.strip())
    return result


def clone_or_pull(
    repo_url: str,
    repo_path: str,
    token: str = "",
    branch: str = "main",
) -> dict:
    """
    Clone the repo if it doesn't exist locally, or pull latest if it does.

    Args:
        repo_url: GitHub HTTPS URL (e.g. https://github.com/your-org/data-platform-dags)
        repo_path: Local filesystem path to clone into
        token: GitHub personal access token (for private repos)
        branch: Branch to checkout (default: main)

    Returns:
        {
            "status": "cloned" | "pulled" | "error",
            "path": str,
            "branch": str,
            "commit": str,        # short SHA
            "commit_date": str,   # ISO date of HEAD
            "error": str | None,
        }
    """
    if not repo_url:
        return {"status": "error", "path": "", "error": "No REPO_URL configured"}

    auth_url = _build_auth_url(repo_url, token)
    target = Path(repo_path)

    try:
        if (target / ".git").is_dir():
            # Repo exists — pull latest
            logger.info("Pulling latest from %s into %s", repo_url, repo_path)

            # Update remote URL in case token changed
            _run_git(["remote", "set-url", "origin", auth_url], cwd=repo_path)

            # Fetch and reset to branch tip (handles force pushes gracefully)
            result = _run_git(["fetch", "origin", branch], cwd=repo_path)
            if result.returncode != 0:
                return {
                    "status": "error",
                    "path": repo_path,
                    "error": f"git fetch failed: {result.stderr.strip()}",
                }

            result = _run_git(["reset", "--hard", f"origin/{branch}"], cwd=repo_path)
            if result.returncode != 0:
                return {
                    "status": "error",
                    "path": repo_path,
                    "error": f"git reset failed: {result.stderr.strip()}",
                }

            action = "pulled"
        else:
            # Clone fresh
            logger.info("Cloning %s into %s (branch: %s)", repo_url, repo_path, branch)
            target.parent.mkdir(parents=True, exist_ok=True)

            result = _run_git(
                ["clone", "--depth", "1", "--branch", branch, auth_url, repo_path],
                timeout=600,
            )
            if result.returncode != 0:
                # Try without --branch in case default branch is different
                result = _run_git(
                    ["clone", "--depth", "1", auth_url, repo_path],
                    timeout=600,
                )
                if result.returncode != 0:
                    return {
                        "status": "error",
                        "path": repo_path,
                        "error": f"git clone failed: {result.stderr.strip()}",
                    }
            action = "cloned"

        # Get commit info
        sha_result = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_path)
        commit = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        date_result = _run_git(
            ["log", "-1", "--format=%cI"],
            cwd=repo_path,
        )
        commit_date = date_result.stdout.strip() if date_result.returncode == 0 else ""

        branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
        actual_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else branch

        logger.info(
            "Repo %s: %s at %s (%s)", action, repo_path, commit, actual_branch,
        )

        return {
            "status": action,
            "path": repo_path,
            "branch": actual_branch,
            "commit": commit,
            "commit_date": commit_date,
            "error": None,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "path": repo_path,
            "error": "Git operation timed out (repo may be very large — try increasing timeout)",
        }
    except Exception as e:
        logger.exception("Repo clone/pull failed")
        return {
            "status": "error",
            "path": repo_path,
            "error": str(e),
        }


def get_repo_status(repo_path: str) -> dict:
    """Check the current state of the cloned repo."""
    target = Path(repo_path)

    if not (target / ".git").is_dir():
        return {"exists": False, "path": repo_path}

    sha_result = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_path)
    commit = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

    date_result = _run_git(["log", "-1", "--format=%cI"], cwd=repo_path)
    commit_date = date_result.stdout.strip() if date_result.returncode == 0 else ""

    # Count YAML files to give a sense of content
    yaml_count = len(list(target.rglob("*.yaml"))) + len(list(target.rglob("*.yml")))
    sql_count = len(list(target.rglob("*.sql")))

    return {
        "exists": True,
        "path": repo_path,
        "branch": branch,
        "commit": commit,
        "commit_date": commit_date,
        "yaml_files": yaml_count,
        "sql_files": sql_count,
    }
