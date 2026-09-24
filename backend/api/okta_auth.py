"""
Okta OIDC Authentication — SSO login for the organization employees.

Flow:
1. User clicks "Sign in with Okta" → redirected to Okta authorize URL
2. User authenticates (Okta handles MFA)
3. Okta redirects back with auth code
4. Backend exchanges code for tokens → gets user info (email, name)
5. If first login → needs onboarding (name, team, persona)
6. Creates/updates user, issues app auth token

Requires: OKTA_CLIENT_ID, OKTA_CLIENT_SECRET, OKTA_ISSUER in .env
Feature-flagged: falls back to password login if not configured.
"""
import asyncio
import logging
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from config import config

logger = logging.getLogger("genie.okta_auth")
router = APIRouter()


def _okta_configured() -> bool:
    return bool(getattr(config, "OKTA_CLIENT_ID", "") and getattr(config, "OKTA_ISSUER", ""))


@router.get("/config")
async def okta_config():
    """Return Okta config for the frontend (public — no secrets)."""
    if not _okta_configured():
        return {"enabled": False}
    return {
        "enabled": True,
        "issuer": config.OKTA_ISSUER,
        "client_id": config.OKTA_CLIENT_ID,
        "redirect_uri": f"{getattr(config, 'APP_URL', 'https://genie.example.com')}/auth/callback",
    }


@router.get("/authorize")
async def authorize():
    """Generate Okta authorization URL."""
    if not _okta_configured():
        raise HTTPException(400, "Okta not configured")

    state = secrets.token_urlsafe(32)
    # Store state for CSRF protection (in-memory for now)
    _pending_states[state] = True

    params = {
        "client_id": config.OKTA_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": f"{getattr(config, 'APP_URL', 'https://genie.example.com')}/auth/callback",
        "state": state,
    }
    auth_url = f"{config.OKTA_ISSUER}/v1/authorize?{urlencode(params)}"
    return {"authorize_url": auth_url, "state": state}


# In-memory CSRF state store
_pending_states: dict[str, bool] = {}


class CallbackRequest(BaseModel):
    code: str
    state: str


@router.post("/callback")
async def callback(body: CallbackRequest, request: Request):
    """Exchange auth code for tokens, get user info, create/login user."""
    if not _okta_configured():
        raise HTTPException(400, "Okta not configured")

    # Verify CSRF state
    if body.state not in _pending_states:
        raise HTTPException(400, "Invalid state parameter")
    del _pending_states[body.state]

    # Exchange code for tokens (worker thread — never block the event loop on Okta)
    token_url = f"{config.OKTA_ISSUER}/v1/token"
    token_resp = await asyncio.to_thread(requests.post, token_url, data={
        "grant_type": "authorization_code",
        "code": body.code,
        "redirect_uri": f"{getattr(config, 'APP_URL', 'https://genie.example.com')}/auth/callback",
        "client_id": config.OKTA_CLIENT_ID,
        "client_secret": config.OKTA_CLIENT_SECRET,
    }, timeout=10)

    if token_resp.status_code != 200:
        logger.error("Okta token exchange failed: %s", token_resp.text[:200])
        raise HTTPException(400, "Okta authentication failed")

    tokens = token_resp.json()
    access_token = tokens.get("access_token", "")

    # Get user info
    userinfo_url = f"{config.OKTA_ISSUER}/v1/userinfo"
    userinfo_resp = await asyncio.to_thread(requests.get, userinfo_url, headers={
        "Authorization": f"Bearer {access_token}"
    }, timeout=10)

    if userinfo_resp.status_code != 200:
        raise HTTPException(400, "Failed to get user info from Okta")

    userinfo = userinfo_resp.json()
    email = userinfo.get("email", "").lower()
    name = userinfo.get("name", "") or userinfo.get("preferred_username", "")

    if not email:
        raise HTTPException(400, "No email in Okta profile")

    if not email.endswith("@example.com"):
        raise HTTPException(403, "Only @example.com accounts are allowed")

    pool = request.app.state.db_pool

    # Check if user exists
    row = await pool.fetchrow(
        "SELECT id, email, name, role, is_active, team, pillar FROM users WHERE email = $1", email
    )

    if row and not row["is_active"]:
        raise HTTPException(403, "Account is deactivated")

    needs_onboarding = False
    if not row:
        # First-time user — create with viewer role, needs onboarding
        row = await pool.fetchrow("""
            INSERT INTO users (email, name, password_hash, role)
            VALUES ($1, $2, '', 'viewer')
            RETURNING id, email, name, role, is_active, team, pillar
        """, email, name)
        needs_onboarding = True
        logger.info("New Okta user: %s (%s) — needs onboarding", email, name)

        # Notify admins
        try:
            from api.notifications import notify_all_admins
            await notify_all_admins(pool, "registration_request",
                f"New user signed in via Okta: {name} ({email})",
                "Auto-created with viewer role. Review in Settings > Users.",
                "/settings?tab=users")
        except Exception:
            pass
    else:
        # Check if onboarding was completed (has team set)
        needs_onboarding = not row.get("team")

    # Generate app auth token
    from api.users import _create_token, ROLE_PERMISSIONS
    token = _create_token(row["id"], row["email"], row["role"])

    return {
        "token": token,
        "needs_onboarding": needs_onboarding,
        "user": {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "team": row.get("team"),
            "pillar": row.get("pillar"),
            "permissions": ROLE_PERMISSIONS.get(row["role"], {}),
        },
    }


class OnboardingRequest(BaseModel):
    name: str
    team: str
    persona: str = "engineer"
    pillar: str = ""


@router.post("/onboard")
async def complete_onboarding(body: OnboardingRequest, request: Request):
    """Complete first-time user onboarding after Okta login."""
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    pool = request.app.state.db_pool
    await pool.execute("""
        UPDATE users SET name = $2, team = $3, pillar = $4, updated_at = NOW()
        WHERE id = $1
    """, user["user_id"], body.name, body.team, body.pillar)

    # Save persona as user setting
    await pool.execute("""
        INSERT INTO user_settings (user_id, session_id, persona, updated_at)
        VALUES ($1, $1, $2, NOW())
        ON CONFLICT (user_id) DO UPDATE SET persona = $2, updated_at = NOW()
    """, str(user["user_id"]), body.persona)

    return {"status": "onboarded"}


class RoleChangeRequest(BaseModel):
    requested_role: str
    reason: str = ""


@router.post("/request-role-change")
async def request_role_change(body: RoleChangeRequest, request: Request):
    """Request a role upgrade. Sends notification to admins."""
    from api.users import get_current_user, ROLE_PERMISSIONS
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")

    if body.requested_role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"Invalid role: {body.requested_role}")

    pool = request.app.state.db_pool
    user_row = await pool.fetchrow("SELECT email, name, role FROM users WHERE id = $1", user["user_id"])

    if user_row["role"] == body.requested_role:
        raise HTTPException(400, "You already have this role")

    # Create feedback ticket for admin review
    from api.notifications import notify_all_admins
    await notify_all_admins(pool, "role_change_request",
        f"Role change request: {user_row['name']} ({user_row['email']})",
        f"Current: {user_row['role']} -> Requested: {body.requested_role}\nReason: {body.reason or 'Not provided'}",
        "/settings?tab=users")

    # Also create a feedback ticket
    admin_row = await pool.fetchrow("SELECT email FROM users WHERE role = 'admin' AND is_active = true ORDER BY id LIMIT 1")
    await pool.execute("""
        INSERT INTO feedback_tickets (title, description, status, priority, category, created_by, assigned_to)
        VALUES ($1, $2, 'open', 'medium', 'other', $3, $4)
    """,
        f"Role change: {user_row['name']} wants {body.requested_role}",
        f"User: {user_row['email']}\nCurrent role: {user_row['role']}\nRequested: {body.requested_role}\nReason: {body.reason}",
        user_row["email"],
        admin_row["email"] if admin_row else None,
    )

    return {"status": "requested", "message": "Role change request sent to admin"}


@router.get("/roles")
async def list_roles_with_capabilities():
    """List all roles with their capabilities — for display in UI."""
    from api.users import ROLE_PERMISSIONS

    ROLE_DESCRIPTIONS = {
        "viewer": "Read-only access. Chat with Genie, view glossary and lineage.",
        "analyst": "Query nonprod Redshift, submit glossary definitions, browse repo files.",
        "engineer": "Query prod, profile tables, review glossary, git operations, build KB.",
        "admin": "Full access including connections, user management, ANALYZE, and merge glossary.",
    }

    CAPABILITY_LABELS = {
        "chat": "Chat with AI",
        "query_np": "Query Redshift (nonprod)",
        "query_prd": "Query Redshift (prod)",
        "table_ops_view": "View table operations",
        "table_ops_profile": "Profile tables",
        "table_ops_analyze": "Analyze tables (prod)",
        "table_ops_discover": "Discover tables",
        "glossary_view": "View glossary",
        "glossary_submit": "Submit glossary entries",
        "glossary_review": "Review glossary entries",
        "glossary_merge": "Merge glossary entries",
        "glossary_assign": "Assign glossary reviewers",
        "kb_build": "Build knowledge base",
        "admin_console": "Admin settings (connection, agents)",
        "user_management": "Manage users",
        "git_browse": "Browse repo files",
        "git_edit": "Edit repo files",
        "git_commit": "Commit and push",
        "lineage": "View lineage",
        "settings": "Access settings",
    }

    roles = []
    for role_name, perms in ROLE_PERMISSIONS.items():
        capabilities = []
        for perm, granted in perms.items():
            capabilities.append({
                "permission": perm,
                "label": CAPABILITY_LABELS.get(perm, perm),
                "granted": granted,
            })
        roles.append({
            "role": role_name,
            "description": ROLE_DESCRIPTIONS.get(role_name, ""),
            "capabilities": capabilities,
        })
    return roles
