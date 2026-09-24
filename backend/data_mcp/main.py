"""
Data MCP standalone FastAPI app.

Deployed as data-mcp in np K8s (separate from Genie backend).
Provides direct Redshift access + MWAA log reads via MCP Streamable HTTP.

Authentication: validates Bearer tokens issued by Genie's OAuth server.
Token validation is stateless — verifies HMAC signature using same secret.

Environment variables:
  REDSHIFT_HOST, REDSHIFT_PORT, REDSHIFT_USER, REDSHIFT_PASSWORD, REDSHIFT_DATABASE
  MWAA_ENV_NAME
  GENIE_TOKEN_SECRET    — shared HMAC secret with Genie OAuth server
  PUBLIC_BASE_URL       — for OAuth metadata URL in 401 headers (e.g. https://dev-apis.example.com/genie)
"""

import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_mcp.main")


# ---------------------------------------------------------------------------
# Token validation (stateless HMAC — matches Genie's _create_token format)
# ---------------------------------------------------------------------------

def _get_token_secret() -> str:
    # Match Genie's exact secret derivation: sha256(DATABASE_URL + "genie-auth-signing-key")
    db_url = os.environ.get("DATABASE_URL", "")
    return hashlib.sha256((db_url + "genie-auth-signing-key").encode()).hexdigest()


def _decode_token(token: str) -> dict | None:
    """
    Validate a Genie HMAC token. Returns payload dict or None if invalid/expired.
    Token format: base64url(payload_json).hex_sig[:32]
    Matches _create_token / _decode_token in backend/api/users.py exactly.
    """
    try:
        import base64
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(
            _get_token_secret().encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


class DataMCPAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer tokens on all requests (except OPTIONS + health)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Pass through health check and OPTIONS
        if path in ("/health", "/") or request.method == "OPTIONS":
            return await call_next(request)

        token = _extract_bearer(request)
        if token:
            session = _decode_token(token)
            if session:
                request.state.user = session
                return await call_next(request)
            return Response(
                content='{"error":"invalid_token","error_description":"Token is expired or invalid"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Bearer realm="your-org", error="invalid_token"'},
            )

        genie_base = os.environ.get("PUBLIC_BASE_URL", "")
        meta_url = (
            f"{genie_base}/.well-known/oauth-authorization-server"
            if genie_base
            else "/.well-known/oauth-authorization-server"
        )
        return Response(
            content='{"error":"unauthorized","error_description":"Bearer token required"}',
            status_code=401,
            media_type="application/json",
            headers={"WWW-Authenticate": f'Bearer realm="your-org", resource_metadata="{meta_url}"'},
        )


# ---------------------------------------------------------------------------
# MCP session manager lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from data_mcp.server import mcp

    logger.info("Data MCP: starting session manager")
    _ = mcp.streamable_http_app()  # ensure session manager is initialized
    async with mcp._session_manager.run():
        logger.info("Data MCP: session manager running")
        yield
    logger.info("Data MCP: session manager stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Jennie Data MCP", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(DataMCPAuthMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "data-mcp"}


# Mount the MCP ASGI app at /mcp
# Note: requests to /mcp (no trailing slash) get a 307 → /mcp/ (standard Starlette behavior)
# MCP clients and claude.ai follow redirects automatically.
# K8s ingress should point to /data-mcp/mcp/ directly.
from data_mcp.server import mcp as _data_mcp  # noqa: E402

app.mount("/mcp", _data_mcp.streamable_http_app())
