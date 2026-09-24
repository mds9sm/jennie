"""
KB Enricher — AI-powered enrichment phase that runs after data fetch.

Each agent domain has an enrichment task that analyzes raw KB data and adds
structured insights. Uses Haiku for cost efficiency (~$0.001 per enrichment).

Enrichment tasks:
1. Pipeline: Summarize non-SQL DAGs from task names/operators
2. Glossary: Generate draft descriptions for undocumented tables
3. Redshift: Generate column descriptions from name patterns + data types
4. Metrics: Detect duplicate/conflicting metrics across pillars
5. Repo: Cross-reference repo configs with MWAA data (flag gaps)
"""

import json
import logging
from typing import Any

logger = logging.getLogger("genie.kb_enricher")

# Token budget for entire enrichment phase per build
# Default 100K tokens — roughly $1.50 on Opus, $0.10 on Haiku
MAX_ENRICHMENT_TOKENS = 100_000

_token_usage = {"input": 0, "output": 0}


def _reset_token_usage():
    _token_usage["input"] = 0
    _token_usage["output"] = 0


def _total_tokens() -> int:
    return _token_usage["input"] + _token_usage["output"]


def _budget_remaining() -> int:
    return max(0, MAX_ENRICHMENT_TOKENS - _total_tokens())


def _track_usage(resp):
    """Track token usage from an API response."""
    if hasattr(resp, "usage"):
        _token_usage["input"] += getattr(resp.usage, "input_tokens", 0)
        _token_usage["output"] += getattr(resp.usage, "output_tokens", 0)


async def _ai_batch(client, model: str, prompts: list[dict], label: str) -> list[str]:
    """Run a batch of AI enrichment calls. Stops if token budget exceeded."""
    results = []
    for i, p in enumerate(prompts):
        if _budget_remaining() <= 0:
            logger.warning("Token budget exhausted (%d used) — stopping %s at %d/%d",
                          _total_tokens(), label, i, len(prompts))
            results.extend([""] * (len(prompts) - i))
            break
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=300,
                system=p["system"],
                messages=[{"role": "user", "content": p["user"]}],
            )
            _track_usage(resp)
            results.append(resp.content[0].text if resp.content else "")
        except Exception as e:
            logger.warning("Enrichment %s [%d] failed: %s", label, i, e)
            results.append("")
    return results


async def enrich_pipeline_metadata(
    metadata_dags: list[dict],
    client,
    model: str,
    progress: dict | None = None,
) -> list[dict]:
    """Summarize what non-SQL DAGs do based on task names and operators."""
    if not metadata_dags:
        return metadata_dags

    system = (
        "You are a data pipeline expert. Given a DAG's task list and operator types, "
        "write a 1-2 sentence summary of what this DAG does. Be specific about data flow. "
        "Output ONLY the summary, nothing else."
    )

    # Batch DAGs that have task info
    to_enrich = [(i, d) for i, d in enumerate(metadata_dags)
                 if d.get("task_ids") and not d.get("summary")]

    if not to_enrich:
        return metadata_dags

    logger.info("Enriching %d DAGs with AI summaries", len(to_enrich))
    if progress:
        progress["mwaa_detail"] = f"AI enriching {len(to_enrich)} DAGs..."

    prompts = []
    for _, dag in to_enrich:
        dag_id = dag.get("dag_id", "")
        tasks = dag.get("task_ids", [])
        operators = dag.get("operator_types", [])
        schedule = dag.get("schedule", "")
        user_text = (
            f"DAG: {dag_id}\n"
            f"Schedule: {schedule}\n"
            f"Tasks: {', '.join(tasks[:15])}\n"
            f"Operators: {', '.join(operators)}\n"
            f"Tags: {', '.join(dag.get('tags', []))}"
        )
        prompts.append({"system": system, "user": user_text})

    results = await _ai_batch(client, model, prompts, "pipeline")

    for (idx, _), summary in zip(to_enrich, results):
        if summary:
            metadata_dags[idx]["summary"] = summary.strip()

    enriched = sum(1 for r in results if r)
    logger.info("Pipeline enrichment: %d/%d DAGs summarized", enriched, len(to_enrich))
    return metadata_dags


async def enrich_table_descriptions(
    tables: list[dict],
    client,
    model: str,
    progress: dict | None = None,
) -> list[dict]:
    """Generate descriptions for tables that have none, using column names + context."""
    if not tables:
        return tables

    system = (
        "You are a data catalog expert in the organization. "
        "Given a table's schema, name, and columns, write a 1-2 sentence description "
        "of what this table likely contains. Use platform domain knowledge. "
        "Output ONLY the description, nothing else."
    )

    to_enrich = [(i, t) for i, t in enumerate(tables)
                 if not t.get("description") and t.get("columns")]

    if not to_enrich:
        return tables

    # Limit to 50 tables per build to control costs
    to_enrich = to_enrich[:50]

    logger.info("Enriching %d tables with AI descriptions", len(to_enrich))
    if progress:
        progress["mwaa_detail"] = f"AI describing {len(to_enrich)} tables..."

    prompts = []
    for _, tbl in to_enrich:
        schema = tbl.get("schema", "")
        name = tbl.get("table_name", tbl.get("name", ""))
        cols = tbl.get("columns", [])
        col_names = [c.get("column_name", "") for c in cols[:20]]
        user_text = (
            f"Table: {schema}.{name}\n"
            f"Columns: {', '.join(col_names)}"
        )
        prompts.append({"system": system, "user": user_text})

    results = await _ai_batch(client, model, prompts, "table_desc")

    for (idx, _), desc in zip(to_enrich, results):
        if desc:
            tables[idx]["ai_description"] = desc.strip()

    enriched = sum(1 for r in results if r)
    logger.info("Table enrichment: %d/%d tables described", enriched, len(to_enrich))
    return tables


async def enrich_column_descriptions(
    tables: list[dict],
    client,
    model: str,
    progress: dict | None = None,
) -> list[dict]:
    """Generate descriptions for columns that have none, batched by table."""
    if not tables:
        return tables

    system = (
        "You are a data catalog expert in the organization. Given a table context and column names with types, "
        "generate a brief description for each column. Output as JSON: {\"column_name\": \"description\", ...}. "
        "Be specific to the organization's domain (the product surface, devices, subscriptions, content)."
    )

    # Find tables with undescribed columns
    to_enrich = []
    for i, tbl in enumerate(tables):
        cols = tbl.get("columns", [])
        undescribed = [c for c in cols if not c.get("description") and not c.get("ai_description")]
        if undescribed and len(undescribed) >= 3:  # only if enough columns need help
            to_enrich.append((i, tbl, undescribed))

    if not to_enrich:
        return tables

    # Limit to 30 tables per build
    to_enrich = to_enrich[:30]

    logger.info("Enriching columns for %d tables", len(to_enrich))
    if progress:
        progress["mwaa_detail"] = f"AI describing columns for {len(to_enrich)} tables..."

    prompts = []
    for _, tbl, undescribed in to_enrich:
        schema = tbl.get("schema", "")
        name = tbl.get("table_name", tbl.get("name", ""))
        col_info = ", ".join(f"{c.get('column_name', '')} ({c.get('data_type', '')})" for c in undescribed[:15])
        user_text = f"Table: {schema}.{name}\nColumns needing descriptions: {col_info}"
        prompts.append({"system": system, "user": user_text})

    results = await _ai_batch(client, model, prompts, "col_desc")

    for (idx, tbl, undescribed), result_text in zip(to_enrich, results):
        if not result_text:
            continue
        try:
            # Parse JSON response
            descs = json.loads(result_text)
            if isinstance(descs, dict):
                for col in tbl.get("columns", []):
                    col_name = col.get("column_name", "")
                    if col_name in descs and not col.get("description"):
                        col["ai_description"] = descs[col_name]
        except (json.JSONDecodeError, TypeError):
            pass

    logger.info("Column enrichment complete for %d tables", len(to_enrich))
    return tables


async def cross_reference_repo_mwaa(
    transforms: list[dict],
    repo_transforms: list[dict],
) -> dict:
    """Cross-reference repo configs with MWAA data. Flag gaps."""
    mwaa_dag_ids = {t.get("dag_id", "") for t in transforms}
    repo_dag_ids = {t.get("dag_id", "") for t in repo_transforms}

    in_mwaa_not_repo = sorted(mwaa_dag_ids - repo_dag_ids - {""})
    in_repo_not_mwaa = sorted(repo_dag_ids - mwaa_dag_ids - {""})
    in_both = sorted(mwaa_dag_ids & repo_dag_ids - {""})

    report = {
        "in_both": len(in_both),
        "in_mwaa_only": in_mwaa_not_repo[:20],  # cap for readability
        "in_repo_only": in_repo_not_mwaa[:20],
        "mwaa_only_count": len(in_mwaa_not_repo),
        "repo_only_count": len(in_repo_not_mwaa),
    }

    logger.info(
        "Cross-reference: %d in both, %d MWAA-only, %d repo-only",
        len(in_both), len(in_mwaa_not_repo), len(in_repo_not_mwaa),
    )
    return report


async def detect_metric_conflicts(
    metrics: list[dict],
) -> list[dict]:
    """Detect metrics with same name but different definitions across pillars."""
    by_name: dict[str, list[dict]] = {}
    for m in metrics:
        name = m.get("name", "").lower()
        if name:
            by_name.setdefault(name, []).append(m)

    conflicts = []
    for name, entries in by_name.items():
        if len(entries) > 1:
            # Check if SQL differs
            sqls = set()
            for e in entries:
                sql = e.get("sql_content", "") or ""
                if sql:
                    sqls.add(sql.strip().lower()[:500])
            if len(sqls) > 1:
                conflicts.append({
                    "metric": name,
                    "count": len(entries),
                    "sources": [e.get("dag_name", "") or e.get("view_table", "") for e in entries],
                    "issue": "Same metric name, different SQL definitions",
                })

    if conflicts:
        logger.info("Found %d metric conflicts", len(conflicts))
    return conflicts


async def run_enrichment(
    transforms: list[dict],
    metadata_dags: list[dict],
    tables: list[dict],
    metrics: list[dict],
    repo_transforms: list[dict],
    progress: dict | None = None,
    log_fn=None,
    db_pool=None,
) -> dict:
    """
    Run all enrichment tasks. Returns enrichment results.

    Uses Haiku via Bedrock or Anthropic for cost efficiency.
    """
    from config import config

    stats = {
        "pipeline_summaries": 0,
        "table_descriptions": 0,
        "column_descriptions": 0,
        "metric_conflicts": 0,
        "cross_reference": {},
    }

    # Resolve enrichment model
    model_choice = getattr(config, "_enrichment_model", "haiku")

    BEDROCK_MODELS = {
        "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "sonnet": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "opus": "us.anthropic.claude-opus-4-6-v1",
    }
    ANTHROPIC_MODELS = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6-20250514",
        "opus": "claude-opus-4-6-20250514",
    }

    try:
        if config.AI_PROVIDER == "bedrock":
            from catalog_engine.bedrock_auth import get_bedrock_client_async
            client, auth_source = await get_bedrock_client_async(config, db_pool)
            logger.info("KB enricher using Bedrock via %s", auth_source)
            model = BEDROCK_MODELS.get(model_choice, BEDROCK_MODELS["haiku"])
        else:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            model = ANTHROPIC_MODELS.get(model_choice, ANTHROPIC_MODELS["haiku"])
    except Exception as e:
        logger.warning("Could not create AI client for enrichment: %s", e)
        return stats

    _reset_token_usage()

    if log_fn:
        log_fn(f"Starting AI enrichment ({model_choice}, budget: {MAX_ENRICHMENT_TOKENS:,} tokens)...")

    # 1. Pipeline: summarize non-SQL DAGs
    try:
        metadata_dags = await enrich_pipeline_metadata(metadata_dags, client, model, progress)
        stats["pipeline_summaries"] = sum(1 for d in metadata_dags if d.get("summary"))
        if log_fn:
            log_fn(f"Pipeline: {stats['pipeline_summaries']} DAGs summarized")
    except Exception as e:
        logger.warning("Pipeline enrichment failed: %s", e)

    # 2. Table descriptions
    try:
        tables = await enrich_table_descriptions(tables, client, model, progress)
        stats["table_descriptions"] = sum(1 for t in tables if t.get("ai_description"))
        if log_fn:
            log_fn(f"Tables: {stats['table_descriptions']} descriptions generated")
    except Exception as e:
        logger.warning("Table enrichment failed: %s", e)

    # 3. Column descriptions
    try:
        tables = await enrich_column_descriptions(tables, client, model, progress)
        col_count = sum(
            sum(1 for c in t.get("columns", []) if c.get("ai_description"))
            for t in tables
        )
        stats["column_descriptions"] = col_count
        if log_fn:
            log_fn(f"Columns: {col_count} descriptions generated")
    except Exception as e:
        logger.warning("Column enrichment failed: %s", e)

    # 4. Metric conflicts (no AI needed)
    try:
        conflicts = await detect_metric_conflicts(metrics)
        stats["metric_conflicts"] = len(conflicts)
        if conflicts and log_fn:
            log_fn(f"Metrics: {len(conflicts)} conflicts detected")
    except Exception as e:
        logger.warning("Metric conflict detection failed: %s", e)

    # 5. Cross-reference repo vs MWAA (no AI needed)
    try:
        xref = await cross_reference_repo_mwaa(transforms, repo_transforms)
        stats["cross_reference"] = xref
        if log_fn:
            log_fn(f"Cross-ref: {xref.get('in_both', 0)} matched, {xref.get('mwaa_only_count', 0)} MWAA-only, {xref.get('repo_only_count', 0)} repo-only")
    except Exception as e:
        logger.warning("Cross-reference failed: %s", e)

    stats["tokens_used"] = _total_tokens()
    stats["tokens_input"] = _token_usage["input"]
    stats["tokens_output"] = _token_usage["output"]

    if log_fn:
        log_fn(f"AI enrichment complete — {_total_tokens():,} tokens used ({_token_usage['input']:,} in, {_token_usage['output']:,} out)")

    return stats
