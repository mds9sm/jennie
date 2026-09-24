"""
MCP router — mounts the Genie Knowledge MCP server at /mcp.

Authentication: validates OAuth Bearer tokens issued by /oauth/token.
Tokens are the same HMAC-signed tokens used by the rest of the API —
no format change. The OAuth layer issues/validates them via Bearer header.

Two responsibilities:
  1. MCPAuthMiddleware — validates Bearer tokens on all /mcp paths
  2. setup_mcp(app)    — mounts the MCP ASGI app and wires KB

Lifespan integration in main.py:
    # Inside the @asynccontextmanager lifespan, after KB is loaded:
    from mcp_server.server import lifespan_context as mcp_lifespan
    async with mcp_lifespan():
        yield
"""

import logging

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("genie.mcp_router")


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer tokens on /mcp requests. Other paths pass through."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        token = _extract_bearer(request)
        if token:
            from api.users import _decode_token
            session = _decode_token(token)
            if session:
                request.state.mcp_user = session
                return await call_next(request)
            logger.warning("MCP: invalid Bearer token from %s", request.client)
            return Response(
                content='{"error":"invalid_token","error_description":"Token is expired or invalid"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Bearer realm="genie", error="invalid_token"'},
            )

        from config import config
        base_url = getattr(config, "PUBLIC_BASE_URL", "")
        meta_url = (
            f"{base_url}/.well-known/oauth-authorization-server"
            if base_url
            else "/.well-known/oauth-authorization-server"
        )
        return Response(
            content='{"error":"unauthorized","error_description":"Bearer token required"}',
            status_code=401,
            media_type="application/json",
            headers={"WWW-Authenticate": f'Bearer realm="genie", resource_metadata="{meta_url}"'},
        )


def setup_mcp(app: FastAPI) -> None:
    """
    Mount the MCP ASGI app at /mcp and add the auth middleware.
    Call this at module level in main.py after app = FastAPI(...).

    KB wiring and session manager lifecycle are handled in main.py's lifespan.
    """
    # Auth middleware (only enforced on /mcp paths)
    app.add_middleware(MCPAuthMiddleware)

    # Mount MCP ASGI app — the sub-app has its route at "/" so the effective
    # public path is /mcp (mount prefix) + "/" = /mcp/
    from mcp_server.server import get_mcp_asgi_handler
    mcp_asgi = get_mcp_asgi_handler()
    app.mount("/mcp", mcp_asgi)

    logger.info("MCP server mounted at /mcp (Streamable HTTP)")
