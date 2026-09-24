"""
Per-user AWS credential store with postgres persistence.

Credentials are stored in-memory for fast access AND persisted to postgres
so they survive backend restarts (uvicorn --reload, container restart).
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("genie.credentials")

# Will be set by main.py at startup
_db_pool = None


def set_db_pool(pool):
    global _db_pool
    _db_pool = pool


# SSO refresh tokens for auto-renewal
_sso_refresh_tokens: dict[str, dict] = {}  # environment → {client_id, client_secret, refresh_token, account_id, role_name}


def store_sso_refresh(environment: str, data: dict):
    _sso_refresh_tokens[environment] = data
    # Also persist to postgres
    _persist_sso_refresh(environment, data)


def get_sso_refresh(environment: str) -> dict | None:
    return _sso_refresh_tokens.get(environment)


def _persist_sso_refresh(environment: str, data: dict):
    """Persist refresh token to postgres so it survives backend restarts."""
    if not _db_pool:
        return
    import asyncio
    import json as _json
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_persist_refresh(environment, data))
    except Exception as e:
        logger.warning("Could not persist refresh token: %s", e)


async def _async_persist_refresh(environment: str, data: dict):
    """Write refresh token to postgres."""
    import json as _json
    from datetime import datetime, timezone, timedelta
    try:
        expires = datetime.now(timezone.utc) + timedelta(days=30)  # refresh tokens last longer
        await _db_pool.execute("""
            INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
            VALUES ('_sso_refresh', $1, 'sso_refresh', $2::jsonb, $3)
            ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
                data = $2::jsonb, expires_at = $3, created_at = NOW()
        """, environment, _json.dumps(data), expires)
    except Exception as e:
        logger.warning("Refresh token persist failed: %s", e)


@dataclass
class AWSCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expires_at: float  # unix timestamp
    account_id: str = ""
    role_name: str = ""
    profile: str = ""  # "nonprod" or "prod"

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def minutes_remaining(self) -> int:
        return max(0, int((self.expires_at - time.time()) / 60))

    def to_dict(self) -> dict:
        return {
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "session_token": self.session_token,
            "expires_at": self.expires_at,
            "account_id": self.account_id,
            "role_name": self.role_name,
            "profile": self.profile,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AWSCredentials":
        return cls(**d)


@dataclass
class UserSession:
    session_id: str
    user_email: str = ""
    credentials: dict[str, AWSCredentials] = field(default_factory=dict)

    def get_credentials(self, environment: str) -> AWSCredentials | None:
        creds = self.credentials.get(environment)
        if creds and not creds.is_expired:
            return creds
        if creds and creds.is_expired:
            logger.info("Credentials expired for %s/%s", self.session_id, environment)
            del self.credentials[environment]
        return None

    def set_credentials(self, environment: str, creds: AWSCredentials):
        self.credentials[environment] = creds
        logger.info(
            "Stored credentials for %s/%s (expires in %d min)",
            self.session_id, environment, creds.minutes_remaining,
        )


class CredentialStore:
    """Credential store with in-memory cache + postgres persistence."""

    def __init__(self):
        self._sessions: dict[str, UserSession] = {}
        self._client_id: str = ""
        self._client_secret: str = ""
        self._client_expires_at: float = 0
        self._pending_auth: dict[str, dict] = {}

    def get_session(self, session_id: str) -> UserSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = UserSession(session_id=session_id)
        return self._sessions[session_id]

    def get_credentials(self, session_id: str, environment: str) -> AWSCredentials | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        return session.get_credentials(environment)

    def set_credentials(self, session_id: str, environment: str, creds: AWSCredentials):
        session = self.get_session(session_id)
        session.set_credentials(environment, creds)
        # Persist to postgres async
        _persist_credential(session_id, environment, "aws_sso", creds.to_dict(), creds.expires_at)

    @property
    def client_registered(self) -> bool:
        return bool(self._client_id) and time.time() < self._client_expires_at

    def cleanup_expired(self):
        to_remove = []
        for sid, session in self._sessions.items():
            session.credentials = {
                env: c for env, c in session.credentials.items() if not c.is_expired
            }
            if not session.credentials:
                to_remove.append(sid)
        for sid in to_remove:
            del self._sessions[sid]


def _persist_credential(session_id: str, environment: str, cred_type: str, data: dict, expires_at: float):
    """Persist credential to postgres (fire and forget)."""
    if not _db_pool:
        return
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_persist(session_id, environment, cred_type, data, expires_at))
        else:
            asyncio.run(_async_persist(session_id, environment, cred_type, data, expires_at))
    except Exception as e:
        logger.warning("Could not persist credential: %s", e)


async def _async_persist(session_id: str, environment: str, cred_type: str, data: dict, expires_at: float):
    """Actually write to postgres."""
    try:
        expires_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        await _db_pool.execute("""
            INSERT INTO credential_cache (session_id, environment, cred_type, data, expires_at)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            ON CONFLICT (session_id, environment, cred_type) DO UPDATE SET
                data = $4::jsonb, expires_at = $5, created_at = NOW()
        """, session_id, environment, cred_type, json.dumps(data), expires_dt)
    except Exception as e:
        logger.warning("Credential persist failed: %s", e)


async def restore_credentials_from_db(store: "CredentialStore"):
    """Restore non-expired credentials from postgres on startup."""
    if not _db_pool:
        return
    try:
        rows = await _db_pool.fetch("""
            SELECT session_id, environment, cred_type, data, expires_at
            FROM credential_cache
            WHERE expires_at > NOW()
        """)
        sso_count = 0
        rs_count = 0
        for row in rows:
            data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
            if row["cred_type"] == "aws_sso":
                creds = AWSCredentials.from_dict(data)
                if not creds.is_expired:
                    session = store.get_session(row["session_id"])
                    session.credentials[row["environment"]] = creds
                    sso_count += 1
            elif row["cred_type"] == "sso_refresh":
                # Restore SSO refresh tokens for auto-renewal
                _sso_refresh_tokens[row["environment"]] = data
                logger.info("Restored SSO refresh token for %s", row["environment"])
            elif row["cred_type"] == "redshift_direct":
                # Restore Redshift direct credentials (host/port/db from stored data, fallback to config)
                from connectors.redshift import _direct_creds
                from config import config
                env = row["environment"]
                default_host = config.REDSHIFT_PRD_HOST if env == "prd" else config.REDSHIFT_NP_HOST
                default_port = config.REDSHIFT_PRD_PORT if env == "prd" else config.REDSHIFT_NP_PORT
                default_db = config.REDSHIFT_PRD_DATABASE if env == "prd" else config.REDSHIFT_NP_DATABASE
                _direct_creds[env] = {
                    "host": data.get("host") or default_host,
                    "port": int(data.get("port") or default_port),
                    "database": data.get("database") or default_db,
                    "user": data["username"],
                    "password": data["password"],
                }
                logger.info("Restored Redshift %s credentials (host=%s, user=%s)",
                           env, _direct_creds[env]["host"], data["username"])
                rs_count += 1
        if sso_count or rs_count:
            logger.info("Restored %d SSO + %d Redshift credentials from postgres", sso_count, rs_count)
    except Exception as e:
        logger.warning("Could not restore credentials: %s", e)


# Singleton
credential_store = CredentialStore()
