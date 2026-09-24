# Jennie — Design Specification

## Vision

An AI assistant that has the same knowledge as the most senior data engineer on the team — every table, every pipeline, every metric, every dependency. Engineers and analysts ask questions and get answers grounded in real platform metadata, not generic responses.

## Design Principles

1. **Real data, not mocks** — Knowledge comes from actual MWAA task logs, Git repo, and Redshift system tables. No synthetic data.
2. **MWAA is the source of truth** — Rendered SQL from task execution logs is the authoritative source for what data looks like. Git repo is supplementary.
3. **Context efficiency** — Split knowledge base keeps Claude's context small. Full detail loaded on demand via tools.
4. **Read-only by design** — Only SELECT and ANALYZE queries. Safety guard at connection level. No data modification ever.
5. **In-app self-sufficiency** — All connections, auth, builds, and operations run inside the app. No CLI tools required.
6. **Credentials never leak** — Passwords encrypted in postgres, never logged, never in Claude context, never in .env if set via app.

## Knowledge Base Architecture

### Sources (Priority Order)

```
┌─────────────────────────────────────────────────────┐
│ 1. MWAA Task Logs (PRIMARY)                          │
│    - Rendered SQL (post-Jinja, real table names)     │
│    - Run history (success rate, avg duration)        │
│    - Per-task execution stats (duration, retries)    │
│    - DAG status (active, paused, failing)            │
├─────────────────────────────────────────────────────┤
│ 2. Redshift System Tables                            │
│    - Column names, types, positions                  │
│    - Distkeys, sortkeys, row counts, sizes           │
│    - Table vs view classification                    │
│    - Column-level profiling (via datashare)          │
├─────────────────────────────────────────────────────┤
│ 3. Git Repo (SECONDARY)                             │
│    - YAML config metadata (schedule, tags, params)   │
│    - Git blame (who changed, when, why)             │
│    - DAG template structure understanding           │
├─────────────────────────────────────────────────────┤
│ 4. Human Knowledge                                   │
│    - Glossary (curated definitions)                  │
│    - User corrections (via glossary wizard)          │
│    - DOMO view definitions (planned)                 │
└─────────────────────────────────────────────────────┘
```

### Split File Structure

```
knowledge/
├── catalog.json            → Tables only (~20K)      ← Always in Claude context
├── transforms_index.json   → DAG summaries (~260K)   ← Compact in context
├── lineage.json            → Dependency graph (~196K) ← Available via tools
├── glossary.yaml           → Business definitions     ← In context
├── transforms/             → Per-DAG detail files     ← On demand only
│   └── {dag_id}.json       → Rendered SQL, task stats, run history (~8.6M total)
└── CLAUDE.md               → Platform context         ← In system prompt
```

**Why split?** A single catalog.json with rendered SQL for 160+ DAGs would be 10M+. Claude's system prompt would bloat on every request. The split keeps prompts small (~500K) while the full 8.6M of detail is accessible via the `get_transform_detail` tool when needed.

### KB Build Versioning

Every build creates a record in the `kb_builds` table with a snapshot (table/transform/glossary names) and diff (added/removed vs previous build). History is viewable in Settings > Knowledge Base.

### Knowledge Source Tagging

Every table and transform in the knowledge base is tagged with its data sources:

| Tag | Source | Example |
|-----|--------|---------|
| `platform` | MWAA task logs | Rendered SQL, run history, task stats |
| `database` | Redshift system tables | Column types, distkeys, row counts, profiling |
| `code` | Git repo | YAML configs, git blame, commit history |
| `ai_generated` | AI enrichment | Auto-generated descriptions for tables, columns, non-SQL DAGs |
| `user` | Human input | Glossary entries, wizard contributions, chat corrections |

**Trust hierarchy** (highest to lowest): `user` > `database` > `platform` > `code` > `ai_generated`

When sources conflict (e.g., AI-generated description vs user-provided), the higher-trust source wins. User corrections always take precedence.

**Completeness score**: Each table/transform gets a 0-1 completeness score based on how many knowledge dimensions are filled (description, columns, lineage, SQL, profiling, glossary terms, classification). A table with only a name from Redshift discovery scores ~0.1; a fully profiled, described, lineage-traced table with glossary terms scores ~0.95.

**knowledge_summary.json**: Generated alongside catalog.json on every KB build. Contains:
- Per-source tag distribution (how many items come from each source)
- Completeness score histogram (how many items at each score tier)
- Lowest-coverage items (bottom 20 by completeness)
- Trust hierarchy definition

This file is injected into agent prompts so sub-agents know coverage gaps and can accurately report what's missing vs what's available.

**AI Enrichment phase**: After the primary KB build (MWAA + Redshift + Git), an optional enrichment pass uses Claude to generate descriptions for:
- Tables with no human or MWAA-derived description
- Columns with no description (using table context, naming patterns, and profiling data)
- Non-SQL DAGs (ingest, extract, braze) where MWAA logs don't contain rendered SQL

The enrichment model is selectable in Settings > Knowledge Base: Opus (highest quality, slowest), Sonnet (balanced), or Haiku (fastest, cheapest). All AI-generated content is tagged `ai_generated` and ranks lowest in trust hierarchy.

#### Document Upload

Users can upload `.txt`, `.md`, `.csv`, `.pdf`, or `.docx` files through the Admin Console > Knowledge Base tab. The upload flow:

1. File uploaded (max 5MB, text-only extraction — no executable content)
2. AI extracts candidate glossary terms, table descriptions, and business definitions from the document text
3. Extracted items appear as draft glossary entries in the feedback kanban board
4. Each draft creates a feedback ticket (category: `glossary`) for PR-style review
5. Approved items merge into glossary.yaml on next KB build

This supports onboarding knowledge capture — team leads can upload existing documentation, runbooks, or metric definition spreadsheets and have them flow into the knowledge base through the standard review process.

### Claude Tools

#### KB Tools (internal knowledge base)

| Tool | What it does | Data source |
|------|-------------|-------------|
| `search_tables` | Fuzzy search tables by name/description | catalog.json |
| `search_transforms` | Search DAG configs | transforms_index.json |
| `get_table_detail` | Full table metadata + columns | catalog.json |
| `get_transform_detail` | Rendered SQL, task stats, run history | transforms/{dag_id}.json |
| `get_table_lineage` | Upstream/downstream dependencies | lineage.json |
| `get_view_detail` | View SQL definition and DOMO links | views/{view_name}.json |
| `glossary_lookup` | Business term definitions | glossary.yaml |
| `execute_query` | Run SELECT on Redshift | Direct connection |

#### Local Tools

| Tool | What it does | Data source |
|------|-------------|-------------|
| `repo_search` | Grep locally cloned repos via subprocess (fast) | /app/data-repo-kb |
| `aws_lookup` | Query AWS services (CloudWatch, Glue, Lambda, ECS) | AWS SSO |
| `github_file` | Read files from GitHub repos | GitHub API |

#### MCP Tools (via Model Context Protocol)

The GitHub MCP server (`@modelcontextprotocol/server-github`) runs as a Node.js subprocess inside the backend container. 26 tools discovered, 4 filtered as useful:

| Tool | What it does | Available to |
|------|-------------|-------------|
| `github__search_code` | Search code across GitHub repos | Data Expert, Knowledge Expert |
| `github__get_file_contents` | Read file contents from GitHub | Data Expert, Knowledge Expert |
| `github__list_commits` | List commit history for a repo/path | Data Expert |
| `github__search_repositories` | Search for repositories | Data Expert |

**MCP tools are on sub-agents only** — the principal agent has NO MCP tools. This keeps the principal lean for fast routing. Tools are generic capabilities; agent prompts carry organization-specific context.

#### Tool Distribution Per Agent

```
Principal Agent (routing + direct investigation)
├── Direct tools: execute_query, aws_lookup, repo_search, github_file
├── Delegates to:
│
├── Data Expert
│   ├── KB tools: search_transforms, get_transform_detail, get_table_lineage, get_view_detail
│   ├── Local tools: repo_search, github_file, aws_lookup
│   └── MCP tools: github__search_code, github__get_file_contents, github__list_commits
│
├── Redshift Expert
│   └── KB tools: search_tables, get_table_detail, execute_query
│
└── Knowledge Expert
    ├── KB tools: glossary_lookup
    └── MCP tools: github__search_code, github__get_file_contents
```

## Environment Model

### Nonprod vs Prod

```
Nonprod (111111111111)                   Prod (222222222222)
┌──────────────────────┐                ┌──────────────────────┐
│ np_dw (queries)      │  ← datashare ← │ prd_dw (real data)   │
│ np_data_lake         │                │ prd_data_lake         │
│ np_personalize       │                │ prd_personalize       │
│                      │                │                       │
│ MWAA: nonprod-airflow │                │ MWAA: prod-airflow  │
│ (testing DAGs)       │                │ (production DAGs)     │
│ (dq_sync validates   │                │                       │
│  prod via datashare) │                │                       │
└──────────────────────┘                └──────────────────────┘
```

### MWAA Priority
1. **Prod MWAA** — highest value, real production pipelines
2. **Nonprod dq_sync** — validates production data quality
3. **Nonprod other** — testing/development DAGs

### Redshift Operations
- **PROFILE** → runs on nonprod via `prd_dw.*` datashare (read-only, safe)
- **ANALYZE** → runs on prod directly (updates planner stats, needs prod creds)
- **Discover** → queries SVV_ALL_TABLES on whichever environment has creds

## Table Operations Engine

### Sequential Job Queue

```
┌─────────────────────────────────────────────┐
│ Job Queue (sequential, one at a time)        │
│                                              │
│  [PROFILE prd_dw.dim.country] → completed    │
│  [PROFILE prd_dw.dim.date] → running (45s)   │
│  [PROFILE prd_dw.analytics.onb...] → queued  │
│                                              │
│  Auto-kill if > timeout (configurable)       │
│  Capabilities-aware (checks which creds)     │
└─────────────────────────────────────────────┘
```

### Column Profiling (per column)
- Distinct count + cardinality ratio
- Null count + null rate
- Min/max (numeric and date types)
- Sample-based for large tables (>10M rows)

### Auto-Classification
- **Fact**: high row count + date columns + high cardinality + delta_load/refill_days
- **Dimension**: low row count + few columns + low cardinality + stable
- Manual override always available

## Authentication Flow

### AWS SSO (for MWAA)
```
Frontend → POST /auth/sso/start → Okta SSO page in browser
         → Poll /auth/sso/poll → Device code exchange
         → Credentials stored in postgres + in-memory
         → Used by MWAA fetcher for Airflow API access
```

### Redshift Direct (for queries/profiling)
```
Settings > Connection > Enter username/password
         → POST /auth/redshift/credentials
         → Test connection immediately
         → Stored encrypted in postgres
         → Restored on backend restart
         → Used by all Redshift operations
```

## Git Repo Integration

### How DAGs Are Built
```
YAML Config → TransformDAGTemplate.py → Airflow DAG
(schedule,    (Python template that     (Dynamic DAG with
 params,       reads YAML and            tasks for each
 steps)        creates DAG)              SQL step)
```

### What Genie Extracts from Repo
- YAML config metadata (schedule, tags, delta_load, refill_days, notify_email)
- Git blame per file (last author, date, commit message)
- Recent commit history (last 5 changes)
- SQL step file references

### Repo Structure (data-platform-dags)
```
dags/
├── transform/conf/    → 150+ transform YAML configs
├── dq_sync/conf/      → 39 DQ validation configs
├── events_v3/conf/    → Events pipeline configs
├── ingest_s3/conf/    → S3 ingestion configs
├── personalization/   → ML/recommendation pipelines
├── statsig/           → Feature gate experiment data
├── extract/           → External data pulls
└── braze/             → Marketing automation data
```

## Security Model

### Query Safety
```python
# Every query passes through validate_query_safety()
ALLOWED: SELECT, EXPLAIN, ANALYZE, SET, SHOW, WITH
BLOCKED: CREATE, DROP, TRUNCATE, DELETE, INSERT, UPDATE,
         MERGE, ALTER, GRANT, REVOKE, COPY, UNLOAD
```

### Credential Isolation
- Redshift passwords stored in postgres `credential_cache` table
- Never in environment variables (if set via app)
- Never logged (only username logged)
- Never in Claude's system prompt or tool responses
- Never in knowledge base files
- Restored from postgres on backend restart

## Roadmap

### Phase 1 — Column Intelligence (next)
- Expandable table row → column-level profile data in UI
- Auto-categorize columns: Primary Key, Foreign Key, Dimension, Metric, Date/Time, Flag
- Detection heuristics based on cardinality, naming, data type

### Phase 2 — Full Table Intelligence
- Discover across all schemas (analytics, fact, dim, events, data_lake, personalize)
- Batch profile all high-value tables
- Cross-reference with DOMO views for metric identification

### Phase 3 — Catalog Enrichment
- Parse DOMO DAGs + views for metric/KPI definitions
- Expand lineage to all DAG types (not just TRANSFORM_DAG__)
- Comprehensive glossary from DOMO + SQL + column profiles
- Schedule runner for recurring PROFILE/ANALYZE

### Phase 4 — Polish
- Auto-generated column descriptions from profile + SQL context
- Chat quality validation with full real knowledge base
- Nonprod MWAA data in knowledge base

## RBAC

RBAC is implemented with 4 roles and 22 granular permissions:

| Role | Description |
|------|-------------|
| **viewer** | Chat and catalog read-only |
| **analyst** | + query execution, glossary contributions |
| **engineer** | + pipeline building, git operations, table ops |
| **admin** | + ANALYZE on prod, credential management, schedule config, KB builds |

Settings tabs are role-gated — users only see tabs their role permits. Chat sessions and settings are user-scoped.

## Multi-User Isolation

- **Per-user git worktrees**: Each user gets an isolated worktree at `/app/data-repo-worktrees/{user_id}` for branch/commit operations without conflicts.
- **Separate KB clone**: The knowledge base always clones from main at `/app/data-repo-kb`, independent of user worktrees.
- **Chat sessions scoped by user_id**: Users can only see and access their own conversations.
- **Settings keyed by user_id**: User preferences (persona, system prompt, user context) persist across login sessions.
- **Auth token on every API call**: `fetchJSON` sends an `X-Auth-Token` header with every request for user identification.

## Feedback System

Unified kanban board for all action items across the platform:

- **Categories**: Chat, Glossary, KB Gap, Data, Pipeline
- **Auto-ticket creation**: The agent detects KB gaps during chat and automatically creates feedback tickets.
- **Glossary enricher integration**: Auto-creates review tickets when new glossary entries are generated from view SQL.
- **Per-message flagging**: Every chat message has a flag button for users to report issues or request corrections.
- **Workflow**: New > In Review > Approved > Done (kanban columns)
