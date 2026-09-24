# Admin Guide

## Initial Setup

### 0. Configure Okta OIDC (Optional)

To enable "Sign in with Okta" on the login page:

1. Create an OIDC application in your Okta admin console:
   - **Application type:** Web
   - **Sign-in redirect URI:** `https://genie.example.com/api/auth/okta/callback`
   - **Sign-out redirect URI:** `https://genie.example.com/login`
   - **Allowed grant types:** Authorization Code
2. Set environment variables:
   - `OKTA_CLIENT_ID` — the client ID from Okta
   - `OKTA_CLIENT_SECRET` — the client secret from Okta
   - `OKTA_ISSUER` — your Okta org issuer URL (e.g., `https://your-org.okta.com/oauth2/default`)
3. Restart the backend. The "Sign in with Okta" button appears on the login page when `OKTA_CLIENT_ID` is set.
4. Password login remains as a fallback — it is always available regardless of Okta configuration.

**First-time Okta users** see an onboarding screen (name, team, persona, pillar) before entering the app. The onboarding data is saved to the user's profile.

**Role change requests:** When a user requests a role change from Settings, you receive a notification and a task is created on the Task Board. Review in the Task Board (sidebar) or Settings > Users.

### 1. First Login
- Navigate to `https://genie.example.com`
- Login with your @example.com email and any password (first login sets it)
- You're the default admin

### 2. Connect AWS SSO
- Settings → Connection → Connect SSO for Nonprod and/or Prod
- This enables MWAA access for knowledge base builds
- SSO tokens persist across backend restarts (stored in postgres)
- Auto-refresh: credentials are renewed 10 min before expiry using refresh tokens

### 3. Set AI Provider
- Settings → Connection → AI Provider
- **Bedrock** (default): uses nonprod SSO credentials, no API costs
- **Anthropic API**: needs credits at console.anthropic.com
- Model: `us.anthropic.claude-opus-4-6-v1` for Bedrock

### 4. Add Redshift Credentials
- Settings → Connection → Redshift Credentials → Direct Credentials
- Enter prod username/password → Save & Test (KB builds always use prod)
- Optionally add nonprod credentials for datashare queries
- Stored encrypted in postgres, never logged, never in Claude context

### 4b. Connect DOMO (Optional)
- Settings → Connection → DOMO
- Enter client_id and client_secret (same credentials as Airflow DOMO_REFRESH DAGs)
- Click **Save & Test** — verifies read-only API access
- Enables: DOMO dashboard/dataset browsing, DOMO metrics as glossary Source 3 (167 metrics with pillar context)
- Strictly read-only — no data writes to DOMO
- SSL: `DOMO_VERIFY_SSL=true` in prod, `false` for local dev behind corporate proxy

### 4c. Connect Statsig (Optional)
- Settings → Connection → Statsig
- Enter `STATSIG_CONSOLE_API_KEY` (read-only Console API key from Statsig)
- Click **Save & Test** — verifies read-only API access
- Enables: experiment and feature gate lookups, prd_statsig exposure table queries
- Read-only — no write access to experiments or gates

### 5. Build Knowledge Base
- Settings → Knowledge Base
- Check MWAA + Git Repo + Redshift (always prod) → Build Knowledge Base
- Takes ~6 min (fetches rendered SQL from 160+ DAGs, profiles tables across 7 prd_* databases)
- Runs as background job with live progress
- KB Agent enrichment: 3-phase (DAG summaries, table descriptions, glossary synthesis with DOMO 167 metrics)
- **Schedule builds**: Configure auto-builds (every 6h, daily, weekly, monthly) in the Schedule section

### 6. Add Users
- Settings → Users → Add User
- Set email, name, initial password, role, team
- Users login at `/login` with their credentials

### 7. Approve Registration Requests
- New users can request access via "Request Access" on the login page (email must be @example.com)
- Pending requests appear at the top of **Settings → Users** with an amber highlight
- You receive a **registration_request** notification (amber) in the notification bell
- **Approve**: creates a `viewer` account with a temporary password (you can upgrade the role afterward)
- **Reject**: optionally provide a reason; the request is dismissed

---

## Roles & Permissions

| Role | Description |
|------|-------------|
| **Viewer** | Chat with Genie, view glossary and lineage. Read-only access. |
| **Analyst** | + query nonprod Redshift, submit glossary drafts, browse repo files |
| **Engineer** | + query prod, profile tables, review glossary, git edit/commit/PR, build KB |
| **Admin** | + connections, user management, ANALYZE tables, merge glossary, agent prompts |

22 granular permissions mapped to 4 roles. Assign the minimum role needed.

### Settings Tab Visibility by Role

| Tab | Viewer | Analyst | Engineer | Admin |
|-----|--------|---------|----------|-------|
| Persona | Yes | Yes | Yes | Yes |
| System Prompt | Yes | Yes | Yes | Yes |
| User Context | Yes | Yes | Yes | Yes |
| Git | Yes | Yes | Yes | Yes |
| Activity | Yes | Yes | Yes | Yes |
| Cost Explorer | - | - | - | Yes |
| Connection | - | - | - | Yes |
| Knowledge Base | - | - | Yes | Yes |
| Table Ops | - | - | - | Yes |
| Agent Prompts | - | - | - | Yes |
| Users | - | - | - | Yes |

---

## Knowledge Base Sources

| Source | Priority | What it provides | Requires |
|--------|----------|-----------------|----------|
| MWAA | Primary | Rendered SQL, real lineage, run history, task stats | SSO connected |
| Git Repo | Secondary | YAML configs, git blame, commit history | GitHub token in .env |
| Redshift | Always prod | Column types, distkeys, row counts, column profiling (min/max, cardinality, nulls). Dynamic discovery across 7 prd_* databases. | Prod Redshift creds |
| Swagger | Static | 558 ProductApp event schemas with payload fields | Bundled |
| Statsig | Optional | Experiment configs, feature gates, prd_statsig exposure metadata | STATSIG_CONSOLE_API_KEY |
| MCP GitHub | Agent tools | Code search, file contents, commit history across repos | GitHub token in .env + Node.js in container |

MWAA data comes from **prod MWAA** (highest value) by default. Nonprod dq_sync DAGs are second priority. Table profiling is now part of the KB Redshift step (no separate Table Ops run needed).

### AI Enrichment (KB Agent)
The KB Agent runs 3-phase enrichment during builds, replacing the batch glossary_enricher + kb_enricher:
- **Phase 1**: DAG summaries from rendered SQL + YAML + run stats
- **Phase 2**: Table/column descriptions from Redshift + MWAA + DOMO views + lineage
- **Phase 3**: Glossary synthesis from all sources (167 DOMO metrics as Source 3) + cross-reference gap detection

Select the Claude model used for enrichment:
- **Opus** — best quality, recommended for initial builds.
- **Sonnet** — balanced quality and cost. Default for scheduled builds.
- **Haiku** — cheapest. Use for quick refreshes where enrichment quality is less critical.

Configure in Settings → Knowledge Base before starting a build.

### KB Build Scheduler
Automate KB builds on a cron schedule:
- **Every 6 hours** — keeps KB fresh during active development
- **Daily** — recommended for most teams
- **Weekly** — low-activity periods
- **Monthly** — minimal change environments

Configure in Settings → Knowledge Base → Schedule. Scheduled builds use Sonnet enrichment by default and auto-trigger with all enabled sources.

### All DAG Types
The knowledge base now fetches **all active DAGs** from MWAA, not just `TRANSFORM_DAG__`. Non-SQL DAGs (DOMO, dq_sync, ingest, etc.) get metadata capture: schedule, owner, task types, last run status. This metadata is stored in `metadata_dags.json` and available to agents for cross-referencing.

### Knowledge Tagging
Each table and transform in the knowledge base is tagged with **source provenance** indicating where the information came from:
- **platform** — MWAA execution logs
- **database** — Redshift system views
- **code** — Git repo YAML/SQL files
- **ai_generated** — AI enrichment (summaries, descriptions)
- **user** — Manual glossary entries, corrections

Each item also receives a **completeness score** (0-100%) based on how many knowledge dimensions are filled (description, lineage, owner, schedule, columns, etc.). Low-scoring items are surfaced as KB Gap tasks on the Task Board.

---

## Security

### Credentials
- Redshift passwords encrypted in postgres `credential_cache` table
- Passwords never logged, never in Claude context, never in API responses
- SSO tokens persist across restarts, auto-refresh before expiry
- SSO refresh tokens saved to postgres (survive backend restarts, auto-restored on startup)

### Query Safety
- All SQL queries pass through `validate_query_safety()` before execution
- Allowed: SELECT, EXPLAIN, ANALYZE, SET, SHOW, WITH
- Blocked: CREATE, DROP, INSERT, UPDATE, DELETE, MERGE, TRUNCATE, ALTER, GRANT, COPY, UNLOAD

### Authentication
- Token-based sessions (7-day expiry)
- Passwords hashed with PBKDF2-SHA256
- All routes require authentication (redirect to /login)

---

## Chat Features

### Session Persistence
- All conversations saved to postgres automatically
- Click any session in sidebar to reload full conversation
- URLs include session ID — shareable across team

### Conversation Summarization
- After 10 messages, older messages are auto-compressed into a ~300-word summary
- Last 6 messages always kept in full
- Summary generated using Haiku (cheap) to minimize costs
- Context indicator above input shows message count and summarization status

---

## Task Board

The Task Board is accessible from the **sidebar** (not Settings) and is available to all authenticated users — engineers, analysts, and admins.

### Task Types
8 task types cover all data team work: **investigation**, **data_issue**, **dag_failure**, **ai_quality**, **kb_gap**, **glossary**, **request**, **general**.

### Priority Levels
**Critical** (red), **High** (orange), **Medium** (yellow), **Low** (gray). Tasks also support due dates and tags.

### Creating Tasks
- **From the sidebar:** Click Tasks > New Task. Self-assigned by default.
- **From chat — "Create Task":** Click the flag icon on any response, select "Create Task". Pre-filled with chat context, self-assigned.
- **From chat — "Request Support":** Click the flag icon, select "Request Support". Assigned to an admin for triage with full chat context.
- Engineers and analysts can create tasks (not admin-only).

### Workflow
Tasks flow through 4 columns: **Open --> In Progress --> Resolved --> Closed**
- Any user can move their own tasks between columns
- Admins can move and reassign any task
- Reassign to any user via the assignee dropdown

### Glossary Review Tracking
- Glossary tasks auto-track review progress of associated entries
- Per-entry reviewer assignment (PR-style) — assign one or more reviewers
- Tasks auto-update as glossary entries move through Draft, In Review, Approved, Merged

### Auto-Created Tasks
- **KB Gap** — auto-created when AI agents detect missing knowledge (low priority, max 3/response, deduplicated within 24h)
- **Glossary** — auto-created when KB build generates new draft entries
- **AI Quality** — created when a user clicks "Request Support" on a chat response

---

## KB Build History

Every knowledge base build is tracked with full versioning:
- **Settings → Knowledge Base → Build History** shows all builds
- Click a build to expand: see diff (added/removed tables, transforms, glossary terms)
- Color-coded: green = success, red = error, yellow = running
- Sources tracked: which data sources were included (MWAA, Repo, Redshift)
- Stats: table count, transform count, lineage entries, duration

Use this to debug: "why did the answer change?" → check what was added/removed in the last build.

---

## Monitoring

### Header Status Icons
Four icons in the top-right show live connectivity and notification status:
- **Cloud**: AWS SSO — green when NP/PRD connected, tooltip shows minutes remaining (polls every 30s)
- **Database**: Redshift — green when connected, shows method (direct/sso) (polls every 30s)
- **Bell**: Notifications — red badge with unread count (polls every 30s). Click to open notification panel.
- **Git**: Repo — green when cloned, shows current branch (polls every 30s)

### Notification Triggers for Admins
Admins receive notifications for:
- **Registration requests** (amber) — a new user has requested access via the login page
- **Task assigned** (red) — a task has been assigned to you
- **KB Gap** (orange) — knowledge gaps detected during chat (auto-created)
- **Scheduled reports** (blue) — report completions/failures for your own scheduled reports
- **Glossary assigned** (purple) — glossary entries assigned for your review

Notifications are accessed via the bell icon in the header. Mark individual or all notifications as read.

### MCP Server
- The MCP (Model Context Protocol) GitHub server runs as a Node.js subprocess inside the backend container
- Requires **Node.js** installed in the backend Docker image (added to `Dockerfile.backend`)
- Uses the same `GITHUB_TOKEN` from `.env` — no separate configuration needed
- Provides tools to sub-agents: `search_code`, `get_file_contents`, `list_commits`, `search_repositories`
- MCP tools are on sub-agents only (Data Expert, Knowledge Expert) — NOT on the principal agent
- Server lifecycle managed by `backend/engine/mcp_bridge.py`
- If the MCP server fails to start, agents fall back to KB tools and `repo_search` (local grep)

### Schedule Runner
- Settings → Table Ops → Schedules tab
- Toggle active/inactive (defaults to inactive)
- Checks every 60 seconds for due cron schedules
- Executes jobs sequentially, never parallel

### Glossary Review
- Auto-generated draft entries from view SQL
- Assign reviewers, track approval progress
- Approved/merged entries feed Claude's context

### Sidebar Navigation
The sidebar includes: **Chat**, **Workbench**, **Glossary**, **Lineage**, **Tasks** (team task board), **Docs** (in-app documentation viewer), and **Reports** (scheduled report outputs). Settings is accessible via the gear icon.

### Activity
- Settings → Activity shows usage heatmap (GitHub-style green squares)
- **Clickable day detail**: click any green dot to see that day's breakdown — capability usage, tokens, cost, and full events table
- Chat sessions in sidebar with timestamps
- Backend: `GET /activity/day-detail`

### Cost Explorer (Admin Only)
- Settings → Cost Explorer tab (admin-only)
- AWS Cost Explorer-style analytics for AI usage across the team
- **Summary cards**: Total Cost, Total Tokens, Total Calls, Avg Cost/Call
- **Usage charts**: daily/weekly/monthly bar charts with model breakdown
  - Opus (purple), Sonnet (blue), Haiku (green)
- **Filters**: by user + date range (7/30/90/365 days)
- **User breakdown table**: per-user cost with percentage of total
- **Token split**: donut chart showing input vs output token distribution
- Backend: `GET /activity/cost-explorer`

### Chat Session Management
- Sidebar shows chats from last 30 days (auto-archive older sessions)
- Delete button (X on hover) for each chat session in the sidebar
- Backend: `DELETE /chat/sessions/{id}`

---

## Production Deployment

### Deployment Files

| File | Purpose |
|------|---------|
| `Dockerfile.backend` | Production backend image (the organization infra standards) |
| `Dockerfile.frontend` | Production frontend image with nginx |
| `docker-compose.prod.yml` | Production compose: external RDS, persistent volumes |
| `nginx.prod.conf` | Security headers, gzip, SSE proxy config |
| `.github/workflows/deploy.yml` | CI/CD pipeline: build, test, deploy |

### Deployment Steps

1. Configure production environment variables (see `docs/DEPLOYMENT.md` for full list)
2. Set up external RDS PostgreSQL instance (replaces local postgres container)
3. Configure Okta OIDC (`OKTA_CLIENT_ID`, `OKTA_CLIENT_SECRET`, `OKTA_ISSUER`)
4. Build production images: `docker compose -f docker-compose.prod.yml build`
5. Deploy via CI/CD pipeline (push to `main` triggers `.github/workflows/deploy.yml`)
6. Verify health check endpoints after deployment

### Full Deployment Guide

See **`docs/DEPLOYMENT.md`** for comprehensive deployment documentation including:
- Infrastructure prerequisites
- Database migration
- SSL/TLS setup
- Rollback procedures
- Monitoring and alerting
