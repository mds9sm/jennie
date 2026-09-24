"""
KB Build Tracker — records every knowledge base build with diffs and snapshots.

Each build creates a record in kb_builds with:
- Stats (counts, duration)
- Snapshot (current table/transform/glossary names)
- Diff vs previous build (added/removed/changed)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("genie.kb_tracker")


async def ensure_table(db_pool):
    """Create kb_builds table if it doesn't exist."""
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS kb_builds (
            id              BIGSERIAL PRIMARY KEY,
            status          TEXT NOT NULL DEFAULT 'running',
            triggered_by    TEXT DEFAULT 'manual',
            duration_seconds NUMERIC(10,2),
            sources         JSONB DEFAULT '{}',
            stats           JSONB DEFAULT '{}',
            diff            JSONB DEFAULT '{}',
            snapshot        JSONB DEFAULT '{}',
            progress        JSONB DEFAULT '{}',
            error           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Add progress column if missing (existing DBs)
    try:
        await db_pool.execute("""
            ALTER TABLE kb_builds ADD COLUMN IF NOT EXISTS progress JSONB DEFAULT '{}'
        """)
    except Exception:
        pass  # Column already exists or DB doesn't support IF NOT EXISTS


async def start_build(db_pool, sources: dict, triggered_by: str = "manual") -> int:
    """Record the start of a KB build. Returns the build ID."""
    await ensure_table(db_pool)
    row = await db_pool.fetchrow("""
        INSERT INTO kb_builds (status, triggered_by, sources)
        VALUES ('running', $1, $2::jsonb)
        RETURNING id
    """, triggered_by, json.dumps(sources))
    build_id = row["id"]
    logger.info("KB build #%d started (triggered by %s)", build_id, triggered_by)
    return build_id


async def queue_build(db_pool, sources: dict, triggered_by: str = "manual") -> int:
    """Insert a queued KB build row. Returns the build ID.

    Used by the API when KB_BUILD_MODE=job — the build_job container picks it up.
    """
    await ensure_table(db_pool)
    row = await db_pool.fetchrow("""
        INSERT INTO kb_builds (status, triggered_by, sources)
        VALUES ('queued', $1, $2::jsonb)
        RETURNING id
    """, triggered_by, json.dumps(sources))
    build_id = row["id"]
    logger.info("KB build #%d queued (triggered by %s)", build_id, triggered_by)
    return build_id


async def update_build_progress(db_pool, build_id: int, progress_dict: dict):
    """Write the live progress dict to the kb_builds row."""
    try:
        await db_pool.execute(
            "UPDATE kb_builds SET progress = $1::jsonb WHERE id = $2",
            json.dumps(progress_dict, default=str), build_id,
        )
    except Exception as e:
        logger.warning("Failed to update build progress for #%d: %s", build_id, e)


async def get_build_progress(db_pool, build_id: int) -> dict:
    """Read the live progress dict from the kb_builds row."""
    row = await db_pool.fetchrow(
        "SELECT progress, status FROM kb_builds WHERE id = $1", build_id,
    )
    if not row:
        return {}
    progress = row["progress"]
    if isinstance(progress, str):
        progress = json.loads(progress)
    return progress or {}


def _build_snapshot(tables: list, transforms: list, lineage: dict, glossary_terms: list) -> dict:
    """Build a lightweight snapshot of current KB state."""
    return {
        "tables": sorted(set(
            f"{t.get('schema', '')}.{t.get('name', t.get('table_name', ''))}"
            for t in tables
        )),
        "transforms": sorted(set(
            t.get("dag_id", t.get("name", "")) for t in transforms
        )),
        "lineage_count": len(lineage) if isinstance(lineage, dict) else 0,
        "glossary_terms": sorted(glossary_terms),
    }


def _compute_diff(prev_snapshot: dict, curr_snapshot: dict) -> dict:
    """Compute what changed between two KB snapshots."""
    diff = {}

    for category in ("tables", "transforms", "glossary_terms"):
        prev_set = set(prev_snapshot.get(category, []))
        curr_set = set(curr_snapshot.get(category, []))

        added = sorted(curr_set - prev_set)
        removed = sorted(prev_set - curr_set)
        unchanged = len(prev_set & curr_set)

        if added or removed:
            diff[category] = {
                "added": added,
                "removed": removed,
                "added_count": len(added),
                "removed_count": len(removed),
                "unchanged_count": unchanged,
            }
        else:
            diff[category] = {
                "added": [], "removed": [],
                "added_count": 0, "removed_count": 0,
                "unchanged_count": unchanged,
            }

    # Lineage count change
    prev_lc = prev_snapshot.get("lineage_count", 0)
    curr_lc = curr_snapshot.get("lineage_count", 0)
    diff["lineage"] = {
        "previous_count": prev_lc,
        "current_count": curr_lc,
        "delta": curr_lc - prev_lc,
    }

    return diff


async def complete_build(
    db_pool,
    build_id: int,
    stats: dict,
    tables: list,
    transforms: list,
    lineage: dict,
    glossary_terms: list,
    duration_seconds: float,
):
    """Record a successful build with snapshot and diff."""
    # Build current snapshot
    snapshot = _build_snapshot(tables, transforms, lineage, glossary_terms)

    # Get previous build's snapshot for diff
    prev_row = await db_pool.fetchrow("""
        SELECT snapshot FROM kb_builds
        WHERE status = 'success' AND id < $1
        ORDER BY id DESC LIMIT 1
    """, build_id)

    prev_snapshot = {}
    if prev_row and prev_row["snapshot"]:
        prev_snapshot = json.loads(prev_row["snapshot"]) if isinstance(prev_row["snapshot"], str) else prev_row["snapshot"]

    diff = _compute_diff(prev_snapshot, snapshot)

    await db_pool.execute("""
        UPDATE kb_builds SET
            status = 'success',
            duration_seconds = $2,
            stats = $3::jsonb,
            snapshot = $4::jsonb,
            diff = $5::jsonb
        WHERE id = $1
    """,
        build_id,
        round(duration_seconds, 2),
        json.dumps(stats),
        json.dumps(snapshot),
        json.dumps(diff),
    )

    # Log summary
    for cat, d in diff.items():
        if isinstance(d, dict) and (d.get("added_count", 0) or d.get("removed_count", 0)):
            logger.info("KB diff [%s]: +%d -%d (=%d unchanged)",
                       cat, d.get("added_count", 0), d.get("removed_count", 0), d.get("unchanged_count", 0))

    logger.info("KB build #%d completed in %.1fs", build_id, duration_seconds)


async def fail_build(db_pool, build_id: int, error: str, duration_seconds: float):
    """Record a failed build."""
    await db_pool.execute("""
        UPDATE kb_builds SET status = 'error', error = $2, duration_seconds = $3
        WHERE id = $1
    """, build_id, error[:2000], round(duration_seconds, 2))
    logger.error("KB build #%d failed: %s", build_id, error[:200])


async def get_build_history(db_pool, limit: int = 20) -> list[dict]:
    """Get recent KB builds."""
    await ensure_table(db_pool)
    rows = await db_pool.fetch("""
        SELECT id, status, triggered_by, duration_seconds, sources, stats, diff,
               error, created_at
        FROM kb_builds
        ORDER BY created_at DESC
        LIMIT $1
    """, limit)
    result = []
    for r in rows:
        d = dict(r)
        for field in ("sources", "stats", "diff"):
            if isinstance(d.get(field), str):
                d[field] = json.loads(d[field])
        result.append(d)
    return result


async def get_build_detail(db_pool, build_id: int) -> dict | None:
    """Get full detail of a specific build including snapshot."""
    row = await db_pool.fetchrow("SELECT * FROM kb_builds WHERE id = $1", build_id)
    if not row:
        return None
    d = dict(row)
    for field in ("sources", "stats", "diff", "snapshot"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    return d
