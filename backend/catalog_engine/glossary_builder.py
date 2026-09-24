"""
Glossary Builder — merges the base glossary.yaml with approved
corrections from the glossary_feedback postgres table.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger("genie.catalog_engine.glossary")


async def _fetch_approved_corrections(db_pool) -> list[dict]:
    """
    Query the glossary_feedback table for approved corrections.
    Returns a list of dicts with term, field, new_value.
    """
    try:
        rows = await db_pool.fetch(
            """
            SELECT term, correction
            FROM glossary_feedback
            WHERE status = 'approved'
            ORDER BY created_at ASC
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Could not fetch glossary corrections: %s", e)
        return []


def _apply_corrections(glossary: dict, corrections: list[dict]) -> dict:
    """
    Apply approved corrections to the glossary dict.
    Each correction has a term and a correction text that becomes the new definition.
    """
    for correction in corrections:
        term = correction.get("term")
        correction_text = correction.get("correction", "")

        if not term or not correction_text:
            continue

        if term not in glossary:
            glossary[term] = {}

        glossary[term]["definition"] = correction_text
        logger.debug(
            "Applied correction: %s.%s = %s (approved %s)",
            term, field, new_value, correction.get("approved_at"),
        )

    return glossary


async def build_glossary(base_path: str, db_pool) -> dict:
    """
    Build the merged glossary from the base YAML file and approved
    corrections from postgres.

    Args:
        base_path: Path to the base glossary.yaml file
        db_pool: asyncpg connection pool for querying feedback table

    Returns:
        Merged glossary dict
    """
    path = Path(base_path)

    # Load base glossary
    if path.exists():
        with open(path) as f:
            glossary = yaml.safe_load(f) or {}
        logger.info("Loaded base glossary: %d terms from %s", len(glossary), path)
    else:
        logger.warning("Base glossary not found at %s, starting empty", path)
        glossary = {}

    # Fetch and apply approved corrections
    corrections = await _fetch_approved_corrections(db_pool)
    if corrections:
        logger.info("Applying %d approved glossary corrections", len(corrections))
        glossary = _apply_corrections(glossary, corrections)

    logger.info("Final glossary: %d terms", len(glossary))
    return glossary
