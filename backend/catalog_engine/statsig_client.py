"""
Statsig Console API Client — fetches experiment metadata for KB enrichment.

Source: https://docs.statsig.com/console-api/introduction
Auth: Console API Key (stored in postgres credential_cache via Settings → Connection)

Fetches:
- Experiments: name, status, hypothesis, target audience, metrics, results
- Feature gates: name, enabled %, rules
- Metrics: definitions used in experiments

All READ-ONLY. Never modifies experiments or gates.
"""

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger("genie.statsig")

_api_key: str = ""
_base_url: str = "https://statsigapi.net/console/v1"
_configured: bool = False

# Corporate proxy SSL
_VERIFY_SSL = os.environ.get("STATSIG_VERIFY_SSL", os.environ.get("DOMO_VERIFY_SSL", "false")).lower() == "true"


def configure(api_key: str):
    """Set Statsig Console API key."""
    global _api_key, _configured
    _api_key = api_key
    _configured = bool(api_key)
    if _configured:
        logger.info("Statsig client configured (read-only)")


def is_configured() -> bool:
    return _configured


def _api(method: str, path: str, **kwargs) -> Any:
    """Make a Statsig Console API call. STRICTLY READ-ONLY — only GET allowed."""
    if method.upper() != "GET":
        return {"error": f"Statsig client is read-only. {method} not allowed."}
    if not _configured:
        return {"error": "Statsig not configured. Add Console API key in Settings → Connection."}

    url = f"{_base_url}{path}"
    headers = {
        "statsig-api-key": _api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.request(method, url, headers=headers, timeout=15, verify=_VERIFY_SSL, **kwargs)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            return {"error": "Statsig authentication failed. Check Console API key."}
        else:
            return {"error": f"Statsig API error {resp.status_code}: {resp.text[:200]}"}
    except requests.Timeout:
        return {"error": "Statsig API timeout (15s)"}
    except Exception as e:
        return {"error": f"Statsig API failed: {str(e)[:200]}"}


# ============================================================
# Experiments
# ============================================================

def list_experiments(limit: int = 100) -> dict:
    """List all experiments with status and basic info."""
    data = _api("GET", "/experiments")
    if isinstance(data, dict) and "error" in data:
        return data

    experiments = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(experiments, list):
        experiments = []

    return {
        "count": len(experiments),
        "experiments": [
            {
                "id": e.get("id", ""),
                "name": e.get("name", ""),
                "description": e.get("description", ""),
                "status": e.get("status", ""),
                "hypothesis": e.get("hypothesis", ""),
                "launched_at": e.get("startTime", e.get("launchedTime", "")),
                "type": e.get("type", ""),
                "groups": [g.get("name", "") for g in e.get("groups", [])],
            }
            for e in experiments[:limit]
        ],
    }


def get_experiment(experiment_id: str) -> dict:
    """Get full experiment details including groups, metrics, and targeting."""
    data = _api("GET", f"/experiments/{experiment_id}")
    if isinstance(data, dict) and "error" in data:
        return data

    exp = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(exp, dict):
        return {"error": f"Unexpected response for experiment {experiment_id}"}

    return {
        "id": exp.get("id", ""),
        "name": exp.get("name", ""),
        "description": exp.get("description", ""),
        "status": exp.get("status", ""),
        "hypothesis": exp.get("hypothesis", ""),
        "type": exp.get("type", ""),
        "groups": [
            {
                "name": g.get("name", ""),
                "size": g.get("size", 0),
                "id": g.get("id", ""),
            }
            for g in exp.get("groups", [])
        ],
        "primary_metrics": [m.get("name", "") for m in exp.get("primaryMetrics", exp.get("primary_metrics", []))],
        "secondary_metrics": [m.get("name", "") for m in exp.get("secondaryMetrics", exp.get("secondary_metrics", []))],
        "targeting": exp.get("targetingGate", ""),
        "allocation": exp.get("allocation", 0),
        "launched_at": exp.get("startTime", exp.get("launchedTime", "")),
    }


# ============================================================
# Feature Gates
# ============================================================

def list_gates(limit: int = 100) -> dict:
    """List all feature gates."""
    data = _api("GET", "/gates")
    if isinstance(data, dict) and "error" in data:
        return data

    gates = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(gates, list):
        gates = []

    return {
        "count": len(gates),
        "gates": [
            {
                "id": g.get("id", ""),
                "name": g.get("name", ""),
                "description": g.get("description", ""),
                "enabled": g.get("enabled", False),
                "type": g.get("type", ""),
            }
            for g in gates[:limit]
        ],
    }


# ============================================================
# KB Integration: fetch all and write to knowledge/
# ============================================================

def fetch_all_for_kb() -> dict:
    """Fetch all Statsig data for KB enrichment."""
    result = {
        "experiments": [],
        "gates": [],
        "experiment_count": 0,
        "gate_count": 0,
    }

    exp_data = list_experiments(limit=500)
    if "error" not in exp_data:
        result["experiments"] = exp_data.get("experiments", [])
        result["experiment_count"] = exp_data.get("count", 0)
        logger.info("Statsig: fetched %d experiments", result["experiment_count"])

    gate_data = list_gates(limit=500)
    if "error" not in gate_data:
        result["gates"] = gate_data.get("gates", [])
        result["gate_count"] = gate_data.get("count", 0)
        logger.info("Statsig: fetched %d feature gates", result["gate_count"])

    return result


def write_statsig_kb(data: dict, knowledge_dir: str) -> str:
    """Write Statsig data to knowledge/statsig.json."""
    from pathlib import Path
    path = Path(knowledge_dir) / "statsig.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Wrote statsig.json: %d experiments, %d gates",
                data.get("experiment_count", 0), data.get("gate_count", 0))
    return str(path)
