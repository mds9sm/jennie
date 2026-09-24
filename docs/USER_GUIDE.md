# Jennie — User Guide

## Overview

Genie is your data platform intelligence layer. It consists of two surfaces:

| Surface | URL | Purpose |
|---------|-----|---------|
| **claude.ai** (Team/Enterprise) | claude.ai | AI chat — ask questions about your data in plain English |
| **Genie Tools** | genie.example.com | Built-in chat, SQL workspace, glossary, lineage, tasks, reports |

**You can ask Genie questions from either surface.** Genie connects to claude.ai as two MCP (Model Context Protocol) servers — a knowledge layer and a data layer — so you get the organization-grounded answers inside claude.ai conversations. Genie Tools also has its own built-in chat at genie.example.com, backed by the same agents and knowledge base.

**Which one to use:** claude.ai when you want the conversation alongside your other work, with Claude's memory and file handling. Genie's built-in chat when you want inline action cards (query results, lineage, pipeline detail) rendered next to the answer, shareable session links, or to schedule a question as a recurring report.

**Genie Tools** is the web app at genie.example.com. Beyond chat, it's where you write and run SQL, manage glossary definitions, browse lineage, track tasks, and view scheduled reports.

---

## Part 1 — AI Chat via claude.ai

### How It Works

When you ask a question in claude.ai, two Genie MCP servers give it deep knowledge of your data platform:

```
You (in claude.ai)
    ↓
claude.ai
    ├── Genie Knowledge MCP   (dev-apis.example.com/genie/mcp)
    │   KB context, lineage, glossary, DOMO metrics, event schemas,
    │   rendered pipeline SQL from MWAA, transform indexes
    │
    └── NP Data MCP           (np-apis.example.com/data-mcp)
        execute_query → Redshift (np + prd tables via datashare)
        DAG run status and task logs → MWAA
```

claude.ai uses the Knowledge MCP to understand *what* the data is and *how* it works, then uses the Data MCP to actually *query* it. You get grounded, accurate answers — not generic LLM responses.

### Connecting to claude.ai (Once per User)

1. Open **claude.ai** → **Settings** → **Connectors**
2. Click **Add connector** and enter the Knowledge MCP URL:
   ```
   https://dev-apis.example.com/genie/mcp
   ```
3. Click through the Okta sign-in popup (auto-closes if you're already logged in to Okta)
4. Repeat for the Data MCP URL:
   ```
   https://np-apis.example.com/data-mcp
   ```

After connecting, both appear as active connectors. You won't need to do this again — your session persists.

> The **Settings → Claude Integration** tab in Genie Tools has copy buttons for both URLs.

### What You Can Ask

Once connected, you can ask claude.ai anything about your data platform:

**Data queries:**
- "Show me daily cutting users by platform for the last 30 days"
- "What's the trial-to-paid conversion rate this week vs last week?"
- "How many users activated in the US in April?"

**Platform knowledge:**
- "What tables feed the onboarding KPI board?"
- "How is activation rate calculated?"
- "What downstream DAGs depend on `fact.cuts_session_master`?"

**Pipeline investigation:**
- "Show me the SQL that runs in TRANSFORM_DAG__onboard_metrics"
- "When did this DAG last succeed? What's the run duration trend?"
- "What changed in the onboarding pipeline last week?"

**Schema discovery:**
- "What columns are in `event.design_session`?"
- "Find all tables related to subscription cancellation"
- "What events fire when a user completes a project?"

### How claude.ai Uses Genie's Tools

claude.ai follows this pattern for data questions:

1. **Calls `get_data_platform_context`** (Genie Knowledge MCP) — gets top 40 tables with schemas, DOMO metrics, glossary definitions, common SQL patterns. This alone answers most questions without further tool calls.

2. **If more detail needed** — calls `search_tables`, `get_table_detail`, `get_transform_detail`, `glossary_lookup`, etc. (all from Genie Knowledge MCP).

3. **To run a query** — calls `execute_query` on the NP Data MCP. np Redshift is used for nonprod queries; prd tables are accessible via Redshift datashare from np.

4. **If KB has gaps** — falls back to `list_tables` + `list_columns` on Data MCP for live schema discovery, then writes SQL directly.

### System Prompt (Admin Setup — One Time)

An admin needs to add Genie's system prompt to the claude.ai Team settings (Settings → Account → System Prompt). This tells claude.ai how to use Genie's tools:

```
You have two MCP connections for your data platform:
- Genie Knowledge: business context, lineage, glossary, DOMO, event schemas, pipeline SQL
- NP Data: direct Redshift + MWAA access (prd tables available via datashare)

RULES:
1. Start every data question with get_data_platform_context (Genie Knowledge).
2. Use NP Data execute_query to run queries against Redshift.
3. If Genie Knowledge is unavailable, use NP Data list_tables + list_columns for schema
   discovery, then write SQL directly.
4. get_transform_detail returns the actual rendered SQL a pipeline runs.
5. Always use SELECT only. Never request data modifications.
```

---

## Part 2 — Genie Tools (genie.example.com)

Genie Tools is the web application for the data team's day-to-day work: the built-in chat, the team's SQL workspace, and its knowledge management system.

### Chat (`/`)

The default page. Ask a question and Genie streams an answer from the same principal + expert agents that back the MCP servers, showing each step of the investigation as it runs.

- **Action cards** — query results (with auto-charts), table detail, lineage, pipeline detail, and glossary definitions render inline under the answer
- **Sessions** — every conversation is saved and listed in the sidebar for 30 days. Double-click to rename, use the link icon to copy a read-only share URL, the X to delete
- **Attachments** — paperclip icon, for images (read directly) and documents (.txt/.md/.csv/.pdf/.docx, text extracted server-side)
- **Per-response actions** — copy, export to PDF, schedule as a recurring report, or create a task / request support

### Login

Navigate to `https://genie.example.com`. You'll be redirected to the login page.

**Sign in with Okta (recommended):** Click the "Sign in with Okta" button. You'll authenticate through the organization's Okta and be returned to Genie automatically.

**Email/Password (fallback):** Enter the email and password your admin provided.

First-time admin: login with your @example.com email and any password — it becomes your password.

### Requesting Access (New Users)

Click **Request Access** on the login page:
- **Email** must be `@example.com`
- Fill in your name, team, and reason for access
- An admin receives a notification and will approve or reject your request
- On approval, you get a `viewer` account with a temporary password

### Your Role

| Role | What you can do |
|------|----------------|
| **Viewer** | View glossary and lineage |
| **Analyst** | + run queries on nonprod, submit glossary definitions, browse repo files |
| **Engineer** | + run queries on prod, profile tables, review glossary, edit and commit code via git |
| **Admin** | + admin console, user management, analyze tables, merge glossary definitions |

To request a role change: Settings → **Request Role Change** → select role + provide reason → admin is notified.

---

### Workbench (SQL IDE)

Multi-tab SQL workspace with Git integration. This is where engineers write, run, and commit SQL.

- **Multiple tabs** — each with its own SQL, connection, and results
- **Schema Browser** — expand databases → schemas → tables → columns. Double-click to insert names.
- **Repo Files** — browse the data platform git repo. Click SQL files to open and run them.
- **Git Panel** — create branches, commit, push, create PRs — all from the app. Each user gets their own git worktree so branches are fully independent.
- **Optimize button** — AI analyzes your SQL and suggests improvements
- **Saved/Shared Queries** — Save any query to the team library (name, description, tags). Browse and reuse team queries from the Shared tab.
- **CSV Export** on results
- **Shortcuts**: `Cmd+Enter` to run, `Cmd+S` to save repo files

### Glossary

Business term definitions with PR-style review workflow. Source of truth for the organization's metric definitions.

- **AI Wizard** — AI asks 5 questions, synthesizes a definition from your answers
- **Document upload** — upload .txt, .md, .csv, .pdf, or .docx. AI extracts business terms and creates draft entries.
- **Review flow**: Draft → In Review → Approved → Merged (live)
- **Comments**: threaded, with @mention autocomplete (tagged users get notifications)
- **Source badges** — View SQL (blue), Redshift (green), Git Repo (orange), DOMO (purple), Document (amber)
- **Auto-generated entries** — from DOMO view SQL and MWAA pipeline analysis during KB builds

### Lineage

Visualize table dependencies across the entire data platform.

- Search any table → see upstream sources and downstream consumers
- **Tables** view: real schema.table references from executed SQL
- **DAGs** view: DAG-level dependencies
- **Depth controls**: +/- to show more/fewer levels (0–5)
- Click any node to navigate to that table's detail

### Tasks

Team task board for tracking data work.

- 8 task types: investigation, data_issue, dag_failure, ai_quality, kb_gap, glossary, request, general
- Priority levels: critical, high, medium, low
- 4 columns: Open → In Progress → Resolved → Closed
- Due dates + tags for organization
- Glossary tasks track per-entry review progress

### Reports

Scheduled report outputs. Each report is an AI-generated response that runs on a schedule.

- **Run Now** for manual trigger
- **Enable/Disable** toggle without deleting
- **Execution history** — last 7 runs with timestamp, status, duration
- Click any historical run to view its output
- You receive a notification when a report completes or fails

### Notifications

Bell icon in the header (polls every 30 seconds):
- **Scheduled Report** (blue) — report completed or failed
- **Task Assigned** (red) — task assigned to you
- **Glossary Assigned** (purple) — glossary entry assigned for review
- **Registration Request** (amber) — new user access request (admin-only)
- **KB Gap** (orange) — knowledge gap detected

### Settings

**Everyone sees:**
- **Claude Integration** — copy buttons for Knowledge MCP and Data MCP URLs + connection instructions
- **Persona**: Data Engineer, Analyst, ML Engineer, Executive, New Member
- **Git**: your git identity (name, email, GitHub token) for commits and PRs
- **Activity**: GitHub-style heatmap. Click any day to see detail (capability breakdown, tokens, cost)

**Engineers + Admins see:**
- **Knowledge Base**: trigger KB builds from MWAA (primary), Git Repo (secondary), Redshift
- **Agent Prompts**: view/edit sub-agent system prompts

**Admins also see:**
- **Connection**: AI Provider, Redshift credentials
- **Cost Explorer**: AI usage analytics (daily/weekly/monthly charts, model breakdown, user breakdown)
- **Table Ops**: profile, analyze, classify tables
- **Users**: add/edit/deactivate users, assign roles and teams

---

## Quick Reference

| I want to... | Use |
|---|---|
| Ask a question about your data | Genie Tools → Chat, OR claude.ai (with Genie MCP connected) |
| Query Redshift directly | Genie Tools → Chat or Workbench, OR claude.ai → ask for a query |
| Write and commit a new SQL transform | Genie Tools → Workbench |
| Look up a metric definition | Either chat ("how is X calculated?") OR Genie Tools → Glossary |
| See what feeds a table | Either chat ("what's upstream of X?") OR Genie Tools → Lineage |
| Review/approve glossary entries | Genie Tools → Glossary |
| Track a DAG failure | Either chat ("why did TRANSFORM_DAG__X fail?") + Genie Tools → Tasks |
| Share an answer with a teammate | Genie Tools → Chat → link icon on the session |
| Schedule a question to run daily | Genie Tools → Chat → clock icon on the response |
| View scheduled report outputs | Genie Tools → Reports |
| Connect Genie to claude.ai | Genie Tools → Settings → Claude Integration |

---

## Keyboard Shortcuts

| Shortcut | Where | Action |
|----------|-------|--------|
| `Cmd+Enter` | Workbench | Run query |
| `Cmd+S` | Workbench (repo file) | Save file |
| `Enter` | Search fields | Select first result |
