"""
Swagger Event Schema Parser — ingests ProductApp event definitions
from the Swagger/OpenAPI spec into the knowledge base.

Source: https://dev55-apis.example.com/events/swagger/v1/swagger.json
These events flow: ProductApp → Kafka → S3 → data_lake → firehose_v3_enriched

Produces: knowledge/event_schemas.json
- Event name → payload fields with types and descriptions
- Used by agents to write precise SQL against SUPER columns in firehose_v3_enriched
"""

import json
import logging
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("genie.catalog_engine.swagger")

DEFAULT_SWAGGER_URL = "https://dev55-apis.example.com/events/swagger/v1/swagger.json"


def fetch_and_parse(swagger_url: str = DEFAULT_SWAGGER_URL, verify_ssl: bool = False) -> dict:
    """
    Fetch Swagger JSON and parse event schemas.

    Returns dict of:
    {
        "event_count": int,
        "events": {
            "CutProjectCompleted": {
                "description": "...",
                "field_count": 10,
                "fields": {
                    "matCount": {"type": "integer", "description": "Count of mats..."},
                    "projectId": {"type": "string", "description": "Cutting project id..."},
                    ...
                }
            },
            ...
        }
    }
    """
    logger.info("Fetching Swagger spec from %s", swagger_url)

    resp = requests.get(swagger_url, timeout=30, verify=verify_ssl)
    if resp.status_code != 200:
        raise RuntimeError(f"Swagger fetch failed: {resp.status_code}")

    spec = resp.json()
    schemas = spec.get("components", {}).get("schemas", {})
    logger.info("Swagger spec loaded: %d schemas", len(schemas))

    events = {}

    for name, schema in schemas.items():
        # Skip attribute/metric schemas — we'll merge them into the event
        if name.endswith("Attributes") or name.endswith("Metrics"):
            continue
        # Skip enums and types
        if schema.get("enum") or name.endswith("Type") or name.endswith("Enum"):
            continue

        event_name = name

        # Get attributes (payload fields)
        attrs_schema = schemas.get(f"{name}Attributes", {})
        attrs_props = attrs_schema.get("properties", {})

        # Get metrics
        metrics_schema = schemas.get(f"{name}Metrics", {})
        metrics_props = metrics_schema.get("properties", {})

        if not attrs_props and not metrics_props:
            # Event with no fields — still record it
            events[event_name] = {
                "field_count": 0,
                "fields": {},
            }
            continue

        fields = {}

        for field_name, field_info in attrs_props.items():
            field_type = field_info.get("type", "")
            # Resolve $ref types
            ref = field_info.get("$ref", "")
            if ref:
                ref_name = ref.split("/")[-1]
                ref_schema = schemas.get(ref_name, {})
                if ref_schema.get("enum"):
                    field_type = f"enum({','.join(str(e) for e in ref_schema['enum'][:5])})"
                else:
                    field_type = ref_name

            fields[field_name] = {
                "type": field_type,
                "description": field_info.get("description", ""),
                "nullable": field_info.get("nullable", False),
                "category": "attribute",
            }

        for field_name, field_info in metrics_props.items():
            fields[field_name] = {
                "type": field_info.get("type", ""),
                "description": field_info.get("description", ""),
                "nullable": field_info.get("nullable", False),
                "category": "metric",
            }

        events[event_name] = {
            "field_count": len(fields),
            "fields": fields,
        }

    logger.info("Parsed %d events from Swagger spec", len(events))
    return {
        "event_count": len(events),
        "swagger_url": swagger_url,
        "events": events,
    }


def write_event_schemas(parsed: dict, knowledge_dir: str | Path) -> str:
    """Write parsed event schemas to knowledge/event_schemas.json."""
    path = Path(knowledge_dir) / "event_schemas.json"
    with open(path, "w") as f:
        json.dump(parsed, f, indent=2, default=str)
    logger.info("Wrote event_schemas.json: %d events", parsed["event_count"])
    return str(path)


def get_event_schema(event_name: str, knowledge_dir: str | Path) -> dict | None:
    """Load a specific event's schema from the KB."""
    path = Path(knowledge_dir) / "event_schemas.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return data.get("events", {}).get(event_name)


def search_events(keyword: str, knowledge_dir: str | Path, limit: int = 10) -> list[dict]:
    """Search events by name."""
    path = Path(knowledge_dir) / "event_schemas.json"
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)

    from rapidfuzz import fuzz, process
    event_names = list(data.get("events", {}).keys())
    if not event_names:
        return []

    matches = process.extract(keyword, event_names, scorer=fuzz.WRatio, limit=limit, score_cutoff=40)
    results = []
    for name, score, idx in matches:
        event = data["events"][event_names[idx]]
        results.append({
            "event_name": event_names[idx],
            "field_count": event.get("field_count", 0),
            "fields": list(event.get("fields", {}).keys())[:10],
            "score": score,
        })
    return results
