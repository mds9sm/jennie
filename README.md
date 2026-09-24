# Jennie

AI-powered data engineering platform for the data team. Built by Sri Maru.

A web-based AI assistant that **knows** your data platform — every table, pipeline, metric, and dependency. It builds its knowledge from real sources (MWAA task logs, Git repo, Redshift metadata) and uses Claude to answer questions with full platform context.

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/your-org/jennie.git
cd jennie
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY at minimum

# 2. Start everything
docker compose up -d

# 3. Open
# Frontend: http://localhost:3333
# Backend:  http://localhost:8000
```

## What It Does

### Chat with Your Data Platform
Ask questions in natural language — Genie searches the catalog, generates SQL, looks up metrics, and traces lineage. Every answer is grounded in real metadata from your pipelines.

### Build Real Knowledge (not mock data)
Genie builds its knowledge base from three real sources:

| Source | What it provides | How |
|--------|-----------------|-----|
| **MWAA** (primary) | Rendered SQL, real table names, run durations, DAG status, lineage | Airflow REST API + task log parsing |
| **Git Repo** (secondary) | Who changed what, when, YAML config details, schedule/tags | Clone + git blame + YAML parsing |
| **Redshift** (optional) | Column names/types, distkeys, sortkeys, row counts | SVV_ALL_TABLES, SVV_ALL_COLUMNS |

### Table Operations
Discover, profile, and classify tables directly from the app:
- **Discover** — query Redshift system tables for all tables/views
- **Profile** — column-level stats (distinct count, cardinality, null rate, min/max) via nonprod datashare
- **Analyze** — update Redshift planner stats on prod
- **Auto-classify** — fact vs dimension from profile heuristics
- Sequential job queue with timeout, kill, and scheduling

### Security
- Redshift credentials encrypted in postgres, never logged, never in Claude's context
- Query safety guard blocks all non-SELECT/ANALYZE operations
- Per-user SSO authentication with credential persistence

## Architecture

```
Docker Compose (3 containers):
├── frontend/    → React 19 + Tailwind + Vite, served via nginx on :3333
├── backend/     → FastAPI + Claude API + Redshift connector on :8000
└── postgres     → Usage tracking, sessions, credentials, glossary on :5434

Knowledge Base (split for context efficiency):
├── catalog.json            → Tables only (~20K, always in Claude context)
├── transforms_index.json   → DAG summaries (~260K, compact in context)
├── lineage.json            → Dependency graph (~196K, available via tools)
├── transforms/             → Per-DAG detail files (~8.6M, loaded on demand)
│   └── {dag_id}.json       → Rendered SQL, task stats, run history
└── glossary.yaml           → Business definitions
```

## Tech Stack

- **Frontend**: React 19, TypeScript, Tailwind CSS, Vite, react-markdown, lucide-react
- **Backend**: FastAPI, Python 3.12, anthropic SDK, asyncpg, redshift_connector, boto3, rapidfuzz
- **AI**: Claude Sonnet 4 via Anthropic API (7 tools: search_tables, search_transforms, get_table_detail, get_transform_detail, get_table_lineage, glossary_lookup, execute_query)
- **DB**: PostgreSQL 16 (usage_events, chat_sessions, user_settings, glossary_feedback, table_registry, table_ops_jobs, credential_cache)
- **Auth**: AWS SSO device auth + direct Redshift credentials (Okta SAML planned)

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `REDSHIFT_MODE` | No | `mock` (default) or `real` |
| `REPO_URL` | No | Git repo URL for data platform transforms |
| `GITHUB_TOKEN` | No | GitHub PAT with repo scope (needs SAML SSO authorization for your-org org) |
| `AWS_PROFILE_NP` / `AWS_PROFILE_PRD` | No | AWS SSO profiles from ~/.aws/config |

Redshift credentials can also be configured in-app via **Settings > Connection** (stored encrypted in postgres).

## Navigation

| Page | Purpose |
|------|---------|
| **Chat** | AI-powered Q&A about the data platform |
| **Query Runner** | Write and execute SQL against Redshift |
| **SQL Optimizer** | Paste SQL → get optimization suggestions |
| **Pipeline Builder** | Describe in NL → generates YAML + SQL configs |
| **Definitions** | Search the business glossary |
| **Glossary Review** | Expert review of auto-generated metric definitions |
| **Lineage** | Interactive table dependency visualization |
| **Impact Analysis** | Describe a change → see downstream impact |
| **Activity** | GitHub-style usage heatmap |

| Admin Console | Purpose |
|---------------|---------|
| **Connection** | AI provider (Anthropic/Bedrock), AWS SSO, Redshift credentials |
| **Knowledge Base** | Build catalog from MWAA + Git repo, toggle sources, live progress |
| **Table Ops** | Discover, PROFILE, ANALYZE, column profiles, schedules with runner toggle |

| Settings | Purpose |
|----------|---------|
| **Persona** | Engineer, Analyst, ML Engineer, New Member — adapts response style |
| **System Prompt** | Custom rules injected into every AI call |
| **User Context** | Personal context (team, focus area) with AI compression |

## Key Directories

```
backend/
├── api/              → FastAPI routers (chat, sql, pipeline, glossary, impact, settings, auth, table_ops)
├── engine/           → Claude client, context builder, pillar definitions, tools
├── catalog/          → Knowledge base loader, fuzzy search, lineage traversal
├── catalog_engine/   → Catalog refresh: repo_cloner, repo_parser, mwaa_fetcher, builder, table_ops
├── connectors/       → Redshift (direct/IAM/SSO), mock Redshift, credential store, okta_mfa
├── tracking/         → Usage event logging + cost estimation
└── knowledge/        → Split knowledge base, glossary, platform context, fixtures

frontend/src/
├── api/              → Fetch client with SSE streaming
├── context/          → React contexts: Pillar, Environment, Auth
├── components/
│   ├── chat/         → ChatView, MessageBubble, SQLCard, DefinitionCard, PipelineCard, ImpactCard, LineageCard
│   ├── sql/          → QueryRunner, SQLOptimizer
│   ├── pipeline/     → PipelineBuilder
│   ├── glossary/     → DefinitionLookup, GlossaryWizard
│   ├── impact/       → ImpactAnalysis
│   ├── activity/     → ActivityPage (GitHub-style heatmap)
│   ├── settings/     → SettingsPage, ConnectionTab, KnowledgeBaseTab, TableOpsTab, PersonaTab, ...
│   ├── layout/       → Header, Sidebar, MainLayout
│   └── common/       → ResultsTable, SSOConnectModal
└── types/            → TypeScript interfaces
```

## Building the Knowledge Base

1. **Connect SSO** — Settings > Connection > Connect SSO for nonprod and/or prod
2. **Build** — Settings > Knowledge Base > check MWAA + Git Repo > Build Knowledge Base
3. **Wait** — MWAA fetch processes ~160 DAGs, extracts SQL from task logs (~15 min)
4. **Result** — catalog.json, transforms_index.json, lineage.json, and per-DAG detail files

The knowledge base is built as a **background batch job** with live progress in the UI.

## Table Operations

1. **Add Redshift credentials** — Settings > Connection > Redshift Credentials
2. **Discover** — Settings > Table Ops > Discover from Redshift (select environment, databases, schemas)
3. **Profile** — Select tables > PROFILE (runs on nonprod via datashare, captures column-level stats)
4. **Analyze** — Select tables > ANALYZE (runs on prod, updates planner stats — needs prod credentials)

All operations run **sequentially, never in parallel**, with configurable timeout and kill capability.

## the organization-Specific Context

- **9 Pillars**: Onboard, Trigger Return, Makeable Content, Content Matching, Design & Make, Guided Flows, Blank Canvas, Marketing, Platform
- **Redshift**: nonprod-redshift-cluster (111111111111), prod-redshift-cluster (222222222222)
- **MWAA**: nonprod-airflow-mwaa (nonprod), prod-airflow-mwaa (prod)
- **DAG prefixes**: `TRANSFORM_DAG__` (pipelines), `DOMO__` (dashboard exports), `dw_sync__` (DQ validation)
- **Data Platform Repo**: `your-org/data-platform-dags` — YAML configs + SQL for all DAGs

## Development

```bash
# Rebuild after code changes
docker compose build && docker compose up -d

# View logs
docker compose logs backend --tail 50 -f

# Fresh database (drops all data)
docker compose down && docker volume rm jennie_pgdata && docker compose up -d

# Backend runs with --reload (auto-restarts on file changes)
# Frontend needs rebuild: docker compose build frontend && docker compose up -d frontend
```

## License

Internal the organization tool. Not for external distribution.
