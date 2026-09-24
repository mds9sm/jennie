"""
DOMO API Client — direct REST calls using OAuth client credentials.

Auth: Same client_id/client_secret as Airflow DOMO_REFRESH DAGs.

STRICTLY READ-ONLY:
- Dataset search, metadata, schema (GET only)
- SQL SELECT queries against datasets
- Refresh execution history (GET only)
- NO writes, NO triggers, NO modifications to any DOMO resource

Credentials stored encrypted in postgres credential_cache via Settings → Connection.
Credentials NEVER logged.
"""

import base64
import logging
import os
from typing import Any

import requests
import urllib3

logger = logging.getLogger("genie.domo")

# Suppress SSL warnings for DOMO API (corporate environment, container CA cert issues)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Use verify=False only for DOMO API calls (container SSL cert chain incomplete)
_VERIFY_SSL = os.environ.get("DOMO_VERIFY_SSL", "false").lower() == "true"

# Module-level state
_access_token: str = ""
_client_id: str = ""
_client_secret: str = ""
_api_host: str = "api.domo.com"
_configured: bool = False


def configure(client_id: str, client_secret: str, api_host: str = "api.domo.com"):
    """Set DOMO credentials. Does NOT log credentials."""
    global _client_id, _client_secret, _api_host, _configured
    _client_id = client_id
    _client_secret = client_secret
    _api_host = api_host
    _configured = bool(client_id and client_secret)
    if _configured:
        _renew_token()
        logger.info("DOMO client configured (read-only)")


def is_configured() -> bool:
    return _configured


def _renew_token():
    """Get OAuth access token using client credentials."""
    global _access_token
    if not _client_id or not _client_secret:
        return
    try:
        auth = base64.b64encode(f"{_client_id}:{_client_secret}".encode()).decode()
        resp = requests.get(
            f"https://{_api_host}/oauth/token?grant_type=client_credentials",
            headers={"Authorization": f"Basic {auth}"},
            timeout=10,
            verify=_VERIFY_SSL,
        )
        if resp.status_code == 200:
            _access_token = resp.json().get("access_token", "")
        else:
            logger.error("DOMO token renewal failed: %d", resp.status_code)
    except Exception as e:
        logger.error("DOMO token renewal error: %s", str(e)[:100])


def _api(method: str, path: str, **kwargs) -> Any:
    """Make a DOMO API call. Auto-renews token on 401."""
    global _access_token
    if not _configured:
        return {"error": "DOMO not configured. Add client credentials in Settings → Connection."}

    if not _access_token:
        _renew_token()
    if not _access_token:
        return {"error": "DOMO authentication failed. Check credentials."}

    url = f"https://{_api_host}{path}"
    headers = {"Authorization": f"bearer {_access_token}", "Content-Type": "application/json"}

    try:
        resp = requests.request(method, url, headers=headers, timeout=15, verify=_VERIFY_SSL, **kwargs)

        # Auto-renew on 401
        if resp.status_code == 401:
            _renew_token()
            if _access_token:
                headers["Authorization"] = f"bearer {_access_token}"
                resp = requests.request(method, url, headers=headers, timeout=15, verify=_VERIFY_SSL, **kwargs)

        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            return {"error": f"DOMO resource not found: {path}"}
        else:
            return {"error": f"DOMO API error {resp.status_code}: {resp.text[:200]}"}
    except requests.Timeout:
        return {"error": "DOMO API timeout (15s)"}
    except Exception as e:
        return {"error": f"DOMO API call failed: {str(e)[:200]}"}


# ============================================================
# Dataset operations (what agents use) — ALL READ-ONLY
# ============================================================

def search_datasets(query: str, limit: int = 20) -> dict:
    """Search DOMO datasets by name."""
    # List datasets and filter (DOMO search API requires different auth scope)
    data = _api("GET", f"/v1/datasets?limit=50&offset=0&sort=name")
    if isinstance(data, dict) and "error" in data:
        return data
    if not isinstance(data, list):
        return {"query": query, "count": 0, "datasets": []}
    query_lower = query.lower()
    matches = [d for d in data if query_lower in (d.get("name", "") or "").lower()]
    return {
        "query": query,
        "count": len(matches),
        "datasets": [
            {
                "id": d.get("id", ""),
                "name": d.get("name", ""),
                "owner": d.get("owner", {}).get("name", "") if isinstance(d.get("owner"), dict) else "",
                "rows": d.get("rows", 0),
                "updated_at": d.get("updatedAt", ""),
            }
            for d in matches[:limit]
        ],
    }


def get_dataset_metadata(dataset_id: str) -> dict:
    """Get metadata for a DOMO dataset — owner, name, dates, row/column counts."""
    data = _api("GET", f"/v1/datasets/{dataset_id}")
    if isinstance(data, dict) and "error" in data:
        return data
    return {
        "dataset_id": dataset_id,
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "owner": data.get("owner", {}).get("name", "") if isinstance(data.get("owner"), dict) else "",
        "created_at": data.get("createdAt", ""),
        "updated_at": data.get("updatedAt", ""),
        "rows": data.get("rows", 0),
        "columns": data.get("columns", 0),
        "data_provider_type": data.get("dataProviderType", ""),
    }


def get_dataset_schema(dataset_id: str) -> dict:
    """Get column schema for a DOMO dataset."""
    data = _api("GET", f"/v1/datasets/{dataset_id}")
    if isinstance(data, dict) and "error" in data:
        return data
    columns = []
    for col in data.get("schema", {}).get("columns", []):
        columns.append({"name": col.get("name", ""), "type": col.get("type", "")})
    return {
        "dataset_id": dataset_id,
        "name": data.get("name", ""),
        "columns": columns,
        "column_count": len(columns),
    }


def list_dashboards(limit: int = 50) -> dict:
    """List DOMO dashboards (pages) with card counts. READ-ONLY."""
    data = _api("GET", f"/v1/pages?limit={limit}&offset=0")
    if isinstance(data, dict) and "error" in data:
        return data
    if not isinstance(data, list):
        return {"dashboards": [], "count": 0}
    dashboards = []
    for p in data:
        # Get detail for card count (list endpoint doesn't include cardIds)
        detail = _api("GET", f"/v1/pages/{p['id']}")
        card_ids = detail.get("cardIds", []) if isinstance(detail, dict) and "error" not in detail else []
        dashboards.append({
            "id": p.get("id"),
            "name": p.get("name", ""),
            "card_count": len(card_ids),
            "children": len(detail.get("children", [])) if isinstance(detail, dict) else 0,
        })
    return {"dashboards": dashboards, "count": len(dashboards)}


def get_dashboard_detail(page_id: str) -> dict:
    """Get a dashboard's cards with titles and types. READ-ONLY."""
    data = _api("GET", f"/v1/pages/{page_id}")
    if isinstance(data, dict) and "error" in data:
        return data
    card_ids = data.get("cardIds", [])
    cards = []
    for cid in card_ids[:50]:  # cap at 50 cards
        card_data = _api("GET", f"/v1/cards/{cid}")
        if isinstance(card_data, dict) and "error" not in card_data:
            cards.append({
                "id": cid,
                "title": card_data.get("cardTitle", ""),
                "type": card_data.get("type", ""),
                "dataset_id": card_data.get("dataSourceId", ""),
            })
    return {
        "page_id": page_id,
        "name": data.get("name", ""),
        "cards": cards,
        "card_count": len(cards),
        "children": [
            {"id": c.get("id"), "name": c.get("name", "")}
            for c in data.get("children", [])
        ],
    }


def query_dataset(dataset_id: str, sql: str) -> dict:
    """Execute a read-only SQL query against a DOMO dataset. READ-ONLY."""
    data = _api("POST", f"/v1/datasets/query/execute/{dataset_id}", json={"sql": sql})
    if isinstance(data, dict) and "error" in data:
        return data
    columns = data.get("columns", [])
    rows = data.get("rows", [])
    return {
        "dataset_id": dataset_id,
        "columns": columns,
        "rows": rows[:500],
        "row_count": len(rows),
        "truncated": len(rows) > 500,
    }
