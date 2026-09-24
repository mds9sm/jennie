# Changelog

All notable changes to Jennie. Format: [semver](https://semver.org/).

- **Major (x.0.0)**: Breaking changes, architecture rewrites
- **Minor (0.x.0)**: New features, UI changes, new integrations
- **Patch (0.0.x)**: Bug fixes, config changes, deployment fixes

---

## [1.3.0] — 2026-09-24

### Built-in Chat Restored

The embedded chat interface, removed on 2026-04-14 when conversation moved to claude.ai
over MCP, is back. Both surfaces now run side by side: Genie's own chat at `/` and the
Knowledge / NP Data MCP servers for claude.ai. The Claude Integration settings tab is
unchanged.

#### Added
- **`POST /api/chat`**: SSE streaming over the principal agent, restored along with session
  CRUD (`/api/chat/sessions`), read-only sharing (`/api/chat/shared/{id}`), file attachment
  extraction (`/api/chat/extract-file`), KB-gap ticket creation, and glossary correction capture.
- **Chat UI**: `ChatView` plus the action cards (SQL, definition, pipeline, impact, lineage,
  table detail, code, result charts) and the Goose-style investigation trail.
- **Sidebar**: Chat nav item and the session browser (rename, share, delete, 30-day window)
  alongside the nav items added since April (Catalog, Events DQ, Digest).
- **Contextual tips**: the four chat tips dropped from `FeatureTips` are back.

#### Fixed
- **Responses lost on disconnect**: the frontend never sent `session_id` on `POST /api/chat`,
  so the backend's "finish in the background and save" path and its completion notification
  silently did nothing on every request. The id is now sent.
- **Background chat could be garbage-collected**: the streaming task was started with a bare
  `asyncio.create_task()` and never referenced again. It is now tracked, which also makes
  `POST /api/chat/background-status/{id}` report real state instead of always `running: false`.
- **File attachments blocked the event loop**: `/api/chat/extract-file` parsed PDFs and .docx
  inline on the loop. Now offloaded via `asyncio.to_thread`, matching the event-loop fixes
  applied across the backend in #27–#31.
- **Attachment upload broken outside docker-compose**: the upload posted to a hardcoded
  `/api/chat/extract-file`, ignoring `VITE_API_BASE` (`/genie/api` in K8s). Routed through the
  API client.
- **Deleting someone else's session reported success**: `DELETE /api/chat/sessions/{id}`
  ignored the command tag and always returned `{"status": "deleted"}`. Returns 404 when
  nothing was deleted.
- **"New chat" forced a full page reload**: the sidebar button set `window.location.href`,
  throwing away SPA state. It now navigates client-side and `ChatView` resets itself.
- **Unbounded caches**: the conversation summary cache and background-task map now evict.
- **Broken tests**: `test_api_contracts.py` and `test_data_isolation.py` still exercised the
  chat endpoints removed in April (9 tests failing against a 404). The two
  `test_glossary_workflow.py` tests stubbed out at the time — one skipped, one with an
  inlined regex that had drifted from the real `_CORRECTION_PATTERN` — test the real code again.
- **Guided tour**: the tour step targeting `[data-tour="chat"]` had no element to point at.

---

## [1.2.0] — 2026-04-03

### Lineage v3.1 — Full Upstream/Downstream Coverage

#### Added
- **TaskLogReader SQL extraction**: Local/ORM mode now reads task logs from CloudWatch instead of XCom. Captures SQL from all tasks in multi-task DAGs (XCom only captured 1 of N).
- **Catalog-based key remap**: Bare and `.public.` lineage keys remapped to correct fully-qualified names using existing 3-part keys in the lineage graph.
- **np lineage filtering**: Only `DQ_SYNC__` DAG lineage included from np MWAA. Dev/test DAGs no longer pollute production lineage with `np_dw.*` tables.
- **In-app Docs page**: 11 markdown docs bundled in `backend/docs/`, served via `/api/docs/pages`. Fallback from `/app/docs` mount (docker-compose) to bundled files (K8s).

#### Changed
- `_resolve_target_from_sql`: Accepts `default_db` from connection_id mapping. Scans FROM/JOIN refs as last resort before bare fallback.
- `merge_and_write_s3`: Qualifies 2-part FROM/JOIN refs to 3-part using target's database prefix.
- Updated LINEAGE_BUILD.md, ROADMAP.md, CLAUDE.md with v3.1 coverage stats.

#### Results
- Tables with upstream: **73 → 167** (2.3x improvement)
- Tables with downstream: **163 → 461** (2.8x improvement)
- Total lineage keys: **499 → 800**
- Bare table keys: **119 → 82**
- `prd_dw.fact.udm_project_cuts`: **0 → 24 upstream sources**
- np_dw pollution: **eliminated**

---

## [1.1.0] — 2026-03-30

### K8s Production Deployment

#### Added
- **Custom nginx entrypoint** (`start-nginx.sh`): Dynamic nginx config generation based on `BACKEND_URL` (proxy mode vs static mode)
- **Runtime env injection**: `VITE_API_BASE` injected into `window.__ENV__` at container startup — no frontend rebuild per environment
- **Signed HMAC auth tokens**: Sessions survive pod restarts + work across multiple replicas. Secret derived from `DATABASE_URL` — no separate key needed
- **10 missing database tables in init.sql**: All 23 tables present with `IF NOT EXISTS` — safe to re-run
- **REPO_URL configurable from Settings UI**: No env var needed, persists in postgres `credential_cache`
- **Non-blocking KB builds**: All sync steps (git clone, repo parse, DOMO parse, Swagger fetch, Statsig fetch, knowledge tagger) wrapped in `asyncio.to_thread` — health endpoint stays responsive during 90-min builds
- **App versioning**: `VERSION` file + `GET /api/version` endpoint + sidebar display (`Genie v1.1.0+<hash>`)
- **S3 storage config persistence**: Status endpoint reads from postgres fallback when in-memory is empty (multi-pod safe)
- **Proxy SSL support**: `proxy_ssl_server_name on` + auto-detected DNS resolver for K8s nginx → external HTTPS backends

#### Fixed
- Nginx `host not found in upstream "backend"` in K8s (separate pods)
- Nginx 500 on HTTPS proxy (missing SNI header for ALB routing)
- `credential_cache` table missing → 500 on GitHub/DOMO/Statsig credential save
- Session lost on page refresh (in-memory-only tokens → signed HMAC tokens)
- S3 bucket config vanishes on refresh (in-memory-only → postgres fallback)
- KB builds killed by K8s liveness probes (blocking event loop → asyncio.to_thread)

---

## [1.0.0] — 2026-03-29

### Added

#### Rich Inline KB Context
- **context.py rewritten**: Compiles Layer 1 KB data into every system prompt (~6K per call).
- **Top 40 tables with columns**: Agent KNOWS the schema inline, writes SQL on first tool call.
- **Top 25 DOMO metrics with S3 columns**: Metric definitions and data sources inline.
- **Top 20 glossary definitions**: Business terms available without tool calls.
- **Active Statsig experiments**: Experiment context inline.
- **Common SQL query patterns**: Cutting users, DAU, subscriptions — agent uses proven patterns.
- **Result**: "daily cutting users by platform" → 1 tool call → 28 rows → 10 seconds (was 4-6 search iterations).

#### Charts-First UX
- **SQL result cards always expanded**: No collapsible wrapper, charts are front and center.
- **SQL cards render above other cards**: Visual priority for data results.
- **Query result cards persist**: Survive page refresh in chat sessions.
- **Only last SQL result shown**: Intermediate query results replaced, keeping chat clean.
- **Agent prompt**: "Default to charts, not text. The chart IS the answer."

#### PDF Export
- **Download icon** on each assistant response captures full content including charts, tables, and markdown as PDF.

#### @Mention Autocomplete
- **MentionInput component** for glossary comments: type @ to trigger user autocomplete, mentioned users receive notifications.

#### Contributor Notifications
- **Merge notification**: "Your entry is live!" sent to contributor on glossary merge.
- **Reject notification**: Reason provided to contributor on glossary rejection.

#### Report Execution History
- **Last 7 runs** shown per scheduled report with timestamp, status, and duration.
- Click any historical run to view its output.

#### Starter Cards
- **Updated for team topics**: Cuts, engagement, subscriptions, experiments — replacing generic starter prompts.

#### KB Build Preferences
- **Persist in localStorage**: Redshift toggle, enrichment model selection, source checkboxes survive page refreshes.

### Changed

#### Knowledge Expert Removed (4 agents → 3)
- **Principal handles 80% directly**: Rich inline KB context means no separate agent call for definitions/glossary.
- **3 chat agents**: Principal (direct), Data Expert (investigation), Redshift Expert (modeling).
- **KB Agent**: Build-mode enrichment only — no longer called during chat.
- **Result**: DEFINITION questions ~3s (was ~15-20s with Knowledge Expert delegation).

#### Token Budget Increased
- **150K token budget** (was 80K): Rich inline context adds ~6K per call, budget increased to accommodate.

#### AI Provider Toggle Removed
- **SSO + Bedrock only**: Anthropic direct API toggle removed from Settings UI.

#### Notification Fixes
- **Chat links**: Clicking a chat notification now reloads the page to the correct session.
- **Glossary links**: Clicking a glossary notification filters to drafts view.

### Added (continued)

#### KB Agent (ask_kb_expert)
- **New sub-agent for KB operations**: `ask_kb_expert` — fast KB lookups and build-mode 3-phase enrichment. Replaces batch `glossary_enricher.py` + `kb_enricher.py` with agent-driven synthesis.
- **Live mode**: Other agents ask KB Agent first before hitting expensive sources (MWAA, Redshift). Fast cached lookups in <3s.
- **Build mode Phase 1 (DAG summaries)**: Generate human-readable pipeline summaries from rendered SQL + YAML config + run stats.
- **Build mode Phase 2 (Table descriptions)**: Generate table/column descriptions combining Redshift metadata + MWAA SQL + DOMO views + lineage context.
- **Build mode Phase 3 (Glossary synthesis)**: Merge all metadata sources into glossary entries. DOMO 167 metrics as glossary Source 3 (pillar context, business definitions). Cross-reference gap detection (repo vs MWAA, tables vs lineage).

#### Swagger Event Schemas
- **558 ProductApp event schemas**: Full payload field definitions from Swagger spec, stored in `knowledge/event_schemas.json`.
- **Agent tools**: `get_event_schema` (by event name), `search_events` (fuzzy search across all 558 events).
- **Precise SUPER column SQL**: Agents use schema knowledge to write accurate SQL against firehose_v3_enriched nested SUPER columns.

#### Statsig Integration
- **Console API (read-only)**: Experiments and feature gates metadata from Statsig.
- **Connection UI**: Settings > Connection > Statsig. Requires `STATSIG_CONSOLE_API_KEY`.
- **Exposure tables**: prd_statsig database for experiment segmentation queries.

#### Saved/Shared Queries
- **Team query library**: Save to Library button on any Workbench query tab.
- **Shared browser panel**: Browse team queries by name, tags, and usage.
- **Tags and search**: Free-form tags for categorization, full-text search.
- **Usage tracking**: Query run counts and last-used timestamps.
- **Backend**: `/api/saved-queries` endpoints. DB table: `saved_queries`.

#### KB Build Improvements
- **Table profiling merged into KB Redshift step**: Prod metadata + profiling (min/max, cardinality, nulls) now runs during KB build Redshift phase. Results saved to both catalog.json and postgres table_registry.
- **Always-prod Redshift**: KB build always connects to prod Redshift — removed np/prd dropdown selector.
- **Dynamic database discovery**: Discovers all 7 prd_* databases automatically instead of hardcoded list.
- **KB build scheduler**: Cron-based scheduling for automated KB builds (every 6h, daily, weekly, monthly). Configurable in Settings > Knowledge Base.
- **KB build #18 results**: 668 tables, 15K columns, 901 transforms, 1576 lineage edges, 169 glossary terms, 558 event schemas.

#### Security
- **All endpoints auth-guarded**: P0/P1 security fixes — every API endpoint requires authentication.
- **150-test suite**: Comprehensive tests covering auth, query safety, KB build, agent tools, and API endpoints.
- **Statsig read-only**: Console API key has read-only scope, no write access to experiments or gates.
- **Swagger endpoint**: Serves event schemas from static JSON file, no external API calls at runtime.

### Changed
- **Tiered model strategy**: Sonnet for routing/tool calls/sub-agents (speed + cost), Opus only for complex synthesis. 2-5x faster responses, 5-7x cheaper per question. Configurable: `BEDROCK_MODEL_FAST`, `BEDROCK_MODEL`.
- **Persona-based agent prompts**: System prompts rewritten as personas (16K → 5.4K chars). "Senior Analytics Engineer" (principal), "Senior Data Engineer" (data), "Senior DBA" (redshift), "Data Governance Lead" (knowledge). Prompts define identity, not instructions.
- **Classification-based routing**: Principal classifies questions as DATA/METRIC/DEFINITION/INVESTIGATION/MODELING/CONVERSATIONAL before acting. DATA questions handled directly (no expert delegation), METRIC questions combine definition + live data visualization.
- **Analytics engineering mental model**: Agent always queries most downstream source first. Resource hierarchy: DOMO S3 → views → aggregates → facts → raw events (last resort).
- **Resource-aware query execution**: Agent prefers DOMO S3 datasets (free, fast) over Redshift. For large tables, proposes query and asks user before running. Uses profile data to assess query cost.
- **System prompt / user context separation**: `prompts.py` = agent identity (static per agent), `context.py` = per-request user context (persona, pillar, environment, custom rules). Clean separation.
- **Principal tools restructured**: Removed investigation tools (repo_search, github_file, aws_lookup) from principal. Added search_tables, search_transforms, analyze_domo_dataset. Investigation stays on sub-agents.
- **Table profiles in agent context**: 66 table profiles from Table Ops injected into agent context at startup (row counts, column classifications, cardinality).
- **prd_dw prefix enforced**: Agents always use prd_dw schema prefix (not np_dw) for data queries.
- **Cost explorer split by model**: Stacked bar chart by model (Opus purple, Sonnet blue, Haiku green), model filter dropdown, cost split pie chart, per-model token breakdown table.
- **Activity day detail**: Model breakdown badges with color dots, per-model call/cost summary.
- **Agent consolidation**: Consolidated 6 sub-agents → 3 (Data Expert, Redshift Expert, Knowledge Expert) — 50% fewer API calls per question. Data Expert merges Repo + Pipeline + Metrics. Knowledge Expert merges Glossary + Platform.
- **Agent admin UI fixed**: 4 agents displayed with toggle collapse, proper save/reset per agent.
- **Chat session restore on navigation**: Switching between sidebar pages preserves active chat session.
- **Tool return schemas**: All agent prompts include expected tool return schemas for better response formatting.
- **UI help text**: Persona, system prompt, and agent prompt editors show contextual help text.
- **Feedback Board → Task Board**: Replaced the admin-only Feedback Board (Settings → Feedback) with a full Task Board accessible to all users from the sidebar. 8 task types, priority levels, due dates, and tags.

### Added

#### Goose-Style Investigation Trail
- **Step log replaces single status**: Real-time accumulated step log showing each tool call as it happens (not just "thinking...").
- **Per-step detail**: Icon + label + detail (search term, SQL snippet, expert question) for each step.
- **Visual states**: Running steps show spinner, completed steps show green checkmark. Fade-in animation for new steps.
- **Intermediate reasoning to step trail**: Agent reasoning goes to the investigation trail, not the message bubble. Clean separation of thinking vs answer.
- **GenieThinking component rewrite**: Now accepts array of ThinkingStep objects instead of a single status string.

#### DOMO REST API Integration (Read-Only)
- **Direct REST API**: DOMO integration via direct REST API using same client_id/secret as Airflow DOMO_REFRESH DAGs. Removed `pydomo` SDK dependency.
- **Strictly read-only tools**: `domo_search` (find datasets by name), `domo_dataset_info` (metadata + schema), `domo_dashboards` (list pages/dashboards), `domo_dashboard_detail` (cards/KPIs on a dashboard). `domo_query` parked awaiting confirmation.
- **Full DOMO hierarchy**: Pages (dashboards) → Cards (KPIs) → Datasets → Streams. Agents access the complete navigation structure.
- **Data analysis via S3/DuckDB**: `analyze_domo_dataset` uses DOMO S3 exports + DuckDB for actual data analysis. DOMO REST API is for metadata only.
- **Connection UI**: DOMO credentials managed via Settings → Connection tab (client_id, client_secret, encrypted in postgres).
- **SSL handling**: `DOMO_VERIFY_SSL=true` in prod, `false` in local dev (corporate proxy compatibility).
- **Agent awareness**: Agents explicitly know DOMO is the richest source of business truth. Principal checks DOMO first for metric questions.

#### DOMO S3 Enrichment
- **domo_s3_enricher.py**: New catalog engine module. During KB build, lists S3 objects at each metric's prod-bi-export path, reads CSV/TSV headers for column names, captures freshness/size/date ranges. Does NOT load full data — just metadata + first 8KB per file.
- **domo_catalog.json**: New unified KB file linking DOMO refresh DAGs → view SQL → S3 metadata → business context (pillar, metric type) per metric.
- **Pillar inference**: Auto-tags metrics with business pillars from names, tags, and patterns.
- **Metric type classification**: north_star, time_series, funnel, cohort, user_level, direct_unload.

#### analyze_domo_dataset Tool
- **Local DOMO data analysis**: Downloads DOMO S3 CSV files (capped at 50MB), loads into DuckDB in-memory, runs SQL aggregations locally — zero Redshift load.
- **Custom SQL support**: Agent can write DuckDB SQL against the dataset (table named 'data').
- **Auto-analysis mode**: Without custom SQL, returns column info, sample rows, date ranges, and basic stats.
- **Available to Principal + Data Expert**: Principal uses it for METRIC questions, Data Expert for deep metric investigation.

#### Correction Capture
- **User corrections → glossary drafts**: When a user corrects Genie, the system detects it, creates a glossary draft entry, assigns a review task to the corrector, and sends notifications.

#### KB Explorer
- **KB Explorer in Settings → Knowledge Base**: 5-tab browser (Summary, Transforms, Tables, DOMO Metrics, Glossary) for browsing the full knowledge base without chat.

#### Additional Repos in KB Build
- **Auto-pull additional repos**: KB build now auto-pulls configured additional repos alongside the primary data platform repo.

#### Demo Script
- **Demo script created**: `docs/DEMO_SCRIPT.md` — 15-minute demo walkthrough for engineering leadership.

### Added

#### Cost Explorer (Admin Only)
- **Cost Explorer tab in Settings**: AWS Cost Explorer-style analytics for AI usage. Admin-only access via Settings > Cost Explorer.
- **Summary cards**: Total Cost, Total Tokens, Total Calls, Avg Cost/Call for the selected period.
- **Usage charts**: Daily/weekly/monthly bar charts with model breakdown — Opus (purple), Sonnet (blue), Haiku (green).
- **Filters**: Filter by user and date range (7/30/90/365 days).
- **User breakdown table**: Per-user cost with percentage of total spend.
- **Token split donut chart**: Input vs output token distribution visualization.
- **Backend API**: `GET /activity/cost-explorer` returns aggregated cost data with filters.

#### Clickable Activity Heatmap
- **Day detail panel**: Click any green dot on the activity heatmap to open a detail panel showing that day's interactions.
- **Detail contents**: Capability breakdown, token usage, estimated cost, and full events table with timestamps.
- **Backend API**: `GET /activity/day-detail` returns detailed activity for a specific day.

#### Chat Session Management
- **Delete chats**: Delete button (X on hover) for each chat session in the sidebar. Permanently removes the session.
- **Auto-archive**: Sidebar only shows chats from the last 30 days. Older sessions are archived but not deleted.
- **Backend API**: `DELETE /chat/sessions/{id}` endpoint for session deletion.

#### SSO Refresh Token Persistence
- **Refresh tokens saved to postgres**: SSO refresh tokens now persist to the `credential_cache` table (previously memory-only).
- **Survive backend restarts**: Tokens are auto-restored on startup, so SSO sessions survive overnight restarts.
- **Fixes overnight expiry**: Scheduled reports and background jobs no longer fail due to SSO token expiry after backend restarts.

#### Task Board
- **Task Board in sidebar**: Moved from Settings to standalone sidebar page. All authenticated users (engineers, analysts, admins) can create and manage tasks.
- **Chat integration**: Flag icon on chat responses now offers "Create Task" (self-assigned) and "Request Support" (admin-assigned), both pre-filled with chat context.
- **Glossary review tracking**: Glossary tasks auto-track review progress. Per-entry reviewer assignment (PR-style) with auto-updates as entries move through review stages.
- **Auto-created tasks**: KB gaps, glossary drafts, and support requests automatically generate tasks with appropriate types and priorities.
- **Due dates and tags**: Tasks support due dates and free-form tags for organization and filtering.

#### Contextual Feature Tips
- **FeatureTips component**: Rotating contextual tips at the bottom of the main content area. Tips are page-aware (Chat, Workbench, Glossary, Tasks, Lineage, Reports) plus general tips shown on any page.
- **Session dismiss**: Dismiss a tip for the current session via the X button.
- **Permanent dismiss**: "Don't show again" option saves to localStorage.
- **Smart rotation**: Rotates through unseen tips every 30 seconds, prioritizing tips relevant to the current page.

#### MCP (Model Context Protocol) Integration
- **GitHub MCP server**: Integrated `@modelcontextprotocol/server-github` as subprocess inside backend container. 26 tools discovered, 4 filtered as useful for Genie's domain.
- **MCP tools on sub-agents only**: Principal agent has NO MCP tools — stays lean for fast routing. MCP tools distributed to experts:
  - **Data Expert**: `github__search_code`, `github__get_file_contents`, `github__list_commits`, `github__search_repositories`
  - **Knowledge Expert**: `github__search_code`, `github__get_file_contents`
- **MCP bridge module**: `backend/engine/mcp_bridge.py` — manages MCP server lifecycle and proxies tool calls from agents to the MCP server.
- **Node.js in backend Dockerfile**: Required to run the MCP server subprocess.

#### repo_search Tool
- **Local repo grep**: `repo_search` tool greps locally cloned repos via subprocess. Much faster than reading files one by one via GitHub API.
- Available to Data Expert and Principal agent.

#### Agent Timeouts
- **Sub-agent timeout**: 2 minute max per sub-agent call. Prevents hanging on broad questions.
- **Total response timeout**: 5 minute max for the entire principal agent response cycle.

#### Golden Rule Prompt
- **"BEFORE answering ANY technical question, MUST use at least one tool"**: Tech questions require tool-based investigation. Business questions can be answered from KB directly.

### Added (continued)

#### Okta OIDC Login
- **"Sign in with Okta" button**: OIDC Authorization Code flow with PKCE on the login page. Feature-flagged via `OKTA_CLIENT_ID` — button only appears when Okta is configured.
- **Onboarding screen**: First-time Okta users complete onboarding (name, team, persona, pillar) before entering the app.
- **Role capabilities matrix**: Visual display on login/settings showing what each role can do.
- **Role change request**: Users can request a role upgrade from Settings. Creates an admin notification + task.
- **Password fallback**: Email/password login remains available alongside Okta.
- **Env vars**: `OKTA_CLIENT_ID`, `OKTA_CLIENT_SECRET`, `OKTA_ISSUER`.

#### Principal Agent Investigation Tools
- **Direct tools on principal agent**: `aws_lookup`, `github_file`, `execute_query` — principal can now investigate directly for quick lookups instead of always delegating to sub-agents.
- **aws_lookup expanded**: Now covers CloudWatch Logs, Glue Jobs, Lambda, ECS, CloudWatch Metrics. Read access to full AWS data platform via SSO (both np + prd accounts).
- **github_file tool**: Reads files from any configured GitHub repo. Two repos available: `your-org/data-platform-dags` (data platform code) and `your-org/gitops-config` (infra configs: Helm values for Glue, MWAA, ECS).

#### Production Deployment
- **Dockerfile.backend**: Production backend image following the organization infra standards.
- **Dockerfile.frontend**: Production frontend image with nginx.
- **docker-compose.prod.yml**: Production compose with external RDS, persistent volumes.
- **nginx.prod.conf**: Security headers (CSP, HSTS, X-Frame-Options), gzip compression, SSE proxy configuration.
- **CI/CD pipeline**: `.github/workflows/deploy.yml` — build, test, deploy on push to main.
- **Deployment guide**: `docs/DEPLOYMENT.md` — full deployment documentation.

#### Scheduled Reports
- **Schedule button on chat responses**: Clock icon on each assistant response. Pick frequency: Daily 7am, Daily 9am, Weekly Monday 7am, or Custom cron.
- **Schedule runner for reports**: Checks every 60 seconds for due reports. AI generates a fresh response using the saved question (not cached).
- **Reports page**: Standalone page in the sidebar for viewing scheduled report outputs. Run Now button for manual trigger, Enable/Disable toggle.
- **Report notifications**: Users receive a notification when a scheduled report completes or fails.

#### Notification System
- **NotificationBell component**: Bell icon in the header (between connectivity icons and environment toggle) with red badge showing unread count.
- **Notification polling**: Polls every 30 seconds for new notifications.
- **Notification types**: scheduled_report (blue), task_assigned (red), task_updated (red), glossary_assigned (purple), registration_request (amber), kb_gap (orange).
- **Notification management**: Mark individual or all notifications as read. Click any notification to navigate to the relevant page.
- **Backend API**: `/api/notifications` endpoints for list, mark-read, mark-all-read.

#### User Registration
- **Request Access form**: "Request Access" button on the login page. Email must be @example.com. Fields: email, name, team, reason.
- **Admin approval workflow**: Pending requests appear in Settings → Users. Approve creates a viewer account with a temporary password. Reject with optional reason.
- **Registration notifications**: Admin receives an amber notification when a new user requests access.
- **Backend API**: `/api/auth/register`, `/api/auth/registrations`, approve/reject endpoints.

#### In-App Documentation
- **Docs page**: Standalone page in the sidebar with an in-app documentation viewer.

#### Chat & UX
- **Auto-charts**: Query results in chat auto-render as bar/line/pie charts using recharts. Toggle between chart types or hide.
- **ResultChart component**: Auto-detects chart type from query data (dates → line, few rows → pie, default → bar).
- **Per-message actions**: Copy and Flag (🚩) buttons on each assistant response in chat.
- **Citations**: Every agent response includes source references (📊 Table, 🔧 DAG, 📐 View, 📖 Glossary, 🔍 Query).
- **KB gap detection**: Sub-agents report `KB_GAP:` when info is missing. Principal surfaces as improvement suggestions. Auto-creates tasks.
- **Frustration detection**: Agent detects user dissatisfaction and offers to create tasks.

#### Knowledge System
- **Knowledge source tagging**: Each table/transform tagged with provenance (platform/database/code/ai_generated/user).
- **Trust hierarchy**: user > database > platform > code > ai_generated.
- **Completeness scoring**: Per-item score (0-1) based on source coverage.
- **knowledge_summary.json**: Coverage stats injected into agent context.
- **AI enrichment phase**: KB build generates pipeline summaries, table descriptions, and column descriptions via Claude.
- **Model selector for enrichment**: Opus (default) / Sonnet / Haiku — radio buttons in KB build UI.
- **Metric conflict detection**: Detects when same metric name means different things across pillars.
- **Cross-reference gap detection**: Repo vs MWAA gap detection — surfaces DAGs in one source but missing from the other.
- **All DAG types from MWAA**: Fetches TRANSFORM, DOMO, dw_sync, ingest_s3, events_v3, personalization, statsig, braze, extract, glue (not just TRANSFORM_DAG__).
- **Non-SQL DAG metadata**: Schedule, owner, tags, task types, operators captured for DAGs without extractable SQL.
- **Nonprod DAG filter**: Only active DAGs included (last 30 days + known frameworks).
- **Coverage report**: coverage.json per environment (total active, SQL extracted, metadata only, by type).
- **metadata_dags.json**: Separate file for non-SQL DAG metadata.
- **Document upload for glossary**: Upload .txt/.md/.csv/.pdf/.docx → AI extracts terms → draft entries → review ticket.
- **KB build logs**: Live terminal-style log panel in UI (color-coded, last 100 lines).
- **Non-blocking KB build**: MWAA HTTP calls in thread pool, API stays responsive during build.
- **Skip rendered template API**: Always 404 → straight to task logs, ~2x faster MWAA fetch.

#### Operations & Tasks
- **KB build versioning**: Every build creates a record with snapshot + diff (added/removed tables, transforms, glossary terms). Build History UI in Settings → Knowledge Base.
- **Task Board**: Full task board in sidebar (replaces Feedback Board). 8 task types (investigation, data_issue, dag_failure, ai_quality, kb_gap, glossary, request, general). Priority levels, due dates, tags. Accessible to all authenticated users.
- **Chat task creation**: Flag icon on chat responses offers "Create Task" (self-assigned) and "Request Support" (admin-assigned).
- **Auto-task creation**: Agent KB gap detection (`💡 KB Improvement:`) auto-creates tasks. Glossary enricher auto-creates review tasks for new drafts.
- **Glossary review tracking**: Glossary tasks auto-track review progress with per-entry reviewer assignment (PR-style).
- **Tasks API**: `/api/tasks` — CRUD for tasks with user assignment, priority, due dates, and tags.
- **KB tracker module**: `catalog_engine/kb_tracker.py` — start_build, complete_build, fail_build, get_history.

#### Glossary & Enrichment
- **Glossary multi-source enrichment**: Entries now combine View SQL + Redshift COMMENT + repo configs. Source badges show provenance (blue/green/orange/purple).

#### Multi-User & Git
- **Multi-user git worktrees**: Each user gets isolated worktree at `/app/data-repo-worktrees/{user_id}/`. Independent branches, no conflicts.
- **Separate KB clone**: `/app/data-repo-kb` always on main, never touched by Workbench edits.

### Changed
- **Sidebar navigation updated**: Now includes Chat, Workbench, Glossary, Lineage, Docs, and Reports. Reports moved from Settings to standalone sidebar page.
- **Admin Console merged into Settings**: All admin tabs (Connection, KB, Table Ops, Agent Prompts, Users) now in Settings with role-gated visibility. `/admin` route removed.
- **Header status icons live**: Cloud (SSO), Database (Redshift), Git icons now poll `/api/connectivity` every 30s. Green + dot when connected, tooltip shows details.
- **Sidebar simplified**: Removed query recents, renamed "Recent" to "Chats", added New Chat button.
- **Chat sessions user-scoped**: `chat_sessions` filtered by `user_id` — users only see their own conversations.
- **Settings keyed by user_id**: Persist across login sessions (previously lost on re-login).
- **Auth token on every request**: `fetchJSON` now sends `X-Auth-Token` header for user identification.
- **Principal prompt improved**: No raw JSON output, mandatory citations, chart-friendly SQL, KB gap detection.
- **Repo file browser**: Right-click context menu replaces top buttons (new file, new folder, rename, delete).
- **Git rename/delete**: Backend `/api/git/rename` and `/api/git/delete` endpoints with `git mv`/`git rm` + filesystem fallback.

### Fixed
- **Git rename not tracked**: `git mv` fallback to filesystem rename + `git add` for untracked files.
- **Chat sessions visible to all users**: Now filtered by `user_id`.
- **Settings lost on re-login**: Now keyed by `user_id` instead of session token.
- **Workbench clone conflicts**: Multiple users sharing one clone → per-user worktrees.
- **KB build stomps Workbench**: Separate `/app/data-repo-kb` clone for KB builder.

---

## [0.1.0] — 2026-03-23 to 2026-03-25

### Phase 1 — Foundation
- Real knowledge base from MWAA task logs (161 transforms, 577 SQL extractions)
- Git repo integration (226 configs, git blame, YAML parsing)
- Split KB structure (catalog.json, transforms_index.json, lineage.json, metrics.json, transforms/, views/)
- DOMO + view parser (166 metrics, 98 datasets, 93 view SQL definitions)
- Lineage v2: dbt-style search, depth controls, SQL-based target resolution (689 entries)
- Table Ops engine (discover, profile, analyze, sequential queue, weighted classifier)
- PR-style glossary (draft → review → approve → merge, comments, assignment, AI wizard)
- AWS SSO device auth + credential persistence across restarts
- AWS Bedrock support (Opus 4.6, runtime toggle)
- Query safety guard (SELECT/ANALYZE only)
- Redshift direct auth (encrypted in postgres)
- Schedule refresh runner with active/inactive toggle
- SSO auto-refresh (10 min before expiry using refresh tokens)

### Phase 3 — Unified Workbench
- Multi-tab workbook merging Query Runner + SQL Optimizer + Pipeline Builder + Git IDE
- Schema browser + Repo file browser with right-click context menu
- Git panel: create branch, switch, commit, push, create PR
- Per-user git identity (name, email, GitHub token)
- Optimize button inline, "Create pipeline like X" via NL bar

### Phase 3.5 — Agent Architecture
- Principal agent + 3 sub-agents (Data, Redshift, Knowledge) — consolidated from original 6 (Repo, Pipeline, Metrics → Data; Glossary, Platform → Knowledge)
- Tool-based delegation with parallel execution
- Per-agent scoped tools and focused prompts
- Admin-editable agent prompts persisted in postgres

### Phase 4 — Operations & Automation
- RBAC: 4 roles (viewer/analyst/engineer/admin), 22 permissions
- User management with per-user git config
- Chat session persistence + conversation summarization
- Task board with auto-task creation (replaces Feedback Board)
- KB build versioning with diffs
- Multi-user isolation (per-user worktrees, user-scoped sessions/settings)
- Glossary multi-source enrichment with source attribution
