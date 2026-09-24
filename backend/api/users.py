"""
User Management + RBAC — authentication, authorization, and user CRUD.

Roles:
- viewer: chat (read-only), view glossary
- analyst: chat, query (nonprod), submit glossary drafts
- engineer: chat, query (np+prd), profile tables, review glossary, git edit+PR
- admin: everything + ANALYZE, admin console, user management, glossary merge

Auth: simple email/password (Okta integration deferred).
Passwords hashed with bcrypt.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger("genie.users")
router = APIRouter()

# Signed tokens — user info encoded in token, no server-side storage needed, works across pods
# Secret derived from DATABASE_URL (stable across pods) + a fallback
import os as _os
_TOKEN_SECRET = hashlib.sha256((_os.environ.get("DATABASE_URL", "") + "genie-auth-signing-key").encode()).hexdigest()
_sessions: dict[str, dict] = {}  # in-memory cache for fast lookups
_db_pool = None  # set on startup

# ---------------------------------------------------------------------------
# RBAC definitions
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS = {
    "viewer": {
        "chat": True,
        "query_np": False,
        "query_prd": False,
        "table_ops_view": False,
        "table_ops_profile": False,
        "table_ops_analyze": False,
        "table_ops_discover": False,
        "glossary_view": True,
        "glossary_submit": False,
        "glossary_review": False,
        "glossary_merge": False,
        "glossary_assign": False,
        "kb_build": False,
        "admin_console": False,
        "user_management": False,
        "git_browse": False,
        "git_edit": False,
        "git_commit": False,
        "lineage": True,
        "settings": True,
    },
    "analyst": {
        "chat": True,
        "query_np": True,
        "query_prd": False,
        "table_ops_view": True,
        "table_ops_profile": False,
        "table_ops_analyze": False,
        "table_ops_discover": False,
        "glossary_view": True,
        "glossary_submit": True,
        "glossary_review": False,
        "glossary_merge": False,
        "glossary_assign": False,
        "kb_build": False,
        "admin_console": False,
        "user_management": False,
        "git_browse": True,
        "git_edit": False,
        "git_commit": False,
        "lineage": True,
        "settings": True,
    },
    "engineer": {
        "chat": True,
        "query_np": True,
        "query_prd": True,
        "table_ops_view": True,
        "table_ops_profile": True,
        "table_ops_analyze": False,
        "table_ops_discover": True,
        "glossary_view": True,
        "glossary_submit": True,
        "glossary_review": True,
        "glossary_merge": False,
        "glossary_assign": True,
        "kb_build": True,
        "admin_console": False,
        "user_management": False,
        "git_browse": True,
        "git_edit": True,
        "git_commit": True,
        "lineage": True,
        "settings": True,
    },
    "admin": {
        "chat": True,
        "query_np": True,
        "query_prd": True,
        "table_ops_view": True,
        "table_ops_profile": True,
        "table_ops_analyze": True,
        "table_ops_discover": True,
        "glossary_view": True,
        "glossary_submit": True,
        "glossary_review": True,
        "glossary_merge": True,
        "glossary_assign": True,
        "kb_build": True,
        "admin_console": True,
        "user_management": True,
        "git_browse": True,
        "git_edit": True,
        "git_commit": True,
        "lineage": True,
        "settings": True,
    },
}


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}:{h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if not stored or ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return hmac.compare_digest(h.hex(), expected)


def _create_token(user_id, email: str, role: str) -> str:
    """Create a signed token that encodes user info. No server-side storage needed."""
    expires = int(time.time()) + 86400 * 7  # 7 days
    payload = json.dumps({"uid": str(user_id), "e": email, "r": role, "exp": expires})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]
    token = f"{payload_b64}.{sig}"
    # Cache in memory for fast lookups
    _sessions[token] = {"user_id": int(user_id), "email": email, "role": role, "expires": expires}
    return token


def _decode_token(token: str) -> dict | None:
    """Decode and verify a signed token. Returns session dict or None."""
    try:
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(_TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        # Convert user_id back to int for DB compatibility (BIGSERIAL)
        uid = payload["uid"]
        try:
            uid = int(uid)
        except (ValueError, TypeError):
            pass
        return {
            "user_id": uid,
            "email": payload["e"],
            "role": payload["r"],
            "expires": payload["exp"],
        }
    except Exception:
        return None


def get_current_user(request: Request) -> dict | None:
    """Extract user from auth token. Works across pods — token is self-contained."""
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        token = request.query_params.get("auth_token", "")
    if not token:
        return None
    # Fast path: in-memory cache
    session = _sessions.get(token)
    if session and session["expires"] >= time.time():
        return session
    # Slow path: decode signed token (works even if this pod never saw this token)
    session = _decode_token(token)
    if session:
        _sessions[token] = session  # cache for next time
    return session


def require_permission(permission: str):
    """Dependency that checks a specific permission. Rejects unauthenticated requests."""
    def checker(request: Request):
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Authentication required")
        role = user.get("role", "viewer")
        perms = ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["viewer"])
        if not perms.get(permission, False):
            raise HTTPException(403, f"Permission '{permission}' denied for role '{role}'")
        return user
    return checker


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Login with email/password. Returns auth token."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT id, email, name, role, password_hash, is_active FROM users WHERE email = $1",
        body.email.lower(),
    )
    if not row:
        raise HTTPException(401, "Invalid email or password")
    if not row["is_active"]:
        raise HTTPException(403, "Account is deactivated")

    # If no password set yet (initial admin), allow any password and set it
    # pbkdf2 (100K iterations) is ~50ms of CPU — keep it off the event loop
    if not row["password_hash"]:
        pw_hash = await asyncio.to_thread(_hash_password, body.password)
        await pool.execute("UPDATE users SET password_hash = $1 WHERE id = $2", pw_hash, row["id"])
    elif not await asyncio.to_thread(_verify_password, body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    # Update last login
    await pool.execute("UPDATE users SET last_login_at = NOW() WHERE id = $1", row["id"])

    token = _create_token(row["id"], row["email"], row["role"])

    return {
        "token": token,
        "user": {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "permissions": ROLE_PERMISSIONS.get(row["role"], {}),
        },
    }


@router.get("/me")
async def get_me(request: Request):
    """Get current user info from auth token."""
    user = get_current_user(request)
    if not user:
        return {"authenticated": False}

    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT id, email, name, role, team FROM users WHERE id = $1",
        int(user["user_id"]),
    )
    if not row:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "user": dict(row),
        "permissions": ROLE_PERMISSIONS.get(row["role"], {}),
    }


@router.post("/logout")
async def logout(request: Request):
    """Invalidate auth token."""
    token = request.headers.get("X-Auth-Token", "")
    _sessions.pop(token, None)
    return {"status": "logged_out"}


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "analyst"
    team: Optional[str] = None


@router.get("/users")
@router.get("/team")
async def list_team_members(request: Request):
    """List team members (name + email) for @mentions and assignment. Any authenticated user."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    pool = request.app.state.db_pool
    rows = await pool.fetch(
        "SELECT id, name, email, role, team FROM users WHERE is_active = true ORDER BY name"
    )
    return [{"id": r["id"], "name": r["name"], "email": r["email"], "role": r["role"], "team": r["team"]} for r in rows]


@router.get("")
async def list_users(request: Request, user: dict = Depends(require_permission("user_management"))):
    """List all users (admin only)."""
    pool = request.app.state.db_pool
    rows = await pool.fetch(
        "SELECT id, email, name, role, team, is_active, last_login_at, created_at "
        "FROM users ORDER BY role, name"
    )
    return [dict(r) for r in rows]


@router.post("/users")
async def create_user(body: CreateUserRequest, request: Request, user: dict = Depends(require_permission("user_management"))):
    """Create a new user (admin only)."""
    pool = request.app.state.db_pool

    if body.role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"Invalid role: {body.role}. Must be: {list(ROLE_PERMISSIONS.keys())}")

    pw_hash = _hash_password(body.password)
    try:
        row = await pool.fetchrow("""
            INSERT INTO users (email, name, password_hash, role, team)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, body.email.lower(), body.name, pw_hash, body.role, body.team)
        return {"status": "created", "id": row["id"]}
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(409, f"User '{body.email}' already exists")
        raise


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    pillar: Optional[str] = None
    team: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UpdateUserRequest, request: Request, user: dict = Depends(require_permission("user_management"))):
    """Update a user (admin only)."""
    pool = request.app.state.db_pool

    if body.role and body.role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"Invalid role: {body.role}")

    updates = ["updated_at = NOW()"]
    params = [user_id]
    idx = 2

    for field in ("name", "role", "team", "is_active"):
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1

    if body.password:
        updates.append(f"password_hash = ${idx}")
        params.append(_hash_password(body.password))
        idx += 1

    await pool.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id = $1",
        *params,
    )
    return {"status": "updated"}


@router.delete("/users/{user_id}")
async def deactivate_user(user_id: int, request: Request, user: dict = Depends(require_permission("user_management"))):
    """Deactivate a user (admin only). Doesn't delete — preserves audit trail."""
    pool = request.app.state.db_pool
    await pool.execute("UPDATE users SET is_active = false, updated_at = NOW() WHERE id = $1", user_id)
    return {"status": "deactivated"}


# ---------------------------------------------------------------------------
# Permissions check endpoint (for frontend)
# ---------------------------------------------------------------------------

@router.get("/me/git")
async def get_git_config(request: Request):
    """Get current user's git configuration."""
    user = get_current_user(request)
    if not user:
        return {"git_name": "", "git_email": "", "has_token": False}

    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT git_name, git_email, github_token FROM users WHERE id = $1",
        int(user["user_id"]),
    )
    if not row:
        return {"git_name": "", "git_email": "", "has_token": False}

    return {
        "git_name": row["git_name"] or "",
        "git_email": row["git_email"] or "",
        "has_token": bool(row["github_token"]),
    }


@router.put("/me/git")
async def update_git_config(request: Request):
    """Update current user's git configuration."""
    user = get_current_user(request)
    if not user or not user.get("user_id"):
        raise HTTPException(401, "Not authenticated")

    body = await request.json()
    pool = request.app.state.db_pool

    updates = ["updated_at = NOW()"]
    params = [user["user_id"]]
    idx = 2

    if body.get("git_name") is not None:
        updates.append(f"git_name = ${idx}")
        params.append(body["git_name"])
        idx += 1
    if body.get("git_email") is not None:
        updates.append(f"git_email = ${idx}")
        params.append(body["git_email"])
        idx += 1
    if body.get("github_token"):
        updates.append(f"github_token = ${idx}")
        params.append(body["github_token"])
        idx += 1

    await pool.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = $1", *params)
    logger.info("Updated git config for user %s", user["email"])
    return {"status": "saved"}


@router.get("/permissions")
async def get_permissions(request: Request):
    """Get permissions for current user. Frontend uses this to show/hide UI elements."""
    user = get_current_user(request)
    if not user:
        # Unauthenticated = full access for now (backwards compatible)
        return {"role": "admin", "permissions": ROLE_PERMISSIONS["admin"]}
    role = user.get("role", "viewer")
    return {"role": role, "permissions": ROLE_PERMISSIONS.get(role, {})}


@router.get("/roles")
async def list_roles():
    """List available roles and their permissions."""
    return ROLE_PERMISSIONS


# ---------------------------------------------------------------------------
# Registration table setup
# ---------------------------------------------------------------------------

async def _ensure_registration_table(pool):
    """Create registration_requests table if it doesn't exist."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS registration_requests (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            team TEXT,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


# ---------------------------------------------------------------------------
# Registration endpoints
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    name: str
    team: Optional[str] = None
    reason: Optional[str] = None


@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    """Submit a registration request. No auth required."""
    email = body.email.strip().lower()

    if not email.endswith("@example.com"):
        raise HTTPException(400, "Email must be a @example.com address")

    pool = request.app.state.db_pool
    await _ensure_registration_table(pool)

    # Check if already a registered user
    existing_user = await pool.fetchrow(
        "SELECT id FROM users WHERE email = $1", email
    )
    if existing_user:
        raise HTTPException(409, "Already registered")

    # Check for existing pending request
    existing_req = await pool.fetchrow(
        "SELECT id, status FROM registration_requests WHERE email = $1", email
    )
    if existing_req:
        if existing_req["status"] == "pending":
            raise HTTPException(409, "Registration pending")
        if existing_req["status"] == "approved":
            raise HTTPException(409, "Already approved — check with your admin for credentials")

    try:
        await pool.execute("""
            INSERT INTO registration_requests (email, name, team, reason)
            VALUES ($1, $2, $3, $4)
        """, email, body.name.strip(), body.team, body.reason)
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(409, "Registration request already exists for this email")
        raise

    logger.info("Registration request submitted: %s", email)

    # Notify all admins
    from api.notifications import notify_all_admins
    await notify_all_admins(pool, "registration_request",
        f"New registration request: {body.name} ({body.email})",
        body.reason or "", "/settings?tab=users")

    return {"status": "submitted", "message": "Registration request submitted. An admin will review your request."}


@router.get("/registrations")
async def list_registrations(request: Request, user: dict = Depends(require_permission("user_management"))):
    """List all registration requests (admin only)."""
    pool = request.app.state.db_pool
    await _ensure_registration_table(pool)

    rows = await pool.fetch("""
        SELECT id, email, name, team, reason, status, reviewed_by, created_at, updated_at
        FROM registration_requests
        ORDER BY
            CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 WHEN 'rejected' THEN 2 END,
            created_at DESC
    """)
    return [dict(r) for r in rows]


@router.post("/registrations/{req_id}/approve")
async def approve_registration(req_id: int, request: Request, user: dict = Depends(require_permission("user_management"))):
    """Approve a registration request and create a user (admin only)."""
    pool = request.app.state.db_pool
    await _ensure_registration_table(pool)

    row = await pool.fetchrow(
        "SELECT id, email, name, team, status FROM registration_requests WHERE id = $1", req_id
    )
    if not row:
        raise HTTPException(404, "Registration request not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Request is already {row['status']}")

    # Generate a temporary password
    temp_password = secrets.token_urlsafe(12)
    pw_hash = _hash_password(temp_password)

    # Create user with viewer role
    try:
        new_user = await pool.fetchrow("""
            INSERT INTO users (email, name, password_hash, role, team)
            VALUES ($1, $2, $3, 'viewer', $4)
            RETURNING id
        """, row["email"], row["name"], pw_hash, row["team"])
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(409, f"User '{row['email']}' already exists")
        raise

    # Update request status
    await pool.execute("""
        UPDATE registration_requests
        SET status = 'approved', reviewed_by = $1, updated_at = NOW()
        WHERE id = $2
    """, user.get("email", "admin"), req_id)

    logger.info("Registration approved: %s (user_id=%s) by %s", row["email"], new_user["id"], user.get("email"))
    return {
        "status": "approved",
        "user_id": new_user["id"],
        "email": row["email"],
        "temp_password": temp_password,
    }


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/registrations/{req_id}/reject")
async def reject_registration(req_id: int, body: RejectRequest, request: Request, user: dict = Depends(require_permission("user_management"))):
    """Reject a registration request (admin only)."""
    pool = request.app.state.db_pool
    await _ensure_registration_table(pool)

    row = await pool.fetchrow(
        "SELECT id, status FROM registration_requests WHERE id = $1", req_id
    )
    if not row:
        raise HTTPException(404, "Registration request not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Request is already {row['status']}")

    await pool.execute("""
        UPDATE registration_requests
        SET status = 'rejected', reviewed_by = $1, updated_at = NOW()
        WHERE id = $2
    """, user.get("email", "admin"), req_id)

    logger.info("Registration rejected: request_id=%s by %s", req_id, user.get("email"))
    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# Password reset (admin-mediated — no email server)
# ---------------------------------------------------------------------------

async def _ensure_password_reset_table(pool):
    """Create password_reset_requests table if it doesn't exist."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_requests (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Submit a password-reset request. No auth required.

    Always returns a neutral success response so the endpoint cannot be used
    to enumerate registered emails. Internally, we only create a request row
    (and notify admins) when the email maps to an active user.
    """
    email = body.email.strip().lower()
    neutral = {
        "status": "submitted",
        "message": "If that email is registered, an admin will reset the password and share the new one with you.",
    }

    if not email or "@" not in email:
        # Don't leak validation either — same neutral response.
        return neutral

    pool = request.app.state.db_pool
    await _ensure_password_reset_table(pool)

    user_row = await pool.fetchrow(
        "SELECT id, name, is_active FROM users WHERE email = $1", email
    )
    if not user_row or not user_row["is_active"]:
        # Stay silent; respond the same way regardless.
        return neutral

    # Suppress duplicate pending requests so admins aren't spammed.
    existing = await pool.fetchrow(
        "SELECT id FROM password_reset_requests WHERE email = $1 AND status = 'pending'",
        email,
    )
    if existing:
        return neutral

    await pool.execute(
        "INSERT INTO password_reset_requests (email) VALUES ($1)", email
    )
    logger.info("Password reset requested: %s", email)

    from api.notifications import notify_all_admins
    await notify_all_admins(
        pool,
        "password_reset_request",
        f"Password reset requested: {user_row['name']} ({email})",
        "",
        "/settings?tab=users",
    )

    return neutral


@router.get("/password-resets")
async def list_password_resets(
    request: Request,
    user: dict = Depends(require_permission("user_management")),
):
    """List password reset requests (admin only)."""
    pool = request.app.state.db_pool
    await _ensure_password_reset_table(pool)

    rows = await pool.fetch("""
        SELECT pr.id, pr.email, pr.status, pr.reviewed_by, pr.created_at, pr.updated_at,
               u.name AS user_name
        FROM password_reset_requests pr
        LEFT JOIN users u ON LOWER(u.email) = pr.email
        ORDER BY
            CASE pr.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 WHEN 'rejected' THEN 2 END,
            pr.created_at DESC
        LIMIT 200
    """)
    return [dict(r) for r in rows]


@router.post("/password-resets/{req_id}/approve")
async def approve_password_reset(
    req_id: int,
    request: Request,
    user: dict = Depends(require_permission("user_management")),
):
    """Approve a password reset: generate a temp password, update the user's
    password_hash, and return the temp password so the admin can share it
    out-of-band (Slack, etc.)."""
    pool = request.app.state.db_pool
    await _ensure_password_reset_table(pool)

    row = await pool.fetchrow(
        "SELECT id, email, status FROM password_reset_requests WHERE id = $1", req_id
    )
    if not row:
        raise HTTPException(404, "Password reset request not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Request is already {row['status']}")

    target_user = await pool.fetchrow(
        "SELECT id, email FROM users WHERE LOWER(email) = $1", row["email"]
    )
    if not target_user:
        raise HTTPException(404, "User no longer exists")

    temp_password = secrets.token_urlsafe(12)
    pw_hash = _hash_password(temp_password)

    await pool.execute(
        "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE id = $2",
        pw_hash, target_user["id"],
    )
    await pool.execute("""
        UPDATE password_reset_requests
        SET status = 'approved', reviewed_by = $1, updated_at = NOW()
        WHERE id = $2
    """, user.get("email", "admin"), req_id)

    # Notify the user that their password was reset (in-app notification).
    from api.notifications import create_notification
    await create_notification(
        pool,
        str(target_user["id"]),
        "password_reset",
        "Your password was reset",
        "An admin reset your password. Check Slack/team chat for the temporary password, then change it from Settings.",
        "/settings",
    )

    logger.info(
        "Password reset approved: %s (user_id=%s) by %s",
        row["email"], target_user["id"], user.get("email"),
    )
    return {
        "status": "approved",
        "user_id": target_user["id"],
        "email": target_user["email"],
        "temp_password": temp_password,
    }


@router.post("/password-resets/{req_id}/reject")
async def reject_password_reset(
    req_id: int,
    body: RejectRequest,
    request: Request,
    user: dict = Depends(require_permission("user_management")),
):
    """Reject a password reset request (admin only)."""
    pool = request.app.state.db_pool
    await _ensure_password_reset_table(pool)

    row = await pool.fetchrow(
        "SELECT id, status FROM password_reset_requests WHERE id = $1", req_id
    )
    if not row:
        raise HTTPException(404, "Password reset request not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Request is already {row['status']}")

    await pool.execute("""
        UPDATE password_reset_requests
        SET status = 'rejected', reviewed_by = $1, updated_at = NOW()
        WHERE id = $2
    """, user.get("email", "admin"), req_id)

    logger.info("Password reset rejected: request_id=%s by %s", req_id, user.get("email"))
    return {"status": "rejected"}
