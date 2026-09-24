# Jennie — Roadmap

## Phase 1 — Foundation (DONE)
*Completed 2026-03-23*

- [x] Real knowledge base from MWAA task logs (161 transforms, 577 SQL extractions)
- [x] Git repo integration (226 configs, git blame, YAML parsing)
- [x] Split KB structure (catalog, transforms_index, lineage, metrics, views, transforms/)
- [x] DOMO + view parser (166 metrics, 98 datasets, 93 view SQL definitions)
- [x] Lineage from rendered SQL + downstream_dags (491 + 60 entries)
- [x] Table Ops engine (discover, profile, analyze, sequential queue)
- [x] Weighted table/column classifier (fact/dim, PK/FK/metric/dimension/date/flag)
- [x] Auto-glossary enricher with expert review workflow + user assignment
- [x] Redshift direct auth (encrypted in postgres, never in Claude context)
- [x] SSO + credential persistence across restarts
- [x] Query safety guard (SELECT/ANALYZE only)
- [x] AWS Bedrock support (runtime toggle)
- [x] Admin Console + Settings split
- [x] Platform context documentation (all 4 DAG frameworks)
- [x] the organization genie lamp logo
- [x] Lineage v2: dbt-style search, depth controls, SQL-based target resolution (689 entries)
- [x] Schedule refresh runner with active/inactive toggle
- [x] PR-style glossary: draft→review→approve→merge, comments, history, assignment
- [x] AI Wizard: persona-aware questionnaire (adapts to engineer/exec/analyst)
- [x] Admin Console + Settings split
- [x] Lineage target resolution from rendered SQL INSERT INTO
- [x] Case normalization in lineage (prd_Dw → prd_dw)
- [x] **Lineage v3**: fully-qualified `db.schema.table` keys, UNLOAD/COPY parsing, TriggerDagRun extraction, all DAG types (see `docs/LINEAGE_BUILD.md`)
- [x] **Lineage v3.1**: TaskLogReader for SQL extraction (captures all tasks in multi-task DAGs), catalog-based key remap, np lineage filtered to DQ_SYNC only. 73→167 tables with upstream, 0 np_dw pollution. Validated locally against MWAA log dump before deploying.

## Phase 2 — Validate & Expand
*Goal: Get chat working, validate KB quality, expand table coverage*

- [x] **Bedrock chat working** — Opus 4.6 via nonprod SSO, runtime provider toggle
- [x] **Per-message copy + flag buttons** — copy response, report issues on each assistant message
- [x] **Auto-charts** — query results auto-render bar/line/pie charts (recharts)
- [x] **Test chat quality** — tested with real questions, identified and fixed analysis paralysis
- [x] **Tool result rendering as cards** — collapsible cards (SQL, Table, Pipeline, Lineage, Definition, Code) in chat
- [ ] **Discover more schemas** — analytics, fact, events, stage, public (only dim.* done)
- [ ] **Profile high-value tables** — batch profile fact tables (test sampling on large tables)
- [ ] **Prod Redshift credentials** — enable ANALYZE and prod-direct discovery
- [ ] **Re-profile with new classifier** — update all tables to get fact/dim/ambiguous scoring
- [ ] **Iterate on chat** — fix gaps found during testing, tune context builder

## Phase 3 — Redshift IDE + Knowledge Depth
*Goal: Replace DataGrip for Redshift workflows, complete the knowledge graph*

### Unified Workbench (DONE — merges Query Runner + SQL Optimizer + Pipeline Builder + Git IDE)
- [x] **Multi-tab workbook** — multiple queries/files per session, independent state
- [x] **Schema browser** — Redshift databases/schemas/tables/columns + Repo files, resizable
- [x] **Git integration** — browse, edit, save, commit, push, create PR
- [x] **Optimize inline** — AI analyzes SQL, suggestions in amber panel
- [x] **Connection manager** — named connections, per-tab environment
- [x] **CSV export, Cmd+Enter, Cmd+S** — keyboard shortcuts
- [x] **Per-user git identity** — name, email, GitHub token in Settings
- [x] **New file/directory creation** — right-click context menu (new, rename, delete)
- [x] **"Create pipeline like X"** — AI replicates existing pipeline structure via NL bar
- [x] **Template shortcuts** — Transform, DQ, DOMO, Ingest patterns
- [x] **Saved/shared queries** — save, name, tag, share across team. Shared browser panel + usage tracking. Click to open and run.
- [ ] **Lineage-aware** — right-click table → show lineage
- [ ] **Glossary tooltips** — hover columns for definitions
- [ ] **Impact warnings** — "this table feeds N downstream DAGs"

### Knowledge Depth

- [x] **All DAG types from MWAA** — TRANSFORM, DOMO, DQ, ingest, events, personalization, statsig, braze, extract, glue
- [x] **Non-SQL DAG metadata** — schedule, owner, tags, task types, operators captured
- [x] **AI enrichment phase** — Opus/Sonnet/Haiku generate table descriptions, DAG summaries, column descriptions
- [x] **Document upload** — upload files to glossary, AI extracts terms, PR-style review
- [ ] **Auto-generate column descriptions** — from profile data + transform SQL + view SQL context
- [ ] **Comprehensive glossary** — merge auto-generated (from views) + manual (from experts) + existing (glossary.yaml) into one authoritative source
- [x] **DOMO REST API integration** — direct REST API (read-only): domo_search, domo_dataset_info, domo_dashboards, domo_dashboard_detail. Full hierarchy: Pages → Cards → Datasets → Streams. Data analysis via S3/DuckDB (analyze_domo_dataset). Connection UI in Settings.
- [ ] **Nonprod MWAA data** — fetch from nonprod-airflow-mwaa (testing DAGs, DQ validation context)
- [x] **Cross-pillar metric comparison** — metric conflict detection in enrichment, Knowledge Expert prompt has cross-pillar conflict awareness

## Phase 3.5 — Agent Architecture (DONE)
*Completed 2026-03-27*

- [x] **Split system prompt** into per-agent prompt files (data, redshift, knowledge)
- [x] **Principal agent** — classification-based routing (DATA/DEFINITION/METRIC/INVESTIGATION/MODELING/CONVERSATIONAL)
- [x] **Tiered model strategy** — Sonnet for routing/sub-agents (speed), Opus for synthesis (quality). 2-5x faster, 5-7x cheaper.
- [x] **Resource-aware execution** — prefers DOMO S3 data (free), auto-runs small tables, asks before large tables
- [x] **Sub-agent wrappers** — each makes a separate Bedrock call with Sonnet + focused prompt + tools
- [x] **Parallel execution** — sub-agents can run concurrently for multi-domain questions
- [x] **Tool scoping** — principal: search + execute + analyze_domo + expert delegation. Investigation tools only on sub-agents.
- [x] **Data Expert** — DAGs, SQL, lineage, views, DOMO metrics, YAML configs, MWAA, repo_search, github_file, aws_lookup, analyze_domo_dataset
- [x] **Redshift Expert** — table metadata, profiling, classification, query optimization, data modeling
- [x] **Knowledge Expert** — business terms, pillar context, environment routing, datashare, security
- [x] **Agent consolidation** — 6 → 3 sub-agents, 50% fewer API calls per question
- [x] **Agent prompt editor** — admin-editable prompts persisted in postgres
- [x] **Goose-style investigation trail** — real-time step log with icons, details, spinners (replaces single "thinking..." status)
- [x] **DOMO S3 enrichment** — S3 metadata (columns, freshness, size) in KB + analyze_domo_dataset tool (DuckDB local)
- [x] **DOMO catalog** — unified domo_catalog.json linking refresh DAG → view SQL → S3 data → business context
- [x] **DOMO REST API** — replaced DOMO MCP server with direct REST API using same client_id/secret as Airflow. Strictly read-only: domo_search, domo_dataset_info, domo_dashboards, domo_dashboard_detail. domo_query parked.
- [x] **KB Explorer** — 5-tab browser in Settings → Knowledge Base (Summary, Transforms, Tables, DOMO Metrics, Glossary)
- [x] **Correction capture** — user corrections → glossary drafts + review tasks + notifications
- [x] **Additional repos auto-pull** — KB build pulls configured additional repos alongside primary
- [x] **Persona-based prompts** — agent prompts rewritten as personas (16K → 5.4K chars)
- [x] **System/context separation** — prompts.py = identity, context.py = per-request user context
- [x] **Table profiles in context** — 66 table profiles injected into agent context from Table Ops
- [x] **prd_dw prefix enforced** — agents always use prd_dw (not np_dw) for data queries
- [ ] **KB Explorer enhancements** — expand browse UI with: click-to-detail, lineage mini-graph per table, coverage gap highlighting
- [x] **Unify Table Ops + KB Redshift** — KB build triggers discover/profile, single source of truth. Always prod, dynamic 7 prd_* database discovery.
- [ ] **Future: Anthropic Agent SDK** — replace tool-based delegation with native agent handoffs

## Phase 4 — Operations & Automation (MOSTLY DONE)
*Goal: Self-maintaining knowledge base that stays fresh without manual intervention*

- [x] **Scheduled KB refresh** — cron executor (schedule_runner.py), checks every 60s, active/inactive toggle
- [x] **Auto SSO refresh** — background task refreshes credentials 10 min before expiry using refresh tokens
- [x] **RBAC** — 4 roles (viewer/analyst/engineer/admin), 22 granular permissions, role-gated UI tabs
- [x] **User management** — create/edit/deactivate users, assign roles/teams, per-user git config
- [x] **Chat session persistence** — conversations saved to postgres, sidebar session list, shareable URLs
- [x] **Conversation summarization** — auto-compress long conversations (Haiku for cheap summary), context indicator
- [x] **Feedback kanban board** — unified ticket system (Settings → Feedback, admin-only)
- [x] **Auto-ticket creation** — agent KB gap detection auto-creates tickets
- [x] **KB build versioning** — every build tracked with snapshot + diff (added/removed/changed)
- [x] **Multi-user isolation** — per-user git worktrees, user-scoped chat sessions and settings
- [x] **Glossary multi-source enrichment** — view SQL + Redshift COMMENT + repo configs merged per entry
- [x] **Source attribution** — glossary entries show colored badges (View SQL, Redshift, Repo, DOMO)
- [x] **Scheduled reports** — schedule button (clock icon) on chat responses, cron-based execution, Reports page in sidebar, Run Now / Enable / Disable
- [x] **In-app notification system** — bell icon in header, red badge with unread count, polls every 30s, 5 notification types (scheduled_report, feedback_assigned, glossary_assigned, registration_request, kb_gap)
- [x] **User registration** — "Request Access" form on login page (@example.com validation), admin approval/rejection in Settings → Users, creates viewer account with temp password
- [x] **In-app documentation viewer** — Docs page in sidebar
- [x] **Reports page** — standalone sidebar page for viewing scheduled report outputs
- [ ] **Audit trail** — who changed what in glossary, who ran which queries, KB build history

## Phase 5 — Trust & Team (in progress — from code review)
*Goal: Make the platform trustworthy, team-shared, and self-governing*

### 5.1 Trust — KB Coverage & Answer Confidence
- [ ] **KB coverage dashboard** — missing schemas, missing column descriptions, stale sources. Visible in Settings → KB.
- [ ] **Confidence indicators** — AI responses show "grounded" vs "inferred" vs "KB gap" per claim
- [ ] **Missing-context banners** — when answering from thin KB areas, show what's missing inline (not just KB Improvement note)
- [ ] **Evidence-first mode** — "show me what you found before answering" option for critical queries
- [x] **150-test suite** — full auth, query safety, KB build, agent tool coverage
- [x] **All endpoints auth-guarded** — P0/P1 security fixes completed

### 5.2 Teamwork — Shared Artifacts & Reuse
- [x] **Saved/shared query library** — save, name, tag, share SQL queries across team in Workbench. Save to Library button, Shared browser panel, usage tracking.
- [x] **Contributor notifications** — merge ("your entry is live!") and reject (with reason) notifications for glossary contributors
- [x] **@mention autocomplete** — MentionInput component in glossary comments, mentioned users receive notifications
- [x] **PDF export** — download icon on each response captures full content including charts
- [x] **Report execution history** — last 7 runs per report with status and output viewing
- [ ] **Pinned answers / playbooks** — promote a chat answer to a reusable knowledge article
- [ ] **Team-curated answer collections** — browse answers by topic/pillar, voted by team
- [ ] **Shared notebooks** — multi-cell SQL + markdown documents (like Observable/Jupyter)

### 5.3 Governance — Audit & Ops
- [ ] **Full audit trail** — who ran what query, who changed glossary, who built KB, who changed settings
- [ ] **Admin ops dashboard** — single view: auth health, KB freshness, build status, report failures, open gaps
- [ ] **DQ issue objects** — data quality issues tied to tables/DAGs with lifecycle and task hooks

### 5.4 Depth — KB Agent & Semantic Layer
- [x] **Rich inline KB context** — context.py compiles top 40 tables+columns, top 25 DOMO metrics, top 20 glossary defs, active experiments, common SQL patterns into every prompt (~6K). Agent writes SQL on first tool call. Knowledge Expert removed (4→3 agents).
- [x] **Charts-first UX** — SQL cards always expanded, render above other cards, only last result shown, query results persist in sessions. Agent prompt: "Default to charts, not text."
- [x] **Token budget 150K** — increased from 80K to accommodate rich inline context
- [x] **KB Agent (ask_kb_expert)** — replaces batch enricher + glossary auto-builder with a dedicated agent that:
  - Maintains glossary (create, update, merge, resolve conflicts across sources)
  - Enriches transforms (summarize DAGs with full cross-referenced context)
  - Describes tables/columns (combining Redshift + MWAA + DOMO + lineage)
  - Serves other agents as fast lookup (check KB before hitting expensive sources)
  - Learns from chat corrections (feedback loop → update entries)
  - Runs in build mode (3-phase: DAG summaries → table descriptions → glossary synthesis) and live mode (during chat)
  - Supersedes: glossary_enricher.py, kb_enricher.py, ai_rewrite_definitions()
- [x] **Swagger event schemas** — 558 ProductApp events with payload fields. Agent tools: get_event_schema, search_events. Precise SQL against firehose_v3_enriched SUPER columns.
- [x] **Statsig integration** — Console API (read-only) for experiments, feature gates. Connection UI in Settings. Exposure tables in prd_statsig for experiment segmentation.
- [x] **DOMO as glossary Source 3** — 167 DOMO metrics with pillar context feed glossary enrichment. AI enrichment synthesizes all metadata.
- [x] **Table profiling merged into KB** — runs during KB Redshift step (always prod, dynamic 7 prd_* database discovery). Results in both catalog.json and postgres.
- [x] **KB build scheduler** — cron: every 6h, daily, weekly, monthly. Auto-triggers full build with Sonnet enrichment.
- [ ] **Canonical semantic layer** — unify glossary + column descriptions + metric view definitions + DOMO card titles into one model (driven by KB Agent)
- [ ] **Column-level lineage** — for high-value assets (cut_session_master, firehose_v3_enriched) using rendered SQL parsing
- [ ] **Usage lineage** — which tables/columns are actually queried (from Redshift STL_QUERY/STL_SCAN)
- [ ] **Lineage Agent** — dedicated AI agent for intelligent lineage maintenance:
  - Claude-powered SQL parsing for complex CTEs, subqueries, dynamic SQL that regex misses
  - Cross-source reconciliation: MWAA lineage vs repo YAML vs Redshift query logs (flag discrepancies)
  - Impact analysis: "If I change column Z in table A, which DOMO dashboards break?" (requires column-level lineage)
  - Lineage gap detection: tables with no upstream or no downstream → auto-create KB gap tasks
  - Runtime validation: compare declared lineage vs actual STL_QUERY activity (phantom/shadow dependencies)
  - Natural language lineage queries: "Show me everything that feeds the engagement KPI dashboard"
  - Change impact preview: PR-time analysis of which downstream paths are affected
  - See `docs/LINEAGE_BUILD.md` for full design

### 5.5 Workbench Context Integrations
- [ ] **Lineage-aware actions** — right-click table → show upstream/downstream, show impact
- [ ] **Glossary tooltips** — hover column name → see definition, formula, pillar
- [ ] **Impact warnings** — "this table feeds N DOMO dashboards" banner before editing transforms

### 5.6 Agent Intelligence — Performance, Cost, and Answer Quality
*Goal: Make the agent faster, cheaper, and more accurate without changing architecture*

**P0 — Prompt & Config (no architecture change):**
- [ ] **Prompt caching** — mark static KB context + principal prompt as `cache_control: ephemeral`. Cached tokens cost 90% less on Bedrock/Anthropic, zero latency for cached portion. ~50-70% cost reduction per request.
- [ ] **SQL error auto-retry** — explicit prompt instruction: on execute_query error, read the error, fix the SQL using inline schema, retry immediately. Never apologize — just fix and rerun. Addresses #1 user frustration.
- [ ] **Clean dead/conflicting prompt instructions** — remove "Ask the KB Agent first" from DATA_EXPERT_PROMPT (tool not in its toolset), remove unused KNOWLEDGE_EXPERT_PROMPT, add "don't search_tables for tables already in your inline context" to principal.
- [ ] **DuckDB query examples** — add `analyze_domo_dataset` query examples to principal prompt (table name is `data`, example aggregations). Agent currently can't use the query parameter effectively.

**P1 — Search & Routing (medium architecture):**
- [x] **pgvector semantic search** — hybrid lexical + semantic search via pgvector. Bedrock Titan Text Embeddings v2 (1024d) for tables, transforms, glossary. Embeddings generated on startup + KB reload (background). Combined score: 0.4 lexical + 0.6 semantic. HNSW index for fast cosine similarity.
- [x] **Lightweight classifier** — Haiku pre-call (~50 tokens, <500ms) classifies DATA/METRIC/DEFINITION/INVESTIGATION/MODELING/CONVERSATIONAL. Adjusts tools + iteration limits per category. CONVERSATIONAL = no tools, 1 iteration. DEFINITION = search only, no experts.
- [x] **Sub-agent tool streaming** — sub-agents push tool_call/tool_result events to shared asyncio.Queue. Principal drains queue after gather and yields to frontend. Users see Data Expert's investigation steps in real time.

**P2 — Iterative Workflow (session improvements):**
- [ ] **Cross-session memory** — inject last 5 user queries from recent sessions into context. Analysts work iteratively across sessions.
- [ ] **Working "continue" support** — store working_messages (with tool results) in session so "continue" resumes from exact state, not from scratch.
- [ ] **Dynamic SQL patterns** — replace hardcoded SQL examples in context.py with top 5 most-run saved queries from team. Self-improving context.
- [ ] **Structured sub-agent responses** — sub-agents return Answer/Evidence/KB_GAP structure instead of free text truncated at 6K chars.

## Phase 6 — Ecosystem (deferred)
*Goal: Integrate with external team workflows — only after internal experience is solid*

- [ ] **Slack ask/share** — ask Genie from Slack, share answers to channels
- [ ] **JIRA task sync** — bi-directional: Genie tasks ↔ JIRA tickets
- [ ] **Export catalog** — PDF/Confluence/Markdown export of glossary, lineage
- [ ] **Slack/email notification delivery** — extend in-app notifications externally
- [ ] **Role-based onboarding paths** — analyst vs engineer vs admin guided tours
- [ ] **Compare mode** — structured comparison of datasets, pipelines, metrics, costs
- [x] **Notifications** — in-app bell with real-time polling
- [x] **Usage analytics** — Cost Explorer with model breakdown
