"""
User settings API.

Each user has persistent settings stored in Postgres, keyed by user_id:
- persona: analyst, engineer, ml_engineer, new_member
- system_prompt: custom rules injected into every AI call
- user_context: personal context (team, focus area, etc.)
- user_context_optimized: AI-compressed version for token efficiency
- redshift_config: connection preferences (default env, auto-routing rules)
"""
import json
import logging

from fastapi import APIRouter, Request, HTTPException

from config import config
from engine.claude_client import ClaudeClient

logger = logging.getLogger("genie.settings")
router = APIRouter()
claude = ClaudeClient()


def _require_auth(request: Request) -> dict:
    """Require authentication. Returns user dict or raises 401."""
    from api.users import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _get_user_id(request: Request) -> str | None:
    """Get user_id from auth token."""
    from api.users import get_current_user
    user = get_current_user(request)
    if user and user.get("user_id"):
        return str(user["user_id"])
    return None

PERSONAS = {
    "engineer": {
        "id": "engineer",
        "name": "Data Engineer",
        "description": "Builds and maintains pipelines. Sees YAML configs, SQL optimization, DAG details.",
        "default_system_rules": (
            "Provide detailed technical answers. Show SQL with DISTKEY/SORTKEY rationale. "
            "Include DAG configuration details. Suggest pipeline patterns."
        ),
    },
    "analytics_engineer": {
        "id": "analytics_engineer",
        "name": "Analytics Engineer",
        "description": "Builds derived tables and views. Focuses on SQL generation and data modeling.",
        "default_system_rules": (
            "Focus on SQL generation and data modeling. Explain business logic behind transforms. "
            "Suggest DOMO view structures. Link metrics to source tables."
        ),
    },
    "analyst": {
        "id": "analyst",
        "name": "Data Analyst",
        "description": "Queries data and builds reports. Needs NL-to-SQL and definition lookups.",
        "default_system_rules": (
            "Explain in business terms, not infrastructure terms. Always generate runnable SQL. "
            "Suggest relevant metrics and dimensions. Link to DOMO dashboards when applicable."
        ),
    },
    "ml_engineer": {
        "id": "ml_engineer",
        "name": "ML Engineer",
        "description": "Builds features and models. Needs feature store context and personalization tables.",
        "default_system_rules": (
            "Focus on feature engineering and data availability. Suggest relevant features from "
            "existing tables. Explain data freshness and update frequencies."
        ),
    },
    "executive": {
        "id": "executive",
        "name": "Executive / Manager",
        "description": "Needs the 'so what' — business impact, KPI trends, team status. No SQL or infrastructure details.",
        "default_system_rules": (
            "Lead with business impact and the 'so what'. Use plain English, no SQL or technical jargon. "
            "Summarize metrics with trends (up/down/flat). Compare to targets or benchmarks when possible. "
            "If asked about pipelines or failures, explain the business impact (which dashboards affected, "
            "which KPIs delayed) not the technical root cause. Keep answers concise — 3-5 bullet points max. "
            "Suggest who to follow up with for technical details."
        ),
    },
    "new_member": {
        "id": "new_member",
        "name": "New Team Member",
        "description": "Onboarding. Needs guided exploration with extra context and explanations.",
        "default_system_rules": (
            "Provide thorough explanations with context. Define acronyms and organization-specific terms. "
            "Explain why things are done a certain way, not just what. Suggest related topics to explore."
        ),
    },
}

DEFAULT_SYSTEM_PROMPT = """## Query Safety Rules
- NEVER generate DELETE, DROP, TRUNCATE, INSERT, UPDATE, or CREATE statements
- All generated SQL must be SELECT or EXPLAIN only
- Default to nonprod (np_) for all queries

## Environment Routing
- Use nonprod for: all analytics queries, schema browsing, SQL validation, business questions
- Use prod ONLY for: MWAA/Airflow logs (prod pipelines), Redshift EXPLAIN plans (prod stats),
  data profiling (row counts/distributions not available via datashare), S3 prod-only data
- When prod is required, explain WHY to the user before executing"""


@router.get("/personas")
async def list_personas():
    return list(PERSONAS.values())


@router.get("")
async def get_settings(request: Request):
    user = _require_auth(request)
    pool = request.app.state.db_pool
    user_id = str(user.get("user_id", ""))

    # Only fetch settings owned by the authenticated user — never by caller-supplied session_id
    row = None
    if user_id:
        row = await pool.fetchrow(
            "SELECT * FROM user_settings WHERE user_id = $1", user_id
        )

    if not row:
        return {
            "user_id": user_id,
            "persona": "engineer",
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "user_context": "",
            "user_context_optimized": "",
            "redshift_config": {
                "default_environment": "np",
                "auto_route_prod": True,
            },
        }
    result = dict(row)
    if isinstance(result.get("redshift_config"), str):
        result["redshift_config"] = json.loads(result["redshift_config"])
    return result


@router.put("")
async def save_settings(request: Request):
    user = _require_auth(request)
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    user_id = str(user.get("user_id", ""))
    pool = request.app.state.db_pool

    if user_id:
        # Save by user_id (persists across login sessions)
        await pool.execute(
            """
            INSERT INTO user_settings (user_id, session_id, persona, system_prompt, user_context,
                                       user_context_optimized, redshift_config, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                session_id = $2,
                persona = $3,
                system_prompt = $4,
                user_context = $5,
                user_context_optimized = $6,
                redshift_config = $7::jsonb,
                updated_at = NOW()
            """,
            user_id,
            session_id,
            body.get("persona", "engineer"),
            body.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
            body.get("user_context", ""),
            body.get("user_context_optimized", ""),
            json.dumps(body.get("redshift_config", {})),
        )
    else:
        # Fallback: save by session_id
        await pool.execute(
            """
            INSERT INTO user_settings (session_id, persona, system_prompt, user_context,
                                       user_context_optimized, redshift_config, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (session_id) DO UPDATE SET
                persona = $2,
                system_prompt = $3,
                user_context = $4,
                user_context_optimized = $5,
                redshift_config = $6::jsonb,
                updated_at = NOW()
            """,
            session_id,
            body.get("persona", "engineer"),
            body.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
            body.get("user_context", ""),
            body.get("user_context_optimized", ""),
            json.dumps(body.get("redshift_config", {})),
        )
    return {"status": "saved"}


@router.post("/optimize-context")
async def optimize_context(request: Request):
    """
    Use AI to compress user context into a token-efficient version.
    Preserves all semantic meaning but removes filler words and redundancy.
    """
    body = await request.json()
    user_context = body.get("user_context", "")

    if not user_context.strip():
        return {"optimized": "", "input_tokens": 0, "output_tokens": 0, "savings_pct": 0}

    kb = request.app.state.kb
    system = (
        "You are a prompt compression specialist. Your job is to compress the user's context "
        "into the most token-efficient version possible while preserving ALL semantic meaning. "
        "Rules:\n"
        "- Remove filler words, redundant phrases, and unnecessary formatting\n"
        "- Use abbreviations where unambiguous (e.g., 'DB' for database, 'env' for environment)\n"
        "- Combine related sentences\n"
        "- Keep all specific names, tables, metrics, team names, and domain-specific terms\n"
        "- Output ONLY the compressed text, no explanations\n"
        "- Target: 50-70% of original token count"
    )
    messages = [{"role": "user", "content": f"Compress this user context:\n\n{user_context}"}]

    result = await claude.generate(system, messages, kb)

    original_len = len(user_context.split())
    optimized_len = len(result["text"].split())
    savings = round((1 - optimized_len / max(original_len, 1)) * 100)

    # Log usage
    pool = request.app.state.db_pool
    from tracking.logger import log_usage
    await log_usage(
        pool,
        capability="optimize_context",
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        model=config.CLAUDE_MODEL,
    )

    return {
        "optimized": result["text"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "original_words": original_len,
        "optimized_words": optimized_len,
        "savings_pct": savings,
    }
