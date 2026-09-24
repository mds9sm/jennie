"""
Tool definitions scoped per sub-agent.
Consolidated from 6 → 3 agents to reduce overlap and cost.
"""

from engine.tools import GENIE_TOOLS

# Build a lookup for easy filtering
_TOOLS_BY_NAME = {t["name"]: t for t in GENIE_TOOLS}


def _pick(names: list[str]) -> list[dict]:
    return [_TOOLS_BY_NAME[n] for n in names if n in _TOOLS_BY_NAME]


# Data Expert = Repo + Pipeline + Metrics (all data flow tools + live AWS + GitHub)
DATA_EXPERT_TOOLS = _pick([
    "search_transforms",
    "get_transform_detail",
    "get_table_lineage",
    "get_view_detail",
    "repo_search",
    "github_file",
    "aws_lookup",
    "analyze_domo_dataset",
    "get_event_schema",
    "search_events",
    "domo_search",
    "domo_dataset_info",
    # "domo_query",  # Parked — uses DOMO's internal query engine. Awaiting confirmation to enable.
    "domo_dashboards",
    "domo_dashboard_detail",
])

# Redshift Expert (SQL + table metadata)
REDSHIFT_EXPERT_TOOLS = _pick([
    "search_tables",
    "get_table_detail",
    "execute_query",
])

# Knowledge Expert removed — glossary + pillar context now inline in every request.
# Kept for backwards compatibility with admin UI prompt editor.
KNOWLEDGE_EXPERT_TOOLS = _pick([
    "glossary_lookup",
])

# Backwards compatibility aliases
REPO_EXPERT_TOOLS = DATA_EXPERT_TOOLS
PIPELINE_EXPERT_TOOLS = DATA_EXPERT_TOOLS
METRICS_EXPERT_TOOLS = DATA_EXPERT_TOOLS
GLOSSARY_EXPERT_TOOLS = KNOWLEDGE_EXPERT_TOOLS
PLATFORM_EXPERT_TOOLS = KNOWLEDGE_EXPERT_TOOLS

# Principal agent's tools = sub-agent calls + direct query
PRINCIPAL_TOOLS = [
    {
        "name": "ask_data_expert",
        "description": "Ask the Data Expert about DAG configs, MWAA execution, run history, rendered SQL, lineage (table + DAG-to-DAG with TriggerDagRun chains), DOMO views, KPI definitions, metric calculations, YAML configs, downstream_dags, and git repo.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Question for the data expert"}},
            "required": ["question"],
        },
    },
    {
        "name": "ask_redshift_expert",
        "description": "Ask the Redshift Expert about table metadata, columns, profiling stats, data types, query optimization, and execute SQL queries.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Question for the redshift expert"}},
            "required": ["question"],
        },
    },
    {
        "name": "execute_query",
        "description": "Execute a read-only SQL query against Redshift. Only SELECT and EXPLAIN are allowed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "The SQL query (SELECT or EXPLAIN only)"},
                "environment": {"type": "string", "enum": ["np", "prd"], "description": "Target environment. Default: np"},
            },
            "required": ["sql"],
        },
    },
] + _pick([
    "search_tables",           # Principal needs this for DATA questions (find the right table → write SQL)
    "search_transforms",       # Quick lookup for pipeline/view names before writing SQL
    "analyze_domo_dataset",    # Principal can analyze DOMO S3 data directly for METRIC questions (no Redshift)
])

# Principal gets: execute_query + search_tables + search_transforms + expert delegation
# This lets it handle DATA questions directly (search → SQL → execute) in 2-3 tool calls
# Investigation tools (repo_search, github_file, aws_lookup) stay on sub-agents only
