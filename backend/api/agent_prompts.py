"""
Agent Prompts API — view and edit sub-agent system prompts.
Admin only. Overrides persisted in postgres, code defaults as fallback.
"""

import logging
from fastapi import APIRouter, Request, HTTPException

from engine.agents import prompts as default_prompts

logger = logging.getLogger("genie.agent_prompts")
router = APIRouter()

AGENT_DEFS = [
    {"id": "principal", "label": "Principal Agent (handles 80% directly)", "attr": "PRINCIPAL_PROMPT"},
    {"id": "data_expert", "label": "Data Expert (pipeline investigation)", "attr": "DATA_EXPERT_PROMPT"},
    {"id": "redshift_expert", "label": "Redshift Expert (data modeling)", "attr": "REDSHIFT_EXPERT_PROMPT"},
    {"id": "kb_expert", "label": "KB Agent (build-mode enrichment)", "attr": "KB_AGENT_PROMPT"},
]

# In-memory cache of active prompts (loaded from postgres on startup)
_active_prompts: dict[str, str] = {}


def get_prompt(agent_id: str) -> str:
    """Get the active prompt for an agent (override or code default)."""
    if agent_id in _active_prompts:
        return _active_prompts[agent_id]
    agent = next((a for a in AGENT_DEFS if a["id"] == agent_id), None)
    if agent:
        return getattr(default_prompts, agent["attr"], "")
    return ""


async def load_overrides(db_pool):
    """Load prompt overrides from postgres on startup."""
    try:
        rows = await db_pool.fetch("SELECT agent_id, prompt FROM agent_prompt_overrides")
        for row in rows:
            _active_prompts[row["agent_id"]] = row["prompt"]
            # Also update the module-level variable so sub-agent runner picks it up
            agent = next((a for a in AGENT_DEFS if a["id"] == row["agent_id"]), None)
            if agent:
                setattr(default_prompts, agent["attr"], row["prompt"])
        if rows:
            logger.info("Loaded %d agent prompt overrides from postgres", len(rows))
    except Exception as e:
        logger.warning("Could not load agent prompt overrides: %s", e)


@router.get("")
async def list_agents():
    """List all agents with their current prompt."""
    result = []
    for agent in AGENT_DEFS:
        prompt = get_prompt(agent["id"])
        code_default = getattr(default_prompts, agent["attr"], "")
        is_overridden = agent["id"] in _active_prompts
        result.append({
            "id": agent["id"],
            "label": agent["label"],
            "prompt": prompt,
            "char_count": len(prompt),
            "is_overridden": is_overridden,
        })
    return result


@router.get("/{agent_id}")
async def get_agent_prompt(agent_id: str):
    """Get a specific agent's prompt."""
    agent = next((a for a in AGENT_DEFS if a["id"] == agent_id), None)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    prompt = get_prompt(agent_id)
    return {
        "id": agent_id,
        "label": agent["label"],
        "prompt": prompt,
        "char_count": len(prompt),
        "is_overridden": agent_id in _active_prompts,
    }


@router.put("/{agent_id}")
async def update_agent_prompt(agent_id: str, request: Request):
    """Update an agent's prompt. Persisted in postgres, takes effect immediately."""
    agent = next((a for a in AGENT_DEFS if a["id"] == agent_id), None)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    body = await request.json()
    new_prompt = body.get("prompt", "")
    if not new_prompt.strip():
        raise HTTPException(400, "Prompt cannot be empty")

    pool = request.app.state.db_pool
    await pool.execute("""
        INSERT INTO agent_prompt_overrides (agent_id, prompt, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (agent_id) DO UPDATE SET prompt = $2, updated_at = NOW()
    """, agent_id, new_prompt)

    # Update in-memory
    _active_prompts[agent_id] = new_prompt
    setattr(default_prompts, agent["attr"], new_prompt)

    logger.info("Updated %s prompt (%d chars), persisted to postgres", agent["label"], len(new_prompt))
    return {"status": "updated", "id": agent_id, "char_count": len(new_prompt)}


@router.post("/{agent_id}/reset")
async def reset_agent_prompt(agent_id: str, request: Request):
    """Reset an agent's prompt to the code default."""
    agent = next((a for a in AGENT_DEFS if a["id"] == agent_id), None)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    pool = request.app.state.db_pool
    await pool.execute("DELETE FROM agent_prompt_overrides WHERE agent_id = $1", agent_id)

    # Reload code default
    import importlib
    from engine.agents import prompts as fresh
    importlib.reload(fresh)
    code_default = getattr(fresh, agent["attr"], "")
    setattr(default_prompts, agent["attr"], code_default)
    _active_prompts.pop(agent_id, None)

    logger.info("Reset %s prompt to code default (%d chars)", agent["label"], len(code_default))
    return {"status": "reset", "id": agent_id, "char_count": len(code_default)}
