import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import config
from catalog.loader import KnowledgeBase

logger = logging.getLogger("genie")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=config.LOG_LEVEL)

    # Connect to postgres FIRST (needed for KB S3 config + everything else)
    dsn = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    app.state.db_pool = await asyncpg.create_pool(
        dsn, min_size=0, max_size=10,
        command_timeout=120,
        max_inactive_connection_lifetime=60,
    )
    logger.info("Database pool created")

    # Load KB S3 storage config from postgres, then download if configured
    try:
        kb_s3_row = await app.state.db_pool.fetchrow("""
            SELECT data->>'bucket' as bucket, data->>'prefix' as prefix
            FROM credential_cache WHERE cred_type = 'kb_s3_storage' AND expires_at > NOW() LIMIT 1
        """)
        if kb_s3_row and kb_s3_row["bucket"]:
            from connectors.kb_storage import configure as configure_kb_s3, download_kb_from_s3
            configure_kb_s3(kb_s3_row["bucket"], kb_s3_row["prefix"] or "knowledge/")
            result = download_kb_from_s3(config.KNOWLEDGE_DIR)
            s3_status = result.get("status", "?") if isinstance(result, dict) else str(result)
            logger.info("KB S3 sync: %s", s3_status)
    except Exception as e:
        logger.warning("KB S3 download skipped: %s", e)

    # Load knowledge base into memory
    kb = KnowledgeBase(config.KNOWLEDGE_DIR)
    kb.load()
    app.state.kb = kb

    # Load postgres-backed data (glossary, profiles, lineage) — these persist across restarts
    try:
        await kb.load_glossary_from_db(app.state.db_pool)
        await kb.load_table_profiles(app.state.db_pool)
        # Load lineage from postgres if file-based lineage is empty (S3 download failed)
        if not kb.lineage:
            await kb.load_lineage_from_db(app.state.db_pool)
    except Exception as e:
        logger.warning("Postgres KB data load partial failure: %s", str(e)[:200])

    logger.info(
        "Knowledge base loaded: %d tables, %d transforms, %d lineage, %d glossary terms",
        len(kb.catalog.get("tables", [])),
        len(kb.transforms_index),
        len(kb.lineage),
        len(kb.glossary),
    )

    # Share pool with search module (for semantic search) and auth module
    from catalog.search import set_db_pool as set_search_pool
    set_search_pool(app.state.db_pool)

    import api.users as _users_mod
    _users_mod._db_pool = app.state.db_pool

    # Generate embeddings for semantic search (background — don't block startup)
    async def _generate_embeddings_bg():
        try:
            from catalog.embeddings import generate_embeddings
            result = await generate_embeddings(kb, app.state.db_pool)
            logger.info("Embeddings: %s", result)
        except Exception as e:
            logger.warning("Embedding generation skipped: %s", str(e)[:200])
    asyncio.create_task(_generate_embeddings_bg())

    # Cancel any stuck jobs from previous run
    try:
        cancelled = await app.state.db_pool.execute(
            "UPDATE table_ops_jobs SET status = 'cancelled' WHERE status IN ('queued', 'running')"
        )
        if cancelled and cancelled != "UPDATE 0":
            logger.info("Cancelled stuck table ops jobs: %s", cancelled)
    except Exception:
        pass

    # Mark any KB builds stuck as "running" from a previous container as failed
    try:
        fixed = await app.state.db_pool.execute(
            "UPDATE kb_builds SET status = 'failed', error = 'Container restarted during build' WHERE status = 'running'"
        )
        if fixed and fixed != "UPDATE 0":
            logger.info("Marked stale KB builds as failed: %s", fixed)
    except Exception:
        pass

    # Migrate user_settings: add user_id column if missing
    try:
        await app.state.db_pool.execute("""
            ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS user_id TEXT
        """)
        # If user_id exists but isn't PK yet, create index
        await app.state.db_pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id)
        """)
    except Exception as e:
        logger.debug("user_settings migration: %s", e)

    # Ensure table_ownership exists on existing deployments (init.sql only runs on fresh volumes)
    try:
        await app.state.db_pool.execute("""
            CREATE TABLE IF NOT EXISTS table_ownership (
                id                  BIGSERIAL PRIMARY KEY,
                database            TEXT NOT NULL,
                schema_name         TEXT NOT NULL,
                table_name          TEXT NOT NULL,
                primary_owner       TEXT,
                secondary_owner     TEXT,
                business_area       TEXT,
                updated_by_user_id  BIGINT REFERENCES users(id),
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(database, schema_name, table_name)
            )
        """)
        await app.state.db_pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_table_ownership_db_schema ON table_ownership(database, schema_name)"
        )
    except Exception as e:
        logger.debug("table_ownership migration: %s", e)

    # Ensure feedback_comments exists on existing deployments
    try:
        await app.state.db_pool.execute("""
            CREATE TABLE IF NOT EXISTS feedback_comments (
                id          BIGSERIAL PRIMARY KEY,
                ticket_id   BIGINT NOT NULL REFERENCES feedback_tickets(id) ON DELETE CASCADE,
                author      TEXT NOT NULL,
                comment     TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await app.state.db_pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_comments_ticket ON feedback_comments(ticket_id, created_at)"
        )
    except Exception as e:
        logger.debug("feedback_comments migration: %s", e)

    # Set up credential persistence and restore saved credentials
    from connectors.credential_store import set_db_pool, restore_credentials_from_db, credential_store
    set_db_pool(app.state.db_pool)
    await restore_credentials_from_db(credential_store)
    logger.info("Credential store initialized")

    # Load glossary from postgres (approved/merged entries)
    await kb.load_glossary_from_db(app.state.db_pool)

    # Load table profiles from Table Ops (row counts, types, profile data)
    await kb.load_table_profiles(app.state.db_pool)

    # Load DOMO credentials from postgres (client_id/secret — never logged)
    try:
        domo_row = await app.state.db_pool.fetchrow("""
            SELECT data->>'client_id' as client_id, data->>'client_secret' as client_secret
            FROM credential_cache WHERE cred_type = 'domo_oauth' AND expires_at > NOW() LIMIT 1
        """)
        if domo_row and domo_row["client_id"] and domo_row["client_secret"]:
            from connectors.domo_client import configure as configure_domo
            configure_domo(domo_row["client_id"], domo_row["client_secret"])
            logger.info("DOMO client restored from credential cache")
    except Exception as e:
        logger.warning("Could not load DOMO credentials: %s", e)

    # Load Statsig API key from postgres
    try:
        statsig_row = await app.state.db_pool.fetchrow("""
            SELECT data->>'api_key' as api_key
            FROM credential_cache WHERE cred_type = 'statsig_api' AND expires_at > NOW() LIMIT 1
        """)
        if statsig_row and statsig_row["api_key"]:
            from catalog_engine.statsig_client import configure as configure_statsig
            configure_statsig(statsig_row["api_key"])
            logger.info("Statsig client restored from credential cache")
    except Exception as e:
        logger.warning("Could not load Statsig credentials: %s", e)

    # Load GitHub token from postgres (if set via UI, overrides .env)
    try:
        gh_row = await app.state.db_pool.fetchrow("""
            SELECT data->>'token' as token
            FROM credential_cache WHERE cred_type = 'github_token' AND expires_at > NOW() LIMIT 1
        """)
        if gh_row and gh_row["token"]:
            config.GITHUB_TOKEN = gh_row["token"]
            logger.info("GitHub token restored from credential cache")
    except Exception as e:
        logger.warning("Could not load GitHub token: %s", e)

    # Load REPO_URL from postgres (if set via UI, overrides .env)
    try:
        repo_row = await app.state.db_pool.fetchrow("""
            SELECT data->>'url' as url
            FROM credential_cache WHERE cred_type = 'repo_url' AND expires_at > NOW() LIMIT 1
        """)
        if repo_row and repo_row["url"]:
            config.REPO_URL = repo_row["url"]
            logger.info("REPO_URL restored from credential cache")
    except Exception as e:
        logger.warning("Could not load REPO_URL: %s", e)

    # Load agent prompt overrides from postgres
    from api.agent_prompts import load_overrides
    await load_overrides(app.state.db_pool)

    # Start background schedule runner (defaults to inactive)
    from catalog_engine.schedule_runner import start_schedule_runner
    await start_schedule_runner(app.state.db_pool)
    logger.info("Schedule runner started (inactive by default)")

    # Initialize MCP servers (GitHub, etc.)
    try:
        from engine.mcp_bridge import initialize as init_mcp, get_mcp_tools
        await init_mcp()
        mcp_tools = get_mcp_tools()
        if mcp_tools:
            # Add MCP tools to sub-agents (NOT principal — keep it lean)
            from engine.agents.tools import DATA_EXPERT_TOOLS, KNOWLEDGE_EXPERT_TOOLS

            # Filter: only useful tools, not all 26
            USEFUL_TOOLS = {"github__search_code", "github__get_file_contents",
                           "github__list_commits", "github__search_repositories"}

            for tool in mcp_tools:
                if tool["name"] not in USEFUL_TOOLS:
                    continue
                clean = {k: v for k, v in tool.items() if not k.startswith("_")}
                DATA_EXPERT_TOOLS.append(clean)
                if tool["name"] in ("github__search_code", "github__get_file_contents"):
                    KNOWLEDGE_EXPERT_TOOLS.append(clean)

            logger.info("MCP: %d GitHub tools registered (filtered to %d useful)",
                       len(mcp_tools), len(USEFUL_TOOLS))
        else:
            logger.info("MCP: no tools discovered (GitHub token may be missing)")
    except Exception as e:
        logger.warning("MCP initialization skipped: %s", e)

    # Wire KB into MCP server (must happen after KB is loaded)
    try:
        from mcp_server.server import set_kb as mcp_set_kb, set_db_pool as mcp_set_db_pool
        mcp_set_kb(kb)
        mcp_set_db_pool(app.state.db_pool)
        logger.info("MCP server: KB wired")
    except Exception as e:
        logger.warning("MCP KB wiring skipped: %s", e)

    # Start MCP session manager within FastAPI lifespan (required before requests arrive)
    try:
        from mcp_server.server import lifespan_context as _mcp_lifespan
        async with _mcp_lifespan():
            yield

            # Shutdown GitHub MCP bridge
            try:
                from engine.mcp_bridge import shutdown as shutdown_mcp
                await shutdown_mcp()
            except Exception:
                pass

            await app.state.db_pool.close()
            return  # early return — pool already closed inside the context manager
    except Exception as e:
        logger.warning("MCP lifespan skipped (%s) — running without MCP session manager", e)

    yield

    # Shutdown MCP servers
    try:
        from engine.mcp_bridge import shutdown as shutdown_mcp
        await shutdown_mcp()
    except Exception:
        pass

    await app.state.db_pool.close()


app = FastAPI(title="Jennie", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api import auth, chat, sql, pipeline, glossary, impact, catalog, meta, settings, history, glossary_wizard, activity, table_ops, glossary_review, connections, git_ide, users, agent_prompts, feedback, kb_repos, docs_api, notifications, scheduled_reports, okta_auth, saved_queries, table_ownership, events_dq, task_digest  # noqa: E402
from api import oauth  # noqa: E402
from catalog_engine import api as catalog_engine_api  # noqa: E402

app.include_router(meta.router, prefix="/api", tags=["meta"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(sql.router, prefix="/api/sql", tags=["sql"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(glossary.router, prefix="/api/glossary", tags=["glossary"])
app.include_router(impact.router, prefix="/api/impact", tags=["impact"])
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(glossary_wizard.router, prefix="/api/glossary", tags=["glossary-wizard"])
app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
app.include_router(events_dq.router, prefix="/api/events-dq", tags=["events-dq"])
app.include_router(catalog_engine_api.router, prefix="/api/catalog-engine", tags=["catalog-engine"])
app.include_router(table_ops.router, prefix="/api/table-ops", tags=["table-ops"])
app.include_router(table_ownership.router, prefix="/api/table-ownership", tags=["table-ownership"])
app.include_router(glossary_review.router, prefix="/api/glossary-review", tags=["glossary-review"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(git_ide.router, prefix="/api/git", tags=["git-ide"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(agent_prompts.router, prefix="/api/agent-prompts", tags=["agent-prompts"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(task_digest.router, prefix="/api/task-digest", tags=["task-digest"])
app.include_router(kb_repos.router, prefix="/api/kb-repos", tags=["kb-repos"])
app.include_router(docs_api.router, prefix="/api/docs", tags=["docs"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(scheduled_reports.router, prefix="/api/scheduled-reports", tags=["scheduled-reports"])
app.include_router(saved_queries.router, prefix="/api/saved-queries", tags=["saved-queries"])
app.include_router(okta_auth.router, prefix="/api/okta", tags=["okta"])

# OAuth 2.1 authorization server (for MCP) — routes at root level (not /api)
app.include_router(oauth.router, tags=["oauth"])

# Genie Knowledge MCP server — mounted at /mcp (Streamable HTTP)
try:
    from api.mcp_router import setup_mcp
    setup_mcp(app)
    logger.info("Genie Knowledge MCP server registered at /mcp")
except Exception as _mcp_err:
    logger.warning("MCP server setup skipped: %s", _mcp_err)
