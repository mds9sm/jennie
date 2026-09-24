"""
FastAPI router for Catalog Engine operations.

The catalog build is a long-running batch job (fetches from MWAA, repo, etc.).
It runs as a background asyncio task with progress polling via /status.
"""

import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config import config
from catalog_engine.builder import build_catalog, get_build_status, preview_catalog

logger = logging.getLogger("genie.catalog_engine.api")

router = APIRouter()

# Track the running build task (used in local/in-process mode)
_build_task: asyncio.Task | None = None
_build_progress: dict = {}

# Build mode: "local" (default, in-process asyncio.create_task) or "job" (K8s Job via queued row)
KB_BUILD_MODE = os.getenv("KB_BUILD_MODE", "local")


class RefreshRequest(BaseModel):
    session_id: Optional[str] = None
    include_repo: bool = True
    include_mwaa: bool = True
    include_redshift: bool = False
    mwaa_environments: list[str] = ["np", "prd"]
    redshift_environment: str = "np"
    enrichment_model: str = "opus"  # haiku, sonnet, opus
    # Phases to run — empty = all phases
    # Options: data_collection, merge, lineage, glossary, enrichment, tagging, write
    phases: list[str] = []  # empty = full build


@router.post("/refresh")
async def refresh_catalog(request: Request, body: RefreshRequest = RefreshRequest()):
    """
    Start a catalog build as a background task.
    Returns immediately — poll /status for progress.

    Two modes controlled by KB_BUILD_MODE env var:
    - "local" (default): runs in-process via asyncio.create_task
    - "job": inserts a queued row in kb_builds for a K8s Job container to pick up
    """
    global _build_task, _build_progress

    db_pool = request.app.state.db_pool
    kb = request.app.state.kb if hasattr(request.app.state, "kb") else None

    logger.info(
        "Build requested (mode=%s): session_id=%s, mwaa=%s, envs=%s, redshift=%s, repo=%s",
        KB_BUILD_MODE, body.session_id, body.include_mwaa, body.mwaa_environments,
        body.include_redshift, body.include_repo,
    )

    sources_config = {
        "mwaa": body.include_mwaa,
        "redshift": body.include_redshift,
        "repo": body.include_repo,
        "mwaa_environments": body.mwaa_environments,
        "redshift_environment": body.redshift_environment,
        "enrichment_model": body.enrichment_model,
        "phases": body.phases,
        "session_id": body.session_id,
    }

    # ── Job mode: queue a row for the K8s Job container ──
    if KB_BUILD_MODE == "job":
        # Auto-clean stale builds stuck as "running" for over 2 hours
        await db_pool.execute(
            "UPDATE kb_builds SET status = 'failed', error = 'Timed out (stuck >2h)' "
            "WHERE status = 'running' AND created_at < NOW() - INTERVAL '2 hours'"
        )

        # Check for already-queued or running builds
        existing = await db_pool.fetchrow(
            "SELECT id, status FROM kb_builds WHERE status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1"
        )
        if existing:
            return {
                "status": "already_running",
                "message": f"Build #{existing['id']} is {existing['status']}. Check /status for updates.",
                "build_id": existing["id"],
            }

        from catalog_engine.kb_tracker import queue_build
        build_id = await queue_build(db_pool, sources_config)
        return {
            "status": "queued",
            "build_id": build_id,
            "message": f"Build #{build_id} queued. A Job container will pick it up. Poll /status for progress.",
        }

    # ── Local mode (default): in-process asyncio task ──
    if _build_task and not _build_task.done():
        return {
            "status": "already_running",
            "message": "A build is already in progress. Check /status for updates.",
        }

    # Pass selected options to builder via config override
    config._mwaa_envs = body.mwaa_environments  # type: ignore[attr-defined]
    config._include_redshift = body.include_redshift  # type: ignore[attr-defined]
    config._redshift_environment = body.redshift_environment  # type: ignore[attr-defined]
    config._enrichment_model = body.enrichment_model  # type: ignore[attr-defined]
    config._build_phases = body.phases  # type: ignore[attr-defined]

    _build_progress = {
        "status": "running",
        "phase": "starting",
        "errors": [],
    }

    async def _run_build():
        global _build_progress
        try:
            _build_progress["phase"] = "building"
            stats = await build_catalog(
                config, db_pool,
                session_id=body.session_id,
                include_mwaa=body.include_mwaa,
                include_redshift=body.include_redshift,
                progress=_build_progress,
            )

            # Reload knowledge base
            if kb:
                kb.reload()
                logger.info("Knowledge base reloaded after catalog refresh")

            _build_progress.update({
                "status": "success",
                "phase": "complete",
                **stats,
            })
        except Exception as e:
            logger.exception("Background catalog build failed")
            _build_progress.update({
                "status": "error",
                "phase": "failed",
                "error": str(e),
            })

    _build_task = asyncio.create_task(_run_build())

    return {
        "status": "started",
        "message": "Catalog build started. Poll /status for progress.",
    }


@router.post("/reload-from-s3")
async def reload_from_s3(request: Request):
    """
    Download latest KB from S3 and reload in-memory.

    Called by Airflow DAG after KB build writes to S3, or manually
    to pick up fresh KB without a full rebuild.
    """
    kb = request.app.state.kb if hasattr(request.app.state, "kb") else None
    if not kb:
        return {"status": "error", "message": "Knowledge base not initialized"}

    try:
        from connectors.kb_storage import download_kb_from_s3, _s3_bucket, _s3_prefix
        if not _s3_bucket:
            return {"status": "error", "message": "S3 storage not configured"}

        logger.info("Reloading KB from s3://%s/%s", _s3_bucket, _s3_prefix)
        # 600+ sequential S3 GETs — must run off the event loop or the whole
        # app (including /login) freezes for the duration of the download.
        result = await asyncio.to_thread(download_kb_from_s3, config.KNOWLEDGE_DIR)
        logger.info("S3 download result: %s", result)

        # Reload KB from disk (S3 files) — heavy JSON parse, also off-loop
        await asyncio.to_thread(kb.reload)

        # Also reload postgres-backed data (glossary entries + table profiles)
        # These are NOT in S3 files — they live in Genie postgres
        db_pool = request.app.state.db_pool if hasattr(request.app.state, "db_pool") else None
        if db_pool:
            try:
                await kb.load_glossary_from_db(db_pool)
                await kb.load_table_profiles(db_pool)
                logger.info("Reloaded glossary (%d terms) and profiles (%d tables) from postgres",
                            len(kb.glossary), len(kb.table_profiles))
            except Exception as e:
                logger.warning("Failed to reload postgres data: %s", str(e)[:100])

            # Persist lineage to postgres so it survives container restarts
            if kb.lineage:
                try:
                    await kb.save_lineage_to_db(db_pool)
                except Exception as e:
                    logger.warning("Failed to save lineage to postgres: %s", str(e)[:100])

        download_status = result.get("status", "unknown") if isinstance(result, dict) else str(result)
        files_downloaded = result.get("files", 0) if isinstance(result, dict) else 0

        logger.info("KB reloaded: %d transforms, %d lineage, %d tables, %d profiles (download: %s)",
                     len(kb.transforms_index), len(kb.lineage),
                     len(kb.catalog.get("tables", [])), len(kb.table_profiles), download_status)

        # Regenerate embeddings for semantic search (background — don't block response)
        if db_pool:
            async def _regen_embeddings():
                try:
                    from catalog.embeddings import generate_embeddings
                    emb_result = await generate_embeddings(kb, db_pool)
                    logger.info("Embeddings regenerated after S3 reload: %s", emb_result)
                except Exception as emb_err:
                    logger.warning("Embedding regeneration skipped: %s", str(emb_err)[:200])
            asyncio.create_task(_regen_embeddings())

        return {
            "status": "success",
            "message": f"KB reloaded (download: {download_status}, {files_downloaded} files)",
            "download": result if isinstance(result, dict) else {"raw": str(result)},
            "transforms": len(kb.transforms_index),
            "lineage": len(kb.lineage),
            "tables": len(kb.catalog.get("tables", [])),
            "table_profiles": len(kb.table_profiles),
            "glossary": len(kb.glossary),
        }
    except Exception as e:
        logger.exception("Failed to reload KB from S3")
        return {"status": "error", "message": str(e)[:500]}


@router.get("/status")
async def catalog_status(request: Request):
    """
    Return build status. If a build is running, includes live progress
    (current phase, DAG count, etc.). Otherwise returns last build stats.

    In job mode, reads progress from postgres (kb_builds.progress).
    In local mode, reads from the in-memory _build_progress dict.
    """
    global _build_task, _build_progress

    # ── Job mode: always read from postgres ──
    if KB_BUILD_MODE == "job":
        db_pool = request.app.state.db_pool
        row = await db_pool.fetchrow(
            "SELECT id, status, progress, stats, error, duration_seconds "
            "FROM kb_builds ORDER BY created_at DESC LIMIT 1"
        )
        if not row:
            return {**get_build_status(), "running": False}

        is_active = row["status"] in ("queued", "running")
        progress_data = row["progress"]
        if isinstance(progress_data, str):
            progress_data = json.loads(progress_data)

        result = {
            "build_id": row["id"],
            "status": row["status"],
            "running": is_active,
            **(progress_data or {}),
        }
        # Merge final stats on completion
        if not is_active:
            stats_data = row["stats"]
            if isinstance(stats_data, str):
                stats_data = json.loads(stats_data)
            if stats_data:
                result.update(stats_data)
            if row["error"]:
                result["error"] = row["error"]
            if row["duration_seconds"]:
                result["duration_seconds"] = float(row["duration_seconds"])
        return result

    # ── Local mode: in-memory progress ──
    if _build_task and not _build_task.done():
        return {
            **_build_progress,
            "running": True,
        }

    if _build_progress.get("status") in ("success", "error"):
        result = {**_build_progress, "running": False}
        return result

    return {**get_build_status(), "running": False}


@router.post("/preview")
async def preview_changes(request: Request, body: RefreshRequest = RefreshRequest()):
    """Dry-run catalog build — returns what would change without writing files."""
    db_pool = request.app.state.db_pool
    try:
        changes = await preview_catalog(
            config, db_pool, session_id=body.session_id
        )
        return {"status": "ok", "changes": changes}
    except Exception as e:
        logger.exception("Catalog preview failed")
        return {"status": "error", "error": str(e)}


@router.get("/kb-schedule")
async def get_kb_schedule(request: Request):
    """Get the KB build schedule cron expression."""
    pool = request.app.state.db_pool
    try:
        row = await pool.fetchrow("SELECT value FROM schedule_runner_config WHERE key = 'kb_build_cron'")
        return {"cron": row["value"] if row else ""}
    except Exception:
        return {"cron": ""}


@router.post("/kb-schedule")
async def set_kb_schedule(request: Request):
    """Set or disable the KB build schedule."""
    body = await request.json()
    cron = body.get("cron", "").strip()
    pool = request.app.state.db_pool
    if cron:
        await pool.execute("""
            INSERT INTO schedule_runner_config (key, value, updated_at)
            VALUES ('kb_build_cron', $1, NOW())
            ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()
        """, cron)
    else:
        await pool.execute("DELETE FROM schedule_runner_config WHERE key = 'kb_build_cron'")
    return {"status": "saved", "cron": cron}


@router.post("/cancel")
async def cancel_build(request: Request):
    """Cancel a running or queued KB build."""
    global _build_task, _build_progress
    pool = request.app.state.db_pool

    # Job mode: cancel queued/running builds in postgres
    if KB_BUILD_MODE == "job":
        result = await pool.execute(
            "UPDATE kb_builds SET status = 'failed', error = 'Cancelled by user' "
            "WHERE status IN ('queued', 'running')"
        )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.info("KB build cancelled by user (job mode, %d rows)", count)
            return {"status": "cancelled"}
        return {"status": "not_running"}

    # Local mode: cancel the asyncio task
    if _build_task and not _build_task.done():
        _build_task.cancel()
        _build_progress["status"] = "cancelled"
        _build_progress["running"] = False
        try:
            await pool.execute(
                "UPDATE kb_builds SET status = 'failed', error = 'Cancelled by user' WHERE status = 'running'"
            )
        except Exception:
            pass
        logger.info("KB build cancelled by user")
        return {"status": "cancelled"}
    return {"status": "not_running"}


@router.get("/repo/status")
async def repo_status():
    """Check the current state of the cloned KB repo."""
    from catalog_engine.repo_cloner import get_repo_status
    kb_path = config.REPO_PATH_KB or config.REPO_PATH
    return get_repo_status(kb_path)


@router.post("/repo/clone")
async def clone_repo():
    """Clone or pull the data platform repo (KB clone — always main, read-only)."""
    from catalog_engine.repo_cloner import clone_or_pull
    kb_path = config.REPO_PATH_KB or config.REPO_PATH
    result = clone_or_pull(
        config.REPO_URL,
        kb_path,
        token=config.GITHUB_TOKEN,
        branch="main",
    )
    return result


@router.get("/kb/explore")
async def kb_explore(request: Request):
    """Return a summary of everything in the KB for the explorer UI."""
    kb = request.app.state.kb

    # Transforms summary
    transforms = []
    for t in kb.transforms_index[:500]:
        transforms.append({
            "dag_id": t.get("dag_id", ""),
            "name": t.get("name", ""),
            "target_table": t.get("target_table", ""),
            "schedule": t.get("schedule", ""),
            "dag_type": t.get("dag_type", ""),
            "run_state": t.get("run_state", ""),
            "last_run_date": t.get("last_run_date", ""),
            "success_rate": t.get("success_rate"),
            "source": t.get("source", ""),
        })

    # Tables from catalog
    tables = []
    for t in kb.catalog.get("tables", [])[:500]:
        tables.append({
            "name": t.get("name", ""),
            "schema": t.get("schema", ""),
            "description": t.get("description", "")[:100] if t.get("description") else "",
            "column_count": len(t.get("columns", [])),
        })

    # Table profiles from Table Ops
    profiles = []
    for key, p in sorted(kb.table_profiles.items(), key=lambda x: -(x[1].get("row_count") or 0))[:100]:
        profiles.append({
            "name": key,
            "row_count": p.get("row_count"),
            "size_mb": p.get("size_mb"),
            "type": p.get("type"),
            "last_profiled": p.get("last_profiled"),
            "has_profile": bool(p.get("profile")),
        })

    # DOMO metrics
    domo = []
    for m in getattr(kb, "domo_catalog", []):
        s3 = m.get("s3_metadata") or {}
        domo.append({
            "name": m.get("name", ""),
            "pillar": m.get("pillar", ""),
            "metric_type": m.get("metric_type", ""),
            "domo_dataset_id": m.get("domo_dataset_id", ""),
            "transform_dag": m.get("transform_dag", ""),
            "has_view_sql": m.get("has_view_sql", False),
            "s3_last_modified": s3.get("last_modified", ""),
            "s3_size_mb": s3.get("total_size_mb", 0),
            "s3_columns": len(s3.get("columns", [])) if isinstance(s3.get("columns"), list) else 0,
            "source_tables": m.get("source_tables", []),
        })

    # Glossary
    glossary = []
    for key, g in list(kb.glossary.items())[:200]:
        glossary.append({
            "term": g.get("term", key),
            "definition": (g.get("definition") or "")[:120],
            "has_formula": bool(g.get("formula")),
            "source_tables": len(g.get("source_tables") or []),
        })

    # Lineage stats
    lineage_count = len(kb.lineage)
    lineage_with_upstream = sum(1 for v in kb.lineage.values() if isinstance(v, dict) and v.get("upstream"))
    lineage_with_downstream = sum(1 for v in kb.lineage.values() if isinstance(v, dict) and v.get("downstream"))

    # Last build info
    pool = request.app.state.db_pool
    last_build = None
    try:
        row = await pool.fetchrow(
            "SELECT id, status, created_at, duration_seconds FROM kb_builds ORDER BY id DESC LIMIT 1"
        )
        if row:
            last_build = {
                "id": row["id"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "duration_seconds": float(row["duration_seconds"]) if row["duration_seconds"] else None,
            }
    except Exception:
        pass

    return {
        "transforms": transforms,
        "tables": tables,
        "profiles": profiles,
        "domo_metrics": domo,
        "glossary": glossary,
        "last_build": last_build,
        "summary": {
            "transform_count": len(kb.transforms_index),
            "table_count": len(kb.catalog.get("tables", [])),
            "profile_count": len(kb.table_profiles),
            "domo_metric_count": len(getattr(kb, "domo_catalog", [])),
            "glossary_count": len(kb.glossary),
            "lineage_count": lineage_count,
            "lineage_with_upstream": lineage_with_upstream,
            "lineage_with_downstream": lineage_with_downstream,
            "metadata_dag_count": len(kb.metadata_dags),
        },
    }


@router.get("/kb/history")
async def kb_history(request: Request):
    """Get KB build history with diffs."""
    pool = request.app.state.db_pool
    from catalog_engine.kb_tracker import get_build_history
    return await get_build_history(pool)


@router.get("/kb/history/{build_id}")
async def kb_build_detail(build_id: int, request: Request):
    """Get full detail of a specific KB build including snapshot."""
    pool = request.app.state.db_pool
    from catalog_engine.kb_tracker import get_build_detail
    detail = await get_build_detail(pool, build_id)
    if not detail:
        from fastapi import HTTPException
        raise HTTPException(404, "Build not found")
    return detail
