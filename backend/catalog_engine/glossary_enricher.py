"""
Auto-Glossary Enricher — generates glossary entries from multiple sources.

Sources (merged per entry):
1. View SQL definitions (CREATE VIEW → formulas, source tables, dimensions)
2. Redshift metadata (COMMENT ON TABLE/COLUMN → descriptions)
3. Repo configs (YAML → owners, schedules, pillar tags)

Entries are stored as "draft" in postgres for expert review.
Approved entries persist across refreshes. Human opinion always wins.
"""

import json
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("genie.glossary_enricher")

# Aggregation patterns that indicate metrics
AGG_PATTERN = re.compile(
    r"(COUNT|SUM|AVG|MIN|MAX|MEDIAN|PERCENTILE_CONT|LISTAGG)\s*\(\s*(DISTINCT\s+)?(.+?)\)",
    re.IGNORECASE,
)

# GROUP BY extraction
GROUP_BY_PATTERN = re.compile(
    r"GROUP\s+BY\s+(.+?)(?:HAVING|ORDER|LIMIT|UNION|\)|;|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# WHERE clause extraction
WHERE_PATTERN = re.compile(
    r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|UNION|\)|;|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Table references
TABLE_PATTERN = re.compile(
    r"(?:FROM|JOIN)\s+(?:(\w+)\.)?(\w+)\.(\w+)",
    re.IGNORECASE,
)


def _extract_aggregations(sql: str) -> list[dict]:
    """Extract aggregation functions from SQL — these define the metrics."""
    aggs = []
    for match in AGG_PATTERN.finditer(sql):
        func = match.group(1).upper()
        distinct = bool(match.group(2))
        expr = match.group(3).strip()
        expr = re.sub(r"\s+", " ", expr)
        if len(expr) > 100:
            expr = expr[:100] + "..."
        aggs.append({
            "function": func,
            "distinct": distinct,
            "expression": expr,
            "formula": f"{func}({'DISTINCT ' if distinct else ''}{expr})",
        })
    return aggs


def _extract_group_by(sql: str) -> list[str]:
    """Extract GROUP BY columns — these are the dimensions."""
    match = GROUP_BY_PATTERN.search(sql)
    if not match:
        return []
    group_text = match.group(1).strip()
    cols = []
    for part in group_text.split(","):
        col = part.strip()
        if col.isdigit():
            continue
        col = col.split(".")[-1] if "." in col else col
        col = col.strip('"').strip("'")
        if col and len(col) < 60:
            cols.append(col)
    return cols


def _extract_where_summary(sql: str) -> str:
    """Extract a brief summary of WHERE conditions."""
    match = WHERE_PATTERN.search(sql)
    if not match:
        return ""
    where_text = match.group(1).strip()
    if len(where_text) > 200:
        where_text = where_text[:200] + "..."
    return where_text


def _extract_source_tables(sql: str) -> list[str]:
    """Extract source tables from FROM/JOIN."""
    refs = []
    for match in TABLE_PATTERN.finditer(sql):
        db, schema, table = match.groups()
        if not schema or not table:
            continue
        if schema.upper() in ("SELECT", "WHERE", "GROUP", "ORDER", "WITH", "AS"):
            continue
        if len(schema) <= 2 and schema.isalpha():
            continue
        if db:
            refs.append(f"{db}.{schema}.{table}")
        else:
            refs.append(f"{schema}.{table}")
    return list(set(refs))


def generate_glossary_entry(
    view_name: str,
    view_schema: str,
    sql_content: str,
    dag_name: str = "",
    domo_dataset_id: str = "",
) -> dict:
    """Generate a draft glossary entry from a view's SQL definition."""
    aggs = _extract_aggregations(sql_content)
    dimensions = _extract_group_by(sql_content)
    source_tables = _extract_source_tables(sql_content)
    where_summary = _extract_where_summary(sql_content)

    term = view_name.replace("_", " ").title()
    formulas = [a["formula"] for a in aggs]
    formula_str = "; ".join(formulas[:5]) if formulas else "View definition (no aggregation detected)"

    parts = []
    if aggs:
        metric_types = set(a["function"] for a in aggs)
        parts.append(f"Computes {', '.join(metric_types).lower()} metrics")
    if source_tables:
        short_tables = [t.split(".")[-1] for t in source_tables[:4]]
        parts.append(f"from {', '.join(short_tables)}")
    if dimensions:
        parts.append(f"grouped by {', '.join(dimensions[:5])}")
    if where_summary and len(where_summary) < 100:
        parts.append(f"filtered by {where_summary}")

    definition = " ".join(parts) + "." if parts else f"Redshift view: {view_schema}.{view_name}"

    confidence = 0.3
    if aggs:
        confidence += 0.3
    if dimensions:
        confidence += 0.2
    if source_tables:
        confidence += 0.1
    if domo_dataset_id:
        confidence += 0.1

    return {
        "term": term,
        "term_key": view_name,
        "definition": definition,
        "formula": formula_str,
        "source_tables": source_tables,
        "dimensions": dimensions,
        "filters": where_summary,
        "dag": dag_name,
        "domo_dataset_id": domo_dataset_id,
        "view": f"{view_schema}.{view_name}" if view_schema else view_name,
        "confidence": round(confidence, 2),
        "aggregations": aggs,
    }


async def ai_rewrite_definitions(db_pool, log_fn=None):
    """
    AI rewrites technical glossary definitions into business-friendly language.
    Only rewrites draft entries that are still auto-generated (never touches human edits).
    Uses the configured enrichment model.
    """
    from config import config

    rows = await db_pool.fetch("""
        SELECT id, term, term_key, definition, formula, source_tables, view_name, dag,
               domo_dataset_id, sources, expert_notes
        FROM glossary_entries
        WHERE auto_generated = true AND workflow_state = 'draft'
          AND definition NOT LIKE 'Business definition:%'
        ORDER BY confidence DESC
        LIMIT 100
    """)

    if not rows:
        return 0

    if log_fn:
        log_fn(f"AI rewriting {len(rows)} glossary definitions...")

    # Create AI client
    try:
        model_choice = getattr(config, "_enrichment_model", "opus")
        if config.AI_PROVIDER == "bedrock":
            from catalog_engine.bedrock_auth import get_bedrock_client_async

            BEDROCK_MODELS = {
                "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                "sonnet": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                "opus": "us.anthropic.claude-opus-4-6-v1",
            }
            client, auth_source = await get_bedrock_client_async(config, db_pool)
            logger.info("Glossary enricher using Bedrock via %s", auth_source)
            model = BEDROCK_MODELS.get(model_choice, BEDROCK_MODELS["opus"])
        else:
            import anthropic
            ANTHROPIC_MODELS = {
                "haiku": "claude-haiku-4-5-20251001",
                "sonnet": "claude-sonnet-4-6-20250514",
                "opus": "claude-opus-4-6-20250514",
            }
            client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            model = ANTHROPIC_MODELS.get(model_choice, ANTHROPIC_MODELS["opus"])
    except Exception as e:
        logger.warning("Could not create AI client for glossary rewrite: %s", e)
        return 0

    system = """You are a senior data glossary expert in the organization.
Synthesize all available metadata into a clear, business-friendly glossary entry.

You may receive: SQL formulas, column names, DOMO dashboard info, pillar context, source tables, refresh schedules, row counts, and owner info. Combine all of it into one coherent definition.

Rules:
- Start with what this metric/table MEASURES or TRACKS in plain business language
- Mention which pillar/team uses it and what decisions it drives
- If DOMO columns are listed, describe the key dimensions and measures
- If an owner is mentioned, note who maintains it
- If refresh/freshness info is available, mention the cadence
- Keep it 3-5 sentences — comprehensive but concise
- Never output raw SQL or technical table names — translate to business language
- Include the time granularity if obvious (daily, weekly, etc.)
- If it's a DOMO dashboard metric, mention that
- Output ONLY the rewritten definition, nothing else

Format: "Business definition: [your rewrite]"
"""

    # Use the selected enrichment model (from UI dropdown) for glossary rewrite
    rewrite_model = model

    # Batch entries for efficiency — 10 per API call instead of 1
    BATCH_SIZE = 10
    rewritten = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]

        # Check token budget
        try:
            from catalog_engine.kb_enricher import _budget_remaining
            if _budget_remaining() <= 0:
                logger.warning("Token budget exhausted — stopping glossary rewrite at %d/%d", rewritten, len(rows))
                break
        except ImportError:
            pass

        # Build batch prompt
        batch_entries = []
        for row in batch:
            source_tables = row["source_tables"]
            if isinstance(source_tables, str):
                try:
                    source_tables = json.loads(source_tables)
                except Exception:
                    source_tables = []

            parts = [f"Term: {row['term']}", f"Definition: {row['definition']}"]
            if row.get("formula"):
                parts.append(f"Formula: {row['formula']}")
            if row.get("view_name"):
                parts.append(f"View: {row['view_name']}")
            if source_tables:
                parts.append(f"Sources: {', '.join(source_tables[:5])}")
            batch_entries.append(f"[{row['id']}]\n" + "\n".join(parts))

        user_text = "Rewrite each entry below. Return ONLY the rewritten definitions in the same order, separated by ---\n\n" + "\n\n---\n\n".join(batch_entries)

        try:
            resp = await client.messages.create(
                model=rewrite_model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user_text}],
            )

            # Track tokens
            try:
                from catalog_engine.kb_enricher import _track_usage
                _track_usage(resp)
            except ImportError:
                pass

            result_text = resp.content[0].text.strip() if resp.content else ""
            definitions = [d.strip() for d in result_text.split("---") if d.strip()]

            for j, new_def in enumerate(definitions):
                if j < len(batch) and new_def and len(new_def) > 20:
                    await db_pool.execute("""
                        UPDATE glossary_entries SET definition = $2, updated_at = NOW()
                        WHERE id = $1 AND auto_generated = true AND workflow_state = 'draft'
                    """, batch[j]["id"], new_def)
                    rewritten += 1
        except Exception as e:
            logger.warning("Failed to rewrite glossary batch %d-%d: %s", i, i + len(batch), e)

    if log_fn:
        log_fn(f"Glossary: {rewritten}/{len(rows)} definitions rewritten to business-friendly")

    logger.info("AI glossary rewrite: %d/%d definitions rewritten", rewritten, len(rows))
    return rewritten


async def _ensure_glossary_table(db_pool):
    """Ensure glossary_entries table exists with sources column."""
    try:
        await db_pool.execute("""
            CREATE TABLE IF NOT EXISTS glossary_entries (
                id              BIGSERIAL PRIMARY KEY,
                term_key        TEXT NOT NULL UNIQUE,
                term            TEXT NOT NULL,
                definition      TEXT NOT NULL,
                formula         TEXT,
                source_tables   JSONB DEFAULT '[]',
                dimensions      JSONB DEFAULT '[]',
                filters         TEXT,
                dag             TEXT,
                domo_dataset_id TEXT,
                view_name       TEXT,
                confidence      NUMERIC(3,2),
                status          TEXT NOT NULL DEFAULT 'draft',
                expert_notes    TEXT,
                auto_generated  BOOLEAN DEFAULT true,
                sql_hash        TEXT,
                sources         JSONB DEFAULT '[]',
                created_by      TEXT DEFAULT 'kb_agent',
                created_by_type TEXT DEFAULT 'agent',
                workflow_state  TEXT DEFAULT 'draft',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # Add sources column to existing tables
        await db_pool.execute("""
            ALTER TABLE glossary_entries ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]'
        """)
    except Exception as e:
        logger.warning("Could not create/alter glossary_entries table: %s", e)


def _build_sources_list(
    has_view_sql: bool = False,
    view_name: str = "",
    has_redshift_desc: bool = False,
    redshift_desc: str = "",
    has_repo_config: bool = False,
    repo_info: str = "",
    has_domo: bool = False,
) -> list[dict]:
    """Build a list of source attributions for a glossary entry."""
    sources = []
    if has_view_sql:
        sources.append({"type": "view_sql", "label": "View SQL", "detail": f"CREATE VIEW {view_name}"})
    if has_redshift_desc:
        sources.append({"type": "redshift", "label": "Redshift COMMENT", "detail": redshift_desc[:200]})
    if has_repo_config:
        sources.append({"type": "repo", "label": "Git Repo", "detail": repo_info})
    if has_domo:
        sources.append({"type": "domo", "label": "DOMO Dataset", "detail": "Linked DOMO refresh config"})
    return sources


async def enrich_glossary(
    knowledge_dir: str,
    db_pool,
    catalog_data: dict | None = None,
) -> dict:
    """
    Auto-enrich glossary from multiple sources:
    1. View SQL definitions (knowledge/views/)
    2. Redshift column/table descriptions (from catalog.json)
    3. Repo configs (DAG owners, schedules)

    Approved entries are NEVER overwritten — human opinion wins.
    """
    views_dir = Path(knowledge_dir) / "views"
    metrics_path = Path(knowledge_dir) / "metrics.json"
    catalog_path = Path(knowledge_dir) / "catalog.json"

    await _ensure_glossary_table(db_pool)

    # Load metrics for DOMO dataset links
    domo_links: dict[str, str] = {}
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
            for m in metrics:
                if m.get("domo_dataset_id"):
                    domo_links[m["name"].lower()] = m["domo_dataset_id"]

    # Load catalog for Redshift descriptions
    catalog_tables: dict[str, dict] = {}
    if catalog_data:
        for t in catalog_data.get("tables", []):
            key = f"{t.get('schema', '')}.{t.get('table_name', '')}".lower()
            catalog_tables[key] = t
    elif catalog_path.exists():
        with open(catalog_path) as f:
            cat = json.load(f)
            for t in cat.get("tables", []):
                tname = t.get('name', t.get('table_name', ''))
                key = f"{t.get('schema', '')}.{tname}".lower()
                catalog_tables[key] = t

    # Load existing approved entries
    existing: dict[str, dict] = {}
    try:
        rows = await db_pool.fetch("SELECT term_key, status, sql_hash FROM glossary_entries")
        for r in rows:
            existing[r["term_key"]] = {"status": r["status"], "sql_hash": r["sql_hash"]}
    except Exception:
        pass

    stats = {"new_drafts": 0, "needs_review": 0, "skipped_approved": 0,
             "total_views": 0, "redshift_entries": 0}

    # ── Source 1: View SQL definitions ──────────────────────────────────

    if views_dir.is_dir():
        for view_path in views_dir.glob("*.json"):
            stats["total_views"] += 1
            try:
                with open(view_path) as f:
                    view_data = json.load(f)
            except Exception:
                continue

            sql_content = view_data.get("sql_content", "")
            if not sql_content:
                continue

            view_name = view_data.get("view_table", view_path.stem)
            view_schema = view_data.get("view_schema", "")
            dag_name = view_data.get("dag_name", "")
            domo_id = domo_links.get(view_name.lower(), "")

            entry = generate_glossary_entry(
                view_name, view_schema, sql_content, dag_name, domo_id,
            )

            sql_hash = hashlib.md5(sql_content.encode()).hexdigest()
            term_key = entry["term_key"]

            # Build sources
            sources = _build_sources_list(
                has_view_sql=True, view_name=f"{view_schema}.{view_name}",
                has_domo=bool(domo_id),
                has_repo_config=bool(dag_name), repo_info=f"DAG: {dag_name}" if dag_name else "",
            )

            # Check if Redshift has a description for this table
            cat_key = f"{view_schema}.{view_name}".lower()
            cat_entry = catalog_tables.get(cat_key)
            if cat_entry and cat_entry.get("description"):
                rs_desc = cat_entry["description"]
                sources.append({"type": "redshift", "label": "Redshift COMMENT", "detail": rs_desc[:200]})
                # Merge Redshift description into the definition
                entry["definition"] = f"{rs_desc}. {entry['definition']}"
                entry["confidence"] = min(1.0, entry["confidence"] + 0.1)

            # Check existing
            ex = existing.get(term_key)
            if ex:
                if ex["status"] in ("approved", "merged"):
                    if ex["sql_hash"] != sql_hash:
                        await db_pool.execute("""
                            UPDATE glossary_entries
                            SET status = 'needs_review', sql_hash = $2, sources = $3::jsonb, updated_at = NOW()
                            WHERE term_key = $1
                        """, term_key, sql_hash, json.dumps(sources))
                        stats["needs_review"] += 1
                    else:
                        stats["skipped_approved"] += 1
                    continue
                elif ex["status"] == "rejected":
                    continue

            # Upsert draft
            await db_pool.execute("""
                INSERT INTO glossary_entries (
                    term_key, term, definition, formula, source_tables, dimensions,
                    filters, dag, domo_dataset_id, view_name, confidence, status,
                    auto_generated, sql_hash, sources, created_by, created_by_type, workflow_state
                ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10, $11, 'draft', true, $12, $13::jsonb, 'kb_agent', 'agent', 'draft')
                ON CONFLICT (term_key) DO UPDATE SET
                    definition = $3, formula = $4, source_tables = $5::jsonb,
                    dimensions = $6::jsonb, filters = $7, confidence = $11,
                    sql_hash = $12, sources = $13::jsonb, updated_at = NOW()
                WHERE glossary_entries.status = 'draft' OR glossary_entries.workflow_state = 'draft'
            """,
                term_key, entry["term"], entry["definition"], entry["formula"],
                json.dumps(entry["source_tables"]), json.dumps(entry["dimensions"]),
                entry["filters"], dag_name, domo_id, entry["view"],
                entry["confidence"], sql_hash, json.dumps(sources),
            )
            stats["new_drafts"] += 1

    # ── Source 2: Redshift table/column descriptions ────────────────────
    # Create entries for tables with COMMENT ON descriptions that weren't
    # already covered by view SQL above.

    seen_keys = set(existing.keys())
    # Also track what we just inserted from views
    if views_dir.is_dir():
        for view_path in views_dir.glob("*.json"):
            try:
                with open(view_path) as f:
                    vd = json.load(f)
                    seen_keys.add(vd.get("view_table", view_path.stem))
            except Exception:
                pass

    for cat_key, tbl in catalog_tables.items():
        table_desc = tbl.get("description", "").strip()
        table_name = tbl.get("name", tbl.get("table_name", ""))
        schema_name = tbl.get("schema", "")
        term_key = table_name.lower()

        if not table_desc or term_key in seen_keys:
            continue

        # Check for column-level descriptions
        col_descs = []
        for col in tbl.get("columns", []):
            cd = col.get("description", "").strip()
            if cd:
                col_descs.append(f"- **{col['column_name']}**: {cd}")

        if not table_desc and not col_descs:
            continue

        # Build definition from Redshift metadata
        definition_parts = []
        if table_desc:
            definition_parts.append(table_desc)
        if col_descs:
            definition_parts.append("Column descriptions:\n" + "\n".join(col_descs[:20]))

        definition = "\n\n".join(definition_parts)
        sources = _build_sources_list(
            has_redshift_desc=True,
            redshift_desc=table_desc or f"{len(col_descs)} column descriptions",
        )

        # Confidence based on richness
        confidence = 0.4
        if table_desc:
            confidence += 0.2
        if col_descs:
            confidence += 0.1 * min(len(col_descs), 3)  # up to 0.3 for many col descs

        ex = existing.get(term_key)
        if ex and ex["status"] in ("approved", "merged", "rejected"):
            continue

        content_hash = hashlib.md5(definition.encode()).hexdigest()

        await db_pool.execute("""
            INSERT INTO glossary_entries (
                term_key, term, definition, formula, source_tables, dimensions,
                confidence, status, auto_generated, sql_hash, sources,
                created_by, created_by_type, workflow_state
            ) VALUES ($1, $2, $3, '', '[]'::jsonb, '[]'::jsonb,
                      $4, 'draft', true, $5, $6::jsonb, 'kb_agent', 'agent', 'draft')
            ON CONFLICT (term_key) DO UPDATE SET
                definition = $3, confidence = $4, sql_hash = $5, sources = $6::jsonb, updated_at = NOW()
            WHERE glossary_entries.status = 'draft' OR glossary_entries.workflow_state = 'draft'
        """,
            term_key,
            table_name.replace("_", " ").title(),
            definition,
            round(confidence, 2),
            content_hash,
            json.dumps(sources),
        )
        stats["redshift_entries"] += 1
        stats["new_drafts"] += 1

    # ── Source 3: DOMO metrics (business names, owners, columns, pillar) ──
    # Create entries for DOMO metrics not already covered by views or Redshift
    domo_catalog_path = Path(knowledge_dir) / "domo_catalog.json"
    if domo_catalog_path.exists():
        try:
            with open(domo_catalog_path) as f:
                domo_catalog = json.load(f)

            stats["domo_entries"] = 0
            for m in domo_catalog:
                metric_name = m.get("name", "")
                if not metric_name:
                    continue

                term_key = metric_name.lower()
                # Skip if already covered by views or Redshift
                ex = existing.get(term_key)
                if ex and ex["status"] in ("approved", "merged", "rejected"):
                    continue

                # Build definition from all available DOMO metadata
                parts = []
                pillar = m.get("pillar", "")
                if pillar:
                    parts.append(f"**Pillar:** {pillar}")

                # S3 metadata (columns = what execs see)
                s3 = m.get("s3_metadata") or {}
                s3_cols = s3.get("columns", [])
                if isinstance(s3_cols, list) and s3_cols and isinstance(s3_cols[0], str):
                    # Filter out internal columns
                    visible_cols = [c for c in s3_cols if not c.startswith("_BATCH")]
                    if visible_cols:
                        parts.append(f"**Columns in DOMO:** {', '.join(visible_cols[:15])}")
                if s3.get("last_modified"):
                    parts.append(f"**Last refreshed:** {s3['last_modified'][:10]}")
                if s3.get("estimated_rows"):
                    parts.append(f"**Rows:** ~{s3['estimated_rows']:,}")

                # Source tables
                src_tables = m.get("source_tables", [])
                if src_tables:
                    parts.append(f"**Source tables:** {', '.join(src_tables[:5])}")

                # Transform DAG
                dag = m.get("transform_dag", "")
                if dag:
                    parts.append(f"**Transform:** {dag}")

                metric_type = m.get("metric_type", "")
                if metric_type:
                    parts.append(f"**Type:** {metric_type}")

                if not parts:
                    continue

                definition = "\n".join(parts)
                # Strip null bytes (cause postgres UTF8 encoding errors)
                definition = definition.replace("\x00", "")
                domo_id = (m.get("domo_dataset_id") or "").replace("\x00", "")

                sources = [{
                    "type": "domo",
                    "label": "DOMO Metric",
                    "detail": f"Dataset: {domo_id[:12]}..." if domo_id else "No dataset ID",
                }]
                if m.get("has_view_sql"):
                    sources.append({"type": "view_sql", "label": "View SQL", "detail": f"View: {metric_name}"})
                if pillar:
                    sources.append({"type": "pillar", "label": f"Pillar: {pillar}"})

                content_hash = hashlib.md5(definition.encode()).hexdigest()

                await db_pool.execute("""
                    INSERT INTO glossary_entries (
                        term_key, term, definition, dag, domo_dataset_id, view_name,
                        source_tables, confidence, status, auto_generated, sql_hash, sources,
                        created_by, created_by_type, workflow_state
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, 'draft', true, $9, $10::jsonb,
                              'kb_agent', 'agent', 'draft')
                    ON CONFLICT (term_key) DO UPDATE SET
                        definition = $3, dag = $4, domo_dataset_id = $5, source_tables = $7::jsonb,
                        confidence = $8, sql_hash = $9, sources = $10::jsonb, updated_at = NOW()
                    WHERE glossary_entries.status = 'draft' OR glossary_entries.workflow_state = 'draft'
                """,
                    term_key,
                    metric_name.replace("_", " ").title(),
                    definition,
                    dag,
                    domo_id,
                    metric_name,
                    json.dumps(src_tables),
                    0.5 if pillar else 0.3,
                    content_hash,
                    json.dumps(sources),
                )
                stats["domo_entries"] += 1
                stats["new_drafts"] += 1

            logger.info("DOMO glossary entries: %d created from domo_catalog", stats["domo_entries"])
        except Exception as e:
            logger.warning("DOMO glossary enrichment failed: %s", e)

    # ── Create tickets for new glossary drafts ────────────────────────
    await _create_glossary_tickets(db_pool, stats["new_drafts"])

    logger.info(
        "Glossary enrichment: %d views, %d redshift, %d drafts, %d needs review, %d approved unchanged",
        stats["total_views"], stats["redshift_entries"],
        stats["new_drafts"], stats["needs_review"], stats["skipped_approved"],
    )
    return stats


async def _create_glossary_tickets(db_pool, new_count: int):
    """Create a summary ticket for new glossary drafts needing review."""
    if new_count == 0:
        return

    try:
        # Ensure feedback_tickets table exists (with task management columns)
        await db_pool.execute("""
            CREATE TABLE IF NOT EXISTS feedback_tickets (
                id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
                status TEXT DEFAULT 'open', priority TEXT DEFAULT 'medium', category TEXT DEFAULT 'glossary',
                created_by TEXT NOT NULL, assigned_to TEXT, chat_session_id TEXT,
                chat_messages JSONB, resolution TEXT,
                task_type TEXT NOT NULL DEFAULT 'general', due_date DATE, tags JSONB NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Check for existing open glossary review ticket (don't duplicate)
        existing = await db_pool.fetchval(
            """SELECT id FROM feedback_tickets
               WHERE category = 'glossary' AND status IN ('open', 'in_progress')
                 AND title LIKE 'Glossary review:%'"""
        )
        if existing:
            # Update existing ticket description
            await db_pool.execute("""
                UPDATE feedback_tickets SET
                    description = $2, updated_at = NOW()
                WHERE id = $1
            """, existing, f"{new_count} new draft glossary entries need expert review.\n\nGo to Glossary to review, approve, or reject.")
            return

        # Get first admin for assignment
        admin_row = await db_pool.fetchrow(
            "SELECT email FROM users WHERE role = 'admin' AND is_active = true ORDER BY id LIMIT 1"
        )
        assigned = admin_row["email"] if admin_row else None

        await db_pool.execute("""
            INSERT INTO feedback_tickets (title, description, status, priority, category, created_by, assigned_to)
            VALUES ($1, $2, 'open', 'medium', 'glossary', 'kb_agent', $3)
        """,
            f"Glossary review: {new_count} new draft entries",
            f"{new_count} new draft glossary entries were auto-generated from view SQL and Redshift metadata.\n\nGo to Glossary to review, approve, or reject each entry.",
            assigned,
        )
        logger.info("Created glossary review ticket for %d drafts", new_count)
    except Exception as e:
        logger.warning("Failed to create glossary ticket: %s", e)
