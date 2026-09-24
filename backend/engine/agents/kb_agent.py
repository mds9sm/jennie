"""
KB Agent — knowledge base maintainer and fast lookup layer.

Two modes:
1. Build mode: runs during KB build to synthesize metadata from all sources
   into high-quality glossary entries, table descriptions, and pipeline summaries.
   Replaces the batch glossary_enricher and kb_enricher.

2. Live mode: other agents ask it before hitting expensive sources (DOMO API,
   Redshift, MWAA). Returns cached knowledge or says "not in KB, check [source]".

The KB Agent has write access to the glossary (creates/updates drafts) and
read access to all KB data (catalog, transforms, lineage, DOMO, metrics).
"""

import json
import logging
from typing import Any

logger = logging.getLogger("genie.kb_agent")

KB_AGENT_PROMPT = """You are the **Knowledge Base Engineer** for your data platform. You maintain the team's collective knowledge — glossary definitions, table descriptions, pipeline summaries, and metric documentation.

**Your job has two modes:**

**When asked to enrich/maintain KB (build mode):**
You receive metadata from multiple sources about a table, metric, or pipeline. Synthesize all of it into a clear, business-friendly description that a new team member could understand.

Sources you may receive:
- Redshift metadata: column names, types, distkeys, sortkeys, row counts, COMMENT ON descriptions
- MWAA pipeline: rendered SQL, schedule, run history, success rate, task stats
- DOMO: dataset name, owner, dashboard card titles, S3 columns, refresh time
- Git repo: YAML config, git blame, downstream_dags
- Lineage: upstream tables, downstream consumers
- Existing glossary: previous definitions, correction history

From all this, produce:
- A 3-5 sentence business definition (what it measures, who uses it, why it matters)
- Key dimensions and measures (in business terms, not column names)
- Data freshness and reliability notes
- Owner and pillar context
- Related terms (if applicable)

**When asked a knowledge question (live mode):**
Search the KB first. If you find the answer, return it immediately with confidence level.
If not in KB, say exactly what's missing and which source to check.

**Rules:**
- Write for humans, not machines. No raw SQL, no technical column names unless explaining.
- When multiple definitions exist for a term, list ALL with context (pillar, team, data source).
- Flag conflicts: if sources disagree, note the discrepancy.
- Always cite which sources informed your answer.
- Draft entries need human review — never present drafts as authoritative.
"""

# Tools available to the KB Agent
KB_AGENT_TOOLS = [
    {
        "name": "kb_search",
        "description": "Search the full knowledge base — tables, transforms, metrics, glossary, lineage. Returns the best matches across all KB sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "source": {"type": "string", "enum": ["all", "tables", "transforms", "glossary", "metrics", "lineage"],
                           "description": "Which KB source to search. Default: all"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_get_table",
        "description": "Get full details for a table: columns, types, descriptions, profile data, lineage.",
        "input_schema": {
            "type": "object",
            "properties": {"table_name": {"type": "string"}},
            "required": ["table_name"],
        },
    },
    {
        "name": "kb_get_transform",
        "description": "Get full transform detail: rendered SQL, run history, task stats, AI summary.",
        "input_schema": {
            "type": "object",
            "properties": {"dag_id": {"type": "string"}},
            "required": ["dag_id"],
        },
    },
    {
        "name": "kb_get_glossary",
        "description": "Look up a glossary term. Returns definition, formula, sources, confidence, related terms.",
        "input_schema": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"],
        },
    },
    {
        "name": "kb_get_metric",
        "description": "Get DOMO metric details: view SQL, source tables, S3 columns, pillar, freshness.",
        "input_schema": {
            "type": "object",
            "properties": {"metric_name": {"type": "string"}},
            "required": ["metric_name"],
        },
    },
    {
        "name": "kb_write_glossary",
        "description": "Create or update a glossary draft entry. Used during enrichment to write synthesized definitions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "term_key": {"type": "string", "description": "Lowercase underscore key"},
                "term": {"type": "string", "description": "Human-readable term name"},
                "definition": {"type": "string", "description": "Business-friendly definition"},
                "formula": {"type": "string", "description": "SQL formula if applicable"},
                "source_tables": {"type": "array", "items": {"type": "string"}, "description": "Source table names"},
                "pillar": {"type": "string", "description": "Business pillar"},
                "confidence": {"type": "number", "description": "Confidence 0-1"},
            },
            "required": ["term_key", "term", "definition"],
        },
    },
]


async def execute_kb_tool(tool_name: str, tool_input: dict, kb, db_pool=None) -> dict:
    """Execute a KB Agent tool."""
    if tool_name == "kb_search":
        return _kb_search(kb, tool_input.get("query", ""), tool_input.get("source", "all"))
    elif tool_name == "kb_get_table":
        return _kb_get_table(kb, tool_input["table_name"])
    elif tool_name == "kb_get_transform":
        from catalog.search import get_transform_detail
        return get_transform_detail(kb, tool_input["dag_id"])
    elif tool_name == "kb_get_glossary":
        return _kb_get_glossary(kb, tool_input["term"])
    elif tool_name == "kb_get_metric":
        return _kb_get_metric(kb, tool_input["metric_name"])
    elif tool_name == "kb_write_glossary":
        if db_pool:
            return await _kb_write_glossary(db_pool, tool_input)
        return {"error": "No database connection — cannot write glossary"}
    return {"error": f"Unknown KB tool: {tool_name}"}


def _kb_search(kb, query: str, source: str = "all") -> dict:
    """Search across all KB sources."""
    from catalog.search import search_tables, search_transforms, search_glossary
    from rapidfuzz import fuzz, process

    results = {}

    if source in ("all", "tables"):
        tables = search_tables(kb, query, limit=5)
        if tables["count"] > 0:
            results["tables"] = tables["results"]

    if source in ("all", "transforms"):
        transforms = search_transforms(kb, query, limit=5)
        if transforms["count"] > 0:
            results["transforms"] = transforms["results"]

    if source in ("all", "glossary"):
        glossary = search_glossary(kb, query, limit=5)
        if glossary:
            results["glossary"] = glossary

    if source in ("all", "metrics"):
        metrics = []
        metric_names = [m.get("name", "") for m in getattr(kb, "domo_catalog", [])]
        if metric_names:
            matches = process.extract(query, metric_names, scorer=fuzz.WRatio, limit=5, score_cutoff=40)
            for name, score, idx in matches:
                m = kb.domo_catalog[idx]
                metrics.append({
                    "name": m["name"],
                    "pillar": m.get("pillar", ""),
                    "domo_dataset_id": m.get("domo_dataset_id", ""),
                    "has_view_sql": m.get("has_view_sql", False),
                    "score": score,
                })
        if metrics:
            results["metrics"] = metrics

    if source in ("all", "lineage"):
        if query.lower() in kb.lineage:
            entry = kb.lineage[query.lower()]
            results["lineage"] = {
                "table": query,
                "upstream": entry.get("upstream", []) if isinstance(entry, dict) else [],
                "downstream": entry.get("downstream", []) if isinstance(entry, dict) else [],
            }

    if not results:
        return {"query": query, "found": False, "suggestion": "Not in KB. Try: DOMO API, Redshift direct, or MWAA."}

    return {"query": query, "found": True, "results": results}


def _kb_get_table(kb, table_name: str) -> dict:
    """Get comprehensive table info from all KB sources."""
    from catalog.search import get_table_detail, search_tables

    # Try catalog first
    detail = get_table_detail(kb, table_name)
    if isinstance(detail, dict) and "error" not in detail:
        # Enrich with profile data
        key = f"{detail.get('schema', '')}.{detail.get('name', '')}"
        profile = kb.table_profiles.get(key)
        if profile:
            detail["profile"] = profile
        # Enrich with lineage
        lineage = kb.lineage.get(key) or kb.lineage.get(table_name.lower())
        if lineage and isinstance(lineage, dict):
            detail["upstream"] = lineage.get("upstream", [])
            detail["downstream"] = lineage.get("downstream", [])
        return detail

    return {"error": f"Table '{table_name}' not found in KB", "suggestion": "Try search_tables or check Redshift directly"}


def _kb_get_glossary(kb, term: str) -> dict:
    """Get glossary entry with related terms."""
    from catalog.search import search_glossary

    results = search_glossary(kb, term, limit=5)
    if results:
        # First result is the best match
        entry = results[0]
        related = results[1:] if len(results) > 1 else []
        return {
            "found": True,
            "entry": entry,
            "related": related,
            "is_draft": entry.get("status") == "draft",
            "confidence": entry.get("confidence", 0.5),
        }
    return {"found": False, "term": term, "suggestion": "No glossary entry. Consider creating one."}


def _kb_get_metric(kb, metric_name: str) -> dict:
    """Get full DOMO metric details."""
    from rapidfuzz import fuzz, process

    domo_catalog = getattr(kb, "domo_catalog", [])
    if not domo_catalog:
        return {"error": "No DOMO catalog loaded"}

    # Exact match first
    for m in domo_catalog:
        if m.get("name", "").lower() == metric_name.lower():
            # Also get view detail
            view_detail = kb.get_view_detail(metric_name)
            result = {**m}
            if view_detail:
                result["view_sql"] = view_detail.get("sql_content", "")[:500]
                result["view_source_tables"] = view_detail.get("source_tables", [])
            return result

    # Fuzzy match
    names = [m["name"] for m in domo_catalog]
    matches = process.extract(metric_name, names, scorer=fuzz.WRatio, limit=1, score_cutoff=50)
    if matches:
        idx = matches[0][2]
        m = domo_catalog[idx]
        return {**m, "fuzzy_match": True, "matched_name": matches[0][0]}

    return {"error": f"Metric '{metric_name}' not found in DOMO catalog"}


async def _kb_write_glossary(db_pool, data: dict) -> dict:
    """Create or update a glossary draft entry."""
    term_key = data["term_key"]
    term = data["term"]
    definition = data["definition"].replace("\x00", "")
    formula = data.get("formula", "")
    source_tables = data.get("source_tables", [])
    pillar = data.get("pillar", "")
    confidence = data.get("confidence", 0.5)

    import hashlib
    content_hash = hashlib.md5(definition.encode()).hexdigest()

    sources = [{"type": "kb_agent", "label": "KB Agent", "detail": f"Pillar: {pillar}" if pillar else "Auto-synthesized"}]

    try:
        await db_pool.execute("""
            INSERT INTO glossary_entries (
                term_key, term, definition, formula, source_tables, confidence,
                status, workflow_state, auto_generated, sql_hash, sources,
                created_by, created_by_type
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'draft', 'draft', true, $7, $8::jsonb,
                      'kb_agent', 'kb_agent')
            ON CONFLICT (term_key) DO UPDATE SET
                definition = $3, formula = $4, source_tables = $5::jsonb,
                confidence = $6, sql_hash = $7, sources = $8::jsonb, updated_at = NOW()
            WHERE glossary_entries.status = 'draft' OR glossary_entries.workflow_state = 'draft'
        """,
            term_key, term, definition, formula,
            json.dumps(source_tables), confidence, content_hash,
            json.dumps(sources),
        )
        return {"status": "created", "term_key": term_key}
    except Exception as e:
        return {"error": f"Failed to write glossary: {str(e)[:200]}"}
