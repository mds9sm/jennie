"""
Hybrid search — combines lexical (rapidfuzz) and semantic (pgvector) results.

Lexical is instant and always available. Semantic requires embeddings in postgres
and an async db_pool. When both are available, results are merged by combined score.
"""

from rapidfuzz import fuzz, process

from catalog.loader import KnowledgeBase

# Module-level db_pool reference — set by main.py on startup
_db_pool = None


def set_db_pool(pool):
    """Set the database pool for semantic search. Called once on startup."""
    global _db_pool
    _db_pool = pool


def _lexical_search(keyword: str, candidates: list[tuple[str, dict]], limit: int = 10, cutoff: int = 40) -> list[tuple[dict, float]]:
    """Run rapidfuzz WRatio search. Returns [(item, score_0_to_1), ...]."""
    if not candidates:
        return []
    matches = process.extract(
        keyword,
        [c[0] for c in candidates],
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=cutoff,
    )
    return [(candidates[idx][1], score / 100.0) for _, score, idx in matches]


async def _hybrid_merge(keyword: str, entity_type: str, lexical_results: list[tuple[dict, float]],
                        key_fn, limit: int = 10) -> list[tuple[dict, float]]:
    """Merge lexical + semantic results. Semantic boosts score for meaning matches.

    Combined score = 0.4 * lexical + 0.6 * semantic (semantic weighted higher for intent matching).
    Items found only by one method keep their score * their weight.
    """
    if not _db_pool:
        return lexical_results[:limit]

    try:
        from catalog.embeddings import semantic_search
        sem_results = await semantic_search(_db_pool, keyword, entity_type=entity_type, limit=limit)
    except Exception:
        return lexical_results[:limit]

    if not sem_results:
        return lexical_results[:limit]

    # Build lookup: entity_key → semantic similarity
    sem_scores = {r["entity_key"]: r["similarity"] for r in sem_results}

    # Build lookup: entity_key → (item, lexical_score)
    lex_lookup = {}
    for item, score in lexical_results:
        key = key_fn(item)
        lex_lookup[key] = (item, score)

    # Merge — all items from both sources
    merged = {}
    LEXICAL_WEIGHT = 0.4
    SEMANTIC_WEIGHT = 0.6

    for key, (item, lex_score) in lex_lookup.items():
        sem_score = sem_scores.get(key, 0.0)
        combined = (LEXICAL_WEIGHT * lex_score) + (SEMANTIC_WEIGHT * sem_score)
        merged[key] = (item, combined)

    for r in sem_results:
        key = r["entity_key"]
        if key not in merged:
            # Semantic-only match — not found by lexical. Still valuable.
            # We need to find the original item from the KB to return full data.
            merged[key] = ({"_semantic_key": key, "_content": r["content_text"]}, SEMANTIC_WEIGHT * r["similarity"])

    # Sort by combined score descending
    sorted_results = sorted(merged.values(), key=lambda x: -x[1])
    return sorted_results[:limit]


def search_tables(kb: KnowledgeBase, keyword: str, limit: int = 10) -> dict:
    tables = kb.catalog.get("tables", [])

    if tables:
        candidates = []
        for t in tables:
            search_str = f"{t.get('schema', '')}.{t['name']} {t.get('description', '')}"
            candidates.append((search_str, t))

        lexical = _lexical_search(keyword, candidates, limit=limit)

        # Try hybrid search if db_pool available
        if _db_pool:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're inside an async context — can't await directly from sync function
                    # Fall back to lexical only (hybrid search used from async callers)
                    pass
            except RuntimeError:
                pass

        results = []
        for table, score in lexical:
            if isinstance(table, dict) and "_semantic_key" not in table:
                results.append({
                    "schema": table.get("schema", ""),
                    "name": table["name"],
                    "description": table.get("description", ""),
                    "columns": [c["name"] for c in table.get("columns", [])],
                    "dag": table.get("dag", ""),
                    "score": round(score * 100, 1),
                })
        return {"results": results, "count": len(results)}

    # Fallback: search lineage keys
    if kb.lineage:
        table_names = list(kb.lineage.keys())
        matches = process.extract(keyword, table_names, scorer=fuzz.WRatio, limit=limit, score_cutoff=40)
        results = []
        for match_str, score, idx in matches:
            name = table_names[idx]
            lineage_entry = kb.lineage[name]
            parts = name.rsplit(".", 1)
            schema = parts[0] if len(parts) > 1 else ""
            tbl_name = parts[-1]
            upstream = lineage_entry.get("upstream", []) if isinstance(lineage_entry, dict) else []
            downstream = lineage_entry.get("downstream", []) if isinstance(lineage_entry, dict) else []
            results.append({
                "schema": schema, "name": tbl_name, "full_name": name,
                "upstream_count": len(upstream), "downstream_count": len(downstream),
                "source": "lineage", "score": score,
            })
        return {"results": results, "count": len(results),
                "note": "Results from lineage (catalog empty — enable Redshift in KB build for column details)"}

    # Check table profiles from Table Ops
    profiles = getattr(kb, "table_profiles", {})
    if profiles:
        profile_names = list(profiles.keys())
        matches = process.extract(keyword, profile_names, scorer=fuzz.WRatio, limit=limit, score_cutoff=40)
        results = []
        for match_str, score, idx in matches:
            key = profile_names[idx]
            p = profiles[key]
            results.append({
                "schema": p.get("schema", ""), "name": p.get("table", key),
                "row_count": p.get("row_count"), "type": p.get("type"),
                "source": "table_ops_profile", "score": score,
            })
        return {"results": results, "count": len(results), "note": "Results from Table Ops profiles (catalog empty)"}

    return {"results": [], "count": 0, "note": "No table data available. Run KB build with Redshift enabled."}


async def search_tables_hybrid(kb: KnowledgeBase, keyword: str, limit: int = 10) -> dict:
    """Async version with hybrid lexical + semantic search."""
    tables = kb.catalog.get("tables", [])
    if not tables:
        return search_tables(kb, keyword, limit)

    candidates = []
    for t in tables:
        search_str = f"{t.get('schema', '')}.{t['name']} {t.get('description', '')}"
        candidates.append((search_str, t))

    lexical = _lexical_search(keyword, candidates, limit=limit)

    def key_fn(item):
        if "_semantic_key" in item:
            return item["_semantic_key"]
        return f"{item.get('schema', '')}.{item.get('name', '')}"

    hybrid = await _hybrid_merge(keyword, "table", lexical, key_fn, limit=limit)

    results = []
    for item, score in hybrid:
        if isinstance(item, dict) and "_semantic_key" not in item:
            results.append({
                "schema": item.get("schema", ""),
                "name": item["name"],
                "description": item.get("description", ""),
                "columns": [c["name"] for c in item.get("columns", [])],
                "dag": item.get("dag", ""),
                "score": round(score * 100, 1),
            })
        elif isinstance(item, dict) and "_semantic_key" in item:
            # Semantic-only match — resolve from catalog
            key = item["_semantic_key"]
            for t in tables:
                if f"{t.get('schema', '')}.{t.get('name', '')}" == key:
                    results.append({
                        "schema": t.get("schema", ""),
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "columns": [c["name"] for c in t.get("columns", [])],
                        "dag": t.get("dag", ""),
                        "score": round(score * 100, 1),
                        "source": "semantic",
                    })
                    break
    return {"results": results, "count": len(results)}


def search_transforms(kb: KnowledgeBase, keyword: str, limit: int = 10) -> dict:
    transforms = kb.transforms_index
    if not transforms:
        return {"results": [], "count": 0}

    candidates = []
    for t in transforms:
        search_str = (
            f"{t.get('name', '')} {t.get('target_table', '')} "
            f"{t.get('dag_id', '')} {' '.join(t.get('tags', []))}"
        )
        candidates.append((search_str, t))

    matches = process.extract(
        keyword, [c[0] for c in candidates],
        scorer=fuzz.WRatio, limit=limit, score_cutoff=40,
    )

    results = []
    for match_str, score, idx in matches:
        t = candidates[idx][1]
        results.append({
            "name": t.get("name", ""),
            "target_table": t.get("target_table", ""),
            "schedule": t.get("schedule", ""),
            "dag_id": t.get("dag_id", ""),
            "dag_type": t.get("dag_type", ""),
            "run_state": t.get("run_state", ""),
            "last_run_date": t.get("last_run_date", ""),
            "success_rate": t.get("success_rate"),
            "score": score,
        })

    return {"results": results, "count": len(results)}


def get_table_detail(kb: KnowledgeBase, table_name: str) -> dict:
    tables = kb.catalog.get("tables", [])
    for t in tables:
        full_name = f"{t.get('schema', '')}.{t['name']}"
        if table_name.lower() in (t["name"].lower(), full_name.lower()):
            return t

    results = search_tables(kb, table_name, limit=1)
    if results["results"]:
        name = results["results"][0]["name"]
        for t in tables:
            if t["name"] == name:
                return t

    return {"error": f"Table '{table_name}' not found in catalog"}


def get_transform_detail(kb: KnowledgeBase, dag_id: str) -> dict:
    """Load full transform detail including rendered SQL, task stats, run history."""
    detail = kb.get_transform_detail(dag_id)
    if detail:
        return detail

    for t in kb.transforms_index:
        if t.get("dag_id") == dag_id:
            return t

    return {"error": f"Transform '{dag_id}' not found"}


def search_glossary(kb: KnowledgeBase, term: str, limit: int = 5) -> list[dict]:
    if not kb.glossary:
        return []

    terms = list(kb.glossary.keys())
    matches = process.extract(
        term, terms, scorer=fuzz.WRatio, limit=limit, score_cutoff=50
    )

    results = []
    for match_term, score, idx in matches:
        entry = kb.glossary[terms[idx]]
        results.append({
            "term": terms[idx],
            "score": score,
            **(entry if isinstance(entry, dict) else {"definition": str(entry)}),
        })

    return results
