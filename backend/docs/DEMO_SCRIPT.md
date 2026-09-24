# Jennie — Demo Script

**Duration**: ~15 minutes
**Audience**: Engineering leadership
**Goal**: Show how Genie replaces 5+ tools (DOMO, DataGrip, Airflow UI, GitHub, Slack) with one AI-powered interface

---

## 1. The Problem (1 min)

"Today, to answer a simple question like 'why are cutting numbers down this week', an engineer needs to:
- Check DOMO dashboards for the numbers
- Open DataGrip to query Redshift
- Check Airflow to see if a pipeline failed
- Search GitHub for the SQL logic
- Slack the pillar lead to understand the metric definition

Genie does all of this in one conversation."

---

## 2. Quick Data Query (2 min) — Speed Demo

**Ask**: "Show me daily cutting users by platform for this week"

**What to show**:
- Genie classifies this as a DATA question (no expert delegation)
- Agent already KNOWS the schema inline (top 40 tables with columns) — no search needed
- Writes SQL on first tool call → execute → chart rendered
- Results appear as auto-rendered chart (charts-first UX — always expanded, no collapsible wrapper)
- Total time: **~10 seconds** (1 tool call)
- Token cost shown at bottom: ~$0.03 (Sonnet pricing)

**Talking point**: "The agent has the organization's schema built into every conversation — top 40 tables with columns, metrics, glossary definitions. It writes SQL on the first tool call instead of searching. This query took 10 seconds and one tool call."

---

## 3. Metric Deep Dive (3 min) — DOMO Integration

**Ask**: "Tell me about engagement depth metrics"

**What to show**:
- Genie classifies as METRIC — combines definition + live data
- Looks up view SQL (the actual metric calculation)
- Shows source tables, DOMO dataset link
- Analyzes DOMO S3 data directly (no Redshift load)
- Auto-renders chart from the pre-aggregated data

**Talking point**: "Genie reads the same data that feeds DOMO dashboards, but shows you the calculation logic too. Engineers see SQL, analysts see charts, execs see impact — same question, adapted by persona."

---

## 3b. DOMO Dashboard Exploration (2 min) — DOMO REST API

**Ask**: "What dashboards does the Onboard pillar have in DOMO? Show me the KPIs on the activation dashboard."

**What to show**:
- Genie calls domo_dashboards to list all pages
- Filters to Onboard pillar dashboards
- Calls domo_dashboard_detail to get cards (KPIs)
- Shows card names, dataset links, owner info
- Cross-references with view SQL to show calculation logic
- Full hierarchy: Page → Cards → Datasets

**Talking point**: "Genie now has direct read-only access to DOMO's full structure — dashboards, cards, datasets, streams. Same credentials as Airflow, strictly read-only. For actual data analysis, it uses DOMO's S3 exports with DuckDB — zero load on DOMO or Redshift."

---

## 4. Pipeline Investigation (2 min) — Multi-Agent

**Ask**: "Is the CutSessionsMasterDAG healthy? Any recent failures?"

**What to show**:
- Genie classifies as INVESTIGATION → delegates to Data Expert
- Investigation trail shows: "Consulting Data Expert" → searching transforms → checking MWAA → reading run history
- Returns: DAG status, last 10 runs, success rate, schedule, downstream DOMO dashboards affected
- Citations at the bottom (DAG, Table, View)

**Talking point**: "The Data Expert agent has access to MWAA, S3, CloudWatch, GitHub — all through SSO. It checks live AWS state, not just cached metadata."

---

## 5. Business Definitions (1 min) — Knowledge Expert

**Ask**: "What is activation rate? How is it different across pillars?"

**What to show**:
- Quick answer: ~20 seconds
- Definition with formula, source table, pillar-specific variations
- KB gap detection if something is missing
- Glossary source badges (View SQL, Redshift, Repo)

**Talking point**: "Every term has provenance — you know if it came from SQL, a human review, or AI inference."

---

## 5b. Statsig Experiments (1 min) — New Integration

**Ask**: "What experiments are running for the Onboard pillar? Show me exposure data for the latest one."

**What to show**:
- Genie looks up active experiments from Statsig Console API
- Filters by pillar, shows experiment config (groups, allocation %)
- Writes SQL against prd_statsig exposure tables for segmentation
- Cross-references with DOMO metrics for outcome measurement

**Talking point**: "Statsig experiment metadata is now in the knowledge base. Engineers can go from 'what experiments exist?' to 'show me the exposure data' in one question."

---

## 6. Workbench (2 min) — Quick Tour

**Show**:
- Multi-tab SQL editor with schema browser
- Repo file browser (right-click: new file, rename, delete)
- Git panel: branch, commit, push, create PR — all in-app
- Optimize button (sends SQL to AI for analysis)
- **Saved/Shared Queries**: Save to Library button → name, description, tags. Open the Shared tab → browse team queries, search by name/tag/SQL content. Click any saved query to open and run it. Show usage tracking (run count, last used).
- **PDF Export**: Click the download icon on any chat response → full PDF with charts and tables

**Talking point**: "Engineers don't need to switch to DataGrip or GitHub Desktop. Feature branch workflow built in. The team query library means no more 'can you Slack me that query?' — save it, tag it, and everyone can find and reuse it."

---

## 7. Glossary Review (1 min) — PR-Style

**Show**:
- Draft entries auto-generated from view SQL + AI enrichment
- PR-style flow: draft → review → approve → merge
- Source badges on each entry
- Document upload (PDF/DOCX → AI extracts terms)

**Talking point**: "We're building a living glossary. AI generates drafts, humans review and approve. Every definition links back to its source."

---

## 7b. Event Schema Lookup (1 min) — Swagger Integration

**Ask**: "What fields does the cut_complete event have? Write me a query to count cuts by material type this week."

**What to show**:
- Genie calls `get_event_schema` to look up cut_complete from 558 Swagger event definitions
- Shows payload fields with types
- Writes precise SQL against firehose_v3_enriched SUPER columns using exact field paths
- No guessing about nested JSON structure

**Talking point**: "558 ProductApp event schemas from the Swagger spec. No more guessing at SUPER column field names — the agent knows every payload field."

---

## 8. Admin / Operations (2 min) — Cost & Activity

**Show**:
- **Cost Explorer**: Stacked bar chart by model (Opus vs Sonnet). Show the cost drop after tiered models.
- **Activity Heatmap**: Click a day → model breakdown, capability breakdown
- **Task Board**: Auto-created tasks from KB gaps and chat flags
- **KB Build History**: Show build #9 with S3 DOMO enrichment step

**Talking point**: "Full visibility into AI spend. We reduced cost per question from ~$0.50 to ~$0.07 by using Sonnet for routing and Opus only for complex synthesis."

---

## 9. Architecture Slide (1 min)

```
User Question
    ↓ classify
Principal Agent (Sonnet + rich inline KB context ~6K)
    ├── DATA → write SQL from inline schema → execute (1 tool call, ~10s)
    ├── METRIC → inline DOMO metrics + DOMO S3 analysis (~15s)
    ├── DEFINITION → inline glossary → reply directly (~3s)
    ├── INVESTIGATION → Data Expert deep dive (1-2 min)
    └── CONVERSATIONAL → reply (3s)

Inline KB context (compiled per-request by context.py):
    Top 40 tables with columns | Top 25 DOMO metrics
    Top 20 glossary definitions | Active experiments
    Common SQL patterns (cuts, DAU, subscriptions)
```

---

## Key Numbers

| Metric | Before | After |
|--------|--------|-------|
| Simple query response | 2 min | **~10s** (1 tool call with inline schema) |
| Definition lookup | 35s | **~3s** (inline glossary, no agent call) |
| Conversational | 8s | **3s** |
| Cost per question | $0.50-1.00 | **$0.03-0.10** |
| Knowledge sources | MWAA only | MWAA + Repo + Redshift + S3 + DOMO + Swagger + Statsig + AI |
| Metrics tracked | 0 | **167** (103 with DOMO links) |
| Event schemas | 0 | **558** (from Swagger spec) |
| Tables profiled | 0 | **668** (15K columns across 7 prd_* databases) |
| Agent tools | 8 | **21** (+ 4 MCP + 4 DOMO + 2 event schema) |

---

## Questions to Anticipate

**"What about data security?"**
- Read-only access (SELECT only, enforced at connection level)
- Credentials encrypted in postgres, never in AI context
- Per-user isolation (sessions, git worktrees, settings)
- Okta OIDC for authentication

**"How much does this cost to run?"**
- ~$0.05-0.15 per question with tiered models
- Cost Explorer shows real spend per user, per day, per model
- Token budget caps prevent runaway costs (150K tokens max per question)

**"What if the AI gives wrong answers?"**
- Every answer cites sources (table, DAG, view, query)
- Flag button on every response → creates task for review
- KB gap detection surfaces what's missing
- Glossary review ensures human-vetted definitions

**"Can we add more data sources?"**
- DOMO already integrated — direct REST API (read-only) for metadata, S3/DuckDB for data analysis
- Statsig integrated — Console API (read-only) for experiments and feature gates
- 558 ProductApp event schemas from Swagger spec
- Architecture supports any MCP-compatible tool
- KB build is extensible (toggleable sources, scheduled daily/weekly/monthly)
