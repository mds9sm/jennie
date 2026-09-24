# Lineage Build — Design & Implementation

How Genie builds its data lineage graph from MWAA task logs, repo configs, and runtime metadata.

## Architecture

Lineage is built during the KB build process (Airflow DAGs) and stored as `lineage.json`:

```
MWAA Task Logs ──┐
                 ├──→ mwaa_fetcher.py ──→ lineage dict ──┐
Repo YAML Configs ┘                                       ├──→ lineage.json
                                                          │
GenieKBBuildDAGTemplate.py ── merge + augment ────────────┘
```

## lineage.json Structure

```json
{
  "prd_dw.fact.cut_session_master": {
    "upstream": ["prd_dw.dim.user_profile", "prd_dw.dim.date", ...],
    "downstream": ["DOMO_REFRESH_DAG__cut_session_master__cut_session_master", ...]
  },
  "TRANSFORM_DAG__cuts_session_master__CutSessionsMasterDAG": {
    "upstream": ["events_v3__enriched"],
    "downstream": ["DOMO_REFRESH_DAG__cut_session_master__cut_session_master", ...]
  }
}
```

- **Keys**: `db.schema.table` for tables, DAG IDs for DAG-to-DAG lineage
- **Values**: `{upstream: string[], downstream: string[]}` — always both keys, always string arrays
- **Bidirectional**: if A is upstream of B, then B is downstream of A
- Used by: frontend LineageGraph (2 tabs: Tables, DAGs), agent tools (`get_table_lineage`), API (`/catalog/lineage`)

## Data Sources (Priority Order)

### 1. MWAA Rendered SQL (Primary — highest confidence)

**What**: Jinja2-resolved SQL from last successful task run. The actual executed query.

**How**: `mwaa_fetcher.py` fetches via:
- **Local mode** (same MWAA): Airflow ORM → `TaskLogReader` reads task logs from CloudWatch. Captures SQL from all tasks in multi-task DAGs (XCom only captured 1 of N tasks). Connection_id and TriggerDagRun edges extracted from the same logs.
- **Remote mode** (cross-env): REST API → task instance logs via `create_web_login_token`

**Extraction patterns** (from task logs):
- `Running statement: <SQL>` — 1,079 matches in prd MWAA (primary)
- `Executing: <SQL>` — 665 matches (secondary)
- Fallback: `CREATE|INSERT|SELECT|WITH` blocks > 50 chars

**Source tables** (upstream): Parsed from `FROM` / `JOIN` clauses
```
Regex: (?:FROM|JOIN)\s+(?:(\w+)\.)?(\w+)\.(\w+)
→ Captures: db.schema.table (3-part) or schema.table (2-part)
→ 2-part refs qualified using connection_id → database mapping
```

**Target tables** (what the DAG writes to): Parsed from `INSERT INTO` / `CREATE TABLE`
```
Regex: (?:INSERT INTO|CREATE TABLE ...)\s*(\w+\.\w+\.\w+)
→ Falls back to 2-part qualified with default_db from connection_id
→ Last resort: scan FROM/JOIN refs for bare target name to infer schema
→ Final fallback: bare name (resolved later via lineage remap)
```

**UNLOAD sources** (Redshift → S3 export): Parsed from `UNLOAD('SELECT ... FROM schema.table')`
```
→ Inner SELECT parsed for FROM/JOIN refs
→ Captured as upstream dependencies (DOMO reads FROM these tables)
```

**COPY targets** (S3 → Redshift ingestion): Parsed from `COPY schema.table FROM 's3://...'`
```
→ Captured as downstream write destinations
```

### 2. Database Inference from Airflow Connections

When SQL uses 2-part refs like `analytics.engagement_depth` (no database prefix), the database is inferred from the Airflow connection_id visible in task logs:

| Connection ID | Database |
|---|---|
| `redshift_default` / `redshift_dw` | `prd_dw` |
| `redshift_braze` | `prd_braze` |
| `redshift_board_kpi` | `prd_board_kpi` |
| `redshift_personalization` | `prd_personalization` |
| `redshift_data_lake` | `prd_data_lake` |
| `redshift_default_netspring` | `prd_netspring` |

Fallback chain: connection_id in logs → INSERT INTO target's db prefix → `prd_dw` default.

### 3. TriggerDagRunOperator (DAG-to-DAG runtime edges)

**What**: Live DAG trigger chains visible in MWAA task logs.

**How**: Task IDs named `TRIGGER_DAG_<child_dag>` or `task_trigger_<child_dag>` combined with `AIRFLOW_CTX_DAG_ID` for the parent.

```
Example: events_v3__enriched → TRANSFORM_DAG__cuts_session_master__CutSessionsMasterDAG
```

- **Remote mode**: Extracted from accumulated log text via regex
- **Local mode**: Extracted from task_id names in task_instance ORM query
- ~90 edges in prd MWAA, including ~9 not declared in any YAML config

### 4. Repo YAML `downstream_dags` (declared dependencies)

**What**: Explicit `downstream_dags` field in DAG YAML configs — corresponds to `TriggerDagRunOperator` usage.

**Where**: All config dirs: `transform/conf/`, `domo_refresh/conf/`, `events_v3/conf/`, `personalization/conf/`, etc.

```yaml
# transform/conf/cuts_session_master.yaml
CutSessionsMasterDAG:
  downstream_dags:
    - TRANSFORM_DAG__statsig_cuts_session_master__Statsig_Session_Master_DAG
    - DOMO_REFRESH_DAG__cut_session_master__cut_session_master
```

- **88 DAG-to-DAG edges** from 65 YAML configs
- Parsed by `repo_parser.py` (all config dirs) and `domo_parser.py` (domo_refresh + transform only)
- Both sources merged into lineage in `GenieKBBuildDAGTemplate.py`

### 5. DOMO downstream_dags (metric chain)

Same YAML field but specifically from `domo_refresh/conf/` — links transform outputs to DOMO refresh pipelines:

```
TRANSFORM → view SQL → UNLOAD to S3 → DOMO_REFRESH_DAG → DOMO dataset → dashboard
```

## DAG Types Processed

| DAG Type | Prefix | SQL? | Lineage Contribution |
|---|---|---|---|
| Transform | `TRANSFORM_DAG__` | Yes | INSERT INTO + FROM/JOIN (core lineage) |
| DOMO Refresh | `DOMO_REFRESH_DAG__`, `DOMO__` | Yes | UNLOAD sources (downstream of analytics tables) |
| DQ Sync | `DQ_SYNC__` | Yes | SELECT validation queries (np only, validates prd tables) |
| Events | `events_v3__` | Yes | COPY ingestion + trigger chains |
| Personalization | `personalization__`, `PERSONALIZATION_DAG__` | Yes | INSERT/UNLOAD for ML feature tables |
| Braze | `braze__`, `BRAZE_CURRENTS*` | Yes | COPY ingestion + INSERT transforms |
| Statsig | `statsig__`, `STATSIG_FEATURE_GATE_DAG__` | Yes | COPY feature gate data |
| Ingestion | `ingest_s3__`, `ingestion_pipelines__` | Some | COPY from S3 into stage tables |
| Subscriptions | `subscription_*` | Yes | INSERT transforms for subscription data |
| Other | (various) | Some | export_import, apple_sales, google, etc. |

**Metadata-only** (no SQL extraction): `ingest_sqs`, `extract`, `glue`

## Coverage (prd MWAA, Build #37 → #38 after task log fix)

| Metric | Build #37 (XCom) | Build #38 (Task Logs) |
|---|---|---|
| Total active DAGs | 321 | 331 |
| 3-part tables with upstream | 73 | **167** |
| 3-part tables with downstream | 163 | **461** |
| Total lineage keys | 499 | **800** |
| Bare table keys | 119 | **82** |
| np_dw pollution keys | many | **0** |

**Key improvement**: Switched from XCom `return_value` to `TaskLogReader` (CloudWatch) for SQL extraction in local/ORM mode. XCom only captured 1 of N tasks in multi-task DAGs (e.g., `udm_project_cuts` has 12 tasks but only `PREPARE_DELTA_DATA` pushed XCom). Task logs capture all tasks.

**Post-extraction remap**: Remaining bare/`.public.` keys are remapped to correct fully-qualified names using existing 3-part keys already in the lineage (e.g., bare `udm_project_cuts` → `prd_dw.fact.udm_project_cuts`). No catalog DB prefix mapping needed — `dw` and `prd_dw` are separate databases.

## Key Design Decisions

### Always `db.schema.table` format
All table references are fully qualified (e.g., `prd_dw.fact.cut_session_master`, not `fact.cut_session_master`). This prevents disconnected nodes when the same table appears with different prefixes. The database is inferred from:
1. The SQL itself (3-part refs)
2. Airflow connection_id in task logs
3. INSERT INTO target's database prefix
4. `prd_dw` as safe default (94% of targets)

### Bidirectional edges always
Every edge is written in both directions. If `A.upstream = [B]`, then `B.downstream = [A]`. This is enforced in `_build_lineage_edges()`.

### MWAA over repo for SQL lineage
Repo SQL has Jinja2 placeholders (`{{ params.database }}`). MWAA has the resolved, actually-executed SQL. Repo is used only for YAML metadata (schedule, tags, downstream_dags), never for SQL lineage.

### Two Airflow DAGs (cross-account)
- **PRD DAG** (5 AM UTC, deploys from `main`): Runs on prd MWAA, reads task logs via `TaskLogReader` (CloudWatch), extracts prd rendered SQL + Redshift SVV metadata → writes to `s3://dw-data-share-bucket/genie-kb/prd/`
- **NP DAG** (6 AM UTC, deploys from `stage`): Reads prd data from S3 + fetches np MWAA (local ORM) + enriches → writes to `s3://dev-kb-bucket/genie-kb/` → calls `POST /api/catalog-engine/reload-from-s3`

np can't access prd MWAA directly (cross-account). prd can't reach Genie postgres (cross-VPC).

### np lineage is filtered
Only `DQ_SYNC__` DAG lineage is included from np MWAA. All other np DAGs are dev/test noise that pollutes the production lineage graph with `np_dw.*` tables. `DQ_SYNC__` DAGs validate prd_* tables from nonprod (via datashare) — valuable for lineage even though they don't write data.

### Deployment: two PRs needed
- Changes to prd DAG behavior → PR to `main` (deploys to prd MWAA)
- Changes to np DAG behavior → PR to `stage` (deploys to np MWAA)
- Changes to both → two separate PRs

## Gaps & Future Work

### Current gaps
- **82 bare table keys** — DAG-to-DAG trigger edge names and tables not found in any existing 3-part lineage key (no catalog match). Most are trigger-based edges (expected).
- **CloudWatch log reads add ~30 min** to prd DAG runtime — 1225 task log reads across 331 DAGs. Acceptable for daily/weekly runs but not for on-demand builds.
- **Column-level lineage** — we know table-to-table, not column-to-column. Would require parsing SELECT column lists against target table DDL.
- **Redshift query logs** — `STL_QUERY` / `SVL_STATEMENTTEXT` could catch queries from non-MWAA sources (Glue, Lambda, ad-hoc). 2-7 day retention, high volume, needs heavy filtering. Not yet implemented.

### Testing lineage changes locally
Before deploying lineage changes to MWAA, validate against a local MWAA log dump:
1. Download task logs from MWAA (CloudWatch or the log dump script)
2. Parse with `_extract_sql_from_logs()`, `_extract_table_references()`, `_resolve_target_from_sql()` from `mwaa_fetcher.py`
3. Simulate `_build_lineage_edges()` and check key format, upstream/downstream counts
4. Compare against the current S3 lineage.json (download from `s3://dw-data-share-bucket/genie-kb/prd/lineage.json`)

### Future: Lineage Agent
A dedicated AI agent that maintains and improves lineage continuously:

1. **Intelligent SQL parsing** — use Claude to parse complex SQL (CTEs, subqueries, CASE expressions, dynamic SQL) that regex misses. Understand column-level transformations, not just table references.

2. **Cross-source reconciliation** — compare MWAA lineage vs repo YAML vs Redshift query logs. Flag discrepancies: "DAG X claims to read from table Y, but no query in STL_QUERY touched Y in the last 30 days."

3. **Impact analysis** — "If I change column Z in table A, which downstream DOMO dashboards break?" Requires column-level lineage + DOMO card → dataset → view → table chain.

4. **Lineage gap detection** — identify tables with no upstream (where does the data come from?) or no downstream (is anyone using this?). Auto-create KB gap tasks.

5. **Runtime lineage validation** — periodically compare declared lineage (from SQL parsing) against actual Redshift query logs. Surface phantom dependencies (declared but never queried) and shadow dependencies (queried but not declared).

6. **Natural language lineage queries** — "Show me everything that feeds the engagement KPI dashboard" → traces from DOMO dashboard → cards → datasets → views → source tables → upstream DAGs.

7. **Change impact preview** — before merging a PR that modifies a DAG config, the agent previews which downstream lineage paths are affected and who owns them.
