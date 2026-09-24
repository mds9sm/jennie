"""
Catalog Builder — main orchestrator that combines all knowledge sources.

Priority order:
  1. MWAA (primary) — rendered SQL, real table names, run stats, lineage
  2. Repo (secondary) — git metadata: who changed what, when, config details
  3. Redshift — physical table metadata (columns, distkeys, row counts)
  4. Glossary — business definitions from base + user corrections

Can be run as a module: python -m catalog_engine.builder
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("genie.catalog_engine.builder")

# State tracking for the last build
_last_build_status: dict[str, Any] = {
    "last_refresh_time": None,
    "table_count": 0,
    "transform_count": 0,
    "lineage_count": 0,
    "glossary_count": 0,
    "duration_seconds": 0,
    "status": "never_run",
    "error": None,
}


def get_build_status() -> dict:
    """Return the status of the last catalog build."""
    return dict(_last_build_status)


def _merge_tables(
    existing_tables: list[dict],
    redshift_tables: list[dict],
) -> list[dict]:
    """
    Merge Redshift-discovered tables with existing catalog entries.

    Existing entries take priority for fields like description, sources,
    consumers, and dag — since those are curated. Redshift provides
    columns, distkey, sortkey, row_count_estimate, and discovers new tables.
    """
    # Index existing tables by schema.name
    existing_index: dict[str, dict] = {}
    for t in existing_tables:
        key = f"{t['schema']}.{t['name']}"
        existing_index[key] = t

    merged: list[dict] = []
    seen_keys: set[str] = set()

    for rs_table in redshift_tables:
        key = f"{rs_table['schema']}.{rs_table['name']}"
        seen_keys.add(key)

        if key in existing_index:
            # Merge: existing curated data + fresh Redshift metadata
            existing = existing_index[key]
            entry = dict(existing)

            # Update columns from Redshift if we got them
            if rs_table.get("columns"):
                # Keep existing descriptions where Redshift has none
                existing_col_descs = {
                    c["name"]: c.get("description", "")
                    for c in existing.get("columns", [])
                }
                for col in rs_table["columns"]:
                    if not col.get("description") and col["name"] in existing_col_descs:
                        col["description"] = existing_col_descs[col["name"]]
                entry["columns"] = rs_table["columns"]

            # Update physical metadata from Redshift
            if rs_table.get("distkey"):
                entry["distkey"] = rs_table["distkey"]
            if rs_table.get("sortkey"):
                entry["sortkey"] = rs_table["sortkey"]
            if rs_table.get("row_count_estimate") is not None:
                entry["row_count_estimate"] = rs_table["row_count_estimate"]

            merged.append(entry)
        else:
            # New table discovered in Redshift
            merged.append(rs_table)

    # Keep existing tables not found in Redshift (may be views or datashared)
    for key, existing in existing_index.items():
        if key not in seen_keys:
            merged.append(existing)

    return merged


def _enrich_with_repo_metadata(
    transforms: list[dict],
    repo_transforms: list[dict],
) -> list[dict]:
    """
    Enrich MWAA-primary transforms with repo git metadata.

    MWAA data (rendered SQL, sources, lineage, run stats) is authoritative.
    Repo adds: last_author, last_modified, recent_history, tags, notify_email,
    config details (delta_load, refill_days, etc.).
    """
    # Index repo transforms by dag_id for lookup
    repo_index: dict[str, dict] = {}
    for t in repo_transforms:
        repo_index[t["dag_id"]] = t

    enriched: list[dict] = []

    for transform in transforms:
        entry = dict(transform)
        dag_id = entry.get("dag_id", "")

        # Try exact match first, then try TRANSFORM_DAG__ prefix extraction
        repo_match = repo_index.get(dag_id)
        if not repo_match and dag_id.startswith("TRANSFORM_DAG__"):
            # MWAA dag_id like TRANSFORM_DAG__foo__bar → repo dag_id might be "foo"
            parts = dag_id.split("__", 2)
            if len(parts) >= 2:
                repo_match = repo_index.get(parts[1])

        if repo_match:
            # Enrich with git metadata (never overwrite MWAA primary fields)
            for key in (
                "last_author", "last_author_email", "last_modified",
                "last_commit_message", "recent_history",
                "tags", "notify_email", "dag_type",
                "delta_load", "refill_days", "days_per_batch",
                "max_active_runs", "yaml_file", "sql_files",
                "sql_step_count",
            ):
                if repo_match.get(key) is not None and key not in entry:
                    entry[key] = repo_match[key]

            # Tags and notify always merge (additive)
            if repo_match.get("tags"):
                existing_tags = entry.get("tags", [])
                entry["tags"] = list(set(existing_tags + repo_match["tags"]))
            if repo_match.get("notify_email"):
                existing_notify = entry.get("notify_email", [])
                entry["notify_email"] = list(set(existing_notify + repo_match["notify_email"]))

        enriched.append(entry)

    # Append repo-only transforms (not seen in MWAA — may be paused/new)
    seen_ids = {t["dag_id"] for t in transforms}
    for dag_id, repo_t in repo_index.items():
        if dag_id not in seen_ids:
            repo_t["source"] = "repo_only"
            enriched.append(repo_t)

    return enriched


def _merge_lineage(
    existing_lineage: dict[str, dict],
    repo_lineage: dict[str, dict],
    tables: list[dict],
) -> dict[str, dict]:
    """
    Merge lineage from existing catalog and repo parsing.
    Also ensures all tables with sources/consumers have lineage entries.
    """
    merged: dict[str, dict] = {}

    # Start with existing lineage
    for table_key, info in existing_lineage.items():
        merged[table_key] = {
            "upstream": list(info.get("upstream", [])),
            "downstream": list(info.get("downstream", [])),
        }

    # Merge repo lineage
    for table_key, info in repo_lineage.items():
        if table_key not in merged:
            merged[table_key] = {"upstream": [], "downstream": []}
        merged[table_key]["upstream"] = list(
            set(merged[table_key]["upstream"] + info.get("upstream", []))
        )
        merged[table_key]["downstream"] = list(
            set(merged[table_key]["downstream"] + info.get("downstream", []))
        )

    # Ensure tables with sources/consumers are in lineage
    for table in tables:
        key = f"{table['schema']}.{table['name']}"
        if key not in merged:
            merged[key] = {"upstream": [], "downstream": []}
        if table.get("sources"):
            merged[key]["upstream"] = list(
                set(merged[key]["upstream"] + table["sources"])
            )
        if table.get("consumers"):
            merged[key]["downstream"] = list(
                set(merged[key]["downstream"] + table["consumers"])
            )

    return merged


async def build_catalog(
    config,
    db_pool,
    session_id: str | None = None,
    include_mwaa: bool = True,
    include_redshift: bool = False,
    progress: dict | None = None,
) -> dict:
    """
    Build the complete data catalog by combining all sources.

    1. Fetches Redshift metadata (if REDSHIFT_MODE != 'mock')
    2. Parses data platform repo (if REPO_PATH configured)
    3. Fetches MWAA rendered SQL and run metadata (if include_mwaa)
    4. Merges with existing catalog data
    5. Builds complete lineage graph
    6. Builds glossary
    7. Writes catalog.json and glossary.yaml to knowledge dir

    Args:
        config: Application config object
        db_pool: asyncpg connection pool
        session_id: Optional session ID for Redshift auth
        include_mwaa: Whether to fetch MWAA rendered SQL (default True)

    Returns:
        Stats dict with counts and timing
    """
    global _last_build_status

    start = time.time()
    knowledge_dir = Path(config.KNOWLEDGE_DIR)
    stats: dict[str, Any] = {"errors": []}
    build_id = None

    # Phase control — empty = all phases
    selected_phases = set(getattr(config, "_build_phases", []) or [])
    run_all = not selected_phases

    def _should_run(phase: str) -> bool:
        return run_all or phase in selected_phases

    async def _sync_progress_to_db():
        """Persist progress dict to postgres for external consumers (K8s job mode)."""
        if db_pool and progress and progress.get("build_id"):
            try:
                from catalog_engine.kb_tracker import update_build_progress
                await update_build_progress(db_pool, progress["build_id"], progress)
            except Exception:
                pass  # Non-fatal — don't break the build for progress tracking

    _cancelled = False

    async def _check_cancelled():
        """Check if build was cancelled via UI. Sets _cancelled flag."""
        nonlocal _cancelled
        if _cancelled or not db_pool or not build_id:
            return
        try:
            status = await db_pool.fetchval(
                "SELECT status FROM kb_builds WHERE id = $1", build_id
            )
            if status in ("failed", "cancelled"):
                _cancelled = True
                logger.info("Build #%d cancelled — stopping", build_id)
        except Exception:
            pass

    def _progress(phase: str, **extra):
        if _cancelled:
            raise asyncio.CancelledError("Build cancelled by user")
        if progress is not None:
            progress["phase"] = phase
            progress.update(extra)
            # Schedule async DB sync + cancellation check
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_sync_progress_to_db())
                loop.create_task(_check_cancelled())
            except RuntimeError:
                pass  # No running loop — skip

    def _log(msg: str):
        """Append a log line to the progress object for UI display."""
        if progress is not None:
            if "logs" not in progress:
                progress["logs"] = []
            progress["logs"].append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")
            # Keep last 100 lines
            if len(progress["logs"]) > 100:
                progress["logs"] = progress["logs"][-100:]

    # Start KB build tracking
    # If progress already has a build_id (e.g., from build_job.py picking up a
    # queued row), reuse it instead of creating a duplicate kb_builds row.
    if progress and progress.get("build_id"):
        build_id = progress["build_id"]
        logger.info("Reusing existing build_id #%d from progress", build_id)
    elif db_pool:
        try:
            from catalog_engine.kb_tracker import start_build
            sources_config = {
                "mwaa": include_mwaa,
                "repo": bool(getattr(config, "REPO_URL", "")),
                "redshift": getattr(config, "REDSHIFT_MODE", "mock") != "mock",
            }
            build_id = await start_build(db_pool, sources_config)
            if progress is not None:
                progress["build_id"] = build_id
        except Exception as e:
            logger.warning("KB tracker start failed: %s", e)

    # Checkpoint support — save/load intermediate state between phases
    checkpoint_path = knowledge_dir / ".build_checkpoint.json"

    def _save_checkpoint(phase: str, data: dict):
        """Save intermediate build state so interrupted builds can resume."""
        checkpoint = {"phase": phase, "data": data}
        with open(checkpoint_path, "w") as _f:
            json.dump(checkpoint, _f, default=str)
        logger.info("Checkpoint saved: %s", phase)

    def _load_checkpoint(phase: str) -> dict | None:
        """Load checkpoint if available for this phase."""
        if not checkpoint_path.exists():
            return None
        try:
            with open(checkpoint_path) as _f:
                cp = json.load(_f)
            if cp.get("phase") == phase:
                logger.info("Resuming from checkpoint: %s", phase)
                return cp.get("data")
        except Exception:
            pass
        return None

    def _clear_checkpoint():
        if checkpoint_path.exists():
            checkpoint_path.unlink()

    try:
        # Load existing catalog
        catalog_path = knowledge_dir / "catalog.json"
        if catalog_path.exists():
            with open(catalog_path) as f:
                existing_catalog = json.load(f)
        else:
            existing_catalog = {"tables": [], "transforms": [], "lineage": {}}

        existing_tables = existing_catalog.get("tables", [])
        existing_transforms = existing_catalog.get("transforms", [])
        existing_lineage = existing_catalog.get("lineage", {})

        # ── PHASE: data_collection ─────────────────────────────────
        # Try loading from checkpoint if skipping data collection
        _checkpoint_loaded = False
        if not _should_run("data_collection"):
            cp = _load_checkpoint("data_collected")
            if cp:
                _log("Loaded data from previous checkpoint (skipping data collection)")
                redshift_tables = cp.get("redshift_tables", [])
                repo_result = cp.get("repo_result", {"transforms": [], "lineage": {}})
                mwaa_result = cp.get("mwaa_result", {"transforms": [], "lineage": {}, "dag_runs": {}})
                mwaa_result["lineage"] = cp.get("mwaa_lineage", {})
                _checkpoint_loaded = True

        # 1. Fetch Redshift metadata (uses SSO creds from credential_store)
        _progress("redshift")
        if not _checkpoint_loaded:
            redshift_tables: list[dict] = []
        logger.info("Redshift gate: include_redshift=%s, _checkpoint_loaded=%s, run_all=%s",
                    include_redshift, _checkpoint_loaded, run_all)
        if include_redshift and not _checkpoint_loaded:
            _log("Starting Redshift metadata fetch + profiling...")
            try:
                from catalog_engine.redshift_metadata import fetch_redshift_metadata
                _progress("redshift", redshift_detail="querying prd system tables + profiling via np datashare")
                _log("Querying prd system tables (SVV_ALL_TABLES, SVV_ALL_COLUMNS) + profiling via nonprod...")
                redshift_tables = await fetch_redshift_metadata(
                    environment="prd", session_id=session_id,
                    profile_tables=True, db_pool=db_pool,
                )
                profiled = sum(1 for t in redshift_tables if t.get("profile"))
                stats["redshift_tables_found"] = len(redshift_tables)
                stats["redshift_tables_profiled"] = profiled
                _log(f"Redshift: {len(redshift_tables)} tables, {profiled} profiled")
            except Exception as e:
                logger.error("Redshift metadata fetch failed: %s", e)
                stats["errors"].append(f"Redshift: {e}")
                stats["redshift_tables_found"] = 0
                _log(f"Redshift fetch failed: {e}")
        elif _should_run("data_collection"):
            _log("Skipping Redshift (not selected)")
            stats["redshift_tables_found"] = 0
        else:
            _log("Skipping data collection (phase not selected)")
            stats["redshift_tables_found"] = 0

        # 2. Clone/pull repo, then parse
        _progress("repo_clone")
        repo_result = {"transforms": [], "lineage": {}}
        repo_url = getattr(config, "REPO_URL", os.getenv("REPO_URL", ""))
        repo_path = getattr(config, "REPO_PATH_KB", os.getenv("REPO_PATH_KB", "")) or getattr(config, "REPO_PATH", os.getenv("REPO_PATH", ""))
        github_token = getattr(config, "GITHUB_TOKEN", os.getenv("GITHUB_TOKEN", ""))

        if not _should_run("data_collection"):
            _log("Skipping repo + MWAA (data_collection phase not selected)")
            stats["repo_transforms_found"] = 0
            stats["mwaa_transforms_found"] = 0
            stats["mwaa_dag_runs"] = 0
        elif repo_url:
            try:
                _log(f"Cloning/pulling repo to {repo_path}...")
                from catalog_engine.repo_cloner import clone_or_pull
                clone_result = await asyncio.to_thread(clone_or_pull, repo_url, repo_path, github_token)
                stats["repo_clone"] = clone_result
                if clone_result["status"] == "error":
                    _log(f"Repo clone failed: {clone_result['error']}")
                    stats["errors"].append(f"Repo clone: {clone_result['error']}")
                else:
                    _log(f"Repo {clone_result['status']}: {clone_result.get('branch', '')} @ {clone_result.get('commit', '')[:8]}")
            except Exception as e:
                logger.error("Repo clone failed: %s", e)
                stats["errors"].append(f"Repo clone: {e}")

        # Pull additional KB repos from postgres
        try:
            _progress("additional_repos")
            extra_repos = await db_pool.fetch(
                "SELECT name, url, token, branch, clone_path FROM kb_repos WHERE is_active = true"
            )
            if extra_repos:
                from catalog_engine.repo_cloner import clone_or_pull
                for repo in extra_repos:
                    rname = repo["name"]
                    rpath = repo["clone_path"] or f"/app/data-repo-kb/{rname.replace(' ', '_').lower()}"
                    try:
                        _log(f"Pulling additional repo: {rname}...")
                        result = await asyncio.to_thread(
                            clone_or_pull,
                            repo["url"], rpath,
                            repo["token"] or github_token,
                            repo["branch"] or "main",
                        )
                        _log(f"  {rname}: {result['status']} ({result.get('branch', '')}@{result.get('commit', '')[:8]})")
                    except Exception as e:
                        _log(f"  {rname}: pull failed — {e}")
                        stats["errors"].append(f"Repo {rname}: {e}")
                stats["additional_repos_pulled"] = len(extra_repos)
        except Exception as e:
            logger.warning("Could not pull additional repos: %s", e)

        if repo_path and Path(repo_path).is_dir():
            try:
                _log("Parsing repo YAML configs + git blame...")
                from catalog_engine.repo_parser import parse_repo
                repo_result = await asyncio.to_thread(parse_repo, repo_path)
                stats["repo_transforms_found"] = len(repo_result["transforms"])
                _log(f"Repo: parsed {len(repo_result['transforms'])} transforms")
            except Exception as e:
                logger.error("Repo parse failed: %s", e)
                stats["errors"].append(f"Repo parse: {e}")
        else:
            logger.info("Skipping repo parse (no REPO_URL configured)")
            stats["repo_transforms_found"] = 0

        # 3. Fetch MWAA rendered SQL and run metadata (both np + prd)
        _progress("mwaa", mwaa_detail="connecting")
        mwaa_result: dict[str, Any] = {"transforms": [], "lineage": {}, "dag_runs": {}}
        if _should_run("data_collection") and include_mwaa:
            _log("Starting MWAA fetch (rendered SQL from task logs)...")
            from catalog_engine.mwaa_fetcher import fetch_mwaa_metadata

            mwaa_envs = getattr(config, "_mwaa_envs", ["np", "prd"])
            total_transforms = 0
            total_dag_runs = 0

            for mwaa_env in mwaa_envs:
                try:
                    _progress("mwaa", mwaa_detail=f"fetching {mwaa_env}")
                    env_result = await fetch_mwaa_metadata(
                        environment=mwaa_env, session_id=session_id,
                        progress=progress,
                    )
                    # Tag transforms with their source environment
                    for t in env_result["transforms"]:
                        t["mwaa_environment"] = mwaa_env

                    mwaa_result["transforms"].extend(env_result["transforms"])
                    mwaa_result["dag_runs"].update(env_result.get("dag_runs", {}))
                    # Merge lineage from this env
                    for key, info in env_result.get("lineage", {}).items():
                        if key not in mwaa_result["lineage"]:
                            mwaa_result["lineage"][key] = {"upstream": [], "downstream": []}
                        mwaa_result["lineage"][key]["upstream"] = list(
                            set(mwaa_result["lineage"][key]["upstream"] + info.get("upstream", []))
                        )
                        mwaa_result["lineage"][key]["downstream"] = list(
                            set(mwaa_result["lineage"][key]["downstream"] + info.get("downstream", []))
                        )

                    total_transforms += len(env_result["transforms"])
                    total_dag_runs += len(env_result.get("dag_runs", {}))
                    metadata_count = len(env_result.get("metadata_dags", []))
                    coverage = env_result.get("coverage", {})
                    # Capture environment metadata
                    env_meta = env_result.get("environment", {})
                    if env_meta:
                        mwaa_result.setdefault("environments", {})[mwaa_env] = env_meta
                        if env_meta.get("environment_class"):
                            _log(f"MWAA {mwaa_env}: class={env_meta['environment_class']}, airflow={env_meta.get('airflow_version','')}, workers={env_meta.get('min_workers','')}-{env_meta.get('max_workers','')}")

                    _log(f"MWAA {mwaa_env}: {len(env_result['transforms'])} SQL transforms, {metadata_count} metadata DAGs, {len(env_result.get('dag_runs', {}))} runs")
                    if coverage:
                        _log(f"  Coverage: {coverage.get('total_active_dags', 0)} active DAGs — by type: {coverage.get('by_type', {})}")

                    # Merge metadata DAGs into a separate list
                    mwaa_result.setdefault("metadata_dags", []).extend(env_result.get("metadata_dags", []))
                    mwaa_result.setdefault("coverage", {})[mwaa_env] = coverage
                except Exception as e:
                    _log(f"MWAA {mwaa_env} failed: {e}")
                    stats["errors"].append(f"MWAA ({mwaa_env}): {e}")

            stats["mwaa_transforms_found"] = total_transforms
            stats["mwaa_dag_runs"] = total_dag_runs
            stats["mwaa_metadata_dags"] = len(mwaa_result.get("metadata_dags", []))
            stats["mwaa_coverage"] = mwaa_result.get("coverage", {})
        else:
            logger.info("Skipping MWAA fetch (include_mwaa=False)")
            stats["mwaa_transforms_found"] = 0
            stats["mwaa_dag_runs"] = 0

        # Checkpoint: save data collection results
        if _should_run("data_collection") and (mwaa_result.get("transforms") or redshift_tables):
            _save_checkpoint("data_collected", {
                "redshift_tables": redshift_tables,
                "repo_result": repo_result,
                "mwaa_result": {
                    k: v for k, v in mwaa_result.items()
                    if k != "lineage"  # lineage can be large, rebuild from transforms
                },
                "mwaa_lineage": mwaa_result.get("lineage", {}),
            })
            _log("Checkpoint saved after data collection")

        # 4. Merge tables
        _progress("merging")
        merged_tables = _merge_tables(existing_tables, redshift_tables)

        # 5. Build transforms: MWAA is primary, then enrich with repo metadata
        _log("Merging transforms (MWAA primary + repo enrichment)...")
        #    Start from MWAA transforms (real SQL, real table names, run stats)
        #    Then layer on repo git metadata (who changed, when, config details)
        mwaa_transforms = mwaa_result.get("transforms", [])
        if not mwaa_transforms:
            # Fall back to existing if no MWAA data
            mwaa_transforms = existing_transforms

        merged_transforms = _enrich_with_repo_metadata(
            mwaa_transforms, repo_result.get("transforms", [])
        )

        # 6. Build lineage from multiple sources
        _progress("lineage")
        _log(f"Building lineage ({len(merged_transforms)} transforms)...")

        # 6a. Start with MWAA lineage (from current build)
        merged_lineage = _merge_lineage(
            existing_lineage, mwaa_result.get("lineage", {}), merged_tables
        )

        # 6a-ii. Also extract lineage from existing transform detail files
        # (covers previous MWAA builds even when current build is repo-only)
        transforms_dir = knowledge_dir / "transforms"
        if transforms_dir.is_dir():
            detail_lineage: dict[str, dict] = {}

            # Build a short-name → full-name lookup from sources
            # e.g., "cut_session_master" → "prd_dw.fact.cut_session_master"
            all_known_tables: dict[str, str] = {}  # short_name → full qualified name

            for detail_file in transforms_dir.glob("*.json"):
                try:
                    with open(detail_file) as f:
                        detail = json.load(f)
                    for src in detail.get("resolved_sources", []):
                        src_lower = src.lower()
                        short = src_lower.split(".")[-1]
                        # Prefer prd_dw entries over bare names
                        if short not in all_known_tables or "prd_" in src_lower:
                            all_known_tables[short] = src_lower
                except Exception:
                    continue

            for detail_file in transforms_dir.glob("*.json"):
                try:
                    with open(detail_file) as f:
                        detail = json.load(f)

                    raw_target = (detail.get("target_table", "") or "").lower()
                    sources = [s.lower() for s in detail.get("resolved_sources", [])]

                    # Resolve target from rendered SQL (most accurate)
                    target = raw_target
                    rendered_sql = (detail.get("rendered_sql", "") or "")
                    if rendered_sql and "." not in target:
                        import re as _re
                        # Find all INSERT INTO / CREATE TABLE targets
                        sql_targets = _re.findall(
                            r'(?:INSERT\s+INTO|CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)\s*(\w+\.\w+\.\w+)',
                            rendered_sql, _re.IGNORECASE
                        )
                        sql_targets = list(set(t.lower() for t in sql_targets))

                        # 1. Best match: target whose short name matches the raw_target
                        for t in sql_targets:
                            t_short = t.split(".")[-1]
                            if t_short == raw_target and ".stage." not in t:
                                target = t
                                break
                        else:
                            # 2. Any non-stage target containing the raw name
                            for t in sql_targets:
                                if raw_target.replace("s_", "_") in t or raw_target in t:
                                    if ".stage." not in t and ".temp." not in t:
                                        target = t
                                        break
                            else:
                                # 3. Exact match in known tables index
                                if raw_target in all_known_tables:
                                    target = all_known_tables[raw_target]

                    # Filter out bad sources (aliases, column refs)
                    clean_sources = [s for s in sources if "." in s and not s.startswith("c.") and not s.startswith("i.")]

                    if target and clean_sources:
                        if target not in detail_lineage:
                            detail_lineage[target] = {"upstream": [], "downstream": []}
                        for src in clean_sources:
                            if src != target and src not in detail_lineage[target]["upstream"]:
                                detail_lineage[target]["upstream"].append(src)
                            if src not in detail_lineage:
                                detail_lineage[src] = {"upstream": [], "downstream": []}
                            if target not in detail_lineage[src]["downstream"]:
                                detail_lineage[src]["downstream"].append(target)
                except Exception:
                    continue
            if detail_lineage:
                merged_lineage = _merge_lineage(merged_lineage, detail_lineage, merged_tables)
                logger.info("Extracted lineage from %d transform detail files", len(detail_lineage))

        # 6b. Parse DOMO + views + downstream_dags from repo
        domo_result = {"metrics": [], "downstream_dags": {}, "views": [], "domo_datasets": []}
        if repo_path and Path(repo_path).is_dir():
            try:
                _progress("domo_views")
                from catalog_engine.domo_parser import parse_all as parse_domo
                domo_result = await asyncio.to_thread(parse_domo, repo_path)
                stats["domo_metrics"] = len(domo_result["metrics"])
                stats["domo_datasets"] = len(domo_result["domo_datasets"])
                stats["domo_views"] = len(domo_result["views"])
                stats["downstream_dags_count"] = len(domo_result["downstream_dags"])
                logger.info(
                    "DOMO parse: %d metrics, %d datasets, %d views, %d downstream mappings",
                    len(domo_result["metrics"]), len(domo_result["domo_datasets"]),
                    len(domo_result["views"]), len(domo_result["downstream_dags"]),
                )

                # Enrich lineage with downstream_dags — decode DAG names to table names
                # Build a DAG→target_table lookup from transforms
                dag_to_table: dict[str, str] = {}
                for t in merged_transforms:
                    dag_id = t.get("dag_id", "")
                    target = t.get("target_table", "")
                    if dag_id and target:
                        dag_to_table[dag_id] = target
                        # Also map the short name (without TRANSFORM_DAG__ prefix)
                        name = t.get("name", "")
                        if name:
                            dag_to_table[name] = target

                for dag_name, downstreams in domo_result["downstream_dags"].items():
                    # Resolve this DAG's target table
                    source_table = dag_to_table.get(dag_name, "")

                    for ds in downstreams:
                        # Resolve downstream DAG's target table
                        ds_table = dag_to_table.get(ds, "")

                        if source_table and ds_table:
                            # Table-level lineage: source_table → ds_table
                            if source_table not in merged_lineage:
                                merged_lineage[source_table] = {"upstream": [], "downstream": []}
                            if ds_table not in merged_lineage[source_table]["downstream"]:
                                merged_lineage[source_table]["downstream"].append(ds_table)
                            if ds_table not in merged_lineage:
                                merged_lineage[ds_table] = {"upstream": [], "downstream": []}
                            if source_table not in merged_lineage[ds_table]["upstream"]:
                                merged_lineage[ds_table]["upstream"].append(source_table)
                        else:
                            # Can't resolve to table — keep DAG-level as fallback
                            key = source_table or dag_name
                            if key not in merged_lineage:
                                merged_lineage[key] = {"upstream": [], "downstream": []}
                            ds_key = ds_table or ds
                            if ds_key not in merged_lineage[key]["downstream"]:
                                merged_lineage[key]["downstream"].append(ds_key)

                # Enrich lineage with view source tables
                for view in domo_result["views"]:
                    view_fq = f"{view['view_schema']}.{view['view_table']}" if view.get("view_schema") and view.get("view_table") else ""
                    if view_fq and view.get("source_tables"):
                        if view_fq not in merged_lineage:
                            merged_lineage[view_fq] = {"upstream": [], "downstream": []}
                        for src in view["source_tables"]:
                            if src not in merged_lineage[view_fq]["upstream"]:
                                merged_lineage[view_fq]["upstream"].append(src)

            except Exception as e:
                logger.error("DOMO parse failed: %s", e)
                stats["errors"].append(f"DOMO: {e}")

        # 6b-ii. Write view files NOW (before glossary enrichment reads them)
        views_dir = knowledge_dir / "views"
        views_dir.mkdir(exist_ok=True)
        view_count = 0
        for view in domo_result.get("views", []):
            if not view.get("sql_content") or not view.get("view_table"):
                continue
            safe_name = view["view_table"].replace("/", "_")
            view_path = views_dir / f"{safe_name}.json"
            with open(view_path, "w") as f:
                json.dump(view, f, indent=2, default=str)
            view_count += 1
        if view_count:
            _log(f"Wrote {view_count} view files (for glossary enrichment)")

        # 6b-iii. Swagger event schemas (ProductApp events → firehose_v3_enriched)
        try:
            _progress("swagger_events")
            _log("Fetching Swagger event schemas...")
            from catalog_engine.swagger_parser import fetch_and_parse, write_event_schemas
            swagger_data = await asyncio.to_thread(fetch_and_parse)
            await asyncio.to_thread(write_event_schemas, swagger_data, knowledge_dir)
            stats["event_schemas"] = swagger_data["event_count"]
            _log(f"Swagger: {swagger_data['event_count']} event schemas parsed")
        except Exception as e:
            logger.warning("Swagger event schema fetch failed (non-fatal): %s", e)
            _log(f"Swagger events skipped: {e}")

        # 6b-iv. Statsig experiments and feature gates
        try:
            from catalog_engine.statsig_client import is_configured as statsig_configured, fetch_all_for_kb, write_statsig_kb
            if statsig_configured():
                _progress("statsig")
                _log("Fetching Statsig experiments and feature gates...")
                statsig_data = await asyncio.to_thread(fetch_all_for_kb)
                await asyncio.to_thread(write_statsig_kb, statsig_data, knowledge_dir)
                stats["statsig_experiments"] = statsig_data.get("experiment_count", 0)
                stats["statsig_gates"] = statsig_data.get("gate_count", 0)
                _log(f"Statsig: {statsig_data['experiment_count']} experiments, {statsig_data['gate_count']} feature gates")
            else:
                _log("Statsig: not configured (add Console API key in Settings → Connection)")
        except Exception as e:
            logger.warning("Statsig fetch failed (non-fatal): %s", e)
            _log(f"Statsig skipped: {e}")

        # 6c. Auto-enrich glossary from view SQL + Redshift descriptions + repo
        if _should_run("glossary"):
            try:
                _progress("glossary_enrichment")
                from catalog_engine.glossary_enricher import enrich_glossary
                # Pass current in-memory catalog (not stale file from previous build)
                catalog_data_for_glossary = {"tables": merged_tables} if merged_tables else None
                enrich_stats = await enrich_glossary(str(knowledge_dir), db_pool, catalog_data_for_glossary)
                stats["glossary_drafts"] = enrich_stats.get("new_drafts", 0)
                stats["glossary_needs_review"] = enrich_stats.get("needs_review", 0)
                stats["glossary_redshift"] = enrich_stats.get("redshift_entries", 0)
                _log(f"Glossary: {enrich_stats.get('new_drafts', 0)} drafts, {enrich_stats.get('redshift_entries', 0)} from Redshift")

                # AI rewrite technical definitions → business-friendly
                if _should_run("enrichment"):
                    from catalog_engine.glossary_enricher import ai_rewrite_definitions
                    rewritten = await ai_rewrite_definitions(db_pool, log_fn=_log)
                    stats["glossary_rewritten"] = rewritten
            except Exception as e:
                logger.error("Glossary enrichment failed: %s", e)
                stats["errors"].append(f"Glossary enrichment: {e}")

        # 7. Build glossary
        glossary_path = knowledge_dir / "glossary.yaml"
        try:
            from catalog_engine.glossary_builder import build_glossary
            merged_glossary = await build_glossary(str(glossary_path), db_pool)
            stats["glossary_terms"] = len(merged_glossary)
        except Exception as e:
            logger.error("Glossary build failed: %s", e)
            stats["errors"].append(f"Glossary: {e}")
            # Fall back to existing
            if glossary_path.exists():
                with open(glossary_path) as f:
                    merged_glossary = yaml.safe_load(f) or {}
            else:
                merged_glossary = {}
            stats["glossary_terms"] = len(merged_glossary)

        # 7a-ii. Tag knowledge sources on tables and transforms
        _progress("tagging")
        _log("Tagging knowledge sources (platform/database/code/ai/user)...")
        try:
            from catalog_engine.knowledge_tagger import tag_tables, tag_transforms, build_knowledge_summary

            # Load glossary entries from postgres for user knowledge tagging
            glossary_entries_list = []
            if db_pool:
                try:
                    rows = await db_pool.fetch(
                        "SELECT term_key, definition, status, reviewed_by, updated_at FROM glossary_entries WHERE status IN ('approved', 'merged')"
                    )
                    glossary_entries_list = [dict(r) for r in rows]
                except Exception:
                    pass

            merged_tables = await asyncio.to_thread(
                tag_tables,
                merged_tables, redshift_tables,
                mwaa_result.get("transforms", []),
                repo_result.get("transforms", []),
                glossary_entries_list,
            )
            merged_transforms = await asyncio.to_thread(
                tag_transforms,
                merged_transforms,
                repo_result.get("transforms", []),
            )

            # Build and write knowledge summary
            knowledge_summary = await asyncio.to_thread(build_knowledge_summary, merged_tables, merged_transforms)
            summary_path = knowledge_dir / "knowledge_summary.json"
            with open(summary_path, "w") as f:
                json.dump(knowledge_summary, f, indent=2, default=str)

            _log(f"Tagged {len(merged_tables)} tables, {len(merged_transforms)} transforms — avg completeness: {knowledge_summary['tables']['avg_completeness']}")
            stats["knowledge_summary"] = knowledge_summary
        except Exception as e:
            logger.warning("Knowledge tagging failed (non-fatal): %s", e)
            _log(f"Knowledge tagging skipped: {e}")

        # 7b. DOMO S3 metadata (before AI enrichment so enrichment can reference S3 columns + freshness)
        if domo_result.get("metrics") and _should_run("s3_metadata"):
            try:
                _progress("domo_s3_metadata")
                _log("Enriching metrics with S3 DOMO data metadata...")
                from catalog_engine.domo_s3_enricher import enrich_metrics_from_s3, build_domo_catalog
                enrich_metrics_from_s3(domo_result["metrics"], progress_callback=_progress)
                s3_enriched = sum(1 for m in domo_result["metrics"]
                                 if m.get("s3_metadata") and m["s3_metadata"].get("columns"))
                stats["domo_s3_enriched"] = s3_enriched
                _log(f"S3 enrichment: {s3_enriched} metrics with column metadata")

                domo_cat_stats = build_domo_catalog(domo_result["metrics"], knowledge_dir)
                stats["domo_catalog"] = domo_cat_stats
                _log(f"DOMO catalog: {domo_cat_stats['total_metrics']} metrics, "
                     f"{domo_cat_stats['with_s3_metadata']} with S3 data, "
                     f"{domo_cat_stats['total_s3_size_mb']:.0f} MB total")
            except Exception as e:
                logger.error("DOMO S3 enrichment failed: %s", e)
                stats["errors"].append(f"DOMO S3: {e}")

        # 7c. KB Agent enrichment (runs LAST — synthesizes ALL collected data)
        _progress("enrichment")
        if _should_run("enrichment"):
            _log("Running KB Agent enrichment...")
            try:
                from catalog_engine.kb_agent_enricher import run_kb_agent_enrichment
                enrichment_stats = await run_kb_agent_enrichment(
                    kb_state={
                        "tables": merged_tables,
                        "transforms": merged_transforms,
                        "metadata_dags": mwaa_result.get("metadata_dags", []),
                        "metrics": domo_result.get("metrics", []),
                        "domo_catalog": knowledge_dir / "domo_catalog.json",
                        "lineage": merged_lineage,
                    },
                    db_pool=db_pool,
                    session_id=session_id,
                    log_fn=_log,
                    progress=progress,
                )
                stats["enrichment"] = enrichment_stats
                # Merge AI-enriched data back into tables and transforms
                if enrichment_stats.get("enriched_tables"):
                    for tbl in merged_tables:
                        key = f"{tbl.get('schema','')}.{tbl.get('name','')}"
                        if key in enrichment_stats["enriched_tables"]:
                            tbl["ai_description"] = enrichment_stats["enriched_tables"][key]
                if enrichment_stats.get("enriched_transforms"):
                    for t in merged_transforms:
                        dag_id = t.get("dag_id", "")
                        if dag_id in enrichment_stats["enriched_transforms"]:
                            t["ai_summary"] = enrichment_stats["enriched_transforms"][dag_id]
                mwaa_result["metadata_dags"] = mwaa_result.get("metadata_dags", [])
                _log(f"KB Agent enrichment: {enrichment_stats.get('glossary_entries', 0)} glossary entries, "
                     f"{enrichment_stats.get('dag_summaries', 0)} DAG summaries, "
                     f"{enrichment_stats.get('table_descriptions', 0)} table descriptions")
            except Exception as e:
                logger.warning("KB Agent enrichment failed, falling back to batch: %s", e)
                _log(f"KB Agent failed: {e}. Falling back to batch enrichment...")
                # Fallback to old batch enricher
                try:
                    from catalog_engine.kb_enricher import run_enrichment
                    metadata_dags = mwaa_result.get("metadata_dags", [])
                    enrichment_stats = await run_enrichment(
                        transforms=merged_transforms,
                        metadata_dags=metadata_dags,
                        tables=merged_tables,
                        metrics=domo_result.get("metrics", []),
                        repo_transforms=repo_result.get("transforms", []),
                        progress=progress,
                        log_fn=_log,
                        db_pool=db_pool,
                    )
                    stats["enrichment"] = enrichment_stats
                    mwaa_result["metadata_dags"] = metadata_dags
                except Exception as e2:
                    logger.warning("Batch enrichment also failed: %s", e2)
                    _log(f"Batch enrichment also failed: {e2}")
        else:
            _log("Skipping enrichment (phase not selected)")

        # 8. Write split knowledge base
        _progress("writing")
        _log(f"Writing KB files: {len(merged_tables)} tables, {len(merged_transforms)} transforms, {len(merged_lineage)} lineage entries...")
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        transforms_dir = knowledge_dir / "transforms"
        transforms_dir.mkdir(exist_ok=True)

        # 8a. catalog.json — tables only (lightweight, always in context)
        catalog_out = {"tables": merged_tables}
        with open(catalog_path, "w") as f:
            json.dump(catalog_out, f, indent=2, default=str)
        logger.info("Wrote catalog.json: %d tables", len(merged_tables))

        # 8b. transforms_index.json — summaries only (no rendered SQL, no task stats)
        transforms_index = []
        for t in merged_transforms:
            summary = {
                "dag_id": t.get("dag_id", ""),
                "name": t.get("name", ""),
                "target_table": t.get("target_table", ""),
                "schedule": t.get("schedule", ""),
                "dag_type": t.get("dag_type", ""),
                "run_state": t.get("run_state", ""),
                "last_run_date": t.get("last_run_date", ""),
                "last_run_duration_seconds": t.get("last_run_duration_seconds"),
                "resolved_sources": t.get("resolved_sources", t.get("sources", [])),
                "tags": t.get("tags", []),
                "source": t.get("source", ""),
            }
            # Include run_history summary if present
            rh = t.get("run_history", {})
            if rh:
                summary["success_rate"] = rh.get("success_rate")
                summary["avg_duration_seconds"] = rh.get("avg_duration_seconds")
                summary["current_failure_streak"] = rh.get("current_failure_streak", 0)
            # Include git metadata if present
            for key in ("last_author", "last_modified", "notify_email"):
                if t.get(key):
                    summary[key] = t[key]
            # Include AI summary if present
            if t.get("ai_summary"):
                summary["ai_summary"] = t["ai_summary"]
            transforms_index.append(summary)

        # Merge metadata_dags into transforms_index (non-SQL DAGs with AI summaries)
        metadata_dags = mwaa_result.get("metadata_dags", [])
        metadata_dag_ids = {t["dag_id"] for t in transforms_index if t.get("dag_id")}
        for md in metadata_dags:
            dag_id = md.get("dag_id", "")
            if dag_id in metadata_dag_ids:
                # Already in transforms — merge summary
                for t in transforms_index:
                    if t["dag_id"] == dag_id and md.get("summary") and not t.get("ai_summary"):
                        t["ai_summary"] = md["summary"]
                        break
            else:
                # New DAG not in transforms — add to index
                transforms_index.append({
                    "dag_id": dag_id,
                    "name": md.get("name", dag_id),
                    "schedule": md.get("schedule", ""),
                    "dag_type": md.get("dag_type", "metadata"),
                    "run_state": md.get("run_state", ""),
                    "last_run_date": md.get("last_run_date", ""),
                    "source": "mwaa_metadata",
                    "ai_summary": md.get("summary", ""),
                    "tasks": [t.get("task_id", "") for t in md.get("tasks", [])],
                })

        index_path = knowledge_dir / "transforms_index.json"
        with open(index_path, "w") as f:
            json.dump(transforms_index, f, indent=2, default=str)
        logger.info("Wrote transforms_index.json: %d entries", len(transforms_index))

        # 8c. lineage.json — full lineage graph
        lineage_path = knowledge_dir / "lineage.json"
        with open(lineage_path, "w") as f:
            json.dump(merged_lineage, f, indent=2, default=str)
        logger.info("Wrote lineage.json: %d entries", len(merged_lineage))

        # 8d. transforms/{dag_id}.json — per-DAG detail (rendered SQL, task stats, run history)
        detail_count = 0
        for t in merged_transforms:
            dag_id = t.get("dag_id", "")
            if not dag_id:
                continue
            # Only write detail file if there's substantive content
            has_detail = t.get("rendered_sql") or t.get("task_stats") or t.get("run_history")
            if not has_detail:
                continue
            safe_id = dag_id.replace("/", "_").replace("\\", "_")
            detail_path = transforms_dir / f"{safe_id}.json"
            with open(detail_path, "w") as f:
                json.dump(t, f, indent=2, default=str)
            detail_count += 1
        logger.info("Wrote %d transform detail files to transforms/", detail_count)

        # 8e. metrics.json (S3 enrichment already done in step 7b)
        if domo_result.get("metrics"):
            metrics_path = knowledge_dir / "metrics.json"
            with open(metrics_path, "w") as f:
                json.dump(domo_result["metrics"], f, indent=2, default=str)
            logger.info("Wrote metrics.json: %d metrics", len(domo_result["metrics"]))

        # 8f. views/ — already written in step 6b-ii (before glossary enrichment)
            view_count += 1
        if view_count:
            logger.info("Wrote %d view detail files to views/", view_count)

        # 8g. metadata_dags.json — non-SQL DAGs (schedule, owner, task types)
        metadata_dags = mwaa_result.get("metadata_dags", [])
        if metadata_dags:
            metadata_path = knowledge_dir / "metadata_dags.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata_dags, f, indent=2, default=str)
            logger.info("Wrote metadata_dags.json: %d DAGs", len(metadata_dags))
            _log(f"Wrote {len(metadata_dags)} metadata-only DAGs")

        # 8g-ii. mwaa_environments.json — environment class, config, versions
        mwaa_envs_data = mwaa_result.get("environments", {})
        if mwaa_envs_data:
            env_path = knowledge_dir / "mwaa_environments.json"
            with open(env_path, "w") as f:
                json.dump(mwaa_envs_data, f, indent=2, default=str)
            _log(f"Wrote MWAA environment metadata: {list(mwaa_envs_data.keys())}")

        # 8h. coverage.json — what's in KB vs what exists
        coverage_data = mwaa_result.get("coverage", {})
        if coverage_data:
            coverage_path = knowledge_dir / "coverage.json"
            with open(coverage_path, "w") as f:
                json.dump(coverage_data, f, indent=2, default=str)
            logger.info("Wrote coverage.json")

        # 8i. enrichment_report.json — cross-reference + conflicts
        if stats.get("enrichment"):
            report_path = knowledge_dir / "enrichment_report.json"
            with open(report_path, "w") as f:
                json.dump(stats["enrichment"], f, indent=2, default=str)
            logger.info("Wrote enrichment_report.json")

        with open(glossary_path, "w") as f:
            yaml.dump(merged_glossary, f, default_flow_style=False, sort_keys=True)
        logger.info("Wrote glossary.yaml: %d terms", len(merged_glossary))

        elapsed = time.time() - start
        _log(f"Build complete in {elapsed:.1f}s: {len(merged_tables)} tables, {len(merged_transforms)} transforms, {len(merged_lineage)} lineage, {len(merged_glossary)} glossary")

        stats.update({
            "table_count": len(merged_tables),
            "transform_count": len(merged_transforms),
            "lineage_count": len(merged_lineage),
            "glossary_terms": len(merged_glossary),
            "duration_seconds": round(elapsed, 2),
            "status": "success",
        })

        _last_build_status = {
            "last_refresh_time": datetime.now(timezone.utc).isoformat(),
            "table_count": len(merged_tables),
            "transform_count": len(merged_transforms),
            "lineage_count": len(merged_lineage),
            "glossary_count": len(merged_glossary),
            "duration_seconds": round(elapsed, 2),
            "status": "success",
            "error": None,
        }

        # Record build completion with diff
        if db_pool and build_id:
            try:
                from catalog_engine.kb_tracker import complete_build
                glossary_term_list = list(merged_glossary.keys()) if isinstance(merged_glossary, dict) else [str(t) for t in merged_glossary]
                await complete_build(
                    db_pool, build_id, stats,
                    tables=merged_tables,
                    transforms=merged_transforms,
                    lineage=merged_lineage,
                    glossary_terms=glossary_term_list,
                    duration_seconds=elapsed,
                )
            except Exception as te:
                logger.warning("KB tracker complete failed: %s", te)

        _clear_checkpoint()

        # Upload KB to S3 for persistence across deploys
        try:
            from connectors.kb_storage import is_configured as s3_configured, upload_kb_to_s3
            if s3_configured():
                _log("Uploading KB to S3...")
                s3_result = upload_kb_to_s3(str(knowledge_dir))
                stats["s3_upload"] = s3_result
                _log(f"S3 upload: {s3_result.get('files', 0)} files")
        except Exception as e:
            logger.warning("S3 upload failed (non-fatal): %s", e)

        return stats

    except Exception as e:
        elapsed = time.time() - start
        logger.exception("Catalog build failed")

        # Record build failure
        if db_pool and build_id:
            try:
                from catalog_engine.kb_tracker import fail_build
                await fail_build(db_pool, build_id, str(e), elapsed)
            except Exception:
                pass

        _last_build_status = {
            "last_refresh_time": datetime.now(timezone.utc).isoformat(),
            "table_count": 0,
            "transform_count": 0,
            "lineage_count": 0,
            "glossary_count": 0,
            "duration_seconds": round(elapsed, 2),
            "status": "error",
            "error": str(e),
        }
        raise


async def preview_catalog(
    config,
    db_pool,
    session_id: str | None = None,
) -> dict:
    """
    Dry-run catalog build — returns what would change without writing files.
    """
    knowledge_dir = Path(config.KNOWLEDGE_DIR)
    catalog_path = knowledge_dir / "catalog.json"

    # Load existing catalog for comparison
    if catalog_path.exists():
        with open(catalog_path) as f:
            existing = json.load(f)
    else:
        existing = {"tables": [], "transforms": [], "lineage": {}}

    existing_table_keys = {
        f"{t['schema']}.{t['name']}" for t in existing.get("tables", [])
    }
    existing_transform_ids = {
        t["dag_id"] for t in existing.get("transforms", [])
    }

    changes: dict[str, Any] = {
        "new_tables": [],
        "new_transforms": [],
        "updated_tables": [],
        "redshift_available": getattr(config, "REDSHIFT_MODE", "mock") != "mock",
        "repo_configured": bool(
            getattr(config, "REPO_PATH_KB", "") or getattr(config, "REPO_PATH", os.getenv("REPO_PATH", ""))
        ),
    }

    # Check Redshift
    if changes["redshift_available"]:
        try:
            from catalog_engine.redshift_metadata import fetch_redshift_metadata
            redshift_tables = await fetch_redshift_metadata(
                environment="np", session_id=session_id
            )
            for t in redshift_tables:
                key = f"{t['schema']}.{t['name']}"
                if key not in existing_table_keys:
                    changes["new_tables"].append(key)
                else:
                    changes["updated_tables"].append(key)
        except Exception as e:
            changes["redshift_error"] = str(e)

    # Check repo (KB clone)
    repo_path = getattr(config, "REPO_PATH_KB", "") or getattr(config, "REPO_PATH", os.getenv("REPO_PATH", ""))
    if repo_path:
        try:
            from catalog_engine.repo_parser import parse_repo
            repo_result = parse_repo(repo_path)
            for t in repo_result["transforms"]:
                if t["dag_id"] not in existing_transform_ids:
                    changes["new_transforms"].append(t["dag_id"])
        except Exception as e:
            changes["repo_error"] = str(e)

    return changes


# ---------------------------------------------------------------------------
# CLI entry point: python -m catalog_engine.builder
# ---------------------------------------------------------------------------

def _cli_main():
    """CLI entry point for manual catalog builds."""
    parser = argparse.ArgumentParser(description="Jennie Catalog Engine — build data catalog")
    parser.add_argument(
        "--env", default="np", choices=["np", "prd"],
        help="Redshift environment (default: np)",
    )
    parser.add_argument(
        "--knowledge-dir", default=None,
        help="Override knowledge directory path",
    )
    parser.add_argument(
        "--repo-path", default=None,
        help="Path to data platform repo",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing files",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Add parent directory to path so imports work
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from config import config as app_config

    if args.knowledge_dir:
        app_config.KNOWLEDGE_DIR = args.knowledge_dir
    if args.repo_path:
        app_config.REPO_PATH_KB = args.repo_path  # type: ignore[attr-defined]

    async def _run():
        import asyncpg
        dsn = app_config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        try:
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        except Exception as e:
            logger.warning("Could not connect to postgres: %s — continuing without glossary feedback", e)
            pool = None

        try:
            if args.dry_run:
                result = await preview_catalog(app_config, pool)
                print(json.dumps(result, indent=2))
            else:
                result = await build_catalog(app_config, pool)
                print(json.dumps(result, indent=2))
        finally:
            if pool:
                await pool.close()

    asyncio.run(_run())


if __name__ == "__main__":
    _cli_main()
