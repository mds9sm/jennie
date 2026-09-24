# Jennie

AI-powered data engineering platform for the data team. Built by Sri Maru.

## What This Is

A web-based AI assistant that knows your data platform — catalog, glossary, lineage, pipelines, and business definitions. Engineers and analysts use it to query data, build pipelines, look up metrics, and trace impact.

## Architecture

```
Docker Compose (3 containers):
├── frontend/    → React 19 + Tailwind + Vite, served via nginx on :3333
├── backend/     → FastAPI + Codex API + Redshift connector on :8000
└── postgres     → Usage tracking, sessions, glossary, tasks, KB builds on :5434
```

## Tech Stack

- **Frontend**: React 19, TypeScript, Tailwind CSS, Vite, react-markdown, lucide-react
- **Backend**: FastAPI, Python 3.12, anthropic SDK, asyncpg, redshift_connector, boto3, rapidfuzz
- **AI**: Codex via Anthropic API or AWS Bedrock (switchable in UI). **Tiered model strategy**: Sonnet 4 for routing/tool calls/sub-agents (speed + cost), Opus 4.6 for complex synthesis only. **Persona-based prompts** (5.4K chars total, down from 16K): prompts.py = identity, context.py = per-request user context. **Classification-based routing**: DATA/METRIC/DEFINITION/INVESTIGATION/MODELING/CONVERSATIONAL. **Analytics engineering mental model**: DOMO S3 → views → aggregates → facts → raw events (always most downstream first). Principal tools: search_tables, search_transforms, execute_query, analyze_domo_dataset + expert delegation. Sub-agent KB tools: search_tables, search_transforms, get_table_detail, get_transform_detail, get_table_lineage, get_view_detail, glossary_lookup, execute_query, repo_search, github_file, aws_lookup. DOMO tools (Data Expert): domo_search, domo_dataset_info, domo_dashboards, domo_dashboard_detail. MCP tools (sub-agents only): github__search_code, github__get_file_contents, github__list_commits, github__search_repositories
- **MCP**: GitHub MCP server (`@modelcontextprotocol/server-github`) via `backend/engine/mcp_bridge.py`. 4 filtered tools: search_code, get_file_contents, list_commits, search_repositories.
- **DOMO**: Direct REST API (`backend/connectors/domo_client.py`). Uses same client_id/secret as Airflow DOMO_REFRESH DAGs. STRICTLY READ-ONLY. Agent tools: `domo_search`, `domo_dataset_info`, `domo_dashboards`, `domo_dashboard_detail` (metadata only). `domo_query` parked (awaiting confirmation). Data analysis via S3/DuckDB (`analyze_domo_dataset`). Full hierarchy: Pages → Cards → Datasets → Streams. Credentials encrypted in postgres, managed via Settings → Connection. `DOMO_VERIFY_SSL=true` in prod, `false` in local dev.
- **DB**: PostgreSQL 16 (usage_events, chat_sessions, user_settings, glossary_feedback, glossary_entries, table_registry, table_ops_jobs, table_ops_schedules, credential_cache, schedule_runner_config, tasks, kb_builds, users, scheduled_reports, notifications, registration_requests)
- **Auth**: Okta OIDC (primary, feature-flagged via `OKTA_CLIENT_ID`) + password login (fallback) + AWS SSO device auth + direct Redshift credentials (encrypted in postgres). Credentials persist across restarts. SSO refresh tokens saved to postgres (survive backend restarts, auto-restored on startup).

## Key Directories

```
backend/
├── api/              → FastAPI routers (chat, sql, pipeline, glossary, impact, settings, auth, activity, history, scheduled_reports, notifications, cost_explorer)
├── engine/           → Codex client, context builder, pillar definitions, tools, env router, mcp_bridge
├── catalog/          → Knowledge base loader, fuzzy search, lineage traversal
├── catalog_engine/   → Catalog refresh: repo_cloner, repo_parser, mwaa_fetcher, glossary_builder, builder, api
├── connectors/       → Redshift (IAM/SSO), mock Redshift, credential store
├── tracking/         → Usage event logging + cost estimation
└── knowledge/        → Split knowledge base (see structure below), AGENTS.md, fixtures/

frontend/src/
├── api/              → Fetch client with SSE streaming
├── context/          → React contexts: Pillar, Environment, Auth
├── components/
│   ├── chat/         → ChatView (session persistence, summarization), MessageBubble, SQLCard, DefinitionCard, PipelineCard, ImpactCard, LineageCard
│   ├── sql/          → QueryRunner (unified Workbench), GitPanel (repo browser + git ops)
│   ├── glossary/     → GlossaryReview (PR-style: draft→review→approve→merge, AI wizard)
│   ├── activity/     → ActivityPage (GitHub-style heatmap with clickable day detail), CostExplorer (admin-only usage analytics)
│   ├── admin/        → AgentPrompts, UserManagement (rendered inside Settings)
│   ├── settings/     → SettingsPage (all config: Persona, System Prompt, Git, Activity, Cost Explorer, Connection, KB, Table Ops, Agent Prompts, Users — role-gated tabs)
│   ├── lineage/      → LineageGraph (interactive table dependency visualization)
│   ├── reports/      → ReportsPage (scheduled report outputs, run now, enable/disable)
│   ├── tasks/        → TaskBoard (kanban board, task creation, chat integration)
│   ├── notifications/ → NotificationBell (header bell icon, dropdown, polling)
│   ├── layout/       → Header (live connectivity icons, NotificationBell), Sidebar (chat sessions), MainLayout
│   └── common/       → ResultsTable, SSOConnectModal, FeatureTips (contextual tip rotation)
└── types/            → TypeScript interfaces
```

## Running

```bash
# Start everything
docker compose up -d

# Frontend: https://genie.example.com (production) / http://localhost:3333 (local dev)
# Backend:  http://localhost:8000 (internal)
# Postgres: localhost:5434 (internal)

# Rebuild after changes
docker compose build && docker compose up -d

# Fresh DB (drops usage/sessions)
docker compose down && docker volume rm jennie_pgdata && docker compose up -d
```

## Environment Variables (.env)

- `ANTHROPIC_API_KEY` — Required for AI features
- `REDSHIFT_MODE` — `mock` (default) or `real`
- `AWS_PROFILE_NP` / `AWS_PROFILE_PRD` — AWS SSO profiles from ~/.aws/config
- `CLAUDE_MODEL` — Default: Codex-sonnet-4-20250514
- `REPO_URL` — GitHub HTTPS URL for data platform repo (e.g. https://github.com/your-org/data-platform-dags)
- `GITHUB_TOKEN` — Personal access token (needs repo scope + SAML SSO authorization for your-org org)
- `REPO_PATH` — Local clone path inside container (default: /app/data-repo)
- `AI_PROVIDER` — `anthropic` (default, direct API) or `bedrock` (AWS Bedrock via SSO)
- `BEDROCK_REGION` — AWS region for Bedrock (default: us-west-2)
- `BEDROCK_MODEL` — Bedrock heavy model for synthesis (default: us.anthropic.Codex-opus-4-6-v1)
- `BEDROCK_MODEL_FAST` — Bedrock fast model for routing/sub-agents (default: us.anthropic.Codex-sonnet-4-20250514-v1:0)
- `DOMO_CLIENT_ID` — (optional, prefer Settings → Connection) DOMO OAuth client ID (same client_id/secret as Airflow DOMO_REFRESH DAGs)
- `DOMO_CLIENT_SECRET` — (optional, prefer Settings → Connection) DOMO OAuth client secret
- `DOMO_VERIFY_SSL` — SSL verification for DOMO API (default: `true`, set `false` for local dev behind corporate proxy)
- `REDSHIFT_NP_USER` / `REDSHIFT_NP_PASSWORD` — Direct Redshift credentials for nonprod (optional, can also be set in-app)
- `REDSHIFT_PRD_USER` / `REDSHIFT_PRD_PASSWORD` — Direct Redshift credentials for prod (optional, can also be set in-app)
- `OKTA_CLIENT_ID` — Okta OIDC client ID (feature flag: enables "Sign in with Okta" button)
- `OKTA_CLIENT_SECRET` — Okta OIDC client secret (server-side only)
- `OKTA_ISSUER` — Okta org issuer URL (e.g., `https://your-org.okta.com/oauth2/default`)

### Redshift Connection Priority
1. Direct user/password (from in-app settings or .env) — simple, no IAM/SSO needed
2. AWS SSO credentials (from in-app SSO device auth)
3. Shared fallback (mounted ~/.aws or explicit .env creds)

Note: Okta SAML for Redshift was attempted but doesn't work from container (MFA + app URL issues). Use direct credentials instead. For app login, Okta OIDC is the primary method (see `OKTA_CLIENT_ID`).

### Security
- Redshift credentials stored encrypted in postgres `credential_cache` table
- Passwords NEVER logged, NEVER in Codex context, NEVER in .env (if set via app)
- `validate_query_safety()` blocks all non-SELECT/ANALYZE queries at connection level
- Query guard enforced in: execute_real_query, PROFILE operations, and all tool-based queries

## Design Decisions

- **Chat-first**: All capabilities render as inline action cards (SQLCard, DefinitionCard, etc.) in the chat. Standalone tabs exist as power-user entry points.
- **Mock mode default**: App runs fully without AWS/Redshift — mock data in knowledge/fixtures/
- **Per-user SSO**: Each user authenticates independently via AWS SSO device auth flow. Credentials stored per-session in memory.
- **Split knowledge base**: Catalog (tables), transform index (summaries), lineage graph loaded at startup. Per-DAG detail files (rendered SQL, task stats) loaded on demand when Codex calls `get_transform_detail`. Keeps Codex's context small while full data is always available via tools.
- **Nonprod-first**: All data queries default to nonprod (has prod datashares). Prod direct access only for: table metadata/stats, MWAA prod logs, EXPLAIN plans, DOMO bucket reads. Prod MWAA is highest priority for knowledge base (real pipelines). Nonprod dq_sync DAGs are second priority (validates prod data). Other nonprod DAGs are testing/development.
- **Tiered models**: Sonnet for speed-sensitive operations (routing, tool calls, sub-agents), Opus only for complex synthesis. Matches investigation depth to question type — simple data queries finish in <20s, complex investigations take 1-2 min.
- **Goose-style UX**: Real-time investigation trail (step log with icons, details, spinners) instead of a single "thinking..." status. Users see exactly what the agent is doing at each step.

## the organization-Specific Context

- **Pillars**: Onboard, Trigger Return, Makeable Content, Content Matching, Design & Make, Guided Flows, Blank Canvas, Marketing, Platform
- **Redshift clusters**: nonprod-redshift-cluster (111111111111, role: DataNonProdReadRole), prod-redshift-cluster (222222222222, role: DataProdReadOnlyRole)
- **MWAA**: nonprod-airflow-mwaa (nonprod), prod-airflow-mwaa (prod)
- **DAG prefixes**: `TRANSFORM_DAG__` (pipelines), `DOMO__` (DOMO exports to prod-bi-export S3), `dw_sync__` (DQ validation — runs in nonprod, validates prod)
- **Late arrival**: Board metrics use refill_days: 45 (offline device sync latency)
- **Event source**: firehose_v3_enriched (ProductApp events → Kafka → S3 → data_lake → Redshift)
- **Redshift columns**: No COMMENT ON COLUMN — descriptions come from Genie's catalog annotations
- **YAML downstream_dags**: Transform YAML configs have a `downstream_dags` field for explicit dependency declaration
- **TriggerDagRunOperator**: DAG-to-DAG dependencies visible in MWAA task logs

## Knowledge Base Enrichment

Genie's knowledge comes from 3 tiers with clear priority:

**Tier 1 — MWAA (primary):** Task execution logs from both nonprod and prod MWAA. Fetches rendered SQL (Jinja2-resolved, actual executed queries), real table names, run durations, DAG status, and task metadata. This is the authoritative source for SQL logic, table lineage, and runtime behavior. The catalog engine connects via AWS SSO → `create_web_login_token` → Airflow REST API.

**Tier 2 — Git Repo (secondary):** Clones `your-org/data-platform-dags` inside the container. Provides supplementary context: git blame (who changed what), commit history (when it was updated), YAML config metadata (schedule, tags, delta_load, refill_days, owners). NOT used for SQL lineage — that comes from MWAA. Repo configs span: transform, dq_sync, events_v3, ingest_s3, ingest_sqs, personalization, statsig, extract, ingestion_pipelines, braze.

**Tier 3 — Human Knowledge:** Glossary wizard (AI questionnaire), chat-based capture (auto-detect corrections), bulk CSV/YAML import, Slack/JIRA integration (future), onboarding interviews, monthly review cycles with pillar leads.

The catalog engine (backend/catalog_engine/) runs as a **background batch job** triggered from Settings > Knowledge Base tab. Sources are independently toggleable:
- **MWAA** (primary) — rendered SQL, lineage, run stats from both np + prd
- **Redshift** (optional) — column names/types, distkeys, sortkeys, row counts via read-only SELECT on system views
- **Git Repo** (secondary) — git blame, commit history, YAML config metadata

The UI polls for live progress as each DAG/table is processed.

### Knowledge Base File Structure

```
knowledge/
├── catalog.json            → Tables only (~20K)
├── transforms_index.json   → DAG summaries (~260K)
├── lineage.json            → Dependency graph including downstream_dags (~200K)
├── metrics.json            → DOMO + view metric definitions (166 entries)
├── glossary.yaml           → Business definitions
├── metadata_dags.json      → Non-SQL DAG metadata (schedule, owner, tasks)
├── coverage.json           → MWAA coverage report per environment
├── knowledge_summary.json  → Source provenance stats for agent awareness
├── enrichment_report.json  → AI enrichment results + cross-reference gaps
├── transforms/             → Per-DAG detail files (rendered SQL, task stats)
│   └── {dag_id}.json
├── views/                  → Per-view SQL definitions (the metric definitions!)
│   └── {view_name}.json    → CREATE OR REPLACE VIEW SQL, source tables, DOMO link
└── AGENTS.md               → Platform context
```

**Context efficiency**: Codex's system prompt gets tables + transform summaries + lineage (compact). Rendered SQL and task stats are only loaded when Codex calls `get_transform_detail` for a specific DAG — keeping every prompt small while the full knowledge base is accessible via tools.

### Catalog Engine Modules

- **builder.py** — Orchestrator: MWAA primary → repo enrichment → merge → write catalog.json
- **mwaa_fetcher.py** — Connects to MWAA via boto3, fetches all TRANSFORM_DAG__ DAGs, gets rendered SQL from last successful run
- **repo_cloner.py** — Clones/pulls git repo via subprocess (supports GitHub token auth for private repos)
- **repo_parser.py** — Parses YAML configs + git blame/history (not SQL lineage)
- **redshift_metadata.py** — Queries SVV_ALL_TABLES/COLUMNS for physical metadata (when REDSHIFT_MODE=real)
- **glossary_builder.py** — Merges base glossary.yaml with approved user corrections from postgres
- **redshift_metadata.py** — Read-only SELECT on SVV_ALL_TABLES, SVV_ALL_COLUMNS, SVV_TABLE_INFO, PG_TABLE_DEF for column/distkey/sortkey/row count metadata
- **domo_parser.py** — Parses DOMO refresh configs, transform view definitions, downstream_dags. Builds metric chain: view SQL → DOMO dataset → dashboard
- **glossary_enricher.py** — Auto-generates glossary entries from view SQL (aggregations, source tables, dimensions). Draft → expert review → approved
- **schedule_runner.py** — Background cron executor. Checks every 60s for due schedules. Active/inactive toggle (defaults inactive)
- **classifier.py** — Weighted scoring for table (fact/dim) and column (PK/FK/metric/dimension/date/flag) classification
- **api.py** — Background task runner with progress polling: POST /refresh, GET /status, GET /repo/status, POST /repo/clone
- **kb_enricher.py** — AI-powered enrichment: pipeline summaries, table/column descriptions (Opus/Sonnet/Haiku selectable), metric conflict detection, repo↔MWAA cross-reference
- **knowledge_tagger.py** — Tags each KB item with source provenance (platform/database/code/ai_generated/user), completeness scoring, knowledge summary for agents
- **kb_tracker.py** — Build versioning: snapshot + diff per build, history API

### MCP Bridge

- **backend/engine/mcp_bridge.py** — MCP server lifecycle management and tool proxy. Starts `@modelcontextprotocol/server-github` as Node.js subprocess, proxies tool calls from agent runner, handles restart on failure. Requires Node.js installed in backend Docker image. DOMO access is via direct REST API (not MCP).

### Table Operations Engine (planned/in progress)
Sequential job queue for table-level operations on Redshift:
- **ANALYZE** — runs on prod Redshift directly to update planner stats (SVV metadata becomes accurate)
- **PROFILE** — runs on nonprod against prd_dw.* datashare tables (min/max, cardinality, nulls, distributions)
- **Auto-classify** — fact vs dimension from profile + ETL patterns + DOMO view references
- **Sequential execution** — one operation at a time, never parallel
- **Auto-kill** — configurable timeout per operation (default 120s)
- **Scheduling** — cron-like schedule stored in postgres
- **UI checklist** — table list with analyze/profile status, last run times, manual trigger, fact/dim classification
- **Capabilities** — system checks which creds exist: PROFILE needs nonprod (datashare), ANALYZE needs prod (direct)
- **Discovery** — queries Redshift SVV_ALL_TABLES per environment (np/prd), enriches with lineage value score, only verified tables in registry
- **Column profiling** — per-column: distinct count, cardinality ratio, null count/rate, min/max. Stored in postgres profile_data JSONB.
- **Auto-classification** — weighted scoring classifier (classifier.py): tables as fact/dimension/ambiguous, columns as primary_key/foreign_key/metric/dimension/date/flag. Signals: name patterns, row count, FK ratio, cardinality, data types, SCD detection
- **Capabilities** — system checks which creds exist: PROFILE needs nonprod (datashare), ANALYZE needs prod (direct)
- **RBAC** — admin-only access (future)

## Agent Architecture (DONE — Phase 3.5)
Principal agent + specialist sub-agents with **tiered model strategy** and **classification-based routing**:

### Tiered Model Strategy
- **Sonnet (fast)**: Principal routing, tool calls, sub-agent execution — optimized for speed + cost
- **Opus (heavy)**: Complex synthesis only (forced synthesis when limits hit) — optimized for quality
- Result: 2-5x faster responses, 5-7x cheaper per question vs Opus-everywhere
- Configurable: `BEDROCK_MODEL_FAST` (Sonnet), `BEDROCK_MODEL` (Opus)

### Classification-Based Routing (Principal)
Before acting, the principal classifies each question:
- **DATA** → search_tables → write SQL → execute_query (2-3 tool calls, ~10-20s, NO expert delegation)
- **DEFINITION** → ask expert for lookup → explain (1 expert call, ~15-20s)
- **INVESTIGATION** → delegate to data_expert (multiple tools, ~1-2 min)
- **MODELING** → delegate to redshift_expert (1 expert call, ~20-30s)
- **CONVERSATIONAL** → reply directly (no tools, ~3s)

### Principal Agent
- **Direct tools**: `search_tables`, `search_transforms`, `execute_query` — handles DATA questions without delegating
- **Expert delegation**: `ask_data_expert`, `ask_redshift_expert`, `ask_knowledge_expert`
- **NO investigation tools** (repo_search, github_file, aws_lookup) — prevents over-investigating simple questions

### Sub-agents
- **Data Expert** = Repo + Pipeline + Metrics (DAGs, SQL, lineage, views, DOMO, configs, MWAA, repo_search, github_file, aws_lookup, analyze_domo_dataset) + DOMO tools (domo_search, domo_dataset_info, domo_dashboards, domo_dashboard_detail) + MCP tools
- **Redshift Expert** = SQL queries, table metadata, data modeling, optimization
- **Knowledge Expert** = Glossary + Platform (business terms, pillar context, environment routing, security) + MCP tools
- **MCP integration**: GitHub MCP server (`@modelcontextprotocol/server-github`) — persistent session, 4 filtered tools
- Communication: tool-based delegation (sub-agent = separate Bedrock call with Sonnet)
- Sub-agents can run in parallel for multi-domain questions

### Goose-Style Investigation Trail
- Real-time step log shows each tool call as it happens (not just "thinking...")
- Each step: icon + label + detail (search term, SQL snippet, etc.)
- Running steps show spinner, completed steps show green checkmark
- Fade-in animation for new steps

### Limits & Safety
- Sub-agent: 5 iterations, 4096 max_tokens, 120s timeout
- Principal: 8 iterations, 80K token budget, 3 min max
- Forced synthesis with Opus when any limit hit
- Full spec: docs/ARCHITECTURE_AGENTS.md

## Unified Workbench (built — merges Query Runner + SQL Optimizer + Pipeline Builder + Git IDE)
All SQL development in one place:
- Multi-tab workbook, schema browser, repo file browser, Git panel
- Optimize button inline (AI analyzes SQL)
- "Create pipeline like X" via NL bar (AI replicates existing pipeline structure)
- Right-click context menu on repo files: new file, new folder, rename, delete
- Per-user git identity (name, email, GitHub token)
- Sidebar: Chat, Workbench, Glossary, Lineage, Tasks, Docs, Reports + Settings (Admin Console merged into Settings with role-gated tabs including Cost Explorer for admins)

## Git-Integrated SQL IDE (built — part of Workbench)
Full SQL development environment with Git integration in Query Runner:
- Browse repo SQL files (Schema/Repo Files toggle) alongside Redshift schemas
- Click file → opens in query tab, run against Redshift, edit and save back
- Right-click context menu: new file, new folder, rename, delete (uses git mv/rm)
- Feature branch workflow: create branch, switch, commit, push, create PR — all from app
- Diff view per file, branch status (ahead/behind), changed files with M/A/D badges
- Safety: blocks writes to main — must use feature branches
- Backend: /api/git/ endpoints (files, branches, status, diff, commit, push, PR, rename, delete)

## Chat Features (built)
- Session persistence: conversations saved to postgres, sidebar session list, shareable URLs (`/?session=id`)
- Conversation summarization: auto-compress after 10 messages using Haiku, context indicator
- Per-message actions: Copy + Flag (🚩) buttons on each assistant response
- Citations: source references at end of responses (📊 Table, 🔧 DAG, 📐 View, 📖 Glossary, 🔍 Query)
- Auto-charts: query results auto-render bar/line/pie charts (recharts), toggle between types
- KB gap detection: agents surface 💡 KB Improvement suggestions when info is missing
- Frustration detection: agent offers to create task when user seems unhappy
- No raw JSON: principal prompt enforces natural language synthesis
- Session deletion: delete button (X on hover) per chat in sidebar, DELETE /chat/sessions/{id}
- Auto-archive: sidebar only shows chats from last 30 days

## Cost Explorer (built — admin-only)
AWS Cost Explorer-style analytics for AI usage:
- Settings > Cost Explorer tab (admin-only)
- Summary cards: Total Cost, Total Tokens, Total Calls, Avg Cost/Call
- Daily/weekly/monthly bar charts with model breakdown (Opus=purple, Sonnet=blue, Haiku=green)
- Filters: by user + date range (7/30/90/365 days)
- User breakdown table with % of total
- Token split donut chart (input vs output)
- Backend: GET /activity/cost-explorer
- Frontend: CostExplorer component in components/activity/

## Activity Heatmap (built — clickable day detail)
- GitHub-style heatmap with clickable green dots
- Click any day -> detail panel: capability breakdown, tokens, cost, events table
- Backend: GET /activity/day-detail

## Task Board (built)
Full task board for the data team (sidebar, accessible to all authenticated users):
- 8 task types: investigation, data_issue, dag_failure, ai_quality, kb_gap, glossary, request, general
- Priority levels: critical, high, medium, low
- Due dates + tags for organization and filtering
- 4 columns: Open → In Progress → Resolved → Closed
- Chat integration: "Create Task" (self-assigned) + "Request Support" (admin-assigned) via flag icon
- Engineers + analysts can create tasks (not admin-only)
- Glossary tasks auto-track review progress with per-entry reviewer assignment (PR-style)
- Auto-created tasks: KB gaps, glossary drafts, support requests
- Backend: /api/tasks endpoints
- DB table: tasks

## Scheduled Reports (built)
Schedule button (clock icon) on each chat assistant response:
- Pick frequency: Daily 7am, Daily 9am, Weekly Monday 7am, Custom cron
- Schedule runner checks every 60 seconds for due reports
- AI generates fresh response using saved chat question (not cached)
- Output saved and viewable in Reports page (standalone sidebar page)
- Run Now for manual trigger, Enable/Disable toggle
- Notifications sent on completion or failure
- Backend: /api/scheduled-reports endpoints
- DB table: scheduled_reports

## Notification System (built)
Bell icon in header (between connectivity icons and environment toggle):
- Red badge with unread count, polls every 30 seconds
- Dropdown panel with notification list
- Types: scheduled_report (blue), task_assigned (red), task_updated (red), glossary_assigned (purple), registration_request (amber), kb_gap (orange)
- Mark read (individual + all), click to navigate to relevant page
- Backend: /api/notifications endpoints
- DB table: notifications
- Frontend: NotificationBell component

## User Registration (built)
"Request Access" form on login page:
- Email must be @example.com
- Fields: email, name, team, reason
- Admin sees pending requests in Settings → Users
- Approve creates viewer account with temp password
- Reject with optional reason
- Triggers registration_request notification to admins
- Backend: /api/auth/register, /api/auth/registrations endpoints
- DB table: registration_requests

## KB Build Versioning (built)
Every KB build tracked in `kb_builds` table:
- Snapshot: table names, transform IDs, glossary terms
- Diff vs previous build: added/removed per category
- Build History UI in Settings → Knowledge Base tab
- Sources tracked (MWAA, Repo, Redshift), stats, timing, errors
- Backend: catalog_engine/kb_tracker.py

## Multi-User Isolation (built)
- Per-user git worktrees: `/app/data-repo-worktrees/{user_id}/` (independent branches)
- Separate KB clone: `/app/data-repo-kb` (always main, read-only)
- Chat sessions scoped by user_id (privacy)
- Settings keyed by user_id (persist across login sessions)
- Auth token (X-Auth-Token) sent with every fetchJSON call

## Glossary Enrichment (built)
Multi-source glossary with provenance tracking:
- Source 1: View SQL (formulas, source tables, dimensions, filters)
- Source 2: Redshift COMMENT ON (table + column descriptions)
- Source 3: Repo configs (DAG owners, schedules)
- Source 4: Document uploads (.txt/.md/.csv/.pdf/.docx → AI extracts terms → draft entries → review ticket)
- Source badges in UI: View SQL (blue), Redshift (green), Repo (orange), DOMO (purple), Document (amber)
- Auto-creates task when new drafts generated
- PR-style review: draft → in_review → approved → merged

## Okta OIDC Login (built)
"Sign in with Okta" on login page — feature-flagged via `OKTA_CLIENT_ID`:
- OIDC Authorization Code flow with PKCE
- Onboarding screen for first-time Okta users (name, team, persona, pillar)
- Role capabilities matrix (visual display of what each role can do)
- Role change request → admin notification + task
- Password login remains as fallback
- Env vars: OKTA_CLIENT_ID, OKTA_CLIENT_SECRET, OKTA_ISSUER

## Production Deployment (built)
Deployment files following the organization infra standards:
- `Dockerfile.backend` — production backend image
- `Dockerfile.frontend` — production frontend image with nginx
- `docker-compose.prod.yml` — external RDS, persistent volumes
- `nginx.prod.conf` — security headers (CSP, HSTS), gzip, SSE proxy
- `.github/workflows/deploy.yml` — CI/CD pipeline
- `docs/DEPLOYMENT.md` — full deployment guide

## Planned: Redshift Query Workspace (Phase 3)
DataGrip-style Redshift IDE built into Genie:
- Multi-tab query consoles with independent connections
- Connection manager (np/prd, different users, IAM/direct)
- Schema browser sidebar (database → schema → table → column)
- AI-assisted: explain, optimize, auto-complete from knowledge base
- Lineage-aware: right-click table → show dependencies
- Glossary tooltips on columns, impact warnings on modifications
- Saved/shared queries across team

## Spec

Full product spec at ~/Downloads/Jennie_Spec.md
