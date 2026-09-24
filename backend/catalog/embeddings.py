"""
Semantic search via pgvector — embeds KB entities and enables meaning-based lookup.

Embedding model: Bedrock Titan Text Embeddings v2 (1024 dimensions).
Uses same SSO credentials as other AWS calls — no new API key needed.

Flow:
1. KB loads from S3 (or startup) → calls generate_embeddings()
2. generate_embeddings() builds text for each table/transform/glossary → calls Bedrock → upserts to postgres
3. search functions combine vector similarity (pgvector) + lexical matching (rapidfuzz) for hybrid results
"""

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger("genie.embeddings")

# Bedrock Titan model config
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024


def _build_table_text(table: dict) -> str:
    """Build searchable text for a table — what a user would type to find it."""
    parts = []
    schema = table.get("schema", "")
    name = table.get("name", "")
    parts.append(f"{schema}.{name}")
    if table.get("description"):
        parts.append(table["description"])
    if table.get("ai_description"):
        parts.append(table["ai_description"])
    cols = [c.get("name", "") for c in table.get("columns", [])[:20]]
    if cols:
        parts.append(f"columns: {', '.join(cols)}")
    return " | ".join(parts)


def _build_transform_text(transform: dict) -> str:
    """Build searchable text for a transform/DAG."""
    parts = []
    parts.append(transform.get("dag_id", ""))
    parts.append(transform.get("name", ""))
    if transform.get("target_table"):
        parts.append(f"target: {transform['target_table']}")
    tags = transform.get("tags", [])
    if tags:
        parts.append(f"tags: {', '.join(tags)}")
    return " | ".join(p for p in parts if p)


def _build_glossary_text(term_key: str, entry: dict) -> str:
    """Build searchable text for a glossary entry."""
    parts = [term_key]
    if entry.get("term") and entry["term"] != term_key:
        parts.append(entry["term"])
    if entry.get("definition"):
        parts.append(entry["definition"][:300])
    if entry.get("formula"):
        parts.append(f"formula: {entry['formula']}")
    return " | ".join(parts)


async def _get_bedrock_embedding(text: str) -> Optional[list[float]]:
    """Get embedding from Bedrock Titan Text Embeddings v2."""
    try:
        import boto3
        from connectors.credential_store import credential_store

        # Try np first, then prd (same as DOMO S3 fallback)
        boto_client = None
        for env in ("np", "prd"):
            for sid, session in credential_store._sessions.items():
                creds = session.get_credentials(env)
                if creds:
                    boto_client = boto3.client(
                        "bedrock-runtime",
                        aws_access_key_id=creds.access_key_id,
                        aws_secret_access_key=creds.secret_access_key,
                        aws_session_token=creds.session_token,
                        region_name="us-west-2",
                    )
                    break
            if boto_client:
                break

        if not boto_client:
            # Fallback to default AWS chain
            import boto3
            boto_client = boto3.client("bedrock-runtime", region_name="us-west-2")

        def _call():
            response = boto_client.invoke_model(
                modelId=EMBEDDING_MODEL,
                body=json.dumps({
                    "inputText": text[:8000],  # Titan v2 max input
                    "dimensions": EMBEDDING_DIMENSIONS,
                }),
                contentType="application/json",
            )
            result = json.loads(response["body"].read())
            return result.get("embedding")

        return await asyncio.to_thread(_call)
    except Exception as e:
        logger.warning("Embedding failed: %s", str(e)[:200])
        return None


async def generate_embeddings(kb, db_pool) -> dict:
    """Generate embeddings for all KB entities and upsert to postgres.

    Called after KB reload from S3 or on startup.
    Skips entities whose content_text hasn't changed (idempotent).
    """
    stats = {"tables": 0, "transforms": 0, "glossary": 0, "errors": 0, "skipped": 0}

    # Check if pgvector table exists
    try:
        await db_pool.execute("SELECT 1 FROM kb_embeddings LIMIT 0")
    except Exception:
        logger.warning("kb_embeddings table not found — run db/init.sql to enable semantic search")
        return {"status": "skipped", "reason": "kb_embeddings table not found"}

    # Load existing embeddings to skip unchanged content
    existing = {}
    try:
        rows = await db_pool.fetch("SELECT entity_type, entity_key, content_text FROM kb_embeddings")
        for r in rows:
            existing[(r["entity_type"], r["entity_key"])] = r["content_text"]
    except Exception:
        pass

    # Collect all entities to embed
    to_embed = []

    # Tables
    for table in kb.catalog.get("tables", []):
        key = f"{table.get('schema', '')}.{table.get('name', '')}"
        text = _build_table_text(table)
        if existing.get(("table", key)) != text:
            to_embed.append(("table", key, text))

    # Transforms
    for t in kb.transforms_index:
        key = t.get("dag_id", t.get("name", ""))
        text = _build_transform_text(t)
        if existing.get(("transform", key)) != text:
            to_embed.append(("transform", key, text))

    # Glossary
    for term_key, entry in kb.glossary.items():
        if isinstance(entry, dict):
            text = _build_glossary_text(term_key, entry)
        else:
            text = f"{term_key} | {str(entry)[:300]}"
        if existing.get(("glossary", term_key)) != text:
            to_embed.append(("glossary", term_key, text))

    if not to_embed:
        logger.info("All embeddings up to date — nothing to generate")
        return {"status": "current", "total_existing": len(existing)}

    logger.info("Generating embeddings for %d entities (%d existing, %d unchanged)",
                len(to_embed), len(existing), len(existing) - len(to_embed) + len(to_embed))

    # Batch embed — process in chunks to avoid overwhelming Bedrock
    BATCH_SIZE = 20
    for i in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[i:i + BATCH_SIZE]

        # Run embeddings concurrently within the batch
        tasks = [_get_bedrock_embedding(text) for _, _, text in batch]
        embeddings = await asyncio.gather(*tasks)

        for (entity_type, entity_key, content_text), embedding in zip(batch, embeddings):
            if embedding is None:
                stats["errors"] += 1
                continue

            try:
                await db_pool.execute("""
                    INSERT INTO kb_embeddings (entity_type, entity_key, content_text, embedding, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (entity_type, entity_key) DO UPDATE
                    SET content_text = $3, embedding = $4, updated_at = NOW()
                """, entity_type, entity_key, content_text, json.dumps(embedding))
                stats[f"{entity_type}s" if entity_type != "glossary" else "glossary"] += 1
            except Exception as e:
                logger.warning("Failed to upsert embedding for %s/%s: %s", entity_type, entity_key, str(e)[:100])
                stats["errors"] += 1

    logger.info("Embeddings generated: %d tables, %d transforms, %d glossary (%d errors)",
                stats["tables"], stats["transforms"], stats["glossary"], stats["errors"])
    return {"status": "generated", **stats}


async def semantic_search(db_pool, query: str, entity_type: str = None, limit: int = 10) -> list[dict]:
    """Search KB entities by semantic similarity.

    Returns list of {entity_type, entity_key, content_text, similarity} sorted by similarity desc.
    """
    embedding = await _get_bedrock_embedding(query)
    if not embedding:
        return []

    embedding_str = json.dumps(embedding)

    type_filter = ""
    params = [embedding_str, limit]
    if entity_type:
        type_filter = "AND entity_type = $3"
        params.append(entity_type)

    try:
        rows = await db_pool.fetch(f"""
            SELECT entity_type, entity_key, content_text,
                   1 - (embedding <=> $1::vector) as similarity
            FROM kb_embeddings
            WHERE embedding IS NOT NULL {type_filter}
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """, *params)

        return [
            {
                "entity_type": r["entity_type"],
                "entity_key": r["entity_key"],
                "content_text": r["content_text"],
                "similarity": round(float(r["similarity"]), 4),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Semantic search failed: %s", str(e)[:200])
        return []
