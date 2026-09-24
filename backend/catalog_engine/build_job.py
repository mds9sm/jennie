"""
Standalone KB build job — designed to run as a K8s Job container.

Connects to postgres, picks up the oldest queued kb_builds row, runs the build,
and exits. If no queued builds exist, exits immediately.

Usage:
    python -m catalog_engine.build_job

Required env vars:
    DATABASE_URL  — postgres connection string

Optional env vars (same as backend):
    GITHUB_TOKEN, REPO_URL, REPO_PATH, KNOWLEDGE_DIR,
    AI_PROVIDER, BEDROCK_REGION, BEDROCK_MODEL, BEDROCK_MODEL_FAST,
    AWS_PROFILE_NP, AWS_PROFILE_PRD, REDSHIFT_MODE, etc.
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("genie.build_job")


async def main():
    # Ensure backend directory is on sys.path for imports
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    import asyncpg
    from config import config

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Connect to postgres
    dsn = config.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    logger.info("Connecting to postgres...")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

    try:
        # Ensure table has progress column
        from catalog_engine.kb_tracker import ensure_table
        await ensure_table(pool)

        # Auto-clean stale builds stuck as "running" for over 2 hours
        cleaned = await pool.execute(
            "UPDATE kb_builds SET status = 'failed', error = 'Timed out (stuck >2h)' "
            "WHERE status = 'running' AND created_at < NOW() - INTERVAL '2 hours'"
        )
        cleaned_count = int(cleaned.split()[-1]) if cleaned else 0
        if cleaned_count:
            logger.info("Cleaned %d stale running builds", cleaned_count)

        # Find the oldest queued build
        row = await pool.fetchrow(
            "SELECT id, sources FROM kb_builds "
            "WHERE status = 'queued' "
            "ORDER BY created_at ASC LIMIT 1"
        )
        if not row:
            logger.info("No queued builds found — exiting.")
            return

        build_id = row["id"]
        sources_raw = row["sources"]
        sources = json.loads(sources_raw) if isinstance(sources_raw, str) else (sources_raw or {})

        logger.info("Picked up build #%d — sources: %s", build_id, sources)

        # Mark as running
        await pool.execute(
            "UPDATE kb_builds SET status = 'running' WHERE id = $1", build_id
        )

        # Build progress dict — synced to postgres by builder._sync_progress_to_db
        progress = {
            "status": "running",
            "phase": "starting",
            "errors": [],
            "build_id": build_id,
        }

        # Persist initial progress
        from catalog_engine.kb_tracker import update_build_progress
        await update_build_progress(pool, build_id, progress)

        start = time.time()

        try:
            # Restore build options from sources config
            include_mwaa = sources.get("mwaa", True)
            include_redshift = sources.get("redshift", False)
            session_id = sources.get("session_id")

            # Apply config overrides (same as api.py does)
            config._mwaa_envs = sources.get("mwaa_environments", ["np", "prd"])
            config._include_redshift = include_redshift
            config._redshift_environment = sources.get("redshift_environment", "np")
            config._enrichment_model = sources.get("enrichment_model", "opus")
            config._build_phases = sources.get("phases", [])

            # Restore credentials from postgres if available
            # Also share db_pool with credential_store for SSO refresh fallback
            from connectors.credential_store import credential_store as _cs
            _cs._db_pool = pool
            await _restore_credentials(pool, session_id, config)

            # Run the actual build
            from catalog_engine.builder import build_catalog
            stats = await build_catalog(
                config, pool,
                session_id=session_id,
                include_mwaa=include_mwaa,
                include_redshift=include_redshift,
                progress=progress,
            )

            elapsed = time.time() - start
            logger.info("Build #%d completed in %.1fs", build_id, elapsed)

            # complete_build is already called inside build_catalog when db_pool + build_id exist.
            # Update final progress to postgres.
            progress.update({"status": "success", "phase": "complete"})
            await update_build_progress(pool, build_id, progress)

            # Upload KB to S3 if configured (build_catalog already does this,
            # but we log it explicitly for job visibility)
            logger.info("Build #%d stats: %s", build_id, json.dumps(
                {k: v for k, v in stats.items() if k != "errors"}, default=str
            ))

        except Exception as e:
            elapsed = time.time() - start
            logger.exception("Build #%d failed after %.1fs", build_id, elapsed)

            # fail_build is already called inside build_catalog's except block,
            # but if the error happened before build_catalog ran, we need a fallback.
            try:
                current = await pool.fetchval(
                    "SELECT status FROM kb_builds WHERE id = $1", build_id
                )
                if current == "running":
                    from catalog_engine.kb_tracker import fail_build
                    await fail_build(pool, build_id, str(e), elapsed)
            except Exception:
                pass

            progress.update({"status": "error", "phase": "failed", "error": str(e)})
            await update_build_progress(pool, build_id, progress)

    finally:
        await pool.close()
        logger.info("Build job finished.")


async def _restore_credentials(pool, session_id: str | None, config):
    """Load all cached credentials from postgres for the build.

    In a K8s Job container, there's no in-memory credential store.
    We read from credential_cache (both global and session-scoped)
    and inject into config so connectors can authenticate.
    """
    try:
        # Load ALL non-expired credentials — global + session-specific
        rows = await pool.fetch(
            "SELECT session_id, environment, cred_type, data FROM credential_cache "
            "WHERE expires_at > NOW()"
        )
        for row in rows:
            cred_type = row["cred_type"]
            data = row["data"]
            if isinstance(data, str):
                data = json.loads(data)

            if cred_type == "github_token" and data.get("token"):
                config.GITHUB_TOKEN = data["token"]
                os.environ["GITHUB_TOKEN"] = data["token"]
                logger.info("Restored GitHub token")

            elif cred_type == "repo_url" and data.get("url"):
                config.REPO_URL = data["url"]
                logger.info("Restored REPO_URL: %s", data["url"])

            elif cred_type == "domo_oauth":
                if data.get("client_id") and data.get("client_secret"):
                    os.environ["DOMO_CLIENT_ID"] = data["client_id"]
                    os.environ["DOMO_CLIENT_SECRET"] = data["client_secret"]
                    logger.info("Restored DOMO credentials")

            elif cred_type == "statsig_api" and data.get("key"):
                os.environ["STATSIG_CONSOLE_API_KEY"] = data["key"]
                logger.info("Restored Statsig API key")

            elif cred_type == "kb_s3_storage" and data.get("bucket"):
                os.environ["KB_S3_BUCKET"] = data["bucket"]
                os.environ["KB_S3_PREFIX"] = data.get("prefix", "knowledge/")
                logger.info("Restored KB S3 storage: s3://%s/%s", data["bucket"], data.get("prefix", ""))

            elif cred_type == "redshift_direct":
                env = row["environment"]
                if data.get("user") and data.get("password"):
                    env_upper = env.upper()
                    os.environ[f"REDSHIFT_{env_upper}_USER"] = data["user"]
                    os.environ[f"REDSHIFT_{env_upper}_PASSWORD"] = data["password"]
                    if data.get("host"):
                        os.environ[f"REDSHIFT_{env_upper}_HOST"] = data["host"]
                    logger.info("Restored Redshift %s direct credentials", env)

            elif cred_type == "aws_sso":
                # Use LIVE AWS credentials already refreshed by the API pod's
                # schedule_runner (runs every 60s).  These are the actual
                # access-key / secret / session-token — no SSO refresh needed.
                env = row["environment"]
                try:
                    from connectors.credential_store import credential_store, AWSCredentials
                    creds = AWSCredentials.from_dict(data)
                    if not creds.is_expired:
                        session = credential_store.get_session(row["session_id"])
                        session.set_credentials(env, creds)
                        logger.info("Restored live SSO credentials for %s (session=%s, expires in %d min)",
                                    env, row["session_id"], creds.minutes_remaining)
                    else:
                        logger.warning("SSO credentials for %s already expired (session=%s)", env, row["session_id"])
                except Exception as e:
                    logger.warning("Failed to restore SSO credentials for %s: %s", env, e)

            elif cred_type == "sso_refresh":
                # SSO refresh tokens — kept as fallback but the API pod's
                # schedule_runner should have already refreshed aws_sso creds.
                # Skip attempting refresh in Job mode to avoid
                # InvalidGrantException from single-use refresh tokens.
                logger.info("Skipping sso_refresh for %s — using live aws_sso credentials instead",
                            row["environment"])

    except Exception as e:
        logger.warning("Could not restore credentials: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
