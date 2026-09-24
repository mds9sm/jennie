# Jennie — Product Documentation

> **Version:** 1.0.0 | **Last updated:** 2026-03-30 | **Maintainer:** Sri Maru

---

## Table of Contents

1. [Overview](#1-overview)
2. [Getting Started](#2-getting-started)
3. [Chat](#3-chat)
4. [Scheduled Reports](#4-scheduled-reports)
5. [Workbench (SQL IDE)](#5-workbench-sql-ide)
6. [Glossary](#6-glossary)
7. [Lineage](#7-lineage)
8. [Notifications](#8-notifications)
9. [Task Board](#9-task-board)
10. [Knowledge Base](#10-knowledge-base)
11. [Settings](#11-settings)
12. [Activity & Cost Explorer](#12-activity--cost-explorer)
13. [Security](#13-security)
14. [Architecture](#14-architecture)
15. [Deployment](#15-deployment)
16. [Contextual Feature Tips](#16-contextual-feature-tips)
17. [Keyboard Shortcuts](#17-keyboard-shortcuts)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. Overview

### What is Genie

Jennie is an AI-powered data engineering platform purpose-built for the data team. It combines a conversational AI assistant with a full SQL development environment, glossary management, lineage visualization, and knowledge base operations — all in a single web application. Genie knows every table, pipeline, metric, and dependency across your data platform because it ingests real metadata from MWAA task logs, the Git repository, and Redshift system tables.

### Who Uses It

| Persona | Primary Use Cases |
|---------|------------------|
| **Data Engineers** | Trace pipeline lineage, debug DAG failures, review rendered SQL, build and commit new transforms via the Workbench, profile tables, manage knowledge base |
| **Data Analysts** | Query Redshift through the Workbench, look up metric definitions, explore table schemas, understand how KPIs are calculated |
| **ML Engineers** | Explore feature tables, understand data freshness and latency, trace upstream dependencies for model inputs |
| **Executives** | Ask business questions in plain English, get metric definitions with context, understand data availability and quality |
| **New Team Members** | Onboard quickly by asking Genie questions instead of searching Confluence/Slack, learn platform conventions through guided answers |

### Key Value Proposition

- **Institutional knowledge at your fingertips.** Genie holds the same knowledge as the most senior data engineer — every table, pipeline, metric, and dependency — and makes it available through natural language.
- **Grounded in real metadata.** Answers come from actual MWAA execution logs, Redshift system views, and Git history — not generic LLM responses.
- **All-in-one workspace.** Chat, SQL IDE, glossary, lineage, and operations in a single tool. No context-switching between DataGrip, Airflow UI, GitHub, and Confluence.
- **Self-improving.** The knowledge base grows through automated builds, AI enrichment, glossary contributions, and feedback loops.

---

## 2. Getting Started

### 2.1 Login

1. Navigate to `https://genie.example.com` in your browser.
2. You are redirected to the login page.
3. Choose your login method:
   - **Sign in with Okta** (recommended) — click the "Sign in with Okta" button. You are redirected to the organization's Okta OIDC login. After authenticating, you are returned to Genie automatically. This is the primary login method and is feature-flagged via the `OKTA_CLIENT_ID` environment variable — the button only appears when Okta is configured.
   - **Email/Password** (fallback) — enter the email and password provided by your administrator. This remains available as a fallback when Okta is not configured or for service accounts.
4. Upon successful login, you land on the Chat view.

> **First-time admin:** Log in with your @example.com email and any password. The password you enter on first login becomes your permanent password. You are automatically assigned the `admin` role.

### 2.1b Onboarding (First-Time Users via Okta)

When you log in via Okta for the first time, an onboarding screen guides you through initial setup:

1. **Name** — confirm or edit your display name (pre-filled from Okta profile).
2. **Team** — select your team within the organization.
3. **Persona** — choose how Genie communicates with you (Data Engineer, Analyst, ML Engineer, Executive, New Member).
4. **Pillar** — select your primary business pillar (Onboard, Trigger Return, Makeable Content, etc.).

After completing onboarding, you are assigned a default role and land on the Chat view.

### 2.1a Requesting Access (New Users)

If you do not have an account, you can request access from the login page:

1. Click **Request Access** on the login page.
2. Fill in:
   - **Email** — must be a `@example.com` address (validated on submit)
   - **Name** — your display name
   - **Team** — your team within the organization
   - **Reason** — why you need access
3. Submit the request. An admin receives a notification (see [Notifications](#8-notifications)).
4. Once approved, you receive a `viewer` account with a temporary password. The admin may upgrade your role later.

### 2.2 First-Time Setup (Admin)

After the initial admin login, complete the following steps to make Genie fully operational.

#### Step 1 — Connect AWS SSO

1. Navigate to **Settings > Connection**.
2. Under **AWS SSO**, click **Connect SSO** for the Nonprod environment.
3. A device authorization URL appears. Open it in your browser and approve the request through Okta.
4. Genie polls for approval. Once confirmed, the SSO credentials are stored and persist across backend restarts.
5. Repeat for the Prod environment if needed.

> **Note:** SSO tokens auto-refresh 10 minutes before expiry using refresh tokens. You should not need to re-authenticate unless the refresh token itself expires.

#### Step 2 — Set AI Provider

1. In **Settings > Connection > AI Provider**, choose one of:
   - **Bedrock** (default): Uses your nonprod SSO credentials to call Claude via AWS Bedrock. No separate API key needed. Default model: `us.anthropic.claude-opus-4-6-v1`.
   - **Anthropic API**: Requires an `ANTHROPIC_API_KEY` in your `.env` file. Uses the direct Anthropic API.
2. The setting takes effect immediately for all new chat messages.

#### Step 3 — Add Redshift Credentials

1. In **Settings > Connection > Redshift Credentials**, select **Direct Credentials**.
2. Enter a nonprod username and password. Click **Save & Test**.
3. On success, the credentials are encrypted and stored in PostgreSQL. They are never logged, never included in AI context, and never exposed in API responses.
4. Optionally add prod credentials for ANALYZE operations and table metadata queries.

#### Step 4 — Build the Knowledge Base

1. Navigate to **Settings > Knowledge Base**.
2. Check the data sources to include:
   - **MWAA** (primary) — fetches rendered SQL from 160+ DAGs
   - **Git Repo** (secondary) — clones the repo and parses YAML configs
   - **Redshift** (optional) — pulls column metadata from system views
3. Click **Build Knowledge Base**.
4. The build runs as a background job. A live progress panel shows which DAGs and tables are being processed. Typical build time is approximately 6 minutes.

#### Step 5 — Add Users

1. Navigate to **Settings > Users > Add User**.
2. Set: email, display name, initial password, role (`viewer`, `analyst`, `engineer`, or `admin`), and team.
3. Share the credentials with the new user. They log in at `/login`.

### 2.3 Choosing Your Persona

Navigate to **Settings > Persona** and select one:

| Persona | Behavior |
|---------|----------|
| **Data Engineer** | Technical SQL, pipeline details, schema conventions, optimization tips |
| **Analyst** | Business-friendly language, metric definitions, aggregation guidance |
| **ML Engineer** | Feature engineering focus, data freshness, upstream dependency awareness |
| **Executive** | High-level summaries, business impact framing, "so what" answers |
| **New Member** | Extra context and explanations, links to glossary terms, beginner-friendly |

> **Persona vs Role:** Your *role* (set by an admin) controls what you are *allowed* to do. Your *persona* (set by you) controls how Genie *talks* to you. An analyst with the "Data Engineer" persona will get technical SQL answers but still cannot access admin features.

---

## 3. Chat

### 3.1 How Chat Works

Genie uses a **principal agent with rich inline KB context** architecture. The principal has the organization's schema knowledge built into every conversation: top 40 tables with columns, top 25 DOMO metrics with S3 columns, top 20 glossary definitions, active Statsig experiments, and common SQL query patterns (~6K per call). It handles ~80% of questions directly. For complex investigations and modeling questions, it delegates to specialist sub-agents.

**Inline KB context (compiled per-request by context.py):**

| Context | What's Inline |
|---------|--------------|
| Top 40 tables | Full column names and types — agent KNOWS the schema |
| Top 25 DOMO metrics | Metric definitions with S3 column headers |
| Top 20 glossary definitions | Business terms available without tool calls |
| Active experiments | Statsig experiment configs |
| Common SQL patterns | Cutting users, DAU, subscriptions — proven query templates |

**Principal agent direct tools:** `search_tables`, `search_transforms`, `execute_query`, `analyze_domo_dataset`

The principal writes SQL on the first tool call using inline schema knowledge. Example: "daily cutting users by platform" results in 1 tool call, 28 rows, ~10 seconds.

**The two specialist sub-agents (delegation for complex work only):**

| Expert | Domain | KB Tools | MCP / Local Tools |
|--------|--------|----------|-------------------|
| **Data Expert** | DAGs, SQL, lineage, views, DOMO metrics, YAML configs, MWAA execution, run history, data freshness, Git repo organization | `search_transforms`, `get_transform_detail`, `get_view_detail`, `get_table_lineage` | `repo_search`, `github_file`, `aws_lookup`, MCP: `search_code`, `get_file_contents`, `list_commits` |
| **Redshift Expert** | Table metadata, columns, profiling, query optimization, SQL generation | `search_tables`, `get_table_detail`, `execute_query` | (none) |

> **Knowledge Expert removed.** Glossary definitions and pillar context are now compiled inline into every system prompt. No separate agent call needed for business term lookups. KB Agent is used only during knowledge base builds (not during chat).

> **MCP tools** are provided by the GitHub MCP server (`@modelcontextprotocol/server-github`), which runs as a Node.js subprocess inside the backend container. MCP tools give agents live access to the latest code on GitHub without requiring a KB rebuild.

> **Charts-first UX:** Agent prompt says "Default to charts, not text. The chart IS the answer." SQL result cards always expanded, render above other cards, only last SQL result shown (intermediates replaced).

**Example flow:** You ask "Show me daily cutting users by platform"
1. The principal classifies as DATA. It already has `fact.cuts_session_master` schema inline.
2. The principal writes SQL directly using inline schema knowledge and calls `execute_query`.
3. Result: 1 tool call, 28 rows, chart rendered, ~10 seconds total.

**Example flow:** You ask "What tables feed the onboarding KPI board?"
1. The principal classifies as INVESTIGATION. It has inline glossary context for onboarding metrics.
2. The principal delegates to the Data Expert for pipeline investigation.
3. The Data Expert uses `get_transform_detail`, `get_table_lineage`, and `get_view_detail` to find source tables, DAG dependencies, and DOMO view definitions.
4. The principal combines expert results with inline glossary context: "The onboarding KPI board is fed by 3 tables: ... The metrics are defined in these views: ... The data refreshes daily at ..."

### 3.2 Session Management

- **Auto-save.** Every conversation is automatically saved to PostgreSQL. No manual save required.
- **Sidebar history.** The sidebar shows your recent chat sessions with timestamps. Click any session to reload the full conversation.
- **Auto-archive.** Only chats from the last 30 days are shown in the sidebar. Older sessions are archived but not deleted.
- **Delete chats.** Hover over any chat session in the sidebar to reveal a delete button (X). Click to permanently remove the session.
- **Shareable URLs.** Each session has a unique URL that includes the session ID. Share the URL with a teammate to let them view the conversation.
- **New chat.** Click the **+** button next to the chat input to start a fresh conversation.
- **User-scoped.** You can only see your own sessions. Sessions from other users are not visible.

### 3.3 Conversation Context

Genie manages conversation context to balance quality and cost:

- **Full context** is maintained for the first 10 messages.
- **After 10 messages**, older messages are automatically summarized into a compact context block (~300 words). The last 6 messages are always kept in full.
- **Summarization model.** Summaries are generated using Haiku (the cheapest, fastest Claude model) to minimize cost.
- **Context indicator.** A message count appears above the chat input. When summarization is active, the indicator notes this.

### 3.4 Citations and Sources

Every response from Genie includes a **Sources** section at the bottom, listing every piece of knowledge that informed the answer. Source types are identified by icon:

| Icon | Source Type | Example |
|------|-----------|---------|
| `📊` | Table | `📊 dim.users` |
| `🔧` | DAG / Pipeline | `🔧 TRANSFORM_DAG__cuts_session_master` |
| `📐` | View / Metric | `📐 v_daily_active_users` |
| `📖` | Glossary term | `📖 activation rate` |
| `🔍` | Query executed | `🔍 nonprod` |

Example citation block in a response:

```
> **Sources:** 📊 `dim.users`, 🔧 `TRANSFORM_DAG__cuts_session_master`, 📐 `v_daily_active_users`
```

### 3.5 Charts-First UX

Genie defaults to charts, not text. The agent prompt says: "The chart IS the answer."

- **Always expanded.** SQL result cards are always expanded with no collapsible wrapper. Charts are front and center.
- **Render above.** SQL cards render above other cards in the response for visual priority.
- **Last result only.** Only the last SQL result is shown. Intermediate query results from search iterations are replaced, keeping the chat clean.
- **Persist in sessions.** Query result cards (including charts) survive page refresh in chat sessions.
- **Chart type detection.** The `ResultChart` component analyzes the query output:
  - Date/time column present → **line chart**
  - Few rows (less than ~8) → **pie chart**
  - Default → **bar chart**
- **Toggle.** Click the chart type buttons to switch between bar, line, and pie, or hide the chart entirely.
- **Chart-friendly SQL.** The principal agent writes SQL that produces chart-friendly result sets (a label column and one or more value columns) when numeric/aggregate data is requested.

### 3.6 Per-Message Actions

Each assistant message in the chat has action buttons:

- **Copy** — copies the message text to clipboard.
- **PDF Export** (download icon) — captures the full response content including charts, tables, and markdown as a downloadable PDF.
- **Flag** — reports an issue with the response. Two options appear:
  - **Create Task** — creates a task self-assigned to you, pre-filled with the chat context (question + response).
  - **Request Support** — creates a task assigned to an admin for triage, with full chat context for visibility.

**Frustration detection.** If the agent detects signs of user dissatisfaction (rephrasing the same question, "that's not right," "no," etc.), it proactively offers to create a task:

> Would you like to create a task for the data platform team? They can investigate and improve the answer. Just say "yes" and I'll create one.

### 3.7 KB Improvement Suggestions

When a sub-agent cannot fully answer a question due to missing knowledge, the response includes a note:

> **KB Improvement:** Table `fact.subscription_events` has no column descriptions. Adding COMMENT ON or glossary entries would help.

These suggestions are automatically converted into tasks (type: `kb_gap`) on the Task Board. Deduplication prevents the same gap from being reported more than once within a 24-hour window.

---

## 4. Scheduled Reports

### 4.1 Scheduling a Report

Any chat response can be turned into a recurring scheduled report.

1. On any assistant response in the chat, click the **Schedule** button (clock icon).
2. Choose a frequency:
   - **Daily 7am** — runs every day at 7:00 AM
   - **Daily 9am** — runs every day at 9:00 AM
   - **Weekly Monday 7am** — runs every Monday at 7:00 AM
   - **Custom cron** — enter any cron expression for advanced scheduling
3. Click **Save**. The report is now scheduled.

### 4.2 How It Works

The schedule runner checks for due reports every **60 seconds**. When a report is due:

1. The AI generates a **fresh response** using the saved chat question (not a cached copy of the old answer).
2. The output is saved and becomes viewable in the **Reports** page.
3. A notification is sent to the user (see [Notifications](#8-notifications)) when the report is ready or if it fails.

### 4.3 Managing Reports

Navigate to **Reports** in the sidebar to view all scheduled reports.

- **View output** — click any report to see its latest generated output.
- **Execution history** — each report shows its last 7 runs with timestamp, status (success/fail), and duration. Click any historical run to view its output.
- **Run Now** — manually trigger an immediate execution of any scheduled report.
- **Enable / Disable** — toggle a report on or off without deleting it.
- **Delete** — remove a scheduled report permanently.

---

## 5. Workbench (SQL IDE)

The Workbench is a unified SQL development environment that combines query execution, schema browsing, repo file management, and Git operations in a single view.

### 5.1 Query Editor

- **Multi-tab.** Open multiple query tabs, each with its own SQL, connection settings, and result set.
- **Run query.** Press `Cmd+Enter` (Mac) or click the Run button to execute.
- **Environment selector.** Choose nonprod or prod from the dropdown. Nonprod is the default and recommended environment for data queries (it has prd_dw datashares).
- **Results table.** Query results render in a sortable table. Click any column header to sort.
- **CSV export.** Click **Export CSV** on the results panel to download the result set.
- **Query history.** All queries executed in the current session appear in the History tab. Click any entry to reload it into the editor.

### 5.2 Schema Browser

The left sidebar includes a **Schema** tab with a tree view:

```
Database
└── Schema
    └── Table
        └── Column (type)
```

- **Navigation.** Expand nodes to drill down from database to schema to table to column.
- **Insert name.** Double-click any node to insert its fully qualified name into the active query tab.
- **Metadata.** Column nodes show data types. Table nodes show row counts when available from profiling.

### 5.3 Repo File Browser

Toggle from **Schema** to **Repo Files** in the sidebar to browse the cloned Git repository.

- **File tree.** Displays the full directory structure of the data platform repo (`data-platform-dags`).
- **Open files.** Click any `.sql` or `.yaml` file to open it in a query tab. SQL files can be run directly against Redshift.
- **Right-click context menu.** Right-click any file or folder to access:
  - **New File** — create a new file in the selected directory
  - **New Folder** — create a new directory
  - **Rename** — rename the file or folder (uses `git mv` when tracked)
  - **Delete** — delete the file or folder (uses `git rm` when tracked)

### 5.4 Git Operations

The **Git Panel** in the Workbench provides a complete Git workflow without leaving the application.

- **Branch management.** Create new branches, switch between existing branches. The current branch is shown in the panel header.
- **Changed files.** Files with modifications display badges: **M** (modified), **A** (added), **D** (deleted).
- **Diff view.** Click any changed file to see the diff (additions in green, deletions in red).
- **Branch status.** Shows ahead/behind counts relative to the remote tracking branch.
- **Commit.** Stage files, enter a commit message, and commit — all in-app.
- **Push.** Push your commits to the remote repository.
- **Create PR.** Click **Create PR** to open a pull request on GitHub directly from the app.

> **Safety:** Writes to the `main` branch are blocked. You must create a feature branch for any changes.

### 5.5 Per-User Isolation

Each user gets an independent Git worktree at `/app/data-repo-worktrees/{user_id}`. This means:

- Users can work on different branches simultaneously without conflicts.
- Commits from one user never interfere with another user's working directory.
- The knowledge base clone at `/app/data-repo-kb` is completely separate and always tracks `main`.

Per-user Git identity (name, email, GitHub token) is configured in **Settings > Git**.

### 5.6 Saved/Shared Queries

Build a team query library directly in the Workbench:

- **Save to Library.** Click the **Save to Library** button on any query tab to save the current SQL as a named, tagged query.
- **Shared browser panel.** A **Shared** tab in the Workbench sidebar lets you browse all saved queries across the team.
- **Tags and search.** Add free-form tags when saving. Search by name, tag, or SQL content.
- **Usage tracking.** Each saved query tracks run count and last-used timestamp, so the team can see which queries are most valuable.
- **Load and run.** Click any saved query to open it in a new query tab. Run it directly against Redshift.

---

## 6. Glossary

### 6.1 What is the Glossary

The glossary is a curated dictionary of business terms used across your data platform. It provides standardized definitions for metrics, dimensions, business concepts, and cross-team terminology (for example, "activation rate," "churn," "engaged user"). Glossary entries feed directly into the AI agent's context, so Genie can give accurate, consistent answers about business terms.

### 6.2 Sources

Each glossary entry displays colored badges indicating where its information originates:

| Badge Color | Source | Description |
|-------------|--------|-------------|
| **Blue** | View SQL | Definition extracted from `CREATE OR REPLACE VIEW` SQL in DOMO pipeline definitions |
| **Green** | Redshift COMMENT | Definition from `COMMENT ON` statements in Redshift system views |
| **Orange** | Git Repo | Definition derived from YAML configs, README files, or code comments in the repo |
| **Purple** | DOMO | Definition linked to a DOMO dataset or dashboard metric |
| **Amber** | Document | Definition extracted from an uploaded document (.pdf, .docx, .csv, .txt, .md) |

Entries can have multiple source badges when information is merged from several origins.

### 6.3 PR-Style Review Workflow

Glossary entries follow a pull-request-style review workflow with four stages:

```
Draft → In Review → Approved → Merged (live)
```

| Stage | Description |
|-------|-------------|
| **Draft** | Entry created (manually, via AI wizard, via document upload, or auto-generated from KB build). Not yet visible to the AI agent. |
| **In Review** | Assigned to a reviewer. Open for comments and edits. |
| **Approved** | Reviewer has approved the definition. Awaiting merge. |
| **Merged** | Live in the knowledge base. Visible to the AI agent and used in chat responses. |

**Additional capabilities:**
- **Comments with @mentions.** Threaded conversation on each entry with @mention autocomplete (MentionInput component). Type @ to tag team members — mentioned users receive notifications. Reviewers and contributors can discuss definitions, suggest changes, and resolve disagreements.
- **Assignment.** Entries can be assigned to specific reviewers (typically pillar leads or subject-matter experts).
- **Contributor notifications.** When your entry is merged, you receive a "your entry is live!" notification. When rejected, you receive the reason.
- **History.** Full audit trail of status changes, edits, and comments.

### 6.4 AI Wizard

The Glossary Wizard guides you through defining a business term using a persona-aware questionnaire.

1. Click **New Definition > AI Wizard** in the Glossary view.
2. Genie asks 5 targeted questions based on your persona:
   - Engineers get questions about SQL logic, source tables, and calculation methodology.
   - Analysts get questions about business context, stakeholders, and interpretation caveats.
   - Executives get questions about business impact and strategic relevance.
3. After you answer, the AI synthesizes a draft glossary entry combining your answers with knowledge from the catalog.
4. The draft enters the review workflow.

### 6.5 Document Upload

Upload existing documentation to extract glossary terms:

1. In the Glossary view, click **Upload Doc**.
2. Supported formats: `.txt`, `.md`, `.csv`, `.pdf`, `.docx`.
3. Maximum file size: **5 MB**.
4. The AI extracts candidate business terms, table descriptions, and metric definitions from the document text.
5. Each extracted item creates a **draft** glossary entry and a corresponding **task** (type: `glossary`) for review.
6. Approved items merge into `glossary.yaml` on the next KB build.

> **Security:** Only text content is extracted. No executable content is processed. The raw file is not persisted after extraction — only the extracted text (first 500 characters) is stored in the feedback ticket for context.

### 6.6 Auto-Generation

The knowledge base build process automatically generates draft glossary entries from two sources:

- **View SQL parsing.** The `glossary_enricher` module parses `CREATE OR REPLACE VIEW` SQL from DOMO pipelines, extracting aggregation logic, source tables, dimensions, and filter conditions. Each view becomes a candidate metric definition.
- **Redshift COMMENTs.** Any `COMMENT ON TABLE` or `COMMENT ON COLUMN` statements found in Redshift system views are captured and converted into glossary drafts.

**AI rewrite.** Auto-generated entries are technical by default. An optional AI enrichment pass rewrites them from technical SQL descriptions into business-friendly language using the selected enrichment model (Opus for highest quality).

All auto-generated entries are tagged `ai_generated` and enter the review workflow as drafts. They rank lowest in the trust hierarchy until reviewed and approved by a human.

---

## 7. Lineage

### 7.1 Table Lineage

The Lineage view shows how data flows between tables across your data platform.

- **Search.** Type a table name in the search box. Autocomplete suggests matching tables from the catalog.
- **Upstream.** Tables that feed data *into* the selected table (source tables in `FROM` and `JOIN` clauses of the pipeline SQL).
- **Downstream.** Tables that consume data *from* the selected table (pipelines that reference it as a source).
- **Depth controls.** Use the `+` / `-` buttons to expand or collapse the lineage depth from 0 (selected table only) to 5 (five levels of dependencies).
- **Click to navigate.** Click any node in the lineage graph to center on that table and see its own upstream/downstream.

Lineage is derived from rendered SQL in MWAA task logs (primary source) and `downstream_dags` declarations in YAML configs (secondary source).

### 7.2 DAG Lineage

Switch to the **DAGs** view to see pipeline-level dependencies:

- **DAG-to-DAG links.** Shows which DAGs trigger other DAGs via `TriggerDagRunOperator` or `downstream_dags` YAML config.
- **Cross-framework visibility.** Links between TRANSFORM, DOMO, dq_sync, and other DAG types are all represented.

### 7.3 Search

- **Autocomplete.** The search box provides fuzzy-matched suggestions as you type. Results include both table names and DAG IDs.
- **Click to navigate.** Select any result to jump to its lineage graph.
- **Direct URL.** Lineage views have URL parameters, so you can share a link to a specific table's lineage with a teammate.

---

## 8. Notifications

### 8.1 Notification Bell

A **bell icon** in the header (between the connectivity status icons and the environment toggle) provides real-time notifications. A red badge displays the count of unread notifications. The system polls for new notifications every **30 seconds**.

Click the bell to open a dropdown panel showing all recent notifications.

### 8.2 Notification Types

| Type | Color | Trigger |
|------|-------|---------|
| **Scheduled Report** | Blue | A scheduled report has completed or failed |
| **Task Assigned** | Red | A task has been assigned to you |
| **Task Updated** | Red | A task you created or are assigned to has changed status |
| **Glossary Assigned** | Purple | A glossary entry has been assigned to you for review |
| **Registration Request** | Amber | A new user has requested access (admin-only) |
| **KB Gap** | Orange | A knowledge base gap was detected during chat |

### 8.3 Managing Notifications

- **Mark as read** — click the checkmark on an individual notification to mark it read.
- **Mark all read** — click "Mark all read" at the top of the dropdown to clear all unread indicators.
- **Navigate** — click any notification to navigate to the relevant page (e.g., clicking a scheduled report notification opens the Reports page; clicking a registration request opens Settings > Users).

---

## 9. Task Board

The Task Board is the unified work queue for the data team. It lives in the **sidebar** (not in Settings) and is accessible to all authenticated users — engineers, analysts, and admins can all create tasks.

### 9.1 Task Types

| Type | Icon | Description |
|------|------|-------------|
| **investigation** | Magnifying glass | Open-ended research questions about data or pipelines |
| **data_issue** | Warning | Incorrect data, missing rows, stale tables |
| **dag_failure** | Red circle | Pipeline failures requiring debugging |
| **ai_quality** | Brain | Inaccurate or unhelpful AI responses |
| **kb_gap** | Book | Missing knowledge in the catalog or glossary |
| **glossary** | Dictionary | Glossary entry review, creation, or correction |
| **request** | Hand | Feature requests, access requests, or help requests |
| **general** | Clipboard | Anything that does not fit the above categories |

### 9.2 Priority Levels

| Priority | Color | SLA Guidance |
|----------|-------|-------------|
| **Critical** | Red | Same-day resolution |
| **High** | Orange | Within 2 business days |
| **Medium** | Yellow | Within 1 week |
| **Low** | Gray | Best effort |

Tasks also support **due dates** and **tags** for additional organization and filtering.

### 9.3 Creating Tasks

**From the sidebar:**
1. Click **Tasks** in the sidebar navigation.
2. Click **New Task**.
3. Fill in: type, title, description, priority, due date (optional), tags (optional).
4. The task is self-assigned to you by default.

**From chat — "Create Task":**
1. On any assistant response, click the **flag icon**.
2. Select **Create Task**. The task is pre-filled with the chat context (question + response) and self-assigned to you.
3. Edit the title, type, priority, and description as needed.
4. Click **Save**.

**From chat — "Request Support":**
1. On any assistant response, click the **flag icon**.
2. Select **Request Support**. This creates a task assigned to an admin for triage.
3. The task includes the chat context so the admin has full visibility into the issue.

### 9.4 Workflow

Tasks flow through four columns on the kanban board:

```
Open --> In Progress --> Resolved --> Closed
```

- Any user can move their own tasks between columns.
- Admins can move and reassign any task.
- Tasks can be reassigned to any user via the assignee dropdown.

### 9.5 Glossary Review Tracking

Tasks of type **glossary** automatically track the review progress of associated glossary entries:

- When a glossary entry is assigned to a reviewer, a glossary task is auto-created (or linked if one exists).
- As the glossary entry moves through its review stages (Draft, In Review, Approved, Merged), the task is updated automatically.
- Per-entry reviewer assignment works like PR reviewers on GitHub — assign one or more reviewers to each glossary entry, and the task tracks their approval status.

### 9.6 Auto-Created Tasks

Certain platform events automatically create tasks:

| Trigger | Task Type | Priority | Assigned To |
|---------|-----------|----------|-------------|
| AI cannot answer a question (KB gap) | `kb_gap` | Low | Admin |
| KB build generates new glossary drafts | `glossary` | Medium | Admin |
| User flags a chat response ("Request Support") | `ai_quality` | Medium | Admin |
| User flags a chat response ("Create Task") | `ai_quality` | Medium | Self |
| Glossary entry assigned for review | `glossary` | Medium | Reviewer |

KB gap tasks are deduplicated within a 24-hour window (max 3 per chat response).

### 9.7 Notification Integration

Task events trigger notifications via the bell icon:

- **Task assigned** — you receive a notification when a task is assigned to you.
- **Task updated** — you receive a notification when a task you created or are assigned to changes status.
- **Glossary review** — glossary task updates notify the assigned reviewer.

---

## 10. Knowledge Base

The knowledge base is the foundation of Genie's intelligence. It is a structured collection of metadata about every table, pipeline, metric, and business term in your data platform.

### 10.1 Data Sources

| Source | Priority | What It Provides | Requires |
|--------|----------|-----------------|----------|
| **MWAA** | Primary | Rendered SQL (post-Jinja, real table names), run history (success rate, avg duration), per-task execution stats, DAG status | AWS SSO connected |
| **Git Repo** | Secondary | YAML configs (schedule, tags, params, steps), git blame (who changed what, when), commit history, SQL file references | GitHub token in `.env` |
| **Redshift** | Always prod | Column names/types/positions, distkeys/sortkeys, row counts, table sizes, `COMMENT ON` metadata, column profiling (min/max, cardinality, nulls). Dynamic discovery across 7 prd_* databases. | Prod Redshift credentials |
| **Swagger** | Static | 558 ProductApp event schemas with payload field definitions for firehose_v3_enriched SUPER columns | Bundled (no external calls) |
| **Statsig** | Optional | Experiment configs, feature gate definitions, exposure table metadata in prd_statsig | STATSIG_CONSOLE_API_KEY |

**Priority model:** When information conflicts between sources, MWAA data takes precedence (it represents what actually executed in production). Git repo data supplements with metadata not available in MWAA logs. Redshift provides physical schema details. Table profiling (previously a separate Table Ops step) now runs as part of the KB Redshift phase.

### 10.2 All DAG Types

The knowledge base fetches **all active DAGs** from MWAA, not just `TRANSFORM_DAG__`. Different DAG types receive different levels of extraction:

**Full SQL extraction:**

| DAG Type | Prefix | Description |
|----------|--------|-------------|
| Transform | `TRANSFORM_DAG__` | Primary ETL pipelines. 150+ configs. Full rendered SQL, lineage, task stats. |
| DOMO | `DOMO__` | Dashboard data unloads. View SQL (metric definitions) + S3 export config. |
| dw_sync | `dw_sync__` | Data quality validation. Runs in nonprod, validates prod tables via datashare. |

**Metadata capture (no SQL extraction):**

| DAG Type | What Is Captured |
|----------|-----------------|
| ingest_s3 | Schedule, owner, task types, operators, S3 source paths |
| events_v3 | Firehose event pipeline config, event types |
| personalization | ML feature pipeline metadata |
| statsig | Feature gate experiment data config |
| braze | Marketing automation data pipeline metadata |
| extract | External data pull schedules and sources |
| glue | AWS Glue job metadata |

Metadata-only DAGs are stored in `metadata_dags.json` and available to agents for cross-referencing, even though rendered SQL is not available for them.

### 10.3 AI Enrichment (KB Agent)

After the primary data collection phase (MWAA + Redshift + Git), the **KB Agent** runs a 3-phase enrichment process. This replaces the previous batch `glossary_enricher.py` + `kb_enricher.py` with agent-driven synthesis.

**Phase 1 — DAG Summaries:** Generate human-readable pipeline summaries from rendered SQL + YAML config + run stats.

**Phase 2 — Table Descriptions:** Generate table and column descriptions combining Redshift metadata + MWAA SQL + DOMO views + lineage context. DOMO is now glossary Source 3 (167 metrics with pillar context).

**Phase 3 — Glossary Synthesis:** Merge all metadata sources (Redshift + MWAA + DOMO + S3 + lineage) into glossary entries. Cross-reference gap detection (repo vs MWAA, tables vs lineage).

**Model selection:**

| Model | Quality | Speed | Cost | Best For |
|-------|---------|-------|------|----------|
| **Opus** | Highest | Slowest | Highest | Initial builds, critical enrichment |
| **Sonnet** | Balanced | Moderate | Moderate | Routine rebuilds, scheduled builds |
| **Haiku** | Adequate | Fastest | Lowest | Quick refreshes where quality is less critical |

Select the model in **Settings > Knowledge Base** before starting a build. Default: Sonnet for scheduled builds, Opus for manual builds.

**Token budget.** AI enrichment uses a configurable token budget (default: 100K tokens) to limit costs. The enricher prioritizes items with the lowest completeness scores.

### 10.3a KB Build Scheduler

Automate KB builds on a cron schedule:
- **Every 6 hours** — keeps KB fresh during active development
- **Daily** — recommended for most teams
- **Weekly** — low-activity periods
- **Monthly** — minimal change environments

Configure in **Settings > Knowledge Base > Schedule**. Scheduled builds use Sonnet enrichment by default. The scheduler auto-triggers a full build with all enabled sources.

### 10.4 Knowledge Source Tagging

Every item in the knowledge base is tagged with its data provenance:

| Tag | Source | Example Content |
|-----|--------|----------------|
| `platform` | MWAA task logs | Rendered SQL, run history, task stats |
| `database` | Redshift system views | Column types, distkeys, row counts, profiling |
| `code` | Git repository | YAML configs, git blame, commit history |
| `ai_generated` | AI enrichment | Auto-generated descriptions |
| `user` | Human input | Glossary entries, wizard contributions, corrections |

**Trust hierarchy** (highest to lowest):

```
user > database > platform > code > ai_generated
```

When sources conflict (for example, an AI-generated description vs a user-provided one), the higher-trust source always wins. User corrections take precedence over everything.

**Completeness score.** Each table and transform receives a score from 0.0 to 1.0 based on how many knowledge dimensions are filled (description, columns, lineage, SQL, profiling, glossary terms, classification). A table with only a name scores approximately 0.1. A fully profiled, described, lineage-traced table with glossary terms scores approximately 0.95.

### 10.5 Build Phases

A knowledge base build consists of three independent phases:

| Phase | What Happens | Can Run Independently |
|-------|-------------|----------------------|
| **Data Collection** | Fetches data from MWAA, Git Repo, and/or Redshift (always prod, 7 prd_* databases, includes column profiling). Merges into catalog.json, transforms_index.json, lineage.json. | Yes |
| **Glossary** | Merges base `glossary.yaml` with approved user corrections from PostgreSQL. KB Agent Phase 3 synthesizes new entries from all metadata sources (DOMO 167 metrics as Source 3). | Yes |
| **KB Agent Enrichment** | 3-phase: (1) DAG summaries, (2) table/column descriptions, (3) glossary synthesis + cross-reference gap detection. Replaces batch glossary_enricher + kb_enricher. | Yes |

**Checkpoint system.** If a build is interrupted (network timeout, container restart), the next build resumes from the last checkpoint without re-fetching already-completed DAGs and tables. MWAA HTTP calls run in a thread pool so the API stays responsive during builds.

### 10.6 Build History

Every knowledge base build creates a versioned record in the `kb_builds` PostgreSQL table.

- **Settings > Knowledge Base > Build History** shows all past builds.
- **Expand any build** to see:
  - Added tables, transforms, and glossary terms (green)
  - Removed tables, transforms, and glossary terms (red)
  - Sources included (MWAA, Repo, Redshift)
  - Duration, table count, transform count, lineage entries
- **Color coding:** Green = success, red = error, yellow = currently running.

Use build history to debug changes: "Why did the answer change?" becomes "What was added or removed in the last build?"

### 10.7 Multi-Repo Support

You can configure multiple Git repositories as knowledge sources:

1. Navigate to **Settings > Knowledge Base > Repositories**.
2. Click **Add Repo** and provide the HTTPS URL and GitHub token. The primary `REPO_URL` can also be changed from the UI (no restart required).
3. Each repo is cloned independently at `/app/data-repo-{name}`.
4. **"Parse all files" toggle** — when enabled, the parser processes all files in the repo (not just YAML/SQL configs). Useful for repos with documentation, notebooks, or non-standard file structures.

### 10.8 Coverage Report

After each build, Genie generates a `coverage.json` file containing:

- **DAG type breakdown per environment** — how many DAGs of each type exist in prod vs nonprod MWAA.
- **SQL extraction rate** — how many DAGs have rendered SQL vs metadata-only.
- **Table coverage** — how many tables have descriptions, profiling, lineage, and column metadata.

This report is injected into the agent's context at runtime, so sub-agents know exactly what knowledge is available and what is missing. For example, the Data Expert will not claim to have rendered SQL for an ingest DAG when it only has YAML config metadata.

---

## 11. Settings

### 11.1 Tab Visibility by Role

Settings tabs are role-gated. Users only see tabs their role permits.

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
| Agent Prompts | - | - | Yes | Yes |
| Users | - | - | - | Yes |

### 11.2 Persona

Choose how Genie communicates with you. Options: Data Engineer, Analyst, ML Engineer, Executive, New Member. See [Section 2.3](#23-choosing-your-persona) for details. Note: the sidebar navigation includes Chat, Workbench, Glossary, Lineage, Tasks, Docs, and Reports.

### 11.3 System Prompt

Add custom instructions that apply to every AI interaction. For example:

```
Always include the Redshift schema prefix in table references.
When I ask about metrics, also show the DOMO view SQL.
Keep answers under 3 paragraphs unless I ask for detail.
```

System prompt additions are appended to the agent's base prompt. They persist across sessions.

### 11.4 User Context

Provide background about yourself so Genie can tailor responses:

```
Team: Data Engineering - Platform
Focus: Onboard and Trigger Return pillars
Domain: I own the cuts_session_master pipeline and user activation metrics.
```

### 11.5 Git Configuration

Set your Git identity for commits and pull requests made through the Workbench:

- **Name** — your display name for commits
- **Email** — your email for commits
- **GitHub Token** — personal access token (needs `repo` scope + SAML SSO authorization for the `your-org` org)

### 11.6 Connection (Admin Only)

Manage infrastructure connections:

- **AWS SSO** — connect/disconnect nonprod and prod SSO. Status shows remaining session time.
- **AI Provider** — toggle between Bedrock (uses SSO creds) and Anthropic API (uses API key).
- **Redshift Credentials** — enter direct username/password for nonprod and/or prod. Encrypted in PostgreSQL.

### 11.7 Table Ops (Admin Only)

> **Note:** Table profiling has been merged into the KB Redshift build step. The Table Ops tab now covers standalone operations only.

| Operation | Environment | Description |
|-----------|-------------|-------------|
| **Discover** | Prod | Queries `SVV_ALL_TABLES` across 7 prd_* databases (dynamic discovery). Enriches with lineage value score. |
| **Profile** | Prod (KB build) | Per-column statistics: distinct count, cardinality ratio, null count/rate, min/max. Now runs during KB Redshift phase. Results saved to catalog.json + postgres `table_registry`. |
| **Analyze** | Prod (direct) | Runs `ANALYZE` on prod Redshift to update query planner statistics. |
| **Classify** | N/A | Weighted scoring classifier (`classifier.py`): tables as fact/dimension/ambiguous, columns as primary_key/foreign_key/metric/dimension/date/flag. |

**Job queue.** Standalone operations execute sequentially (one at a time, never parallel) with configurable timeout (default: 120 seconds). Auto-kill terminates operations that exceed the timeout.

**Capabilities.** ANALYZE requires prod credentials (direct access). Profile runs automatically during KB builds.

### 11.8 Agent Prompts (Admin / Engineer)

View and edit the system prompts for all four sub-agents (Data Expert, Redshift Expert, KB Agent, Knowledge Expert) and the principal agent.

- Prompts are stored in PostgreSQL and changes take effect **immediately** — no container restart needed.
- The `prompts.py` file provides defaults that seed the database on first startup.
- Use this to tune agent behavior: add domain-specific instructions, adjust citation format, or modify the routing rules.

### 11.9 Task Board

The Task Board has moved from Settings to the **sidebar** as a standalone page. See [Section 9 — Task Board](#9-task-board) for full documentation. The Task Board is accessible to all authenticated users (engineers, analysts, and admins).

### 11.10 Users (Admin Only)

Manage user accounts:

- **Add user** — set email, name, initial password, role, team.
- **Edit user** — change role, team, or reset password.
- **Deactivate** — disable login without deleting the user or their data.
- **Role assignment** — `viewer`, `analyst`, `engineer`, or `admin`.
- **Registration requests** — pending access requests appear at the top of the Users tab. For each request, admins can:
  - **Approve** — creates a `viewer` account with a temporary password. The admin can upgrade the role afterward.
  - **Reject** — optionally provide a reason. The request is dismissed.
  - Registration requests trigger a `registration_request` notification (amber) to all admins.

---

## 12. Activity & Cost Explorer

### 12.1 Activity Heatmap

The Activity page (**Settings > Activity**) displays a GitHub-style heatmap of your usage over time. Each green square represents a day with activity — darker green means more interactions.

**Clickable day detail.** Click any green dot on the heatmap to open a detail panel showing that day's activity:

- **Capability breakdown** — which features were used (chat, query, glossary, lineage, etc.)
- **Token usage** — total input and output tokens consumed
- **Cost** — estimated cost for the day
- **Events table** — full list of individual interactions with timestamps

### 12.2 Cost Explorer (Admin Only)

The Cost Explorer (**Settings > Cost Explorer** tab) provides AWS Cost Explorer-style analytics for AI usage across the team. Admin-only access.

**Summary cards** at the top show key metrics:
- **Total Cost** — aggregate spend for the selected period
- **Total Tokens** — combined input + output tokens
- **Total Calls** — number of AI API calls
- **Avg Cost/Call** — average cost per interaction

**Usage charts:**
- **Daily/Weekly/Monthly bar charts** — visualize spending trends over time
- **Model breakdown** — color-coded bars by model: Opus (purple), Sonnet (blue), Haiku (green)

**Filters:**
- **User filter** — view costs for a specific user or all users
- **Date range** — preset ranges: 7, 30, 90, or 365 days

**Breakdowns:**
- **User breakdown table** — per-user cost with percentage of total
- **Token split** — donut chart showing input vs output token distribution

**Backend:** `GET /activity/cost-explorer` returns aggregated cost data with filters.

---

## 13. Security

### 13.1 Authentication

**Okta OIDC (primary):**
- **"Sign in with Okta"** on the login page uses the OIDC Authorization Code flow with PKCE.
- Feature-flagged: the button only appears when `OKTA_CLIENT_ID` is configured.
- On successful Okta authentication, the backend exchanges the authorization code for tokens, validates the ID token, and issues a Genie session token.
- User identity (email, name) is extracted from the Okta ID token claims.
- First-time Okta users are directed to an onboarding screen (name, team, persona, pillar) before accessing the app.

**Password login (fallback):**
- Token-based sessions. Upon login, the server issues a session token stored in the browser. The token is sent as an `X-Auth-Token` header on every API request.
- **Token expiry.** Sessions expire after **7 days** of inactivity.
- **Password hashing.** Passwords are hashed using **PBKDF2-SHA256** before storage. Plaintext passwords are never stored.

### 13.2 RBAC

Role-based access control with **4 roles** and **22 granular permissions**:

| Role | Access Level |
|------|-------------|
| **Viewer** | Chat, catalog read-only, glossary read-only, lineage view |
| **Analyst** | + query execution on nonprod, glossary contributions, repo file browsing, task creation |
| **Engineer** | + query execution on prod, table profiling, glossary review, git edit/commit/PR, KB builds, task creation |
| **Admin** | + ANALYZE on prod, credential management, schedule configuration, user management, agent prompt editing, task board management, glossary merge |

All API endpoints enforce role checks. Settings tabs, Workbench operations, and Table Ops are individually gated.

### 13.3 Query Safety

All SQL queries pass through `validate_query_safety()` before execution. This is enforced at the connection level — there is no code path that bypasses it.

**Allowed statements:**

```
SELECT, EXPLAIN, ANALYZE, SET, SHOW, WITH (CTEs)
```

**Blocked statements:**

```
CREATE, DROP, ALTER, INSERT, UPDATE, DELETE, MERGE,
TRUNCATE, GRANT, REVOKE, COPY, UNLOAD
```

**Enforcement points:**
1. `execute_real_query()` — validates before every user-initiated and AI-initiated query.
2. `_run_profile()` — validates profile SQL before execution.
3. Table ops job runner — only accepts `analyze` and `profile` operations.

### 13.4 Credential Management

| Aspect | Policy |
|--------|--------|
| **Storage** | Encrypted in PostgreSQL `credential_cache` table, keyed by (session_id, environment, cred_type) |
| **Logging** | Passwords are **never logged** — only usernames appear in logs |
| **AI context** | Passwords are **never included** in Claude's system prompt, tool responses, or knowledge base files |
| **API responses** | Passwords are **never returned** in API responses — only connection status |
| **Environment variables** | Passwords are **never in `.env`** when set via the in-app UI |
| **Git repository** | `.env` is gitignored — credentials never committed |
| **Restoration** | On backend restart, credentials are restored from PostgreSQL automatically |

**Credential types:**

| Type | Lifetime |
|------|----------|
| AWS SSO tokens | ~4 hours (auto-refreshed 10 min before expiry) |
| Redshift direct credentials | Until manually changed |

### 13.5 Multi-User Isolation

- **Per-user git worktrees.** Each user gets an isolated worktree at `/app/data-repo-worktrees/{user_id}`. Branch and commit operations never conflict between users.
- **Separate KB clone.** The knowledge base always clones from main at `/app/data-repo-kb`, independent of any user's Workbench activity.
- **User-scoped sessions.** Chat sessions are filtered by `user_id`. You can only see your own conversations.
- **User-scoped settings.** Persona, system prompt, and user context are keyed by `user_id` and persist across login sessions.
- **Auth token on every request.** `fetchJSON` sends an `X-Auth-Token` header with every API call for user identification and authorization.

### 13.6 Document Upload Security

- **File size limit:** 5 MB maximum.
- **Text-only extraction.** Binary formats (.pdf, .docx) are parsed for text content only. No executable content is processed or stored.
- **Same AI provider.** Extraction uses the same Claude API configured for chat (Anthropic or Bedrock). No additional external services.
- **No file persistence.** The raw uploaded file is not stored on disk or in the database after extraction completes. Only the first 500 characters of extracted text are saved in the task for context.
- **Review workflow.** Extracted glossary terms go through the standard review process before entering the knowledge base.

---

## 14. Architecture

### 14.1 Infrastructure

Genie runs as three Docker Compose containers:

```
Docker Compose
├── frontend     React 19 + TypeScript + Tailwind CSS + Vite
│                Served via nginx on port 3333
│                nginx proxies /api/* to the backend
│
├── backend      FastAPI + Python 3.12
│                Anthropic SDK + asyncpg + redshift_connector + boto3
│                Runs on port 8000
│
└── postgres     PostgreSQL 16 on port 5434
                 Stores: usage_events, chat_sessions, user_settings,
                 glossary_feedback, glossary_entries, table_registry,
                 table_ops_jobs, table_ops_schedules, credential_cache,
                 schedule_runner_config, kb_builds, users, tasks,
                 scheduled_reports, notifications, registration_requests
```

**Starting the application:**

```bash
# Start all containers
docker compose up -d

# Access points
# Frontend: https://genie.example.com
# Backend:  http://localhost:8000 (internal)
# Postgres: localhost:5434 (internal)

# Rebuild after code changes
docker compose build && docker compose up -d

# Fresh database (drops all data)
docker compose down && docker volume rm jennie_pgdata && docker compose up -d
```

### 14.2 Agent Architecture

**Design principle:** Each agent has a **persona** (who they are) not an instruction manual (what to do). A senior analytics engineer doesn't need rules about checking aggregates — they just do it.

**Tiered model strategy:** Sonnet for routing/tool calls/sub-agents (speed + cost), Opus only for complex synthesis when limits are hit. 2-5x faster, 5-7x cheaper per question.

```
User Question
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  Principal Agent — "Senior Analytics Engineer"        │
│  Model: Sonnet (fast routing)                        │
│                                                       │
│  1. Thinks like an analytics engineer:               │
│     DOMO S3 → views → aggregates → facts → raw       │
│     (always pick most downstream source)              │
│                                                       │
│  2. Checks table profiles for query cost decisions    │
│  3. Handles simple data queries directly              │
│  4. Delegates complex work to specialists             │
│                                                       │
│  Rich inline KB: top 40 tables+columns,               │
│    top 25 DOMO metrics, top 20 glossary defs,          │
│    active experiments, common SQL patterns (~6K)        │
│                                                        │
│  Tools: search_tables, search_transforms,              │
│         execute_query, analyze_domo_dataset,            │
│         ask_{data,redshift}_expert                     │
│  Handles ~80% of questions directly                    │
└───────┬──────────┬─────────────────────────────────────┘
        │          │  (delegation for complex work only)
  ┌─────▼────┐ ┌───▼────┐
  │   Data   │ │Redshift│
  │  Expert  │ │ Expert │
  │"Sr Data  │ │"Sr DBA"│
  │ Engineer"│ │(Sonnet)│
  │ (Sonnet) │ │        │
  └──────────┘ └────────┘
        │          │          │          │
        └──────────┴──────┬───┴──────────┘
                     ▼
         Forced synthesis (Opus — only if limits hit)
                     │
                     ▼
              User Response
         (with investigation trail)
```

**Prompt structure:**

| Layer | What | Changes per |
|-------|------|-------------|
| **System prompt** (`prompts.py`) | Agent persona + platform domain knowledge | Never (per-agent) |
| **User context** (`context.py`) | Who's asking (persona, pillar, environment, custom rules) | Every request |
| **User message** | The actual question | Every message |

**Tool scoping per agent:**

```
Principal Agent (routing + direct data queries)
├── Direct: search_tables, search_transforms, execute_query, analyze_domo_dataset
├── Delegation: ask_{data,redshift,knowledge,kb}_expert
│
├── Data Expert — "Senior Data Engineer"
│   ├── KB: search_transforms, get_transform_detail, get_table_lineage, get_view_detail
│   ├── Local: repo_search, github_file, aws_lookup, analyze_domo_dataset
│   ├── DOMO: domo_search, domo_dataset_info, domo_dashboards, domo_dashboard_detail
│   └── MCP: github__search_code, github__get_file_contents, github__list_commits
│
├── Redshift Expert — "Senior DBA & Data Modeler"
│   ├── KB: search_tables, get_table_detail, execute_query
│   └── Context: table profiles with row counts, cardinality, column classifications
│
├── KB Agent — "KB Enrichment Specialist"
│   ├── Chat mode: fast KB lookups delegated from principal
│   └── Build mode: 3-phase enrichment (descriptions → DOMO metrics/glossary → gap detection)
│
└── Knowledge Expert — "Data Governance Lead"
    ├── KB: glossary_lookup
    └── MCP: github__search_code, github__get_file_contents
```

**Resource-aware query execution:**
- DOMO S3 datasets → free, instant via DuckDB (analyze_domo_dataset tool)
- Small Redshift tables (< 1M rows from profile) → auto-run
- Large tables (> 1M rows) → propose query, ask user before running
- Table profiles loaded from Table Ops at startup (66 tables with row counts + column data)

**Goose-style investigation trail:** Real-time step log shows each tool call as it happens. Each step has icon + label + detail (search term, SQL snippet). Running steps show spinner, completed steps show green checkmark.

**Correction capture:** When a user corrects Genie, the system detects it via `📝 Correction:` markers, creates a glossary draft, assigns a review task to the corrector, and sends notifications.

**Limits:** Sub-agent: 5 iterations, 4096 tokens, 120s timeout. Principal: 8 iterations, 80K token budget, 3 min max. Forced synthesis uses Opus when any limit is hit.

**Key files:**
- `backend/engine/agents/prompts.py` — Persona-based system prompts (~5K chars total, down from 16K)
- `backend/engine/agents/runner.py` — Orchestration, tiered models, parallel execution
- `backend/engine/agents/tools.py` — Tool definitions scoped per agent
- `backend/engine/context.py` — Per-request user context builder
- `backend/engine/mcp_bridge.py` — MCP server lifecycle and tool proxy
- `backend/catalog_engine/domo_s3_enricher.py` — DOMO S3 metadata enrichment

### 14.3 Knowledge Base Pipeline

Triggered manually from Settings > Knowledge Base, or automated via **KB build scheduler** (cron: every 6h, daily, weekly, monthly).

```
┌──────────────────────────────────────────────────────────────┐
│                    Data Collection Phase                      │
│                                                              │
│  MWAA ──────┐                                                │
│  (rendered   │                                               │
│   SQL, runs) ├──→ Merge ──→ Tag Sources ──→ Score ──→ Write  │
│  Git Repo ───┤                                               │
│  (YAML,      │    catalog.json                               │
│   blame)     │    transforms_index.json                      │
│  Redshift ───┘    lineage.json                               │
│  (always prod,    transforms/{dag_id}.json                   │
│   7 prd_* DBs,    metadata_dags.json                         │
│   columns +       coverage.json                              │
│   profiling)      knowledge_summary.json                     │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              KB Agent 3-Phase Enrichment                      │
│              (replaces batch glossary_enricher + kb_enricher) │
│                                                              │
│  Phase 1: Table/column descriptions from SQL + metadata      │
│  Phase 2: Metric + glossary from DOMO views (167 metrics)    │
│           DOMO is glossary Source 3 (pillar context)          │
│  Phase 3: Cross-reference gap detection (repo vs MWAA)       │
│                                                              │
│  Output: glossary.yaml, enrichment_report.json               │
│          Tagged: ai_generated (lowest trust)                 │
└──────────────────────────────────────────────────────────────┘
```

**KB build #18 results:** 668 tables, 15K columns, 901 transforms, 1576 lineage edges, 169 glossary terms, 558 event schemas.
```

### 14.4 API Reference (Brief)

**Chat and AI:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Send a message, receive SSE-streamed AI response |
| GET | `/api/history/sessions` | List user's chat sessions |
| GET | `/api/history/sessions/{id}` | Load a specific session |
| DELETE | `/api/chat/sessions/{id}` | Delete a chat session |

**SQL and Queries:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sql/execute` | Execute a SQL query against Redshift |
| POST | `/api/sql/optimize` | AI-powered SQL optimization |

**Knowledge Base:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/catalog/refresh` | Start a KB build (background task) |
| GET | `/api/catalog/status` | Poll build progress |
| GET | `/api/catalog/repo/status` | Check repo clone status |
| POST | `/api/catalog/repo/clone` | Clone/pull the Git repo |

**Glossary:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/glossary` | List all glossary entries |
| POST | `/api/glossary` | Create a new glossary entry |
| GET | `/api/glossary/review` | List entries pending review |
| PATCH | `/api/glossary/review/{id}` | Update review status |

**Git IDE:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/git/files` | List repo files |
| GET | `/api/git/branches` | List branches |
| POST | `/api/git/commit` | Commit staged changes |
| POST | `/api/git/push` | Push to remote |
| POST | `/api/git/pr` | Create a pull request |
| POST | `/api/git/rename` | Rename a file (`git mv`) |
| DELETE | `/api/git/delete` | Delete a file (`git rm`) |

**Auth and Users:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Authenticate and receive token |
| POST | `/api/auth/sso/start` | Begin AWS SSO device auth |
| GET | `/api/auth/sso/poll` | Poll for SSO approval |
| GET | `/api/users` | List all users (admin) |
| POST | `/api/users` | Create a user (admin) |

**Tasks and Operations:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tasks` | List tasks (filtered by user/role) |
| POST | `/api/tasks` | Create a task |
| PATCH | `/api/tasks/{id}` | Update task status/assignment/priority |
| DELETE | `/api/tasks/{id}` | Delete a task |
| POST | `/api/table-ops/discover` | Start table discovery |
| POST | `/api/table-ops/profile` | Start table profiling job |
| POST | `/api/table-ops/analyze` | Start ANALYZE job |
| GET | `/api/connectivity` | Check SSO/Redshift/Git status |
| GET | `/api/activity/cost-explorer` | Cost explorer data with filters (admin) |
| GET | `/api/activity/day-detail` | Detailed activity for a specific day |

**Scheduled Reports:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scheduled-reports` | List user's scheduled reports |
| POST | `/api/scheduled-reports` | Create a scheduled report |
| PATCH | `/api/scheduled-reports/{id}` | Update report (enable/disable, change schedule) |
| DELETE | `/api/scheduled-reports/{id}` | Delete a scheduled report |
| POST | `/api/scheduled-reports/{id}/run` | Trigger immediate execution |

**Notifications:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/notifications` | List user's notifications (with unread count) |
| PATCH | `/api/notifications/{id}/read` | Mark a notification as read |
| POST | `/api/notifications/read-all` | Mark all notifications as read |

**Registration:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Submit a registration request |
| GET | `/api/auth/registrations` | List pending requests (admin) |
| POST | `/api/auth/registrations/{id}/approve` | Approve a request (admin) |
| POST | `/api/auth/registrations/{id}/reject` | Reject a request (admin) |

---

## 15. Deployment

### 15.1 Production Deployment

Genie is packaged for production deployment on the organization infrastructure:

- **`Dockerfile.backend`** — Production backend image following the organization infra standards. Multi-stage build with optimized Python dependencies.
- **`Dockerfile.frontend`** — Production frontend image with nginx serving the built React app.
- **`docker-compose.prod.yml`** — Production compose file configured for external RDS (instead of local postgres), persistent volumes, and production environment variables.
- **`nginx.prod.conf`** — Production nginx configuration with security headers (CSP, HSTS, X-Frame-Options), gzip compression, and SSE (Server-Sent Events) proxy configuration for streaming chat responses.

### 15.2 CI/CD Pipeline

Automated deployment via GitHub Actions:

- **`.github/workflows/deploy.yml`** — CI/CD pipeline that builds Docker images, runs tests, and deploys to the target environment.
- Triggered on push to `main` or manual dispatch.
- Builds and pushes images to the container registry, then deploys via the standard the organization deployment process.

### 15.3 Kubernetes Support

Genie is K8s-ready with the following production features:

- **HMAC-signed auth tokens** — tokens are signed with SHA256 using a secret derived from `DATABASE_URL`, so they validate on any pod replica without sticky sessions or shared session storage.
- **Runtime environment injection** — all configuration (Okta, Bedrock, Redshift, DOMO, Statsig) is injected via environment variables at container start, compatible with ConfigMaps and Secrets.
- **Non-blocking KB builds** — knowledge base builds run as background tasks and do not block the API server. Multiple replicas can serve requests while a single replica runs the build.

### 15.4 Deployment Guide

Full deployment instructions are documented in **`docs/DEPLOYMENT.md`**, covering:

- Infrastructure prerequisites (RDS, ECS/EKS, networking)
- Environment variable configuration for production
- Database migration steps
- SSL/TLS certificate setup
- Health check endpoints
- Rollback procedures

---

## 16. Contextual Feature Tips

A rotating tip bar appears at the bottom of the main content area, helping users discover features:

- **Page-aware tips.** Tips are contextual to the current page (Chat, Workbench, Glossary, Tasks, Lineage, Reports) plus general tips shown on any page.
- **Session dismiss.** Click the X button to dismiss a tip for the current session.
- **Permanent dismiss.** Click "Don't show again" to suppress a tip permanently (saved to localStorage).
- **Smart rotation.** Rotates through unseen tips every 30 seconds, prioritizing tips relevant to the current page.

---

## 17. Keyboard Shortcuts

| Shortcut | Location | Action |
|----------|----------|--------|
| `Cmd + Enter` | Workbench query editor | Execute the current query |
| `Cmd + S` | Workbench (repo file open) | Save the current file to the repo |
| `Enter` | Chat input | Send the message |
| `Enter` | Search / autocomplete fields | Select the first result |

---

## 18. Troubleshooting

### SSO Session Expired

**Symptom:** MWAA-dependent features fail. Header cloud icon turns gray.

**Fix:** Go to **Settings > Connection** and click **Connect SSO** for the affected environment. SSO sessions last approximately 4 hours and auto-refresh, but the refresh token can also expire after extended inactivity.

### Knowledge Base Build Interrupted

**Symptom:** Build shows "error" status in Build History. Some DAGs/tables missing from catalog.

**Fix:** Start a new build. The checkpoint system resumes from where the previous build stopped — already-fetched DAGs are not re-fetched. If the issue persists, check that SSO is connected (MWAA fetching requires it) and the GitHub token is valid (repo cloning requires it).

### Login Fails on Page Refresh

**Symptom:** After refreshing the browser, you are redirected to the login page even though you were logged in.

**Fix:** Check that your session token has not expired (7-day expiry). If the issue persists, clear browser storage and log in again. Ensure the backend container is running (`docker compose ps`).

### Queries Return Empty Results

**Symptom:** SQL executes successfully but returns zero rows.

**Fix:** Verify:
1. You are connected to the correct environment (nonprod vs prod).
2. Your date filters are correct. Remember that `event_date` (not `file_date_id`) is the correct field for business logic.
3. Table names are fully qualified (e.g., `prd_dw.analytics.table_name` not just `table_name`).
4. For board metrics, account for 45-day late arrival: recent dates may not have complete data.

### Redshift Connection Failed

**Symptom:** "Connection failed" when testing credentials or running queries.

**Fix:**
1. Verify credentials in **Settings > Connection > Redshift Credentials**. Click **Save & Test** to retest.
2. Ensure you are on the the organization VPN or network (Redshift clusters are not publicly accessible).
3. Check the correct cluster: nonprod uses `nonprod-redshift-cluster`, prod uses `prod-redshift-cluster`.

### Git Push Fails

**Symptom:** "Push rejected" or authentication error in the Git Panel.

**Fix:**
1. Verify your GitHub token in **Settings > Git**. It needs the `repo` scope.
2. If the repo is in the `your-org` org, the token must have **SAML SSO authorization** enabled for that org.
3. Ensure you are not trying to push to `main` directly — create a feature branch first.

### Agent Gives Inaccurate Answers

**Symptom:** Genie's responses reference tables or pipelines that do not exist, or give incorrect metric definitions.

**Fix:**
1. Check when the knowledge base was last built (**Settings > Knowledge Base > Build History**). If the KB is stale, rebuild it.
2. Check the coverage report — the agent may be working with incomplete data for certain DAG types.
3. Use the **Flag** button on the message to create a feedback ticket so the team can investigate.
4. If a glossary definition is wrong, submit a correction through the Glossary workflow.

### Docker Containers Fail to Start

**Symptom:** `docker compose up` errors or containers crash.

**Fix:**

```bash
# Check container status
docker compose ps

# Check logs for the failing container
docker compose logs backend
docker compose logs frontend
docker compose logs postgres

# Full rebuild
docker compose build --no-cache && docker compose up -d

# Nuclear option: fresh database (WARNING: drops all data)
docker compose down && docker volume rm jennie_pgdata && docker compose up -d
```

### Slow KB Build

**Symptom:** Knowledge base build takes more than 15 minutes.

**Fix:**
1. MWAA API calls are the bottleneck. The build fetches rendered SQL from the last successful run of 160+ DAGs. Network latency to AWS adds up.
2. Check that the skip-rendered-template optimization is active (default). This goes directly to task logs instead of trying the rendered template API first, which is approximately 2x faster.
3. If only a partial refresh is needed, disable sources you do not need (e.g., skip Redshift metadata if you only want updated MWAA data).

### Auto-Charts Not Appearing

**Symptom:** Query results show a table but no chart visualization.

**Fix:** Auto-charts require at least one numeric column in the result set. Ensure your query returns a label column and one or more numeric value columns. The chart type detector needs at least 2 rows of data.
