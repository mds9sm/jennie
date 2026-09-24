# Changelog

## 2026-03-23 — Real Knowledge Base: MWAA + Git Repo Integration

### Live MWAA Integration (Primary Knowledge Source)
- App connects to both nonprod and prod MWAA via in-app AWS SSO device auth flow
- Fetches rendered SQL (Jinja2-resolved) from last successful run of every TRANSFORM_DAG__
- Extracts real table names, run durations, DAG status, column references from executed queries
- Lineage built from actual rendered SQL — not raw Jinja templates
- Progress reported live to UI as each DAG is processed

### Git Repo Integration (Secondary — Metadata)
- Clones `your-org/data-platform-dags` inside the backend container via GitHub token auth
- Parses 290 YAML configs + 853 SQL files across 10 DAG types (transform, dq_sync, events_v3, ingest_s3, personalization, statsig, etc.)
- Extracts git blame (last author, date, commit message) and recent history per config file
- Provides supplementary context: schedule, tags, notify_email, delta_load, refill_days, owners
- Repo does NOT provide lineage — that's MWAA's job

### Catalog Engine Overhaul
- `repo_cloner.py` — New module: clone/pull via subprocess git with GitHub token auth (SAML SSO supported)
- `repo_parser.py` — Rewritten to match actual the organization YAML format (DAG-name-as-top-key pattern), focuses on git metadata
- `builder.py` — Restructured: MWAA primary → repo enrichment → merge. Fetches from both np + prd. Reports live progress.
- `api.py` — Build runs as background asyncio task with polling (no more gateway timeouts). New endpoints: /repo/status, /repo/clone
- `mwaa_fetcher.py` — Added progress reporting for live UI updates

### Settings — Knowledge Base Tab
- New tab in Settings: repo status, MWAA environment checkboxes, "Build Knowledge Base" button
- Live progress display: current phase, DAG being processed (e.g., "np 45/160: TRANSFORM_DAG__foo")
- Build results: table/transform/lineage counts, MWAA stats, repo stats, errors
- Source toggles: MWAA (primary) and Git Repo (secondary) independently selectable

### SSO Auth Fixes
- Fixed `InvalidGrantException` ("device code already redeemed") causing infinite polling
- Fixed `ForbiddenException` ("No access") giving 500 instead of user-friendly error
- Updated IAM roles: nonprod → `DataNonProdReadRole`, prod → `DataProdReadOnlyRole`
- Generic poll errors now return structured responses instead of 500s

### Redshift Metadata (Optional Source)
- Added Redshift as a toggleable source in Knowledge Base tab
- Queries system views only (SELECT on SVV_ALL_TABLES, SVV_ALL_COLUMNS, SVV_TABLE_INFO, PG_TABLE_DEF)
- Uses SSO credentials from credential_store — no longer gated by REDSHIFT_MODE env var
- Provides: column names/types, distkeys, sortkeys, row counts, table sizes
- Environment selector (nonprod/prod) in the UI
- Clearly labeled as read-only with explanation in UI

### Task Logs SQL Extraction
- Rendered template API returns 404 on MWAA — added task logs fallback
- Parses executed SQL from Airflow task execution logs (patterns: "Running statement:", "Executing:", SQL blocks)
- Skips non-SQL tasks (EmptyOperator, TriggerDagRunOperator, sensors)
- Result: 577 SQL extractions, 677 lineage entries, 156 detail files (8.6M) from prod MWAA
- Knowledge base now has real rendered SQL for every transform DAG

### Platform Context Enrichment (knowledge/CLAUDE.md)
- Documented MWAA environment priority: prod > nonprod dq_sync > nonprod testing
- Documented datashare model: nonprod has prod data for reads, but stats need prod direct
- Added full git repo architecture: YAML → TransformDAGTemplate → rendered SQL chain
- Documented all pipeline template types: transform, dq_sync, events_v3, ingest_s3/sqs, personalization, statsig, extract, braze
- DOMO views as metric/KPI definition source (view SQL → S3 → DOMO dashboard)
- Documented current state of glossary/catalog (scattered, spec planned)

### Split Knowledge Base Structure
- Restructured from single catalog.json to split files optimized for context efficiency:
  - `catalog.json` — tables only (~20K, always in Claude context)
  - `transforms_index.json` — DAG summaries with run stats (~200K, compact in context)
  - `lineage.json` — separate lineage graph (~64K)
  - `transforms/{dag_id}.json` — per-DAG detail files with rendered SQL, task stats, run history (loaded on demand)
- New `get_transform_detail` tool — Claude loads full DAG details only when user asks about a specific pipeline
- Context builder now includes transform summaries with success rates and failure streaks
- Loader has backward compatibility: falls back to old catalog.json format if new files don't exist
- MWAA fetcher enriched: captures per-task execution stats (duration, state, operator, try count) and recent run history (success rate, avg/min/max duration, failure streaks)

### Redshift Connection & Table Ops
- Direct Redshift credentials via Settings > Connection (username/password stored encrypted in postgres, never logged, never in Claude context)
- Credentials persist across backend restarts (restored from postgres on startup)
- SSO credentials also persisted to postgres (no more lost creds on reload)
- Fetch credentials from MWAA Airflow connection attempted (passwords masked by Airflow API, CLI blocked)
- Okta SAML auth attempted but blocked by MFA + app URL issues — removed in favor of direct creds
- Capability-aware UI: ANALYZE button disabled without prod creds, PROFILE disabled without nonprod creds
- Table discovery from Redshift SVV_ALL_TABLES with environment selector (np/prd)
- Registry cleaned: only Redshift-verified tables shown (removed lineage-inferred junk)
- Query safety guard: `validate_query_safety()` blocks all non-SELECT/ANALYZE at connection level

### Git-Integrated SQL IDE
- Browse data platform repo files alongside Redshift schemas (Schema/Repo Files toggle)
- Click SQL/YAML file → opens in new query tab with content
- Edit SQL → Save (green button or Cmd+S) → writes back to repo file
- Dirty indicator (•) on tab when file has unsaved changes
- File path shown in toolbar for repo files
- Git panel: branch info (current, ahead/behind), branch switcher with local + remote branches (last 30 days)
- Create new feature branch from UI
- Changed files: checkboxes, M/A/D status badges, inline diff viewer
- Commit: stage selected files, commit message, commit from app
- Push to origin
- Create GitHub PR with title, description, base branch picker (main/stage/develop)
- Git panel auto-refreshes after file Save
- Safety: blocks all writes to main branch (must use feature branches)
- Connection manager: named Redshift connections stored in postgres
- Backend: full git API (/api/git/ — files, branches, status, diff, commit, push, PR)

### Query Workspace (DataGrip-style)
- Multi-tab query console with independent state per tab
- Per-tab environment selector (np/prd) and connection picker
- Schema browser sidebar: databases → schemas → tables → columns (lazy loaded, cached in localStorage)
- Resizable schema browser panel (drag handle, persists width)
- Double-click table/column in browser → inserts at cursor in SQL editor
- Query history sidebar (toggle, click to re-load)
- CSV export, Cmd+Enter to run, row numbers
- Results table with horizontal + vertical scroll
- Auto-uses real Redshift when direct creds exist (bypasses mock mode)
- Connection manager API (CRUD, test, execute per connection)

### PR-Style Glossary Workflow
- Replaced static glossary.yaml with postgres-backed glossary_entries
- Workflow: draft → in_review → changes_requested → approved → merged (live)
- Source distinction: KB Agent (auto from view SQL) vs User (manual or AI wizard)
- Conversation threads per entry (comments with author, action badges, timestamps)
- History timeline (audit trail of all state changes)
- User assignment for review (bulk assign, filter by assignee)
- Manual "New Definition" form + "Create with AI" wizard
- AI Wizard: persona-aware (engineer gets SQL questions, exec gets business questions)
- Approved/merged entries feed Claude's context (replaces glossary.yaml)

### Lineage v2
- dbt-style search-first UI with autocomplete dropdown
- Two view modes: Tables (588) and DAGs (145) toggle
- Configurable upstream/downstream depth (+/- controls, 0-5, default 1)
- Multi-hop traversal from rendered SQL + transform detail files
- Target resolution from SQL INSERT INTO statements (not DAG name)
- 689 lineage entries, 43 upstream sources for cut_session_master
- Case normalization (prd_Dw → prd_dw)
- Click any node to navigate, scroll zoom, drag pan
- Column headers show depth level labels

### Lineage Visualization (v1 — superseded)
- Interactive lineage graph at /lineage — select table to see upstream/downstream
- Searchable table list with dependency counts
- SVG graph with color-coded nodes and curved edges
- Known issues: mixes DAG names with table names, needs table-only filtering, layout needs Airflow-style improvement

### Schedule Refresh Runner
- Background task checks every 60 seconds for due cron schedules
- Active/inactive toggle (defaults to INACTIVE) in Admin Console > Table Ops > Schedules
- Stored in postgres schedule_runner_config table
- Queues jobs sequentially, prevents double-execution
- Supports: single table, schema-wide, or all enabled tables

### Auto-Glossary Enricher
- glossary_enricher.py: parses view SQL → auto-generates draft glossary entries (32 drafts)
- Expert review workflow: draft → approved/rejected/needs_review
- Approved entries persist across KB refreshes (human opinion always wins)
- User assignment for review (bulk assign, filter by assignee)
- Glossary Review page in sidebar (/glossary/review)

### Admin Console + Settings Split
- Admin Console (/admin): Connection, Knowledge Base, Table Ops
- Settings (/settings): Persona, System Prompt, User Context

### DOMO + View Metric Parser
- New domo_parser.py: extracts metric/KPI definitions from the full chain:
  - Transform YAML "views" sections → SQL file paths → CREATE OR REPLACE VIEW SQL
  - Transform YAML "downstream_dags" → links to DOMO refresh DAGs and other transforms
  - dags/domo_refresh/conf/ → DOMO dataset IDs, S3 paths, schemas
- 166 metrics discovered, 98 with DOMO dataset links, 93 with actual view SQL
- Lineage enriched with downstream_dags (60 transform→DOMO/transform mappings) and view source tables
- metrics.json + views/{name}.json in knowledge base (on-demand loading)
- New get_view_detail tool: Claude can look up any metric's SQL definition
- Context builder includes metric summaries in system prompt

### AWS Bedrock Support
- AI provider toggle in Settings > Connection: switch between Anthropic API and AWS Bedrock at runtime
- Bedrock defaults to Claude Opus 4.6 (us.anthropic.claude-opus-4-20250514-v1:0)
- Uses SSO credentials from credential store (tries both np/prd), falls back to default AWS chain
- No restart needed — client re-creates automatically on provider switch
- Model name displayed in UI

### Column-Level Intelligence UI
- Expandable table rows: click table name → column profile panel
- Per-column: name, type, category badge (PK/FK/metric/dimension/date/flag), distinct count, cardinality %, null count/rate, min/max, classification signals
- Table classification summary in expansion (fact/dim scores + weighted signals)
- Weighted classifier (classifier.py): table-level (name patterns, row count, FK ratio, numeric ratio, timestamps) + column-level (type, name patterns, cardinality, SCD detection)
- Sortable column headers (click to sort asc/desc on any column)
- Settings tab persists in URL (?tab=table-ops) — refresh stays on same tab
- Fix: profile_data JSON parsing, TABLESAMPLE SYSTEM error, job runner continuation, ambiguous stored as NULL

### Table Ops UI Improvements
- Discovery stores original database name (prd_dw, np_dw) instead of stripping prefix
- Environment selector on discovery (nonprod/prod)
- Recent Jobs shows database column
- Column renames: Obj→Table/View, Value→References, Class→Auto Type, Override→Manual Type
- Registry only shows Redshift-verified tables (lineage-inferred junk removed)
- Capabilities-aware: ANALYZE disabled without prod creds, PROFILE disabled without nonprod creds
- PROFILE runs column-level profiling: distinct count, cardinality ratio, null count/rate, min/max (numeric/date)

### Lineage Cleanup
- Fixed SQL parser: filters out single-letter aliases (a, b, aa), numeric patterns (9.29), column references (a.evaluation_date)
- Added `_is_valid_identifier()` check for schema/table names
- Cleaned existing lineage.json: removed 186 bad entries, 491 valid entries remain
- Future builds will produce clean lineage automatically

### Infrastructure
- `git` installed in backend Docker image (python:3.12-slim)
- Persistent `repo_data` Docker volume for cloned repo (survives container restarts)
- nginx proxy timeout increased to 600s
- `.env` additions: `REPO_URL`, `GITHUB_TOKEN`, `REPO_PATH`

---

## 2026-03-23 — Initial Build (Phase 1 + Phase 2 + Enhancements)

### Phase 1: MVP
- Docker Compose setup (frontend, backend, postgres)
- React frontend with 6 capability views + chat
- FastAPI backend with Claude API integration
- Knowledge base: catalog.json (12 tables), glossary.yaml (14 terms), CLAUDE.md (platform context)
- Mock Redshift connector with fixture data
- Pillar selector (9 pillars) and environment toggle (nonprod/prod)
- NL → SQL generation with query execution
- Business definition glossary search with fuzzy matching
- Usage tracking (token consumption, query logging, cost estimation)
- Session persistence in PostgreSQL

### Phase 2: Full Capabilities
- YAML pipeline builder (NL → DAG config + SQL files)
- SQL optimizer (paste SQL → optimization report)
- Impact analysis (change description → dependency trace)
- Catalog engine module:
  - redshift_metadata.py — SVV_ALL_TABLES, SVV_ALL_COLUMNS, SVV_TABLE_INFO
  - repo_parser.py — TransformDAGTemplate YAML + SQL lineage extraction
  - mwaa_fetcher.py — Rendered SQL from Airflow API (post-Jinja, real table names)
  - glossary_builder.py — Merge base glossary with approved corrections
  - builder.py — Orchestrator + CLI (`python -m catalog_engine.builder`)
  - API: /api/catalog-engine/refresh, /status, /preview
- Query history sidebar (last 10 sessions + 10 queries, click-to-reload)
- Glossary contribution with review queue (submit, approve/reject)

### Enhancements (same day)
- Real Redshift IAM/SSO connector (redshift_connector + GetClusterCredentials)
- Per-user AWS SSO device authorization flow (same as `aws sso login`, in-browser)
- Per-user credential store (session-scoped, auto-expiry)
- Settings page:
  - Connection tab (SSO connect/test per environment, default env, auto-route toggle)
  - Persona tab (Engineer, Analytics Engineer, Analyst, ML Engineer, New Member)
  - System Prompt tab (quick-add safety rules, custom rules editor)
  - User Context tab (free-form + "Optimize for Tokens" AI compression)
- Smart Glossary Wizard (AI generates 5 structured questions, synthesizes glossary entry)
- Activity page (GitHub-style 90-day contribution heatmap, streak, capability breakdown)
- MWAA rendered SQL fetcher (post-Jinja lineage from Airflow rendered template fields)

### Chat-First Refactor
- Inline action cards: SQLCard, DefinitionCard, PipelineCard, ImpactCard, LineageCard
- SQLCard: [Run] [Edit] [Optimize] buttons with inline results table
- Auto-detection of SQL code blocks → runnable SQLCard
- 6 organization-specific starter questions with icons and descriptions
- execute_query tool enabled in chat (was disabled)
- Tool results carry structured data for card rendering
- Standalone tabs preserved as power-user workbenches
