"""
Context builder — compiles KB knowledge directly into the system prompt.

Instead of relying on tool calls to discover the platform, the agent
gets the most important KB data injected into every request:
- Top tables with columns (what you query daily)
- DOMO metrics with S3 columns (what execs see)
- Glossary definitions (business terms)
- Active experiments (Statsig)
- Common query patterns

This is Layer 1 — the agent's "working knowledge."
Layer 2 (full catalog, lineage, event schemas) stays as tool calls.
"""

import json
from catalog.loader import KnowledgeBase
from engine.pillar import get_pillar

PERSONA_ADAPTATION = {
    "engineer": "Technical user. Show SQL, distkey rationale, DAG config details. Don't over-explain basics.",
    "analytics_engineer": "Analytics engineer. Focus on SQL patterns, data modeling, view design.",
    "analyst": "Business analyst. Lead with business context. Runnable SQL. DOMO links. No pipeline jargon.",
    "ml_engineer": "ML engineer. Feature engineering focus. Data freshness, completeness.",
    "exec": "Executive. Impact and trends only. No SQL unless asked. Charts preferred.",
    "new_member": "New to the organization data. Explain the organization terms, define acronyms, suggest related topics.",
}


def build_system_prompt(
    kb: KnowledgeBase,
    pillar: str | None = None,
    environment: str = "np",
    capability: str = "chat",
    user_settings: dict | None = None,
    dynamic_sql_patterns: list[dict] | None = None,
    cross_session_context: str | None = None,
) -> str:
    """Build rich KB context injected into every AI request."""
    sections = []

    # 1. User persona
    if user_settings:
        persona = user_settings.get("persona", "engineer")
        adaptation = PERSONA_ADAPTATION.get(persona)
        if adaptation:
            sections.append(f"## User: {adaptation}")

    # 2. User's custom rules
    if user_settings and user_settings.get("system_prompt"):
        sections.append(f"## Rules\n{user_settings['system_prompt']}")

    # 3. Environment
    sections.append(
        f"## Environment: {'nonprod' if environment == 'np' else 'prod'}\n"
        f"Connection: nonprod Redshift (via datashare for prod schemas).\n"
        f"**STRICT RULE — always use `prd_*` database prefixes** (prd_dw, prd_board_kpi, prd_statsig, prd_data_lake, etc.) in ALL SQL queries. "
        f"Nonprod schemas (np_dw) are staging/test only — never query them unless the user explicitly requests a specific np_* or db.schema.table. "
        f"execute_query(environment='{environment}')."
    )

    # 4. Active pillar
    pillar_info = get_pillar(pillar)
    if pillar_info:
        sections.append(
            f"## Pillar: {pillar_info['name']}\n"
            f"Metrics: {', '.join(pillar_info['key_metrics'])}"
        )

    # ── LAYER 1: KB KNOWLEDGE (inline — agent knows this, doesn't need to search) ──

    # 5. Key tables with columns
    tables = kb.catalog.get("tables", [])
    if tables:
        domo_tables = set()
        for m in getattr(kb, "domo_catalog", []):
            for s in m.get("source_tables", []):
                domo_tables.add(s.lower())

        # Score tables by importance
        scored = []
        for t in tables:
            key = f"{t.get('schema','')}.{t.get('name','')}"
            score = 0
            if t.get("ai_description") or t.get("description"):
                score += 3
            if key.lower() in domo_tables:
                score += 5
            rc = t.get("row_count_estimate") or 0
            if rc > 1_000_000:
                score += 2
            if rc > 100_000_000:
                score += 2
            scored.append((score, t))
        scored.sort(key=lambda x: -x[0])

        lines = ["## Key Tables (write SQL directly — don't search)"]
        for _, t in scored[:40]:
            key = f"prd_dw.{t.get('schema','')}.{t.get('name','')}"
            cols = [c.get("name", "") for c in t.get("columns", [])[:15]]
            desc = t.get("ai_description") or t.get("description") or ""
            rc = t.get("row_count_estimate")
            rc_str = ""
            if rc:
                if rc > 1e9:
                    rc_str = f" [{rc/1e9:.0f}B rows]"
                elif rc > 1e6:
                    rc_str = f" [{rc/1e6:.0f}M rows]"
            col_str = ", ".join(cols)
            if len(t.get("columns", [])) > 15:
                col_str += f" +{len(t['columns'])-15}"
            lines.append(f"`{key}`{rc_str}: {col_str}")
            if desc:
                lines.append(f"  → {desc[:150]}")
        sections.append("\n".join(lines))

    # 6. DOMO metrics
    domo_catalog = getattr(kb, "domo_catalog", [])
    if domo_catalog:
        lines = ["## DOMO Metrics (use analyze_domo_dataset — free, instant, same as exec dashboards)"]
        for m in domo_catalog[:25]:
            name = m.get("name", "")
            pillar_name = m.get("pillar", "")
            s3 = m.get("s3_metadata") or {}
            cols = s3.get("columns", [])
            col_str = ""
            if isinstance(cols, list) and cols and isinstance(cols[0], str):
                visible = [c for c in cols if not c.startswith("_BATCH")][:8]
                if visible:
                    col_str = f": {', '.join(visible)}"
            lines.append(f"- `{name}` ({pillar_name}){col_str}")
        sections.append("\n".join(lines))

    # 7. Glossary definitions
    glossary = kb.glossary
    if glossary:
        lines = ["## Business Definitions"]
        # Prioritize merged/approved, then drafts
        sorted_terms = sorted(glossary.items(),
            key=lambda x: (0 if x[1].get("status") in ("merged", "approved") else 1, x[0]))
        for key, g in sorted_terms[:20]:
            term = g.get("term", key)
            defn = g.get("definition", "")[:200]
            status = g.get("status", "draft")
            confidence = g.get("confidence", 0.5)
            marker = "" if status in ("merged", "approved") else " (draft)"
            if defn:
                lines.append(f"- **{term}**{marker}: {defn}")
        sections.append("\n".join(lines))

    # 8. Statsig experiments
    statsig = getattr(kb, "statsig", {})
    experiments = statsig.get("experiments", [])
    if experiments:
        active = [e for e in experiments if e.get("status") in ("active", "running", "started")][:10]
        if active:
            lines = ["## Active Experiments (Statsig)"]
            for e in active:
                groups = ", ".join(e.get("groups", []))
                lines.append(f"- **{e.get('name','')}**: {e.get('description','')[:80]} | groups: {groups}")
            sections.append("\n".join(lines))

    # 9. SQL patterns — dynamic from saved queries (top by usage), then hardcoded fallbacks
    pattern_lines = ["## Common SQL Patterns"]
    if dynamic_sql_patterns:
        for q in dynamic_sql_patterns[:5]:
            name = q.get("name", "Query")
            sql = q.get("sql", "").strip().replace("\n", " ")[:200]
            pattern_lines.append(f"- {name}: `{sql}`")
    # Always include hardcoded essentials as fallback
    pattern_lines.extend([
        "- Cutting users: `SELECT date_id, client as platform, COUNT(DISTINCT user_id) FROM prd_dw.fact.cut_session_master WHERE date_id >= CURRENT_DATE - 7 GROUP BY 1,2`",
        "- Daily active users: `SELECT event_date, COUNT(DISTINCT user_id) FROM prd_dw.analytics.firehose_v3_enriched WHERE event_name='AppSessionStarted' AND event_date >= CURRENT_DATE - 7 GROUP BY 1`",
        "- Subscriptions: `SELECT subscription_status, COUNT(*) FROM prd_dw.dim.user_subscription GROUP BY 1`",
        "- Engagement by cohort: use `analyze_domo_dataset(\"engagement_depth_wmq\")` instead of Redshift",
    ])
    sections.append("\n".join(pattern_lines))

    # 10. Cross-session memory — recent topics from this user's past sessions
    if cross_session_context:
        sections.append(cross_session_context)

    # 11. KB summary
    event_count = len(getattr(kb, "event_schemas", {}))
    sections.append(
        f"## KB: {len(tables)} tables, {len(kb.transforms_index)} transforms, "
        f"{len(kb.lineage)} lineage, {len(domo_catalog)} DOMO metrics, "
        f"{len(glossary)} glossary, {event_count} event schemas. "
        f"Use tools for deeper lookups."
    )

    return "\n\n".join(sections)
