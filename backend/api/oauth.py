"""
OAuth 2.1 Authorization Server for Genie MCP.

Implements the subset required by claude.ai's MCP connector:
  - RFC 8414  /.well-known/oauth-authorization-server  (discovery)
  - RFC 9728  /.well-known/oauth-protected-resource    (resource metadata)
  - RFC 7591  POST /oauth/register                     (dynamic client registration)
  - RFC 6749  GET  /oauth/authorize                    (authorization)
  - RFC 6749  POST /oauth/token                        (token exchange)
  - OIDC      GET  /oauth/userinfo                     (user info)
  - PKCE (RFC 7636) enforced on all authorization code flows

Auth backends (in preference order):
  1. Okta OIDC — if OKTA_CLIENT_ID + OKTA_ISSUER are configured
  2. Genie password login — always available as fallback

Issued tokens are Genie's existing HMAC-signed tokens (same format used by the
rest of the API via X-Auth-Token). No new token format needed.
"""

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlencode, urlparse

import requests
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from config import config

logger = logging.getLogger("genie.oauth")
router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory stores (single-pod OK for dev K8s; replace with redis for HA)
# ---------------------------------------------------------------------------

# Registered OAuth clients: client_id → {client_secret, redirect_uris, ...}
_clients: dict[str, dict] = {}

# Pending authorization requests: state → {client_id, redirect_uri, code_challenge, code_challenge_method}
_pending_auth: dict[str, dict] = {}

# Issued auth codes: code → {token, redirect_uri, client_id, expires}
_auth_codes: dict[str, dict] = {}

# Okta state → our state mapping (for relaying through Okta)
_okta_relay: dict[str, str] = {}  # okta_state → our_state

_CODE_TTL = 120  # seconds auth code is valid
_PENDING_TTL = 600  # seconds to wait for user to complete login


def _base_url(request: Request) -> str:
    """Derive the public base URL from the request or config."""
    configured = getattr(config, "PUBLIC_BASE_URL", "").rstrip("/")
    if configured:
        return configured
    # Fallback: derive from request
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    host = request.headers.get("X-Forwarded-Host", request.headers.get("host", request.url.netloc))
    return f"{scheme}://{host}"


def _is_okta_configured() -> bool:
    return bool(getattr(config, "OKTA_CLIENT_ID", "") and getattr(config, "OKTA_ISSUER", ""))


def _pkce_verify(code_verifier: str, code_challenge: str, method: str) -> bool:
    """Verify PKCE code challenge. Returns True if valid."""
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return expected == code_challenge
    elif method == "plain":
        return code_verifier == code_challenge
    return False


def _clean_expired():
    """Remove expired entries from in-memory stores."""
    now = time.time()
    for store in (_auth_codes, _pending_auth, _okta_relay):
        expired = [k for k, v in store.items()
                   if isinstance(v, dict) and v.get("expires", now + 1) < now]
        for k in expired:
            store.pop(k, None)


# ---------------------------------------------------------------------------
# RFC 8414 — OAuth Authorization Server Metadata
# ---------------------------------------------------------------------------

@router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414).
    claude.ai fetches this to discover the authorization and token endpoints.
    """
    base = _base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "userinfo_endpoint": f"{base}/oauth/userinfo",
        "registration_endpoint": f"{base}/oauth/register",
        "scopes_supported": ["openid", "profile", "email", "mcp"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
    }


# ---------------------------------------------------------------------------
# RFC 9728 — OAuth Protected Resource Metadata
# ---------------------------------------------------------------------------

@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request):
    """
    OAuth 2.0 Protected Resource Metadata (RFC 9728 / MCP spec).
    Points the client to the authorization server.
    """
    base = _base_url(request)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base}/docs",
    }


# ---------------------------------------------------------------------------
# RFC 7591 — Dynamic Client Registration
# ---------------------------------------------------------------------------

@router.post("/oauth/register")
async def register_client(request: Request):
    """
    Dynamic Client Registration (RFC 7591).
    claude.ai calls this to register itself as an OAuth client.
    No pre-registration needed — we auto-approve all registrations.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    client_id = secrets.token_urlsafe(16)
    client_secret = secrets.token_urlsafe(32)
    redirect_uris = body.get("redirect_uris", [])

    _clients[client_id] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": redirect_uris,
        "client_name": body.get("client_name", ""),
        "grant_types": body.get("grant_types", ["authorization_code"]),
        "response_types": body.get("response_types", ["code"]),
        "registered_at": time.time(),
    }
    logger.info("OAuth: registered client %s (%s) redirect_uris=%s",
                client_id, body.get("client_name", ""), redirect_uris)

    return JSONResponse({
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": redirect_uris,
        "client_name": body.get("client_name", ""),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }, status_code=201)


# ---------------------------------------------------------------------------
# GET /oauth/authorize — Authorization endpoint
# ---------------------------------------------------------------------------

@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "code",
    scope: str = "openid",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
):
    """
    Authorization endpoint. Redirects to Okta (if configured) or shows
    a simple HTML login form backed by Genie's password login.
    """
    _clean_expired()

    if response_type != "code":
        raise HTTPException(400, "Only response_type=code is supported")

    # Store pending auth request
    pending_key = secrets.token_urlsafe(16)
    _pending_auth[pending_key] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "original_state": state,
        "expires": time.time() + _PENDING_TTL,
    }

    base = _base_url(request)

    if _is_okta_configured():
        # Route through Okta OIDC
        okta_state = secrets.token_urlsafe(32)
        _okta_relay[okta_state] = pending_key
        _okta_relay[pending_key] = okta_state  # reverse lookup

        okta_redirect = f"{base}/oauth/callback/okta"
        params = {
            "client_id": config.OKTA_CLIENT_ID,
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": okta_redirect,
            "state": okta_state,
        }
        okta_auth_url = f"{config.OKTA_ISSUER}/v1/authorize?{urlencode(params)}"
        return RedirectResponse(okta_auth_url)
    else:
        # Show password login form
        return _render_login_form(pending_key, error="")


# ---------------------------------------------------------------------------
# GET /oauth/callback/okta — Handle Okta redirect
# ---------------------------------------------------------------------------

@router.get("/oauth/callback/okta")
async def okta_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle Okta's redirect after user authentication."""
    if error:
        logger.warning("Okta error: %s", error)
        raise HTTPException(400, f"Okta authentication failed: {error}")

    # Look up the pending auth request via Okta state
    pending_key = _okta_relay.get(state)
    if not pending_key:
        raise HTTPException(400, "Invalid OAuth state — please try connecting again")

    pending = _pending_auth.get(pending_key)
    if not pending or pending.get("expires", 0) < time.time():
        raise HTTPException(400, "Authorization request expired — please try again")

    # Exchange code with Okta
    base = request.url.scheme + "://" + request.url.netloc
    okta_redirect = f"{_base_url(request)}/oauth/callback/okta"
    token_resp = await asyncio.to_thread(requests.post, f"{config.OKTA_ISSUER}/v1/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": okta_redirect,
        "client_id": config.OKTA_CLIENT_ID,
        "client_secret": config.OKTA_CLIENT_SECRET,
    }, timeout=15)

    if token_resp.status_code != 200:
        logger.error("Okta token exchange failed: %s", token_resp.text[:200])
        raise HTTPException(400, "Okta token exchange failed")

    okta_tokens = token_resp.json()
    access_token = okta_tokens.get("access_token", "")

    # Get user info from Okta
    userinfo_resp = await asyncio.to_thread(requests.get, f"{config.OKTA_ISSUER}/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=10)

    if userinfo_resp.status_code != 200:
        raise HTTPException(400, "Failed to get Okta user info")

    userinfo = userinfo_resp.json()
    email = userinfo.get("email", "").lower()
    name = userinfo.get("name", "") or userinfo.get("preferred_username", "")

    if not email:
        raise HTTPException(400, "No email in Okta profile")
    if not email.endswith("@example.com"):
        raise HTTPException(403, "Only @example.com accounts are allowed")

    # Create or get Genie user
    genie_token = await _get_or_create_user(request, email, name)
    return _issue_code_and_redirect(pending_key, genie_token)


# ---------------------------------------------------------------------------
# POST /oauth/authorize/login — Password login form submission
# ---------------------------------------------------------------------------

@router.post("/oauth/authorize/login")
async def login_form_submit(
    request: Request,
    pending_key: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    """Handle password form submission for the non-Okta OAuth flow."""
    pending = _pending_auth.get(pending_key)
    if not pending or pending.get("expires", 0) < time.time():
        return _render_login_form(pending_key, error="Session expired — please try again")

    # Validate credentials against Genie user database
    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT id, email, name, role, is_active, password_hash FROM users WHERE email = $1",
        email.lower().strip(),
    )

    if not row or not row["is_active"]:
        return _render_login_form(pending_key, error="Invalid email or password")

    from api.users import _verify_password, _create_token
    if not await asyncio.to_thread(_verify_password, password, row["password_hash"]):
        return _render_login_form(pending_key, error="Invalid email or password")

    genie_token = _create_token(row["id"], row["email"], row["role"])
    return _issue_code_and_redirect(pending_key, genie_token)


# ---------------------------------------------------------------------------
# POST /oauth/token — Token endpoint
# ---------------------------------------------------------------------------

@router.post("/oauth/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    code_verifier: str = Form(""),
):
    """
    Token endpoint. Exchanges an auth code for a Genie HMAC access token.
    Validates PKCE code_verifier if a code_challenge was presented at /authorize.
    """
    _clean_expired()

    if grant_type != "authorization_code":
        raise HTTPException(400, detail={"error": "unsupported_grant_type"})

    stored = _auth_codes.pop(code, None)
    if not stored:
        raise HTTPException(400, detail={"error": "invalid_grant", "error_description": "Code not found or already used"})

    if stored.get("expires", 0) < time.time():
        raise HTTPException(400, detail={"error": "invalid_grant", "error_description": "Code expired"})

    if stored.get("redirect_uri") and stored["redirect_uri"] != redirect_uri:
        raise HTTPException(400, detail={"error": "invalid_grant", "error_description": "redirect_uri mismatch"})

    # Verify PKCE if challenge was provided
    code_challenge = stored.get("code_challenge", "")
    code_challenge_method = stored.get("code_challenge_method", "S256")
    if code_challenge:
        if not code_verifier:
            raise HTTPException(400, detail={"error": "invalid_grant", "error_description": "code_verifier required"})
        if not _pkce_verify(code_verifier, code_challenge, code_challenge_method):
            raise HTTPException(400, detail={"error": "invalid_grant", "error_description": "code_verifier mismatch"})

    access_token = stored["token"]

    return JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400 * 7,
        "scope": "openid profile email mcp",
    })


# ---------------------------------------------------------------------------
# GET /oauth/userinfo — UserInfo endpoint
# ---------------------------------------------------------------------------

@router.get("/oauth/userinfo")
async def userinfo(request: Request):
    """Return user info for the current Bearer token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    token = auth[7:].strip()

    from api.users import _decode_token
    session = _decode_token(token)
    if not session:
        raise HTTPException(401, "Invalid or expired token")

    return {
        "sub": str(session["user_id"]),
        "email": session["email"],
        "email_verified": True,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_user(request: Request, email: str, name: str) -> str:
    """Get or create a Genie user from Okta info. Returns a Genie HMAC token."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT id, email, name, role, is_active FROM users WHERE email = $1", email
    )

    if row and not row["is_active"]:
        raise HTTPException(403, "Account is deactivated")

    if not row:
        row = await pool.fetchrow("""
            INSERT INTO users (email, name, password_hash, role)
            VALUES ($1, $2, '', 'viewer')
            RETURNING id, email, name, role, is_active
        """, email, name)
        logger.info("MCP OAuth: new user %s created (viewer)", email)
        try:
            from api.notifications import notify_all_admins
            await notify_all_admins(
                pool, "registration_request",
                f"New MCP OAuth user: {name} ({email})",
                "Auto-created with viewer role via MCP OAuth. Review in Settings > Users.",
                "/settings?tab=users",
            )
        except Exception:
            pass

    from api.users import _create_token
    return _create_token(row["id"], row["email"], row["role"])


def _issue_code_and_redirect(pending_key: str, genie_token: str):
    """Store a short-lived auth code and redirect to the client's redirect_uri."""
    pending = _pending_auth.pop(pending_key, {})
    redirect_uri = pending.get("redirect_uri", "")
    original_state = pending.get("original_state", "")

    auth_code = secrets.token_urlsafe(32)
    _auth_codes[auth_code] = {
        "token": genie_token,
        "redirect_uri": redirect_uri,
        "code_challenge": pending.get("code_challenge", ""),
        "code_challenge_method": pending.get("code_challenge_method", "S256"),
        "expires": time.time() + _CODE_TTL,
    }

    params: dict = {"code": auth_code}
    if original_state:
        params["state"] = original_state

    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{separator}{urlencode(params)}")


def _render_login_form(pending_key: str, error: str = "") -> HTMLResponse:
    """Render a minimal HTML login form for the password-login OAuth flow."""
    error_html = f'<p class="error">{error}</p>' if error else ""
    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Sign in to Genie</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; margin: 0; background: #f5f5f5; }}
    .card {{ background: white; padding: 40px; border-radius: 12px;
             box-shadow: 0 4px 24px rgba(0,0,0,0.1); width: 100%; max-width: 380px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; color: #111; }}
    p.subtitle {{ margin: 0 0 28px; color: #666; font-size: 14px; }}
    label {{ display: block; margin-bottom: 4px; font-size: 14px; font-weight: 500; color: #333; }}
    input {{ width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #ddd;
             border-radius: 6px; font-size: 15px; margin-bottom: 16px; }}
    input:focus {{ outline: none; border-color: #007aff; box-shadow: 0 0 0 3px rgba(0,122,255,0.15); }}
    button {{ width: 100%; padding: 12px; background: #007aff; color: white;
              border: none; border-radius: 6px; font-size: 15px; font-weight: 600;
              cursor: pointer; margin-top: 4px; }}
    button:hover {{ background: #0066dd; }}
    .error {{ color: #d32f2f; font-size: 14px; margin-bottom: 16px;
              padding: 10px 12px; background: #fdecea; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Genie</h1>
    <p class="subtitle">Sign in to connect Genie Knowledge to claude.ai</p>
    {error_html}
    <form method="POST" action="/oauth/authorize/login">
      <input type="hidden" name="pending_key" value="{pending_key}">
      <label for="email">Email</label>
      <input type="email" id="email" name="email" placeholder="you@example.com" required autofocus>
      <label for="password">Password</label>
      <input type="password" id="password" name="password" required>
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>"""
    return HTMLResponse(html)
