"""
Knowledge Base Loader — loads the split knowledge base structure:

  knowledge/
  ├── catalog.json          → Tables (name, schema, columns, description, distkey, sortkey)
  ├── transforms_index.json → DAG summaries (dag_id, target, schedule, sources, run stats)
  ├── lineage.json          → Full lineage graph (table → upstream/downstream)
  ├── glossary.yaml         → Business definitions
  ├── transforms/           → Per-DAG detail files (rendered SQL, task stats, run history)
  │   └── {dag_id}.json
  └── CLAUDE.md             → Platform context
"""

import json
import logging
from pathlib import Path

import yaml

logger = logging.getLogger("genie.catalog")


class KnowledgeBase:
    def __init__(self, knowledge_dir: str):
        self.knowledge_dir = Path(knowledge_dir)
        self.catalog: dict = {}            # tables only (lightweight)
        self.transforms_index: list = []   # transform summaries
        self.lineage: dict = {}            # full lineage graph
        self.metrics: list = []            # DOMO + view metric definitions
        self.metadata_dags: list = []      # non-SQL DAGs (schedule, owner, tasks)
        self.mwaa_environments: dict = {}  # MWAA environment metadata (class, config, versions)
        self.coverage: dict = {}           # KB coverage report
        self.glossary: dict = {}
        self.claude_md: str = ""
        self.table_profiles: dict = {}    # schema.table → {row_count, size_mb, type, profile_data}
        self.domo_catalog: list = []      # unified DOMO metrics catalog
        self.event_schemas: dict = {}     # event_name → {fields, field_count} from Swagger
        self.statsig: dict = {}           # experiments + feature gates from Statsig

    def load(self):
        self._load_catalog()
        self._load_transforms_index()
        self._load_lineage()
        self._load_metrics()
        self._load_event_schemas()
        self._load_statsig()
        self._load_metadata_dags()
        self._load_glossary()
        self._load_claude_md()

    def _load_catalog(self):
        path = self.knowledge_dir / "catalog.json"
        if path.exists():
            with open(path) as f:
                self.catalog = json.load(f)
            logger.info("Loaded catalog: %s", path)
        else:
            logger.warning("No catalog.json found at %s", path)
            self.catalog = {"tables": []}

    def _load_transforms_index(self):
        path = self.knowledge_dir / "transforms_index.json"
        if path.exists():
            with open(path) as f:
                self.transforms_index = json.load(f)
            logger.info("Loaded transforms index: %d entries", len(self.transforms_index))
        else:
            # Fall back to transforms in catalog.json (old format)
            self.transforms_index = self.catalog.get("transforms", [])
            if self.transforms_index:
                logger.info("Loaded transforms from catalog.json (legacy): %d entries", len(self.transforms_index))

    def _load_lineage(self):
        path = self.knowledge_dir / "lineage.json"
        if path.exists():
            with open(path) as f:
                self.lineage = json.load(f)
            logger.info("Loaded lineage: %d entries", len(self.lineage))
        else:
            # Fall back to lineage in catalog.json (old format)
            self.lineage = self.catalog.get("lineage", {})
            if self.lineage:
                logger.info("Loaded lineage from catalog.json (legacy): %d entries", len(self.lineage))

    def _load_metrics(self):
        path = self.knowledge_dir / "metrics.json"
        if path.exists():
            with open(path) as f:
                self.metrics = json.load(f)
            logger.info("Loaded metrics: %d entries", len(self.metrics))
        else:
            self.metrics = []

        # DOMO catalog — unified view linking refresh DAGs, views, S3 metadata, business context
        domo_path = self.knowledge_dir / "domo_catalog.json"
        if domo_path.exists():
            with open(domo_path) as f:
                raw = json.load(f)
            # Handle both formats: flat list or {"entries": [...], "stats": {...}}
            if isinstance(raw, dict) and "entries" in raw:
                self.domo_catalog = raw["entries"]
            elif isinstance(raw, list):
                self.domo_catalog = raw
            else:
                self.domo_catalog = []
            s3_enriched = sum(1 for m in self.domo_catalog
                             if isinstance(m, dict) and m.get("s3_metadata") and m["s3_metadata"].get("columns"))
            logger.info("Loaded DOMO catalog: %d metrics (%d with S3 data)", len(self.domo_catalog), s3_enriched)
        else:
            self.domo_catalog = []

    def _load_statsig(self):
        path = self.knowledge_dir / "statsig.json"
        if path.exists():
            with open(path) as f:
                self.statsig = json.load(f)
            logger.info("Loaded Statsig: %d experiments, %d gates",
                       self.statsig.get("experiment_count", 0), self.statsig.get("gate_count", 0))
        else:
            self.statsig = {}

    def _load_event_schemas(self):
        path = self.knowledge_dir / "event_schemas.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            self.event_schemas = data.get("events", {})
            logger.info("Loaded event schemas: %d events", len(self.event_schemas))
        else:
            self.event_schemas = {}

    def _load_metadata_dags(self):
        path = self.knowledge_dir / "metadata_dags.json"
        if path.exists():
            with open(path) as f:
                self.metadata_dags = json.load(f)
            logger.info("Loaded metadata DAGs: %d entries", len(self.metadata_dags))
        else:
            self.metadata_dags = []

        mwaa_env_path = self.knowledge_dir / "mwaa_environments.json"
        if mwaa_env_path.exists():
            with open(mwaa_env_path) as f:
                self.mwaa_environments = json.load(f)
            logger.info("Loaded MWAA environment metadata: %s", list(self.mwaa_environments.keys()))

        cov_path = self.knowledge_dir / "coverage.json"
        if cov_path.exists():
            with open(cov_path) as f:
                self.coverage = json.load(f)
            logger.info("Loaded KB coverage report")

    def get_view_detail(self, view_name: str) -> dict | None:
        """Load full view SQL definition on demand."""
        safe_name = view_name.replace("/", "_")
        path = self.knowledge_dir / "views" / f"{safe_name}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def _load_glossary(self):
        """Load glossary from postgres (merged entries) with yaml fallback."""
        self.glossary = {}
        # glossary.yaml is deprecated — glossary now lives in postgres glossary_entries
        # This will be populated by load_glossary_from_db() after db_pool is available
        path = self.knowledge_dir / "glossary.yaml"
        if path.exists():
            with open(path) as f:
                self.glossary = yaml.safe_load(f) or {}
            logger.info("Loaded glossary from yaml (fallback): %d terms", len(self.glossary))

    def _load_claude_md(self):
        path = self.knowledge_dir / "CLAUDE.md"
        if path.exists():
            self.claude_md = path.read_text()
            logger.info("Loaded CLAUDE.md: %d chars", len(self.claude_md))
        else:
            logger.warning("No CLAUDE.md found at %s", path)
            self.claude_md = "You are Genie, the organization's AI data platform assistant."

    def get_transform_detail(self, dag_id: str) -> dict | None:
        """Load full transform detail (rendered SQL, task stats, run history) on demand."""
        # Sanitize dag_id for filename
        safe_id = dag_id.replace("/", "_").replace("\\", "_")
        path = self.knowledge_dir / "transforms" / f"{safe_id}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    async def load_glossary_from_db(self, db_pool):
        """Load glossary entries from postgres — approved/merged are authoritative, drafts included with lower confidence."""
        try:
            rows = await db_pool.fetch("""
                SELECT term_key, term, definition, formula, source_tables, dimensions,
                       view_name, domo_dataset_id, workflow_state, confidence
                FROM glossary_entries
                WHERE workflow_state IN ('approved', 'merged', 'draft', 'in_review')
                  AND definition IS NOT NULL AND definition != ''
                ORDER BY
                    CASE workflow_state
                        WHEN 'merged' THEN 1
                        WHEN 'approved' THEN 2
                        WHEN 'in_review' THEN 3
                        WHEN 'draft' THEN 4
                    END,
                    term
            """)
            db_glossary = {}
            for r in rows:
                key = r["term_key"]
                # If we already have an approved/merged entry, skip the draft
                if key in db_glossary and db_glossary[key].get("status") in ("approved", "merged"):
                    continue
                sources = r["source_tables"]
                if isinstance(sources, str):
                    import json
                    sources = json.loads(sources)
                db_glossary[key] = {
                    "term": r["term"],
                    "definition": r["definition"],
                    "formula": r["formula"],
                    "source_tables": sources,
                    "view": r["view_name"],
                    "domo_dataset_id": r["domo_dataset_id"],
                    "status": r["workflow_state"],
                    "confidence": float(r["confidence"]) if r["confidence"] else 0.5,
                }
            if db_glossary:
                self.glossary = db_glossary
                merged = sum(1 for g in db_glossary.values() if g["status"] in ("approved", "merged"))
                drafts = sum(1 for g in db_glossary.values() if g["status"] == "draft")
                logger.info("Loaded glossary from postgres: %d entries (%d approved/merged, %d drafts)",
                           len(db_glossary), merged, drafts)
        except Exception as e:
            logger.warning("Could not load glossary from postgres: %s (using file fallback)", e)

    async def load_table_profiles(self, db_pool):
        """Load table profiles from table_registry (Table Ops discovery/profiling)."""
        try:
            rows = await db_pool.fetch("""
                SELECT schema_name, table_name, database, row_count, size_mb,
                       table_type_auto, last_analyzed_at, last_profiled_at, profile_data
                FROM table_registry
                WHERE row_count > 0 OR profile_data IS NOT NULL
                ORDER BY row_count DESC NULLS LAST
            """)
            profiles = {}
            for r in rows:
                key = f"{r['schema_name']}.{r['table_name']}"
                profile_data = r["profile_data"]
                if isinstance(profile_data, str):
                    profile_data = json.loads(profile_data)
                profiles[key] = {
                    "schema": r["schema_name"],
                    "table": r["table_name"],
                    "database": r["database"],
                    "row_count": r["row_count"],
                    "size_mb": float(r["size_mb"]) if r["size_mb"] else None,
                    "type": r["table_type_auto"],
                    "last_analyzed": r["last_analyzed_at"].isoformat() if r["last_analyzed_at"] else None,
                    "last_profiled": r["last_profiled_at"].isoformat() if r["last_profiled_at"] else None,
                    "profile": profile_data,
                }
            self.table_profiles = profiles
            if profiles:
                logger.info("Loaded table profiles: %d tables (%d with profile data)",
                           len(profiles), sum(1 for p in profiles.values() if p.get("profile")))
        except Exception as e:
            logger.warning("Could not load table profiles: %s", e)

    async def load_lineage_from_db(self, db_pool):
        """Load lineage from postgres lineage_cache — fallback when S3 files are missing."""
        try:
            await db_pool.execute("""
                CREATE TABLE IF NOT EXISTS lineage_cache (
                    table_key       TEXT PRIMARY KEY,
                    upstream        JSONB NOT NULL DEFAULT '[]',
                    downstream      JSONB NOT NULL DEFAULT '[]',
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            rows = await db_pool.fetch(
                "SELECT table_key, upstream, downstream FROM lineage_cache"
            )
            if not rows:
                return
            db_lineage = {}
            for r in rows:
                upstream = r["upstream"]
                downstream = r["downstream"]
                if isinstance(upstream, str):
                    upstream = json.loads(upstream)
                if isinstance(downstream, str):
                    downstream = json.loads(downstream)
                db_lineage[r["table_key"]] = {
                    "upstream": upstream,
                    "downstream": downstream,
                }
            if db_lineage:
                self.lineage = db_lineage
                logger.info("Loaded lineage from postgres: %d entries", len(db_lineage))
        except Exception as e:
            logger.warning("Could not load lineage from postgres: %s", e)

    async def save_lineage_to_db(self, db_pool):
        """Persist lineage to postgres lineage_cache after S3 reload."""
        if not self.lineage:
            return
        try:
            # Don't replace a healthy cache with a drastically smaller graph —
            # that means a broken KB build (e.g. prd data missing from S3), and
            # this cache is the fallback that survives the next pod restart.
            existing = await db_pool.fetchval("SELECT COUNT(*) FROM lineage_cache")
            if existing and len(self.lineage) < existing * 0.25:
                logger.error(
                    "Refusing to overwrite lineage_cache: new lineage has %d entries "
                    "vs %d cached — KB build likely lost its prd data",
                    len(self.lineage), existing,
                )
                return
            async with db_pool.acquire() as conn:
                # Clear old data and bulk insert
                await conn.execute("DELETE FROM lineage_cache")
                # Batch insert
                records = []
                for table_key, edges in self.lineage.items():
                    upstream = edges.get("upstream", [])
                    downstream = edges.get("downstream", [])
                    records.append((
                        table_key,
                        json.dumps(upstream),
                        json.dumps(downstream),
                    ))
                if records:
                    await conn.executemany(
                        "INSERT INTO lineage_cache (table_key, upstream, downstream) "
                        "VALUES ($1, $2::jsonb, $3::jsonb)",
                        records,
                    )
            logger.info("Saved lineage to postgres: %d entries", len(self.lineage))
        except Exception as e:
            logger.warning("Could not save lineage to postgres: %s", e)

    def reload(self):
        """Reload all knowledge files from disk."""
        self.load()
