import logging
from decimal import Decimal

import asyncpg

logger = logging.getLogger("genie.tracking")

# Cost per million tokens by model family
MODEL_COSTS = {
    "opus":   {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0,  "output": 15.0},
    "haiku":  {"input": 0.80, "output": 4.0},
}


def estimate_cost(input_tokens: int, output_tokens: int, model: str = "") -> Decimal:
    # Detect model family from model string
    model_lower = (model or "").lower()
    if "opus" in model_lower:
        rates = MODEL_COSTS["opus"]
    elif "haiku" in model_lower:
        rates = MODEL_COSTS["haiku"]
    else:
        rates = MODEL_COSTS["sonnet"]  # default

    cost = (input_tokens / 1_000_000 * rates["input"]) + (
        output_tokens / 1_000_000 * rates["output"]
    )
    return Decimal(str(round(cost, 6)))


async def log_usage(
    pool: asyncpg.Pool,
    capability: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    pillar: str | None = None,
    environment: str | None = None,
    query_text: str | None = None,
    redshift_query_duration_ms: int | None = None,
    model: str | None = None,
    user_id: str = "local-dev",
):
    cost = estimate_cost(input_tokens, output_tokens, model or "")
    try:
        await pool.execute(
            """
            INSERT INTO usage_events
                (user_id, capability, pillar, environment, input_tokens,
                 output_tokens, estimated_cost, redshift_query_duration_ms,
                 query_text, model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            user_id,
            capability,
            pillar,
            environment,
            input_tokens,
            output_tokens,
            cost,
            redshift_query_duration_ms,
            query_text,
            model,
        )
    except Exception as e:
        logger.error("Failed to log usage event: %s", e)


async def get_usage_summary(pool: asyncpg.Pool) -> dict:
    rows = await pool.fetch(
        """
        SELECT
            capability,
            COUNT(*) as call_count,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(estimated_cost) as total_cost
        FROM usage_events
        WHERE created_at >= CURRENT_DATE
        GROUP BY capability
        ORDER BY total_cost DESC
        """
    )
    today = [
        {
            "capability": r["capability"],
            "call_count": r["call_count"],
            "total_input_tokens": r["total_input_tokens"],
            "total_output_tokens": r["total_output_tokens"],
            "total_cost": float(r["total_cost"]) if r["total_cost"] else 0,
        }
        for r in rows
    ]

    totals = await pool.fetchrow(
        """
        SELECT
            COUNT(*) as call_count,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(estimated_cost) as total_cost
        FROM usage_events
        WHERE created_at >= CURRENT_DATE
        """
    )

    return {
        "today": today,
        "totals": {
            "call_count": totals["call_count"] if totals else 0,
            "total_input_tokens": totals["total_input_tokens"] or 0,
            "total_output_tokens": totals["total_output_tokens"] or 0,
            "total_cost": float(totals["total_cost"]) if totals and totals["total_cost"] else 0,
        },
    }
