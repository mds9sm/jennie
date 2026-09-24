"""
Test fixtures for Jennie backend tests.

Uses a real test postgres database (same docker postgres, separate schema or in-memory state).
Mocks external services (Redshift, AWS, DOMO, MCP).
"""

import asyncio
import time
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Patch external services before importing app
import sys
from unittest.mock import MagicMock

# Mock MCP bridge to avoid Node.js subprocess
mock_mcp = MagicMock()
mock_mcp.initialize = AsyncMock()
mock_mcp.get_mcp_tools = MagicMock(return_value=[])
mock_mcp.shutdown = AsyncMock()
sys.modules.setdefault("engine.mcp_bridge", mock_mcp)


@pytest_asyncio.fixture
async def db_pool():
    """Create a test database pool using the docker postgres."""
    pool = await asyncpg.create_pool(
        "postgresql://genie:genie_local@localhost:5434/genie",
        min_size=1, max_size=3,
    )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def app(db_pool):
    """Create a test FastAPI app with mocked externals."""
    from main import app as fastapi_app

    # Inject test db pool and minimal KB
    fastapi_app.state.db_pool = db_pool

    from catalog.loader import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    kb.load()
    kb.table_profiles = {}
    kb.domo_catalog = []
    fastapi_app.state.kb = kb

    yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    """Unauthenticated HTTP client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_token(db_pool) -> str:
    """Create a test user and return a valid auth token."""
    from api.users import _hash_password, _sessions

    email = f"test_{secrets.token_hex(4)}@example.com"
    password_hash = _hash_password("testpass123")

    # Insert test user
    row = await db_pool.fetchrow("""
        INSERT INTO users (email, name, password_hash, role, team, is_active)
        VALUES ($1, 'Test User', $2, 'engineer', 'Data', true)
        ON CONFLICT (email) DO UPDATE SET password_hash = $2
        RETURNING id
    """, email, password_hash)

    user_id = row["id"]
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user_id,
        "email": email,
        "role": "engineer",
        "expires": time.time() + 3600,
    }

    yield token

    # Cleanup
    _sessions.pop(token, None)
    await db_pool.execute("DELETE FROM users WHERE id = $1", user_id)


@pytest_asyncio.fixture
async def admin_token(db_pool) -> str:
    """Create a test admin user and return a valid auth token."""
    from api.users import _hash_password, _sessions

    email = f"admin_{secrets.token_hex(4)}@example.com"
    password_hash = _hash_password("adminpass123")

    row = await db_pool.fetchrow("""
        INSERT INTO users (email, name, password_hash, role, team, is_active)
        VALUES ($1, 'Test Admin', $2, 'admin', 'Data', true)
        ON CONFLICT (email) DO UPDATE SET password_hash = $2, role = 'admin'
        RETURNING id
    """, email, password_hash)

    user_id = row["id"]
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user_id,
        "email": email,
        "role": "admin",
        "expires": time.time() + 3600,
    }

    yield token

    _sessions.pop(token, None)
    await db_pool.execute("DELETE FROM users WHERE id = $1", user_id)


@pytest_asyncio.fixture
async def auth_client(client, auth_token):
    """Authenticated HTTP client (engineer role)."""
    client.headers["X-Auth-Token"] = auth_token
    yield client
    client.headers.pop("X-Auth-Token", None)


@pytest_asyncio.fixture
async def admin_client(client, admin_token):
    """Authenticated HTTP client (admin role)."""
    client.headers["X-Auth-Token"] = admin_token
    yield client
    client.headers.pop("X-Auth-Token", None)


@pytest_asyncio.fixture
async def second_user_token(db_pool) -> str:
    """Create a second test user for isolation tests."""
    from api.users import _hash_password, _sessions

    email = f"user2_{secrets.token_hex(4)}@example.com"
    password_hash = _hash_password("user2pass")

    row = await db_pool.fetchrow("""
        INSERT INTO users (email, name, password_hash, role, team, is_active)
        VALUES ($1, 'Second User', $2, 'analyst', 'Marketing', true)
        ON CONFLICT (email) DO UPDATE SET password_hash = $2
        RETURNING id
    """, email, password_hash)

    user_id = row["id"]
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user_id,
        "email": email,
        "role": "analyst",
        "expires": time.time() + 3600,
    }

    yield token

    _sessions.pop(token, None)
    await db_pool.execute("DELETE FROM users WHERE id = $1", user_id)
