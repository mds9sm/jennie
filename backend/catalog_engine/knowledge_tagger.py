"""
Knowledge Tagger — tags each knowledge item with its source provenance.

Each item in the KB gets a `knowledge` dict with source-specific data:
- platform: from MWAA (DAG runs, schedule, task stats)
- database: from Redshift (columns, types, COMMENTs, row counts)
- code: from Git repo (config, git blame, commit history)
- ai_generated: from enrichment phase (descriptions, summaries)
- user: from glossary entries, feedback, manual corrections

Trust hierarchy: user > database > platform > code > ai_generated
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("genie.knowledge_tagger")

TRUST_ORDER = ["user", "database", "platform", "code", "documents", "ai_generated"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tag_tables(
    tables: list[dict],
    redshift_tables: list[dict],
    mwaa_transforms: list[dict],
    repo_transforms: list[dict],
    glossary_entries: list[dict] | None = None,
) -> list[dict]:
    """Tag each table with knowledge sources."""

    # Build lookup maps
    mwaa_by_target: dict[str, dict] = {}
    for t in mwaa_transforms:
        target = t.get("target_table", "").lower()
        if target:
            mwaa_by_target[target] = t

    repo_by_target: dict[str, dict] = {}
    for t in repo_transforms:
        target = t.get("target_table", "").lower()
        if target:
            repo_by_target[target] = t

    rs_by_name: dict[str, dict] = {}
    for t in redshift_tables:
        key = f"{t.get('schema_name', '')}.{t.get('table_name', '')}".lower()
        rs_by_name[key] = t
        # Also index by short name
        rs_by_name[t.get("table_name", "").lower()] = t

    glossary_by_name: dict[str, dict] = {}
    if glossary_entries:
        for g in glossary_entries:
            key = g.get("term_key", "").lower()
            if key:
                glossary_by_name[key] = g

    for table in tables:
        schema = table.get("schema", "")
        name = table.get("table_name", table.get("name", ""))
        full_key = f"{schema}.{name}".lower()
        short_key = name.lower()

        knowledge: dict[str, Any] = {}

        # Database source (Redshift)
        rs = rs_by_name.get(full_key) or rs_by_name.get(short_key)
        if rs:
            knowledge["database"] = {
                "source": "redshift",
                "has_description": bool(rs.get("description")),
                "column_count": len(rs.get("columns", [])),
                "has_column_descriptions": any(c.get("description") for c in rs.get("columns", [])),
                "row_count": rs.get("row_count"),
                "updated_at": _now_iso(),
            }

        # Platform source (MWAA)
        mwaa = mwaa_by_target.get(short_key) or mwaa_by_target.get(full_key)
        if mwaa:
            knowledge["platform"] = {
                "source": "mwaa",
                "dag_id": mwaa.get("dag_id", ""),
                "schedule": mwaa.get("schedule", ""),
                "last_run": mwaa.get("last_run_date", ""),
                "run_state": mwaa.get("run_state", ""),
                "has_rendered_sql": bool(mwaa.get("rendered_sql")),
                "updated_at": _now_iso(),
            }

        # Code source (Git repo)
        repo = repo_by_target.get(short_key) or repo_by_target.get(full_key)
        if repo:
            knowledge["code"] = {
                "source": "git_repo",
                "config_path": repo.get("config_path", ""),
                "last_author": repo.get("git_author", ""),
                "last_commit_date": repo.get("git_date", ""),
                "has_yaml_config": bool(repo.get("config_path")),
                "updated_at": _now_iso(),
            }

        # AI-generated
        if table.get("ai_description"):
            knowledge["ai_generated"] = {
                "description": table["ai_description"],
                "updated_at": _now_iso(),
            }

        # User knowledge (glossary)
        glossary = glossary_by_name.get(short_key)
        if glossary and glossary.get("status") in ("approved", "merged"):
            knowledge["user"] = {
                "source": "glossary",
                "definition": glossary.get("definition", ""),
                "approved_by": glossary.get("reviewed_by", ""),
                "updated_at": glossary.get("updated_at", _now_iso()),
            }

        # Compute completeness score
        knowledge["_completeness"] = _compute_completeness(knowledge)
        knowledge["_sources"] = sorted(knowledge.keys() - {"_completeness", "_sources"})

        table["knowledge"] = knowledge

    return tables


def tag_transforms(
    transforms: list[dict],
    repo_transforms: list[dict],
) -> list[dict]:
    """Tag each transform with knowledge sources."""

    repo_by_dag: dict[str, dict] = {}
    for t in repo_transforms:
        dag_id = t.get("dag_id", "")
        if dag_id:
            repo_by_dag[dag_id] = t

    for transform in transforms:
        dag_id = transform.get("dag_id", "")
        knowledge: dict[str, Any] = {}

        # Platform source (always present for transforms from MWAA)
        if transform.get("rendered_sql") or transform.get("run_state"):
            knowledge["platform"] = {
                "source": "mwaa",
                "has_rendered_sql": bool(transform.get("rendered_sql")),
                "task_count": len(transform.get("task_stats", {})),
                "last_run": transform.get("last_run_date", ""),
                "run_state": transform.get("run_state", ""),
                "updated_at": _now_iso(),
            }

        # Code source
        repo = repo_by_dag.get(dag_id)
        if repo:
            knowledge["code"] = {
                "source": "git_repo",
                "config_path": repo.get("config_path", ""),
                "last_author": repo.get("git_author", ""),
                "last_commit_date": repo.get("git_date", ""),
                "updated_at": _now_iso(),
            }

        # AI-generated (from enrichment)
        if transform.get("summary"):
            knowledge["ai_generated"] = {
                "summary": transform["summary"],
                "updated_at": _now_iso(),
            }

        knowledge["_completeness"] = _compute_completeness(knowledge)
        knowledge["_sources"] = sorted(knowledge.keys() - {"_completeness", "_sources"})

        transform["knowledge"] = knowledge

    return transforms


def _compute_completeness(knowledge: dict) -> float:
    """Score 0-1 based on how many source types are present."""
    source_count = len([k for k in knowledge if not k.startswith("_")])
    max_sources = 5  # platform, database, code, ai_generated, user
    return round(min(source_count / max_sources, 1.0), 2)


def build_knowledge_summary(tables: list[dict], transforms: list[dict]) -> dict:
    """Build a summary of knowledge coverage for agents."""
    table_sources: dict[str, int] = {}
    table_completeness = []
    for t in tables:
        k = t.get("knowledge", {})
        for src in k.get("_sources", []):
            table_sources[src] = table_sources.get(src, 0) + 1
        table_completeness.append(k.get("_completeness", 0))

    transform_sources: dict[str, int] = {}
    for t in transforms:
        k = t.get("knowledge", {})
        for src in k.get("_sources", []):
            transform_sources[src] = transform_sources.get(src, 0) + 1

    avg_completeness = round(sum(table_completeness) / max(len(table_completeness), 1), 2)

    # Find items with lowest coverage
    low_coverage_tables = sorted(
        [(t.get("table_name", t.get("name", "")), t.get("knowledge", {}).get("_completeness", 0))
         for t in tables],
        key=lambda x: x[1],
    )[:10]

    return {
        "tables": {
            "total": len(tables),
            "by_source": table_sources,
            "avg_completeness": avg_completeness,
            "low_coverage": low_coverage_tables,
        },
        "transforms": {
            "total": len(transforms),
            "by_source": transform_sources,
        },
        "trust_hierarchy": TRUST_ORDER,
    }
