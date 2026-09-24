"""
Table Ownership — primary/secondary owner + business area per warehouse table/view.

Backs the Catalog page (frontend/src/components/catalog/CatalogBrowser.tsx).
Edits are restricted to non-viewer roles. Reads are open to any authenticated user.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from api.users import get_current_user
from engine.pillar import get_all_pillars

logger = logging.getLogger("genie.table_ownership")
router = APIRouter()


def _require_auth(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


def _require_editor(request: Request) -> dict:
    user = _require_auth(request)
    if user.get("role") == "viewer":
        raise HTTPException(403, "Viewer role cannot edit table ownership")
    return user


class OwnershipUpsert(BaseModel):
    database: str
    schema_name: str
    table: str
    primary_owner: Optional[str] = None
    secondary_owner: Optional[str] = None
    business_area: Optional[str] = None


@router.put("")
@router.put("/")
async def upsert_ownership(body: OwnershipUpsert, request: Request):
    """Upsert ownership fields for a single (database, schema, table). Returns the persisted row."""
    user = _require_editor(request)

    # Normalize empty strings to NULL so the dropdown's "clear" action works.
    primary = (body.primary_owner or "").strip() or None
    secondary = (body.secondary_owner or "").strip() or None
    area = (body.business_area or "").strip() or None

    pool = request.app.state.db_pool
    row = await pool.fetchrow("""
        INSERT INTO table_ownership
            (database, schema_name, table_name, primary_owner, secondary_owner, business_area, updated_by_user_id, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT (database, schema_name, table_name) DO UPDATE SET
            primary_owner = EXCLUDED.primary_owner,
            secondary_owner = EXCLUDED.secondary_owner,
            business_area = EXCLUDED.business_area,
            updated_by_user_id = EXCLUDED.updated_by_user_id,
            updated_at = NOW()
        RETURNING database, schema_name, table_name, primary_owner, secondary_owner, business_area, updated_at
    """, body.database, body.schema_name, body.table, primary, secondary, area, int(user["user_id"]))

    logger.info(
        "Ownership upsert by %s on %s.%s.%s (primary=%s, secondary=%s, area=%s)",
        user.get("email"), body.database, body.schema_name, body.table, primary, secondary, area,
    )

    return {
        "database": row["database"],
        "schema": row["schema_name"],
        "table": row["table_name"],
        "primary_owner": row["primary_owner"],
        "secondary_owner": row["secondary_owner"],
        "business_area": row["business_area"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "updated_by": user.get("email"),
    }


@router.get("/options")
async def get_options(request: Request):
    """
    Dropdown options for the Catalog page.
    - owners: Genie team members + any free-text owner names already saved
    - business_areas: 8 seeded the organization pillar names + any free-text areas already saved
    """
    _require_auth(request)
    pool = request.app.state.db_pool

    user_rows = await pool.fetch(
        "SELECT id, name, email, role FROM users WHERE is_active = true ORDER BY name"
    )

    owner_rows = await pool.fetch("""
        SELECT DISTINCT name FROM (
            SELECT primary_owner AS name FROM table_ownership WHERE primary_owner IS NOT NULL AND primary_owner <> ''
            UNION
            SELECT secondary_owner AS name FROM table_ownership WHERE secondary_owner IS NOT NULL AND secondary_owner <> ''
        ) t
        ORDER BY name
    """)

    area_rows = await pool.fetch("""
        SELECT DISTINCT business_area FROM table_ownership
        WHERE business_area IS NOT NULL AND business_area <> ''
        ORDER BY business_area
    """)

    owners: list[dict] = []
    seen: set[str] = set()
    for u in user_rows:
        if u["name"] and u["name"] not in seen:
            owners.append({"name": u["name"], "email": u["email"], "role": u["role"], "source": "user"})
            seen.add(u["name"])
    for o in owner_rows:
        if o["name"] and o["name"] not in seen:
            owners.append({"name": o["name"], "email": None, "role": None, "source": "free_text"})
            seen.add(o["name"])

    seeded_areas = [p["name"] for p in get_all_pillars()]
    area_seen: set[str] = set()
    business_areas: list[str] = []
    for name in seeded_areas:
        if name and name not in area_seen:
            business_areas.append(name)
            area_seen.add(name)
    for r in area_rows:
        name = r["business_area"]
        if name and name not in area_seen:
            business_areas.append(name)
            area_seen.add(name)

    return {"owners": owners, "business_areas": business_areas}
