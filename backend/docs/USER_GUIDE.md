# Jennie — User Guide

## Getting Started

### Login
Navigate to `https://genie.example.com`. You'll be redirected to the login page.

**Sign in with Okta (recommended):** Click the "Sign in with Okta" button. You'll authenticate through the organization's Okta and be returned to Genie automatically. This button is only visible when Okta is configured (`OKTA_CLIENT_ID` env var).

**Email/Password (fallback):** Enter the email and password your admin provided. This is available when Okta is not configured or for service accounts.

First-time admin: login with your @example.com email and any password — it becomes your password.

### Onboarding (First-Time Okta Users)
When you log in via Okta for the first time, an onboarding screen collects your setup preferences:
- **Name** — confirm or edit (pre-filled from Okta)
- **Team** — select your team
- **Persona** — choose how Genie talks to you
- **Pillar** — select your primary business pillar

After completing onboarding, you land on the Chat view.

### Requesting Access (New Users)
If you don't have an account, click **Request Access** on the login page:
- **Email** must be `@example.com`
- Fill in your name, team, and reason for access
- An admin receives a notification and will approve or reject your request
- On approval, you get a `viewer` account with a temporary password

### Understanding Your Role

Your admin assigns you a **role** that controls what you can access:

| Role | What you can do |
|------|----------------|
| **Viewer** | Chat with Genie, view glossary and lineage |
| **Analyst** | + run queries on nonprod, submit glossary definitions, browse repo files |
| **Engineer** | + run queries on prod, profile tables, review glossary, edit and commit code via git |
| **Admin** | + admin console, user management, analyze tables, merge glossary definitions |

### Role Capabilities Matrix

Your role determines which features are available. The login page and Settings display a visual capabilities matrix showing exactly what each role can do:

| Capability | Viewer | Analyst | Engineer | Admin |
|------------|--------|---------|----------|-------|
| Chat with Genie | Yes | Yes | Yes | Yes |
| View glossary & lineage | Yes | Yes | Yes | Yes |
| Run queries (nonprod) | - | Yes | Yes | Yes |
| Submit glossary definitions | - | Yes | Yes | Yes |
| Browse repo files | - | Yes | Yes | Yes |
| Run queries (prod) | - | - | Yes | Yes |
| Profile tables | - | - | Yes | Yes |
| Review glossary | - | - | Yes | Yes |
| Git edit/commit/PR | - | - | Yes | Yes |
| Build knowledge base | - | - | Yes | Yes |
| Admin console | - | - | - | Yes |
| User management | - | - | - | Yes |
| ANALYZE tables (prod) | - | - | - | Yes |
| Merge glossary definitions | - | - | - | Yes |

### Requesting a Role Change

If your current role does not include capabilities you need:
1. Navigate to **Settings** and click **Request Role Change**.
2. Select the role you are requesting and provide a reason.
3. An admin receives a notification and a task is created for the request.
4. The admin reviews and approves or denies the request.

### Persona vs Role

- **Role** = what you're *allowed* to do (set by admin)
- **Persona** = how Genie *talks* to you (you choose in Settings)

An analyst can pick "Data Engineer" persona to get technical SQL answers. A viewer can pick "Executive" persona to get business-focused summaries. They're independent.

### How Genie's AI Works

Genie uses a layered prompt system:

| Layer | What it controls | Who sets it |
|-------|-----------------|-------------|
| **System prompt** | Genie's identity — senior analytics engineer persona, platform domain knowledge, tool usage patterns | Built-in (admins can edit in Agent Prompts) |
| **Your persona** | How Genie adapts to you — technical depth, language, default suggestions | You (Settings → Persona) |
| **Custom rules** | Team-specific constraints — environment routing, SQL safety, conventions | You (Settings → System Prompt) |
| **Your question** | What you're asking right now | You (chat input) |

Genie thinks like a senior analytics engineer: it checks DOMO dashboard data first (free, instant), then Redshift views, then fact tables, and only queries raw event tables as a last resort. When you correct Genie, it captures the correction and creates a glossary update for review.

---

## Features

### Chat
Ask Genie anything about your data platform:
- "What tables feed the onboarding KPI board?"
- "How is activation rate calculated?"
- "Show me daily cutting users for last week"

Genie has rich knowledge of the organization's schema built into every conversation — top 40 tables with columns, DOMO metrics, glossary definitions, experiments, and common SQL patterns. It handles ~80% of questions directly (Data Expert and Redshift Expert handle complex investigations). Most answers arrive in 10-20 seconds; simple data queries in ~10 seconds.

- **Investigation trail** — while Genie works, you see a real-time step log showing what it's doing: searching tables, consulting experts, running SQL. Each step has an icon, label, and detail.
- **Resource-aware** — Genie checks DOMO S3 aggregates before querying Redshift. For large tables, it shows you the SQL and asks before running.
- **Correction capture** — if you correct Genie ("no, activation rate is 30 days not 7"), it automatically creates a glossary update draft and notifies you to review it.

- **Session persistence** — conversations are saved automatically. Click any session in the sidebar to reload it. URLs include session ID for sharing.
- **Auto-archive** — only chats from the last 30 days appear in the sidebar. Older sessions are archived automatically.
- **Delete chats** — hover over any chat session in the sidebar to reveal a delete button (X). Click to permanently remove the session.
- **New Chat** — click the + button next to the input to start a fresh conversation.
- **Per-message actions** — each assistant response has Copy, Flag, Schedule, and **PDF export** (download icon) buttons. Flag lets you **Create Task** (self-assigned) or **Request Support** (admin-assigned), both pre-filled with the chat context. Schedule (clock icon) lets you turn the response into a recurring report. PDF export captures the full response including charts and tables.
- **Charts-first** — query results are always shown prominently with charts expanded by default. Only the last SQL result is displayed (intermediate queries are replaced to keep the chat clean).
- **Citations** — responses include source references at the bottom, with icons indicating source type (table, DAG, view, glossary term, or query).
- **Auto-charts** — query results automatically render as bar, line, or pie charts. Toggle between chart types or hide the visualization entirely.
- **Context indicator** — shows message count above input. After 10 messages, older messages are auto-summarized to save token costs.
- **KB improvement suggestions** — when the AI cannot fully answer a question, it displays KB Improvement suggestions so admins know what knowledge to add.

### Scheduled Reports
Turn any chat response into a recurring report:
- Click the **Schedule** button (clock icon) on any assistant response
- Choose frequency: Daily 7am, Daily 9am, Weekly Monday 7am, or Custom cron
- The schedule runner generates a **fresh AI response** for each execution (not cached)
- View all reports in the **Reports** page (sidebar)
- **Run Now** — manually trigger a report at any time
- **Enable/Disable** — toggle reports on/off without deleting
- **Execution history** — each report shows its last 7 runs with timestamp, status, and duration. Click any historical run to view its output.
- You receive a notification when a report completes or fails

### Notifications
A **bell icon** in the header shows real-time notifications (polls every 30 seconds):
- **Red badge** shows the count of unread notifications
- Click the bell to open the notification dropdown
- Notification types:
  - **Scheduled Report** (blue) — report completed or failed
  - **Task Assigned** (red) — task assigned to you
  - **Glossary Assigned** (purple) — glossary entry assigned for review
  - **Registration Request** (amber) — new user access request (admin-only)
  - **KB Gap** (orange) — knowledge gap detected during chat
- Mark individual notifications as read, or mark all read at once
- Click any notification to navigate to the relevant page

### Query Runner (Workbench)
Multi-tab SQL workspace with:
- **Multiple tabs** — each with its own SQL, connection, and results
- **Schema Browser** — expand databases → schemas → tables → columns. Double-click to insert names.
- **Repo Files** — browse the data platform git repo, click SQL files to open and run
- **Right-click context menu** — new file, new folder, rename, delete on repo files
- **Git Panel** — create branches, commit, push, create PRs — all from the app
- **Per-user isolation** — each user gets their own git worktree, so branches are fully independent
- **History** — all queries run this session, click to re-load
- **Saved/Shared Queries** — click **Save to Library** on any query tab to save SQL with a name, description, and tags. Browse team queries in the **Shared** tab in the sidebar. Search by name, tag, or SQL content. Click any saved query to open and run it. Usage tracking shows run count and last-used timestamp so the team can see which queries are most valuable.
- **Shortcuts**: `Cmd+Enter` to run, `Cmd+S` to save repo files
- **CSV Export** on results

### Lineage
Search for any table → see upstream sources and downstream consumers.
- **Tables** view: real schema.table references from executed SQL
- **DAGs** view: DAG-level dependencies
- **Depth controls**: +/- to show more/fewer levels (0-5)
- Click any node to navigate

### Glossary
Business term definitions with PR-style review workflow:
- **Auto-generated** entries from DOMO view SQL (marked with bot icon)
- **Manual** entries via "New Definition" form
- **AI Wizard** — answers 5 persona-aware questions, AI synthesizes a definition
- **Review flow**: Draft → In Review → Approved → Merged (live)
- **Comments**: threaded conversation per entry with **@mention autocomplete** (type @ to tag team members, who receive notifications)
- **Assignment**: assign entries to specific reviewers
- **Contributor notifications**: when your entry is merged ("your entry is live!") or rejected (with reason), you get notified
- **Source badges** — each entry shows colored badges indicating where the info came from: View SQL (blue), Redshift COMMENT (green), Git Repo (orange), DOMO (purple), Document (amber)
- **Document upload** — click "Upload Doc" to upload .txt, .md, .csv, .pdf, or .docx files. AI extracts business terms and creates draft glossary entries for review.

### Navigation
The sidebar includes: **Chat**, **Workbench**, **Glossary**, **Lineage**, **Tasks** (team task board), **Docs** (in-app documentation viewer), and **Reports** (scheduled report outputs). Settings is accessible via the gear icon.

### Settings
All configuration lives under Settings. Tabs are role-gated — you only see what you have access to.

**Everyone sees:**
- **Persona**: Data Engineer, Analyst, ML Engineer, Executive, New Member
- **System Prompt**: custom rules for every AI interaction
- **User Context**: your team, focus area, domain knowledge
- **Git**: your git identity (name, email, GitHub token) for commits and PRs
- **Activity**: GitHub-style activity heatmap. Click any green dot to see that day's detail panel (capability breakdown, tokens, cost, events table)

**Engineers + Admins see:**
- **Knowledge Base**: build from MWAA (primary), Git Repo (secondary), Redshift (optional)
- **Agent Prompts**: view/edit sub-agent system prompts

**Admins also see:**
- **Connection**: AWS SSO, AI Provider, Redshift credentials
- **Cost Explorer**: AWS Cost Explorer-style AI usage analytics (daily/weekly/monthly charts, model breakdown, user breakdown, token split)
- **Table Ops**: discover, profile, analyze, classify, schedules
- **Users**: add/edit/deactivate users, assign roles and teams

> **Note:** The Task Board has moved out of Settings into the sidebar. All users (engineers, analysts, admins) can access it directly.

---

## Architecture

Genie uses a **principal agent + sub-agent** architecture:

```
User Question → Principal Agent (rich inline KB context: schemas, metrics, glossary)
                  ├── 80% handled directly (DATA, DEFINITION, METRIC, CONVERSATIONAL)
                  ├── INVESTIGATION → Data Expert (DAGs, lineage, DOMO, MWAA)
                  └── MODELING �� Redshift Expert (optimization, table design)
                  → Response with charts-first UX
```

The principal agent has the organization's schema knowledge built in (top 40 tables with columns, DOMO metrics, glossary definitions, common SQL patterns). It handles most questions directly and only delegates to Data Expert or Redshift Expert for complex investigations. KB Agent is used only during knowledge base builds.

### Event Schema Lookups

Genie knows the payload structure of 558 ProductApp events (from the Swagger spec). When you ask about specific events or need SQL against firehose_v3_enriched SUPER columns, the agent uses `get_event_schema` and `search_events` tools to look up exact field names and types. This means precise SQL against nested JSON payloads instead of guesswork.

### Statsig Experiments

If Statsig is connected (Settings > Connection), you can ask Genie about experiments and feature gates. The agent looks up experiment configs from the Statsig Console API and can write SQL against prd_statsig exposure tables for experiment segmentation analysis.

---

## Contextual Feature Tips

A rotating tip bar at the bottom of the page helps you discover features. Tips are page-aware (relevant to Chat, Workbench, Glossary, etc.). Dismiss for the session with X, or permanently with "Don't show again."

---

## Keyboard Shortcuts

| Shortcut | Where | Action |
|----------|-------|--------|
| `Cmd+Enter` | Query Runner | Run query |
| `Cmd+S` | Query Runner (repo file) | Save file |
| `Enter` | Chat | Send message |
| `Enter` | Search fields | Select first result |
