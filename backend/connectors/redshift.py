import asyncio
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal

import boto3
import redshift_connector
from botocore.config import Config as BotoConfig

from config import config
from connectors.credential_store import AWSCredentials, credential_store

logger = logging.getLogger("genie.redshift")


import re

# ---------------------------------------------------------------------------
# Query safety guard — ONLY SELECT and ANALYZE allowed
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS = re.compile(
    r"^\s*(CREATE|DROP|TRUNCATE|DELETE|INSERT|UPDATE|MERGE|ALTER|GRANT|REVOKE|COPY|UNLOAD)\b",
    re.IGNORECASE | re.MULTILINE,
)

_ALLOWED_PATTERNS = re.compile(
    r"^\s*(SELECT|EXPLAIN|ANALYZE|SET|SHOW|WITH)\b",
    re.IGNORECASE,
)


def validate_query_safety(sql: str) -> None:
    """
    Validate that a SQL query is read-only.
    Only SELECT, EXPLAIN, ANALYZE, SET, SHOW, and WITH (CTEs) are allowed.
    Raises ValueError if forbidden statements are detected.
    """
    # Strip comments
    cleaned = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

    # Check each statement (split by semicolons)
    for stmt in cleaned.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        if _FORBIDDEN_PATTERNS.search(stmt):
            raise ValueError(
                f"BLOCKED: Statement contains forbidden operation. "
                f"Only SELECT, EXPLAIN, and ANALYZE are allowed. "
                f"Detected: {stmt[:80]}..."
            )
        if not _ALLOWED_PATTERNS.match(stmt):
            # Unknown statement type — block it
            first_word = stmt.split()[0] if stmt.split() else "?"
            raise ValueError(
                f"BLOCKED: Unknown statement type '{first_word}'. "
                f"Only SELECT, EXPLAIN, and ANALYZE are allowed."
            )


def _json_safe(cell):
    """Convert a Redshift result cell to a JSON-serializable value."""
    if cell is None:
        return None
    if isinstance(cell, (int, float, str, bool)):
        return cell
    if isinstance(cell, Decimal):
        return float(cell)
    if isinstance(cell, datetime):
        return cell.isoformat()
    if isinstance(cell, bytes):
        return cell.decode("utf-8", errors="replace")
    return str(cell)


def _get_connection_with_user_creds(
    environment: str, user_creds: AWSCredentials
) -> redshift_connector.Connection:
    """
    Connect to Redshift using per-user temporary credentials.

    Uses GetClusterCredentials to get a temporary Redshift user/password
    from the user's AWS IAM credentials.
    """
    if environment == "prd":
        host = config.REDSHIFT_PRD_HOST
        port = config.REDSHIFT_PRD_PORT
        database = config.REDSHIFT_PRD_DATABASE
        cluster_id = config.REDSHIFT_PRD_CLUSTER_ID
    else:
        host = config.REDSHIFT_NP_HOST
        port = config.REDSHIFT_NP_PORT
        database = config.REDSHIFT_NP_DATABASE
        cluster_id = config.REDSHIFT_NP_CLUSTER_ID

    # Create a boto3 session with the user's temporary credentials
    session = boto3.Session(
        aws_access_key_id=user_creds.access_key_id,
        aws_secret_access_key=user_creds.secret_access_key,
        aws_session_token=user_creds.session_token,
        region_name=config.AWS_REGION,
    )

    # Get temporary Redshift credentials
    redshift_client = session.client("redshift", config=BotoConfig(region_name=config.AWS_REGION))
    db_creds = redshift_client.get_cluster_credentials(
        DbUser=f"IAMR:{user_creds.role_name}",
        ClusterIdentifier=cluster_id,
        AutoCreate=False,
    )

    conn = redshift_connector.connect(
        host=host,
        port=port,
        database=database,
        user=db_creds["DbUser"],
        password=db_creds["DbPassword"],
        timeout=config.QUERY_TIMEOUT_SECONDS,
    )
    return conn


# In-memory store for Redshift direct credentials (from Airflow connections)
_direct_creds: dict[str, dict] = {}  # environment -> {host, port, database, user, password}

# In-memory store for Okta Redshift credentials
_okta_creds: dict[str, dict] = {}  # session_id -> {username, password}


def set_okta_credentials(session_id: str, username: str, password: str):
    """Store Okta credentials for a session (in-memory)."""
    _okta_creds[session_id] = {"username": username, "password": password}


def get_okta_credentials(session_id: str) -> dict | None:
    """Get stored Okta credentials for a session."""
    return _okta_creds.get(session_id)


# Cache for temporary AWS credentials from Okta SAML
_okta_aws_creds: dict[str, dict] = {}  # session_id -> {access_key, secret_key, token, expires}


def set_okta_aws_creds(session_id: str, creds: dict):
    """Cache AWS temporary creds obtained via Okta SAML."""
    _okta_aws_creds[session_id] = creds


def get_okta_aws_creds(session_id: str) -> dict | None:
    """Get cached AWS creds. Returns None if expired."""
    creds = _okta_aws_creds.get(session_id)
    if not creds:
        return None
    import time
    if creds.get("expires", 0) < time.time():
        _okta_aws_creds.pop(session_id, None)
        return None
    return creds


def _get_connection_okta(environment: str, session_id: str | None = None) -> redshift_connector.Connection:
    """
    Connect to Redshift via Okta SAML — same as DataGrip JDBC driver.
    Uses redshift_connector's built-in OktaCredentialsProvider with group_federation.
    """
    if environment == "prd":
        host = config.REDSHIFT_PRD_HOST
        port = config.REDSHIFT_PRD_PORT
        database = config.REDSHIFT_PRD_DATABASE
        cluster_id = config.REDSHIFT_PRD_CLUSTER_ID
    else:
        host = config.REDSHIFT_NP_HOST
        port = config.REDSHIFT_NP_PORT
        database = config.REDSHIFT_NP_DATABASE
        cluster_id = config.REDSHIFT_NP_CLUSTER_ID

    # Use cached AWS creds from SAML flow
    aws_creds = get_okta_aws_creds(session_id) if session_id else None
    if aws_creds:
        logger.info("Using cached SAML AWS creds for %s (role: %s)", environment, aws_creds.get("role_arn", "?"))
        conn = redshift_connector.connect(
            iam=True,
            host=host,
            port=port,
            database=database,
            cluster_identifier=cluster_id,
            region=config.AWS_REGION,
            access_key_id=aws_creds["access_key"],
            secret_access_key=aws_creds["secret_key"],
            session_token=aws_creds["token"],
            group_federation=True,
            timeout=config.QUERY_TIMEOUT_SECONDS,
        )
        return conn

    # No cached creds — try re-authenticating with stored Okta username/password
    okta_creds = get_okta_credentials(session_id) if session_id else None
    if not okta_creds:
        raise ConnectionError("No Okta credentials stored. Configure in Settings > Connection.")

    # This will trigger MFA again — not ideal but works as fallback
    logger.info("No cached AWS creds — re-authenticating via Okta SAML for %s", environment)
    app_id = config.OKTA_APP_ID_NP if environment == "np" else config.OKTA_APP_ID_PRD
    conn = redshift_connector.connect(
        iam=True,
        host=host,
        port=port,
        database=database,
        cluster_identifier=cluster_id,
        region=config.AWS_REGION,
        credentials_provider="OktaCredentialsProvider",
        idp_host=config.OKTA_IDP_HOST,
        app_id=app_id,
        user=okta_creds["username"],
        password=okta_creds["password"],
        group_federation=True,
        timeout=config.QUERY_TIMEOUT_SECONDS,
    )
    return conn


def _get_connection_fallback(environment: str) -> redshift_connector.Connection:
    """Fallback: connect using shared ~/.aws mount or explicit user/password."""
    if environment == "prd":
        host = config.REDSHIFT_PRD_HOST
        port = config.REDSHIFT_PRD_PORT
        database = config.REDSHIFT_PRD_DATABASE
        cluster_id = config.REDSHIFT_PRD_CLUSTER_ID
        profile = config.AWS_PROFILE_PRD
        user = config.REDSHIFT_PRD_USER
        password = config.REDSHIFT_PRD_PASSWORD
    else:
        host = config.REDSHIFT_NP_HOST
        port = config.REDSHIFT_NP_PORT
        database = config.REDSHIFT_NP_DATABASE
        cluster_id = config.REDSHIFT_NP_CLUSTER_ID
        profile = config.AWS_PROFILE_NP
        user = config.REDSHIFT_NP_USER
        password = config.REDSHIFT_NP_PASSWORD

    # Explicit user/password
    if user and password:
        return redshift_connector.connect(
            host=host, port=port, database=database,
            user=user, password=password,
            timeout=config.QUERY_TIMEOUT_SECONDS,
        )

    # IAM via mounted ~/.aws
    return redshift_connector.connect(
        iam=True,
        host=host, port=port, database=database,
        cluster_identifier=cluster_id,
        profile=profile,
        region=config.AWS_REGION,
        timeout=config.QUERY_TIMEOUT_SECONDS,
    )


def _get_connection(
    environment: str, session_id: str | None = None
) -> redshift_connector.Connection:
    """
    Get a Redshift connection.

    Priority:
    1. Okta SAML credentials (if stored for this session)
    2. Per-user AWS SSO credentials (from credential_store)
    3. Shared fallback (mounted ~/.aws or explicit user/password)
    """
    # 1. Try direct Redshift credentials (from Airflow or .env)
    direct = _direct_creds.get(environment)
    if not direct:
        # Check .env config
        if environment == "prd" and config.REDSHIFT_PRD_USER and config.REDSHIFT_PRD_PASSWORD:
            direct = {
                "host": config.REDSHIFT_PRD_HOST, "port": config.REDSHIFT_PRD_PORT,
                "database": config.REDSHIFT_PRD_DATABASE,
                "user": config.REDSHIFT_PRD_USER, "password": config.REDSHIFT_PRD_PASSWORD,
            }
        elif environment == "np" and config.REDSHIFT_NP_USER and config.REDSHIFT_NP_PASSWORD:
            direct = {
                "host": config.REDSHIFT_NP_HOST, "port": config.REDSHIFT_NP_PORT,
                "database": config.REDSHIFT_NP_DATABASE,
                "user": config.REDSHIFT_NP_USER, "password": config.REDSHIFT_NP_PASSWORD,
            }

    if direct:
        logger.info("Using direct Redshift credentials for %s (user=%s)", environment, direct["user"])
        return redshift_connector.connect(
            host=direct["host"],
            port=direct["port"],
            database=direct["database"],
            user=direct["user"],
            password=direct["password"],
            timeout=config.QUERY_TIMEOUT_SECONDS,
        )

    # 2. Try AWS SSO credentials
    if session_id:
        user_creds = credential_store.get_credentials(session_id, environment)
        if user_creds:
            logger.info(
                "Using per-user AWS SSO creds for %s/%s (expires in %d min)",
                session_id, environment, user_creds.minutes_remaining,
            )
            return _get_connection_with_user_creds(environment, user_creds)

    # 3. Shared fallback
    logger.info("No per-user creds for %s, using fallback", environment)
    return _get_connection_fallback(environment)


def _execute_query_sync(
    sql: str,
    environment: str,
    max_rows: int,
    session_id: str | None,
    query_id: str,
    start: float,
) -> dict:
    """Blocking connect + execute + fetch. Must run in a worker thread."""
    conn = _get_connection(environment, session_id)
    try:
        cursor = conn.cursor()

        cursor.execute(f"SET statement_timeout = {config.QUERY_TIMEOUT_SECONDS * 1000}")
        cursor.execute(sql)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]

        safe_rows = [[_json_safe(cell) for cell in row] for row in rows]
        elapsed_ms = int((time.time() - start) * 1000)

        cursor.close()

        logger.info("Query %s: %d rows in %dms (%s)", query_id, len(safe_rows), elapsed_ms, environment)

        return {
            "columns": columns,
            "rows": safe_rows,
            "row_count": len(safe_rows),
            "execution_time_ms": elapsed_ms,
            "environment": environment,
            "truncated": truncated,
            "query_id": query_id,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def execute_real_query(
    sql: str,
    environment: str = "np",
    max_rows: int = 1000,
    session_id: str | None = None,
) -> dict:
    """Execute a read-only query against Redshift."""
    start = time.time()
    query_id = f"genie-{uuid.uuid4().hex[:8]}"

    try:
        # Safety check — block all non-read operations
        validate_query_safety(sql)

        # Run all blocking I/O (IAM creds, connect, execute, fetch) in a worker
        # thread so a slow or hung connection can never stall the event loop.
        # The outer wait_for bounds connect (QUERY_TIMEOUT_SECONDS) + query
        # (statement_timeout) even if the socket dies mid-read.
        return await asyncio.wait_for(
            asyncio.to_thread(
                _execute_query_sync, sql, environment, max_rows, session_id, query_id, start
            ),
            timeout=config.QUERY_TIMEOUT_SECONDS * 2 + 30,
        )

    except asyncio.TimeoutError:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.error("Query %s timed out after %dms (%s)", query_id, elapsed_ms, environment)
        return {
            "error": f"Query timed out after {config.QUERY_TIMEOUT_SECONDS * 2 + 30}s (connection or network stall).",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": elapsed_ms,
            "environment": environment,
            "truncated": False,
            "query_id": query_id,
        }

    except Exception as e:
        logger.error("Redshift query error (%s): %s", environment, e)
        elapsed_ms = int((time.time() - start) * 1000)

        error_msg = str(e)
        if "expired" in error_msg.lower() or "token" in error_msg.lower():
            error_msg = (
                f"AWS credentials expired. Please re-authenticate for "
                f"{'prod' if environment == 'prd' else 'nonprod'} in the app.\n"
                f"Original error: {error_msg}"
            )

        return {
            "error": error_msg,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": elapsed_ms,
            "environment": environment,
            "truncated": False,
            "query_id": query_id,
        }


def _test_connection_sync(environment: str, session_id: str | None) -> dict:
    """Blocking connectivity check. Must run in a worker thread."""
    conn = _get_connection(environment, session_id)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT CURRENT_USER, CURRENT_DATABASE(), GETDATE()")
        row = cursor.fetchone()
        cursor.close()
        return {
            "status": "connected",
            "environment": environment,
            "user": row[0],
            "database": row[1],
            "server_time": row[2].isoformat() if row[2] else None,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def test_connection(environment: str = "np", session_id: str | None = None) -> dict:
    """Test Redshift connectivity."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_test_connection_sync, environment, session_id),
            timeout=config.QUERY_TIMEOUT_SECONDS + 15,
        )
    except asyncio.TimeoutError:
        return {"status": "error", "environment": environment, "error": "Connection test timed out"}
    except Exception as e:
        return {"status": "error", "environment": environment, "error": str(e)}
