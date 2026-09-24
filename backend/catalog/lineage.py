from catalog.loader import KnowledgeBase


def get_lineage(
    kb: KnowledgeBase, table_name: str, direction: str = "both"
) -> dict:
    tables = kb.catalog.get("tables", [])
    lineage = kb.lineage

    # Normalize table name
    table_name_lower = table_name.lower()

    result = {"table": table_name, "upstream": [], "downstream": []}

    # Check lineage map
    for key, deps in lineage.items():
        if key.lower() == table_name_lower:
            if direction in ("downstream", "both"):
                result["downstream"] = deps.get("downstream", [])
            if direction in ("upstream", "both"):
                result["upstream"] = deps.get("upstream", [])
            return result

    # Fallback: scan tables for source/target relationships
    for t in tables:
        t_full = f"{t.get('schema', '')}.{t['name']}".lower()
        if t_full == table_name_lower or t["name"].lower() == table_name_lower:
            if direction in ("upstream", "both"):
                result["upstream"] = t.get("sources", [])
            if direction in ("downstream", "both"):
                result["downstream"] = t.get("consumers", [])
            return result

    return result
