"""
KB Agent Enricher — build-mode implementation.

Runs during KB build to synthesize metadata from all sources into
high-quality glossary entries, table descriptions, and pipeline summaries.

Uses the same AI client as the chat agents (Sonnet for speed).
Processes items in batches, writes to postgres glossary_entries.
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("genie.kb_agent_enricher")


async def run_kb_agent_enrichment(
    kb_state: dict,
    db_pool,
    session_id: str | None = None,
    log_fn=None,
    progress=None,
) -> dict:
    """
    Run KB Agent enrichment over all collected data.

    Instead of separate batch loops for DAGs, tables, and glossary,
    this processes each item with full cross-referenced context.
    """
    tables = kb_state.get("tables", [])
    transforms = kb_state.get("transforms", [])
    metadata_dags = kb_state.get("metadata_dags", [])
    metrics = kb_state.get("metrics", [])
    lineage = kb_state.get("lineage", {})

    # Load DOMO catalog if available
    domo_catalog = []
    domo_path = kb_state.get("domo_catalog")
    if domo_path and Path(domo_path).exists():
        with open(domo_path) as f:
            domo_catalog = json.load(f)

    # Create AI client
    from config import config
    model_choice = getattr(config, "_enrichment_model", "sonnet")
    client, model = await _create_client(config, model_choice, db_pool)
    if not client:
        raise RuntimeError("Could not create AI client for KB Agent enrichment")

    if log_fn:
        log_fn(f"KB Agent using {model_choice} model for enrichment")

    stats = {
        "glossary_entries": 0,
        "dag_summaries": 0,
        "table_descriptions": 0,
        "enriched_tables": {},
        "enriched_transforms": {},
    }

    # Token budget tracking
    from catalog_engine.kb_enricher import _budget_remaining, _track_usage, _reset_token_usage
    _reset_token_usage()

    # Build lookup indexes for cross-referencing
    table_index = {f"{t.get('schema','')}.{t.get('name','')}": t for t in tables}
    transform_index = {t.get("dag_id", ""): t for t in transforms}
    metric_index = {m.get("name", ""): m for m in domo_catalog}
    lineage_index = lineage if isinstance(lineage, dict) else {}

    # ── Phase 1: Enrich high-value transforms (DAGs with DOMO downstream) ──
    if log_fn:
        log_fn("Phase 1: Enriching transforms with AI summaries...")

    dags_to_enrich = [t for t in transforms if not t.get("ai_summary")]
    # Prioritize: DOMO-linked first, then by run frequency
    domo_linked_dags = {m.get("transform_dag", "") for m in domo_catalog if m.get("transform_dag")}

    for i, t in enumerate(dags_to_enrich):
        if _budget_remaining() <= 0:
            if log_fn:
                log_fn(f"Token budget exhausted at DAG {i}/{len(dags_to_enrich)}")
            break

        dag_id = t.get("dag_id", "")
        name = t.get("name", "")

        # Build context for this DAG
        context = f"Pipeline: {name} (DAG: {dag_id})\n"
        if t.get("target_table"):
            context += f"Target: {t['target_table']}\n"
        if t.get("schedule"):
            context += f"Schedule: {t['schedule']}\n"
        if t.get("run_state"):
            context += f"Last run: {t['run_state']}\n"
        if dag_id in domo_linked_dags:
            context += "Feeds DOMO executive dashboard\n"

        # Check if target table has column info
        target = t.get("target_table", "")
        if target and target in table_index:
            tbl = table_index[target]
            cols = [c.get("name", "") for c in tbl.get("columns", [])[:10]]
            if cols:
                context += f"Columns: {', '.join(cols)}\n"

        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=150,
                system="You are a data platform expert. Write a 2-sentence business summary of this pipeline. What does it produce and who uses it? No technical jargon.",
                messages=[{"role": "user", "content": context}],
            )
            _track_usage(resp)
            summary = resp.content[0].text.strip() if resp.content else ""
            if summary and len(summary) > 15:
                t["ai_summary"] = summary
                stats["enriched_transforms"][dag_id] = summary
                stats["dag_summaries"] += 1
        except Exception as e:
            logger.debug("DAG summary failed for %s: %s", dag_id, str(e)[:80])

        if progress and i % 20 == 0:
            progress(f"KB Agent: DAG summaries {i}/{len(dags_to_enrich)}")

    if log_fn:
        log_fn(f"Phase 1 done: {stats['dag_summaries']} DAG summaries")

    # ── Phase 2: Enrich tables with AI descriptions ──
    if log_fn:
        log_fn("Phase 2: Enriching tables with AI descriptions...")

    tables_to_enrich = [t for t in tables if not t.get("ai_description") and t.get("columns")]
    # Prioritize: tables with COMMENT descriptions, high row counts, DOMO-linked
    tables_to_enrich.sort(key=lambda t: (
        bool(t.get("description")),  # has COMMENT ON
        t.get("row_count_estimate", 0) or 0,
    ), reverse=True)

    for i, tbl in enumerate(tables_to_enrich[:100]):  # cap at 100
        if _budget_remaining() <= 0:
            break

        schema = tbl.get("schema", "")
        name = tbl.get("name", "")
        key = f"{schema}.{name}"

        context = f"Table: {schema}.{name}\n"
        if tbl.get("description"):
            context += f"Comment: {tbl['description']}\n"
        cols = tbl.get("columns", [])[:15]
        if cols:
            context += f"Columns: {', '.join(c.get('name','') for c in cols)}\n"
        if tbl.get("row_count_estimate"):
            context += f"Rows: {tbl['row_count_estimate']:,}\n"
        if tbl.get("table_type_auto"):
            context += f"Type: {tbl['table_type_auto']}\n"
        # Check lineage
        lin = lineage_index.get(key, {})
        if isinstance(lin, dict):
            up = lin.get("upstream", [])
            down = lin.get("downstream", [])
            if up:
                context += f"Fed by: {', '.join(up[:3])}\n"
            if down:
                context += f"Feeds: {', '.join(down[:3])}\n"
        # Check if it's a DOMO metric source
        for m in domo_catalog:
            if key in [s.lower() for s in m.get("source_tables", [])]:
                context += f"Used by DOMO metric: {m['name']} (pillar: {m.get('pillar','')})\n"
                break

        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=150,
                system="You are a data platform expert. Write a 2-sentence business description of this table. What data does it hold and who uses it? No SQL or technical column names.",
                messages=[{"role": "user", "content": context}],
            )
            _track_usage(resp)
            desc = resp.content[0].text.strip() if resp.content else ""
            if desc and len(desc) > 15:
                tbl["ai_description"] = desc
                stats["enriched_tables"][key] = desc
                stats["table_descriptions"] += 1
        except Exception as e:
            logger.debug("Table description failed for %s: %s", key, str(e)[:80])

        if progress and i % 20 == 0:
            progress(f"KB Agent: table descriptions {i}/{min(len(tables_to_enrich), 100)}")

    if log_fn:
        log_fn(f"Phase 2 done: {stats['table_descriptions']} table descriptions")

    # ── Phase 3: Synthesize glossary entries from all sources ──
    if log_fn:
        log_fn("Phase 3: KB Agent synthesizing glossary entries...")

    # Build items that need glossary entries — DOMO metrics not yet in glossary
    existing_terms = set()
    try:
        rows = await db_pool.fetch("SELECT term_key FROM glossary_entries")
        existing_terms = {r["term_key"] for r in rows}
    except Exception:
        pass

    items_to_enrich = []
    for m in domo_catalog:
        term_key = m.get("name", "").lower()
        if term_key and term_key not in existing_terms:
            items_to_enrich.append(("metric", m))

    # Also add high-value tables not in glossary
    for tbl in tables:
        name = tbl.get("name", "").lower()
        if name and name not in existing_terms and tbl.get("description"):
            items_to_enrich.append(("table", tbl))

    if log_fn:
        log_fn(f"Phase 3: {len(items_to_enrich)} items need glossary entries")

    for i, (item_type, item) in enumerate(items_to_enrich[:150]):  # cap
        if _budget_remaining() <= 0:
            break

        if item_type == "metric":
            name = item.get("name", "")
            context = f"DOMO Metric: {name}\n"
            if item.get("pillar"):
                context += f"Pillar: {item['pillar']}\n"
            s3 = item.get("s3_metadata") or {}
            s3_cols = s3.get("columns", [])
            if isinstance(s3_cols, list) and s3_cols and isinstance(s3_cols[0], str):
                visible = [c for c in s3_cols if not c.startswith("_BATCH")]
                if visible:
                    context += f"Dashboard columns: {', '.join(visible[:10])}\n"
            if item.get("source_tables"):
                context += f"Source tables: {', '.join(item['source_tables'][:3])}\n"
            if item.get("transform_dag"):
                context += f"Pipeline: {item['transform_dag']}\n"
        else:
            name = item.get("name", "")
            context = f"Table: {item.get('schema','')}.{name}\n"
            if item.get("description"):
                context += f"Comment: {item['description']}\n"
            if item.get("ai_description"):
                context += f"Description: {item['ai_description']}\n"

        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=200,
                system="You are a data glossary expert in the organization. Write a 3-sentence business definition for this data asset. What does it measure/contain, who uses it, and why does it matter? Start with 'Business definition:'",
                messages=[{"role": "user", "content": context}],
            )
            _track_usage(resp)
            definition = resp.content[0].text.strip() if resp.content else ""
            if definition and len(definition) > 20:
                definition = definition.replace("\x00", "")
                term_key = name.lower()
                content_hash = hashlib.md5(definition.encode()).hexdigest()
                pillar = item.get("pillar", "") if item_type == "metric" else ""
                source_tables = item.get("source_tables", []) if item_type == "metric" else []

                sources = [{"type": "kb_agent", "label": "KB Agent",
                           "detail": f"Synthesized from {item_type} metadata"}]

                await db_pool.execute("""
                    INSERT INTO glossary_entries (
                        term_key, term, definition, source_tables, confidence,
                        status, workflow_state, auto_generated, sql_hash, sources,
                        created_by, created_by_type
                    ) VALUES ($1, $2, $3, $4::jsonb, $5, 'draft', 'draft', true, $6, $7::jsonb,
                              'kb_agent', 'kb_agent')
                    ON CONFLICT (term_key) DO UPDATE SET
                        definition = $3, source_tables = $4::jsonb, confidence = $5,
                        sql_hash = $6, sources = $7::jsonb, updated_at = NOW()
                    WHERE glossary_entries.status = 'draft' OR glossary_entries.workflow_state = 'draft'
                """,
                    term_key,
                    name.replace("_", " ").title(),
                    definition,
                    json.dumps(source_tables),
                    0.6 if pillar else 0.4,
                    content_hash,
                    json.dumps(sources),
                )
                stats["glossary_entries"] += 1
        except Exception as e:
            logger.debug("Glossary entry failed for %s: %s", name, str(e)[:80])

        if progress and i % 20 == 0:
            progress(f"KB Agent: glossary entries {i}/{min(len(items_to_enrich), 150)}")

    if log_fn:
        log_fn(f"Phase 3 done: {stats['glossary_entries']} glossary entries created")
        log_fn(f"KB Agent enrichment complete: {stats['dag_summaries']} DAGs, "
               f"{stats['table_descriptions']} tables, {stats['glossary_entries']} glossary")

    return stats


async def _create_client(config, model_choice: str = "sonnet", db_pool=None):
    """Create AI client for KB Agent enrichment."""
    try:
        if config.AI_PROVIDER == "bedrock":
            from catalog_engine.bedrock_auth import get_bedrock_client_async

            BEDROCK_MODELS = {
                "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                "sonnet": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                "opus": "us.anthropic.claude-opus-4-6-v1",
            }
            client, auth_source = await get_bedrock_client_async(config, db_pool)
            logger.info("KB Agent enricher using Bedrock via %s", auth_source)
            return client, BEDROCK_MODELS.get(model_choice, BEDROCK_MODELS["sonnet"])
        else:
            import anthropic
            ANTHROPIC_MODELS = {
                "haiku": "claude-haiku-4-5-20251001",
                "sonnet": "claude-sonnet-4-20250514",
                "opus": "claude-opus-4-6-20250514",
            }
            client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            return client, ANTHROPIC_MODELS.get(model_choice, ANTHROPIC_MODELS["sonnet"])
    except Exception as e:
        logger.error("Failed to create AI client: %s", e)
        return None, None
