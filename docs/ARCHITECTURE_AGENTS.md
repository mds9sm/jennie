# Agent Architecture — Genie Knowledge MCP Internal Design

> **Architecture context (2026-09-24):** Genie exposes the same agent stack through **two surfaces**:
> - **Built-in chat** (`/` in the Genie UI, `POST /api/chat`) — streams the principal agent over SSE, with session persistence, action cards, and KB-gap/correction capture
> - **MCP servers** — **Genie Knowledge MCP** (`/genie/mcp`) for the business knowledge layer and **NP Data MCP** (`/data-mcp`) for thin Redshift + MWAA access, both consumed by claude.ai (Team/Enterprise)
>
> The principal + sub-agent design below is shared by both: it runs inside the Genie Knowledge MCP when claude.ai calls tools like `get_data_platform_context`, `get_transform_detail`, or `get_table_lineage`, and inside `/api/chat` when a user talks to Genie directly. On the MCP path claude.ai handles conversation, memory, and context management; on the chat path Genie does it itself (postgres-backed sessions + summarization after 10 messages).
>
> _Chat was removed on 2026-04-14 during the MCP migration and restored on 2026-09-24 — the two surfaces now coexist._

## Overview

Genie's Knowledge MCP uses a **principal agent with specialist sub-agents** architecture (3 agents total: Data Expert, Redshift Expert, and KB Agent for builds only). The principal agent ("Principal Data Analytics Engineer") handles ~80% of questions directly using **rich inline KB context** (top 40 tables with columns, top 25 DOMO metrics, top 20 glossary definitions, active experiments, common SQL patterns). Knowledge Expert was removed — its glossary + pillar context is now compiled inline into every system prompt via context.py.

## Why Sub-Agents?

**Current problem:** One massive system prompt (~21K chars) with everything — repo structure, MWAA pipelines, Redshift profiling, platform conventions, DOMO metrics, glossary. Every question gets all context regardless of relevance, wasting tokens and diluting focus.

**Solution:** Rich inline KB context + persona-based prompts. `context.py` compiles Layer 1 KB data into every system prompt (~6K per call): top 40 tables with columns, top 25 DOMO metrics with S3 columns, top 20 glossary definitions, active Statsig experiments, common SQL query patterns. Agent KNOWS the schema and writes SQL on first tool call (1 tool call, ~10 seconds) instead of 4-6 search iterations. `prompts.py` = agent identity (static). Knowledge Expert removed — its glossary + pillar context is now inline. Result: 3 agents instead of 4, principal handles 80% directly.

### Planned Improvements (Phase 5.6)

**Prompt Caching:** Static KB context (~6K) and agent identity prompts are marked with `cache_control: {"type": "ephemeral"}` so repeat calls within a session pay 90% less for cached tokens. The principal prompt + inline KB context is the same across all 8 iterations — caching eliminates redundant processing.

**SQL Error Recovery:** The principal agent auto-retries failed SQL by reading the error message, cross-referencing inline schema, and fixing the query. No user intervention needed for common errors (wrong column name, missing prefix, syntax).

**Prompt Hygiene:** Dead references removed (Knowledge Expert mentions in Data Expert prompt, unused KNOWLEDGE_EXPERT_PROMPT). Principal instructed to use inline schema directly instead of redundant search_tables calls for top-40 tables.

**DOMO Analysis:** Principal prompt includes DuckDB query examples for `analyze_domo_dataset` — table name is always `data`, with example aggregations for trends, breakdowns, and distributions.

## Architecture

```
User Question
    ↓
┌──────────────────────────────────────────────────┐
│ Principal Agent (Sonnet — fast routing)           │
│                                                   │
│ STEP 1: Classify question type                    │
│   DATA → search + SQL + execute (direct)          │
│   METRIC → view detail + DOMO S3 analysis         │
│   DEFINITION → expert lookup                      │
│   INVESTIGATION → expert deep dive                │
│   MODELING → redshift expert                      │
│   CONVERSATIONAL → reply directly                 │
│                                                   │
│ STEP 2: Choose data source (resource-aware)       │
│   DOMO S3 → analyze_domo_dataset (free, fast)     │
│   Small table → execute_query (auto-run)          │
│   Large table → propose SQL, ask user first       │
│                                                   │
│ Rich inline KB: top 40 tables + columns,          │
│   top 25 DOMO metrics, top 20 glossary defs,      │
│   active experiments, common SQL patterns (~6K)    │
│                                                   │
│ Tools: search_tables, search_transforms,          │
│        execute_query, analyze_domo_dataset,        │
│        ask_{data,redshift}_expert                  │
│                                                   │
│ Forced synthesis uses Opus (heavy model)          │
└──────────────────────────────────────────────────┘
    ↓ tool calls (only for INVESTIGATION/MODELING)
┌──────────┐ ┌──────────┐ ┌─────────┐
│   Data   │ │ Redshift │ │   KB    │
│  Expert  │ │  Expert  │ │  Agent  │
└──────────┘ └──────────┘ └─────────┘
                           (build-mode only)
    ↓ results
┌─────────────────────────────────────────────┐
│ Principal Agent (synthesis)                  │
│ Combines expert responses into coherent     │
│ user-facing answer                          │
└─────────────────────────────────────────────┘
    ↓
User Response
```

## Sub-Agents

### 1. Data Expert
**Persona:** "Senior Data Engineer" — knows DAGs, SQL, lineage, DOMO, MWAA inside and out
**Domain:** DAGs, SQL, lineage, views, DOMO metrics, YAML configs, MWAA execution, run history, data freshness, Git repo organization
**KB Tools:** `search_transforms`, `get_transform_detail`, `get_view_detail`, `get_table_lineage`
**Local Tools:** `repo_search`, `github_file`, `aws_lookup`, `analyze_domo_dataset`
**DOMO Tools:** `domo_search`, `domo_dataset_info`, `domo_dashboards`, `domo_dashboard_detail`
**MCP Tools:** `github__search_code`, `github__get_file_contents`, `github__list_commits`, `github__search_repositories`
**When activated:** Questions about DAG configs, pipeline code, SQL patterns, YAML structure, pipeline status, data freshness, failures, execution times, lineage, metric definitions, how KPIs are calculated, DOMO dashboards
**Merges:** Repo Expert + Pipeline Expert + Metrics Expert

### 2. Redshift Expert
**Domain:** Table metadata, column profiling, classification, query optimization
**System prompt:** Redshift SQL conventions, distkey/sortkey rationale, data types, profiling interpretation
**KB Tools:** `search_tables`, `get_table_detail`, `execute_query`, profile data access
**When activated:** Questions about table structure, columns, data quality, query optimization

### 3. KB Agent (ask_kb_expert)
**Persona:** "KB Enrichment Specialist" — fast KB lookups and build-mode enrichment
**Domain:** Knowledge base operations, table/column descriptions, glossary enrichment, metric definitions, cross-reference gap detection, event schema lookups
**KB Tools:** `search_tables`, `get_table_detail`, `glossary_lookup`, `get_event_schema`, `search_events`

**Mode 1 — Live (Chat):** DEPRECATED. Rich inline KB context in every system prompt means the principal agent has table schemas, glossary definitions, and metric definitions inline — no need to delegate KB lookups. KB Agent is no longer called during chat.

**Mode 2 — Build (KB Build, active):** 3-phase enrichment during KB builds, replacing batch `glossary_enricher.py` + `kb_enricher.py`:
  - **Phase 1 (DAG summaries):** Generate human-readable pipeline summaries from rendered SQL + YAML config + run stats
  - **Phase 2 (Table descriptions):** Generate table and column descriptions combining Redshift metadata + MWAA SQL + DOMO views + lineage context
  - **Phase 3 (Glossary synthesis):** Merge all metadata sources (Redshift + MWAA + DOMO 167 metrics + S3 + lineage) into glossary entries. DOMO is now glossary Source 3 (pillar context, business definitions from dashboard/card metadata). Cross-reference gap detection (repo vs MWAA, tables vs lineage).

**When activated:** KB build enrichment phase, principal delegates KB-specific lookups, or other agents need fast KB data before expensive external calls

### 4. Knowledge Expert (REMOVED)
**Status:** Removed in 2026-03-29 session. Glossary definitions (top 20) and pillar context are now compiled inline into every system prompt via context.py. No separate agent call needed for business term lookups. This eliminated one sub-agent call per DEFINITION question, reducing latency from ~15-20s to ~3s for definition lookups.

**Previous domain:** Business term definitions, pillar context, cross-team terminology, environment routing, datashare model, security, connection management. All of this is now part of the principal's inline KB context.

## Communication Pattern

### Principal Direct Investigation Tools

The principal agent has its own tools for quick, self-contained lookups that do not require full expert analysis:

```python
# Principal's direct investigation tools:
PRINCIPAL_DIRECT_TOOLS = [
    {
        "name": "aws_lookup",
        "description": "Query AWS services: CloudWatch Logs, Glue Jobs, Lambda, ECS, CloudWatch Metrics. Read access to full AWS data platform via SSO (both np + prd accounts).",
        "input_schema": {"type": "object", "properties": {"service": {"type": "string"}, "query": {"type": "string"}, "environment": {"type": "string"}}}
    },
    {
        "name": "github_file",
        "description": "Read files from GitHub repos. Available repos: your-org/data-platform-dags (data platform code), your-org/gitops-config (infra configs: Helm values for Glue, MWAA, ECS).",
        "input_schema": {"type": "object", "properties": {"repo": {"type": "string"}, "path": {"type": "string"}}}
    },
    {
        "name": "execute_query",
        "description": "Run a SELECT query against Redshift for quick data lookups.",
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}, "environment": {"type": "string"}}}
    },
]
```

The principal uses direct tools for simple lookups (e.g., "what's the latest Glue job status?" or "show me the MWAA Helm values"). For complex, multi-step analysis it delegates to sub-agents.

### Tool-based delegation (Pattern #2)
```python
# Principal agent's tools also include sub-agent wrappers:
PRINCIPAL_TOOLS = [
    {
        "name": "ask_data_expert",
        "description": "Consult the Data Expert about DAGs, SQL, lineage, MWAA execution, DOMO views, metric calculations, and pipeline configs",
        "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}}
    },
    {
        "name": "ask_redshift_expert",
        "description": "Consult the Redshift Expert about table metadata, columns, profiling, and query optimization",
        "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}}
    },
    # ask_knowledge_expert — REMOVED (glossary + pillar context now inline in every request)
    # ask_kb_expert — REMOVED from chat (KB Agent used only during KB builds)
]

# When principal calls a sub-agent tool:
async def ask_data_expert(question: str) -> dict:
    response = await bedrock_client.messages.create(
        model=model,
        system=DATA_EXPERT_PROMPT,  # focused, small prompt
        messages=[{"role": "user", "content": question}],
        tools=DATA_TOOLS,  # only data-relevant tools
    )
    return {"expert": "data", "answer": response.text}
```

### Flow for "Show me daily cutting users by platform"
1. **Principal** receives question — classifies as DATA
2. **Principal** already has `fact.cuts_session_master` schema inline (top 40 tables with columns)
3. **Principal** writes SQL directly using inline schema knowledge → calls `execute_query`
4. **Result**: 1 tool call, 28 rows, ~10 seconds total

### Flow for "What tables feed onboarding KPI?"
1. **Principal** receives question — classifies as INVESTIGATION
2. **Principal** has inline glossary definitions for onboarding metrics + DOMO metric context
3. **Principal** calls `ask_data_expert("What DAGs build onboarding KPI tables, sources, and DOMO views?")`
4. **Data Expert** uses `get_transform_detail`, `get_table_lineage`, `get_view_detail` → returns DAG info + lineage + DOMO view SQL
5. **Principal** synthesizes with inline glossary context: "The onboarding KPI board is fed by 3 tables: ... The metrics are defined in these views: ... The data refreshes daily at ..."

## Response Quality

- **No raw JSON** — The principal agent's system prompt explicitly forbids outputting raw tool results. All sub-agent responses are synthesized into natural language before reaching the user.
- **Citations** — Every response includes source references using typed icons: 📊 Table, 🔧 DAG, 📐 View, 📖 Glossary, 🔍 Query. Users can trace any claim back to its source.
- **KB gap detection** — Sub-agents report `KB_GAP` when they cannot find information in the knowledge base. The principal agent surfaces these as 💡 KB Improvement suggestions in the response.
- **Auto-ticket creation** — KB gaps automatically create tickets in the feedback kanban board, so the team can track and fill knowledge holes over time.
- **Frustration detection** — When the user seems unhappy or confused, the agent proactively offers to create a feedback ticket to capture the issue.
- **Charts-first UX** — Agent prompt: "Default to charts, not text. The chart IS the answer." SQL result cards always expanded, render above other cards, only last SQL result shown (intermediates replaced). Query result cards persist in chat sessions (survive refresh).

## Sub-Agent Gap Reporting

Each sub-agent has a **KB Gap Reporting** instruction appended to its system prompt. When a sub-agent cannot find the information needed to answer a question, it includes a structured gap report in its response.

**Format:**
```
KB_GAP: [description of what's missing and how to fix it]
```

**Flow:**
1. Sub-agent searches its tools and knowledge base
2. If information is missing or incomplete, it appends `KB_GAP: ...` to its response
3. Principal agent detects `KB_GAP` lines in sub-agent results
4. Principal transforms them into user-facing 💡 **KB Improvement** suggestions
5. Auto-creates feedback tickets with appropriate category: `kb_gap`, `glossary`, `data`, or `pipeline`

**Deduplication:** The same gap is not created as a ticket more than once within a 24-hour window, preventing noise from repeated questions hitting the same missing knowledge.

## Agent KB Awareness

Sub-agents receive two context injections at runtime:

1. **Coverage report** (from `coverage.json`): DAG type breakdown, SQL vs metadata-only counts per environment. Example: "142 TRANSFORM_DAGs with rendered SQL, 39 dq_sync with metadata only, 12 ingest_s3 with YAML config only."

2. **Knowledge summary** (from `knowledge_summary.json`): table/transform source distribution, completeness scores, lowest-coverage items, trust hierarchy. Example: "485 tables total — 312 have database metadata, 142 have platform (MWAA) SQL, 45 have user descriptions, 89 have only ai_generated descriptions."

This allows agents to:
- **Know which DAG types they have SQL for vs metadata-only** — Data Expert won't claim to have rendered SQL for an ingest DAG when it only has YAML config
- **Identify tables with low knowledge completeness** — Redshift Expert can flag that a table has only a name and row count, no column descriptions or lineage
- **Prefer user-provided knowledge over AI-generated** — Knowledge Expert prioritizes human-curated definitions over auto-generated ones per the trust hierarchy (`user` > `database` > `platform` > `code` > `ai_generated`)
- **Accurately report what's missing instead of guessing** — Sub-agents include specific KB_GAP reports with actionable detail ("table X has no column descriptions — run PROFILE or add via glossary wizard")

The coverage report and knowledge summary are regenerated on every KB build and cached in memory by the agent runner. No additional file reads at query time.

## AWS Access Scope

The `aws_lookup` tool provides read access to the full AWS data platform across both accounts:

| AWS Service | What the Agent Can Access |
|-------------|--------------------------|
| **CloudWatch Logs** | Log groups for MWAA, Glue, Lambda, ECS tasks |
| **Glue Jobs** | Job runs, status, duration, error messages |
| **Lambda** | Function invocations, errors, durations |
| **ECS** | Task status, container logs |
| **CloudWatch Metrics** | Custom metrics, alarms, dashboard data |

Access is authenticated via the same SSO credentials used for MWAA and Redshift. Both nonprod (111111111111) and prod (222222222222) accounts are accessible. Agent prompts are updated to reflect this broad access scope so agents know what they can investigate.

## GitHub File Access

The `github_file` tool reads files from two configured repositories:

| Repository | Contents |
|------------|----------|
| `your-org/data-platform-dags` | Data platform code: DAG configs, SQL templates, YAML definitions |
| `your-org/gitops-config` | Infrastructure configs: Helm values for Glue, MWAA, ECS deployments |

The tool reads raw file content on demand. It does not clone the repo — it uses the GitHub API with the configured `GITHUB_TOKEN`. This gives agents access to infra configuration (e.g., "what are the MWAA worker scaling settings?") without requiring a full repo clone.

## Benefits

| Aspect | Current (monolithic) | Sub-agent architecture |
|--------|---------------------|----------------------|
| System prompt size | ~21K chars always | ~6K per call (rich inline KB context) |
| Token usage | High (full context every call) | Lower — principal handles 80% directly, 3 sub-agents for complex work only |
| Answer quality | Diluted by irrelevant context | Precise, domain-expert |
| Parallelism | Sequential tool calls | Sub-agents run in parallel |
| Extensibility | Edit one giant file | Add new sub-agent |
| Testability | Hard to test specific domains | Test each expert independently |
| Cost | Full context every call | Prompt caching: 90% cheaper for cached tokens across iterations |

## MCP (Model Context Protocol) Integration

### Overview

Genie integrates the GitHub MCP server (`@modelcontextprotocol/server-github`) to give sub-agents live access to GitHub repositories beyond the locally cloned KB snapshot. The MCP server runs as a **Node.js subprocess** inside the backend container, managed by `backend/engine/mcp_bridge.py`.

### Why MCP

The locally cloned repo (`/app/data-repo-kb`) is a snapshot from the last KB build. MCP tools give agents access to the **latest code** in GitHub without requiring a KB rebuild. This is critical for questions like "what changed in this DAG since last week?" or "search for all files referencing this table."

### Tool Discovery and Filtering

The MCP GitHub server exposes 26 tools. Genie filters to 4 that are useful for its domain:

| MCP Tool | Description |
|----------|-------------|
| `github__search_code` | Search code across GitHub repos by pattern |
| `github__get_file_contents` | Read file contents from any branch/path |
| `github__list_commits` | List commit history for a repo or specific path |
| `github__search_repositories` | Search for repositories by name/topic |

### Tool Distribution

**MCP tools are on sub-agents only — NOT on the principal agent.** This keeps the principal lean for fast routing decisions.

```
Principal Agent — "Senior Analytics Engineer" (Sonnet, fast routing)
├── Rich inline KB: top 40 tables+columns, top 25 DOMO metrics, top 20 glossary defs,
│   active experiments, common SQL patterns (~6K per call)
├── Direct: search_tables, search_transforms, execute_query, analyze_domo_dataset
├── Delegation: ask_{data,redshift}_expert (INVESTIGATION/MODELING only)
├── Handles ~80% of questions directly (DATA, DEFINITION, METRIC, CONVERSATIONAL)
│
├── Data Expert — "Senior Data Engineer" (Sonnet)
│   ├── KB: search_transforms, get_transform_detail, get_table_lineage, get_view_detail
│   ├── Local: repo_search, github_file, aws_lookup, analyze_domo_dataset
│   ├── DOMO: domo_search, domo_dataset_info, domo_dashboards, domo_dashboard_detail
│   └── MCP: github__search_code, github__get_file_contents, github__list_commits
│
├── Redshift Expert — "Senior DBA & Data Modeler" (Sonnet)
│   ├── KB: search_tables, get_table_detail, execute_query
│   └── Context: table profiles (66 tables with row counts, cardinality, column classifications)
│
├── KB Agent — "KB Enrichment Specialist" (Sonnet, BUILD MODE ONLY)
│   ├── KB: search_tables, get_table_detail, glossary_lookup, get_event_schema, search_events
│   └── Build mode: 3-phase enrichment (DAG summaries → table descriptions → glossary synthesis)
│
└── Knowledge Expert — REMOVED (glossary + pillar context now inline in every request)
```

### Search Strategy

Agents have a layered search strategy for code-related questions:

1. **KB tools first** — `search_transforms`, `get_transform_detail` for indexed knowledge (fastest, richest context)
2. **`repo_search`** — grep locally cloned repo via subprocess (fast, works offline)
3. **MCP `github__search_code`** — search latest code on GitHub (slower, but always up-to-date)
4. **MCP `github__get_file_contents`** — read specific files from GitHub when path is known

### MCP Bridge (`backend/engine/mcp_bridge.py`)

- Starts the MCP server as a subprocess on backend startup
- Proxies tool calls from agent runner to the MCP server
- Handles server lifecycle (start, restart on failure, graceful shutdown)
- Uses the same `GITHUB_TOKEN` from `.env` — no separate configuration
- Requires Node.js in the backend Docker image

## DOMO REST API Integration

### Overview

Genie accesses DOMO via **direct REST API** using the same `client_id`/`client_secret` as the Airflow DOMO_REFRESH DAGs. The integration is **strictly read-only** — no data writes, no dataset modifications.

### Why Direct REST API (not MCP)

The DOMO MCP server was initially integrated but replaced with direct REST API calls for simplicity. The REST API uses the same OAuth credentials Airflow already has, requires no developer token, and gives access to the full DOMO hierarchy.

### DOMO Tools

| Tool | Description | Available To |
|------|-------------|-------------|
| `domo_search` | Search datasets by name | Data Expert |
| `domo_dataset_info` | Dataset metadata + schema + row count | Data Expert |
| `domo_dashboards` | List all pages (dashboards) | Data Expert |
| `domo_dashboard_detail` | Cards (KPIs) on a specific dashboard | Data Expert |
| `domo_query` | SQL query against dataset (PARKED — awaiting confirmation) | — |
| `analyze_domo_dataset` | Download S3 CSV + DuckDB local analysis | Principal, Data Expert |

### DOMO Hierarchy

```
Pages (Dashboards)
└── Cards (KPIs / Visualizations)
    └── Datasets
        └── Streams (data sources)
```

### Data Analysis Path

For actual data analysis, Genie uses **DOMO S3 exports + DuckDB** (`analyze_domo_dataset`), not the DOMO REST API. The REST API provides metadata only (dataset schema, dashboard structure, card definitions). This avoids DOMO API rate limits and gives full SQL flexibility.

### Configuration

- **Credentials**: Settings → Connection tab (client_id, client_secret, encrypted in postgres)
- **Env vars**: `DOMO_CLIENT_ID`, `DOMO_CLIENT_SECRET` (optional, prefer in-app)
- **SSL**: `DOMO_VERIFY_SSL=true` in prod, `false` in local dev (corporate proxy)

### Golden Rule Prompt

All agents follow the "Golden Rule": **BEFORE answering ANY technical question, MUST use at least one tool.** This ensures answers are grounded in real data, not hallucinated from training knowledge.

- **Technical questions** (DAGs, tables, SQL, configs) → investigate using tools first, then answer
- **Business questions** (definitions, pillar context) → can answer directly from KB context

### Timeouts

- **Sub-agent timeout**: 2 minutes max per sub-agent call
- **Total response timeout**: 5 minutes max for the entire principal agent response cycle
- Prevents hanging on overly broad questions or MCP server latency

## repo_search Tool

`repo_search` greps locally cloned repos instantly via subprocess. Much faster than reading files one by one through the GitHub API or MCP.

- Available to: Data Expert, Principal agent
- Searches: `/app/data-repo-kb` (KB clone, always on main)
- Implementation: subprocess call to `grep -rn` with pattern matching
- Use case: quick searches for table names, column references, SQL patterns across the entire repo

## Implementation

**Status: Complete.**

### Key Files
- `backend/engine/agents/prompts.py` — All sub-agent system prompts (principal, data, redshift, kb_agent). Knowledge Expert removed.
- `backend/engine/agents/runner.py` — Agent orchestration: principal routing, sub-agent invocation, parallel execution, result synthesis
- `backend/engine/agents/tools.py` — Tool definitions per sub-agent, sub-agent wrapper functions for principal
- `backend/engine/mcp_bridge.py` — MCP server lifecycle management and tool proxy
- `backend/api/agent_prompts.py` — Admin API for editing prompts; prompts persisted in postgres so admins can tune without redeployment

### Admin-Editable Prompts
All sub-agent prompts are stored in postgres and editable through the Admin Console. Changes take effect immediately — no container restart needed. The `prompts.py` file provides defaults that seed the database on first run.

### Conversation Summarization
Long sessions are compressed using Haiku (cheap, fast model) to keep context windows manageable. When a conversation exceeds the token threshold, older messages are summarized into a compact context block that preserves key facts and decisions while discarding verbose tool output.

## Future: Anthropic Agent SDK

When the Agent SDK supports multi-agent orchestration natively:
- Replace tool-based delegation with SDK agent handoffs
- Agents get persistent memory across conversations
- Built-in parallel execution and result aggregation
- Shared context without re-sending full prompts
