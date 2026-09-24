"""
Schedule Runner — background task that checks and executes scheduled operations.

Runs as an asyncio task started at app startup. Checks every 60 seconds for
due schedules. Executes KB builds and table profile jobs sequentially.

Controlled by a global active/inactive toggle stored in postgres.
Defaults to INACTIVE — must be explicitly activated.
"""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("genie.schedule_runner")

_runner_task: asyncio.Task | None = None
_runner_active: bool = False


def _parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into a set of valid values."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(min_val, max_val + 1))
        elif "/" in part:
            base, step = part.split("/", 1)
            start = min_val if base == "*" else int(base)
            for v in range(start, max_val + 1, int(step)):
                values.add(v)
        elif "-" in part:
            lo, hi = part.split("-", 1)
            values.update(range(int(lo), int(hi) + 1))
        else:
            values.add(int(part))
    return values


def cron_matches_now(cron_expr: str, now: datetime = None) -> bool:
    """Check if a cron expression matches the current time (minute precision)."""
    if not now:
        now = datetime.now(timezone.utc)

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False

    minute, hour, dom, month, dow = parts
    try:
        return (
            now.minute in _parse_cron_field(minute, 0, 59)
            and now.hour in _parse_cron_field(hour, 0, 23)
            and now.day in _parse_cron_field(dom, 1, 31)
            and now.month in _parse_cron_field(month, 1, 12)
            and now.weekday() in _parse_cron_field(dow, 0, 6)  # 0=Monday in Python
        )
    except (ValueError, TypeError):
        return False


async def _ensure_toggle_table(db_pool):
    """Ensure the schedule_runner_config table exists."""
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS schedule_runner_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # Default to inactive
    await db_pool.execute("""
        INSERT INTO schedule_runner_config (key, value)
        VALUES ('active', 'false')
        ON CONFLICT (key) DO NOTHING
    """)


async def is_runner_active(db_pool) -> bool:
    """Check if the schedule runner is active."""
    try:
        row = await db_pool.fetchrow(
            "SELECT value FROM schedule_runner_config WHERE key = 'active'"
        )
        return row and row["value"] == "true"
    except Exception:
        return False


async def set_runner_active(db_pool, active: bool):
    """Set the schedule runner active/inactive."""
    await db_pool.execute("""
        INSERT INTO schedule_runner_config (key, value, updated_at)
        VALUES ('active', $1, NOW())
        ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()
    """, "true" if active else "false")


async def _check_and_run_schedules(db_pool):
    """Check for due schedules and execute them."""
    now = datetime.now(timezone.utc)

    rows = await db_pool.fetch("""
        SELECT id, operation, schema_name, table_name, cron_expression, timeout_seconds
        FROM table_ops_schedules
        WHERE enabled = true
    """)

    for row in rows:
        if not cron_matches_now(row["cron_expression"], now):
            continue

        # Check if already ran this minute (prevent double execution)
        last_run = await db_pool.fetchval(
            "SELECT last_run_at FROM table_ops_schedules WHERE id = $1", row["id"]
        )
        if last_run and (now - last_run).total_seconds() < 120:
            continue

        logger.info(
            "Schedule %d triggered: %s %s.%s",
            row["id"], row["operation"],
            row.get("schema_name", "*"), row.get("table_name", "*"),
        )

        # Update last_run
        await db_pool.execute(
            "UPDATE table_ops_schedules SET last_run_at = NOW() WHERE id = $1",
            row["id"],
        )

        # Queue the jobs
        if row["schema_name"] and row["table_name"]:
            # Single table
            await db_pool.execute("""
                INSERT INTO table_ops_jobs (operation, schema_name, table_name, environment, timeout_seconds)
                VALUES ($1, $2, $3, $4, $5)
            """, row["operation"], row["schema_name"], row["table_name"],
                "prd" if row["operation"] == "analyze" else "np",
                row["timeout_seconds"])
        elif row["schema_name"]:
            # All enabled tables in schema
            flag = "analyze_enabled" if row["operation"] == "analyze" else "profile_enabled"
            tables = await db_pool.fetch(
                f"SELECT schema_name, table_name, database FROM table_registry WHERE schema_name = $1 AND {flag} = true",
                row["schema_name"],
            )
            for t in tables:
                await db_pool.execute("""
                    INSERT INTO table_ops_jobs (operation, schema_name, table_name, database, environment, timeout_seconds)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, row["operation"], t["schema_name"], t["table_name"], t["database"],
                    "prd" if row["operation"] == "analyze" else "np",
                    row["timeout_seconds"])
        else:
            # All enabled tables
            flag = "analyze_enabled" if row["operation"] == "analyze" else "profile_enabled"
            tables = await db_pool.fetch(
                f"SELECT schema_name, table_name, database FROM table_registry WHERE {flag} = true",
            )
            for t in tables:
                await db_pool.execute("""
                    INSERT INTO table_ops_jobs (operation, schema_name, table_name, database, environment, timeout_seconds)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, row["operation"], t["schema_name"], t["table_name"], t["database"],
                    "prd" if row["operation"] == "analyze" else "np",
                    row["timeout_seconds"])

        # Start the job runner if not already running
        from catalog_engine.table_ops import start_job_runner, _runner_task as job_runner
        if not job_runner or job_runner.done():
            await start_job_runner(db_pool)


async def _check_and_run_reports(db_pool):
    """Check for due scheduled reports and execute them."""
    now = datetime.now(timezone.utc)

    try:
        rows = await db_pool.fetch("""
            SELECT * FROM scheduled_reports WHERE enabled = true
        """)
    except Exception:
        # Table may not exist yet
        return

    for row in rows:
        if not cron_matches_now(row["cron_expression"], now):
            continue

        # Prevent double execution (same as schedule logic)
        last_run = row.get("last_run_at")
        if last_run and (now - last_run).total_seconds() < 120:
            continue

        logger.info("Scheduled report #%d triggered: %s", row["id"], row["title"])

        from api.scheduled_reports import _execute_report
        import asyncio
        asyncio.create_task(_execute_report(db_pool, dict(row)))


def _auto_refresh_sso_sync():
    """Blocking SSO refresh (boto3 network calls). Must run in a worker thread."""
    try:
        from connectors.credential_store import credential_store, get_sso_refresh, AWSCredentials
        import boto3
        from botocore.config import Config as BotoConfig

        for env in ("np", "prd"):
            refresh_data = get_sso_refresh(env)
            if not refresh_data:
                continue

            # Check if any session has this env's creds expiring soon
            for sid, session in credential_store._sessions.items():
                creds = session.credentials.get(env)
                if creds and creds.minutes_remaining < 10 and creds.minutes_remaining > 0:
                    logger.info("SSO %s expires in %d min — auto-refreshing", env, creds.minutes_remaining)

                    try:
                        oidc = boto3.client("sso-oidc", config=BotoConfig(region_name="us-west-2"))
                        token_resp = oidc.create_token(
                            clientId=refresh_data["client_id"],
                            clientSecret=refresh_data["client_secret"],
                            grantType="refresh_token",
                            refreshToken=refresh_data["refresh_token"],
                        )

                        access_token = token_resp["accessToken"]
                        new_refresh = token_resp.get("refreshToken")
                        if new_refresh:
                            refresh_data["refresh_token"] = new_refresh

                        sso = boto3.client("sso", config=BotoConfig(region_name="us-west-2"))
                        role_resp = sso.get_role_credentials(
                            roleName=refresh_data["role_name"],
                            accountId=refresh_data["account_id"],
                            accessToken=access_token,
                        )
                        role_creds = role_resp["roleCredentials"]

                        new_creds = AWSCredentials(
                            access_key_id=role_creds["accessKeyId"],
                            secret_access_key=role_creds["secretAccessKey"],
                            session_token=role_creds["sessionToken"],
                            expires_at=role_creds["expiration"] / 1000,
                            account_id=refresh_data["account_id"],
                            role_name=refresh_data["role_name"],
                            profile=env,
                        )
                        credential_store.set_credentials(sid, env, new_creds)
                        logger.info("SSO %s auto-refreshed for %s (%d min remaining)", env, sid, new_creds.minutes_remaining)
                    except Exception as e:
                        logger.warning("SSO auto-refresh failed for %s: %s", env, e)
    except Exception as e:
        logger.debug("SSO auto-refresh check: %s", e)


async def _auto_refresh_sso():
    """Auto-refresh SSO credentials 10 minutes before expiry using refresh token."""
    try:
        # boto3 calls are blocking — run off the event loop with a hard bound
        # so a stalled AWS call can't freeze the schedule runner (or the app).
        await asyncio.wait_for(asyncio.to_thread(_auto_refresh_sso_sync), timeout=120)
    except asyncio.TimeoutError:
        logger.warning("SSO auto-refresh timed out")
    except Exception as e:
        logger.debug("SSO auto-refresh check: %s", e)


async def _check_kb_build_schedule(db_pool):
    """Check if a scheduled KB build is due and trigger it."""
    now = datetime.now(timezone.utc)
    try:
        row = await db_pool.fetchrow(
            "SELECT value FROM schedule_runner_config WHERE key = 'kb_build_cron'"
        )
        if not row or not row["value"]:
            return

        cron_expr = row["value"]
        if not cron_matches_now(cron_expr, now):
            return

        # Check last build time to prevent double execution
        last_row = await db_pool.fetchrow(
            "SELECT value FROM schedule_runner_config WHERE key = 'kb_build_last_run'"
        )
        if last_row and last_row["value"]:
            try:
                last_run = datetime.fromisoformat(last_row["value"])
                if (now - last_run).total_seconds() < 3600:  # Don't rebuild within 1 hour
                    return
            except Exception:
                pass

        # Check if a build is already running
        from catalog_engine.api import _build_task
        if _build_task and not _build_task.done():
            return

        logger.info("Scheduled KB build triggered (cron: %s)", cron_expr)

        # Update last run time
        await db_pool.execute("""
            INSERT INTO schedule_runner_config (key, value, updated_at)
            VALUES ('kb_build_last_run', $1, NOW())
            ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()
        """, now.isoformat())

        # Trigger build
        from config import config
        config._mwaa_envs = ["np", "prd"]
        config._include_redshift = True
        config._enrichment_model = "sonnet"
        config._build_phases = []  # all phases

        from catalog_engine.builder import build_catalog
        import asyncio
        from catalog_engine.api import _build_progress
        asyncio.create_task(build_catalog(config, db_pool, progress=_build_progress))

    except Exception as e:
        logger.debug("KB build schedule check: %s", e)


async def start_schedule_runner(db_pool):
    """Start the background schedule checker. Runs every 60 seconds."""
    global _runner_task

    if _runner_task and not _runner_task.done():
        return

    await _ensure_toggle_table(db_pool)

    async def _run():
        logger.info("Schedule runner started (checking every 60s)")
        while True:
            try:
                active = await is_runner_active(db_pool)
                if active:
                    await _check_and_run_schedules(db_pool)
                # Always check scheduled reports (independent of runner toggle)
                await _check_and_run_reports(db_pool)
                # Check KB build schedule
                await _check_kb_build_schedule(db_pool)
                # Always try to auto-refresh SSO tokens
                await _auto_refresh_sso()
            except Exception as e:
                logger.error("Schedule runner error: %s", e)
            await asyncio.sleep(60)

    _runner_task = asyncio.create_task(_run())


def get_runner_status() -> dict:
    """Get schedule runner status."""
    running = _runner_task is not None and not _runner_task.done()
    return {"running": running, "active": _runner_active}
