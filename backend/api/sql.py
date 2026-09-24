import json

from fastapi import APIRouter, Request, HTTPException

from api.models import SQLGenerateRequest, SQLExecuteRequest, SQLOptimizeRequest
from config import config
from engine.claude_client import ClaudeClient
from engine.context import build_system_prompt
from engine.environment_router import validate_read_only
from connectors.mock_redshift import execute_mock_query
from connectors.redshift import execute_real_query
from tracking.logger import log_usage

router = APIRouter()
claude = ClaudeClient()


@router.post("/generate")
async def generate_sql(req: SQLGenerateRequest, request: Request):
    kb = request.app.state.kb
    pool = request.app.state.db_pool

    system_prompt = build_system_prompt(
        kb=kb,
        pillar=req.pillar,
        environment=req.environment,
        capability="nl_to_sql",
    )

    messages = [{"role": "user", "content": req.question}]
    result = await claude.generate(system_prompt, messages, kb)

    await log_usage(
        pool,
        capability="nl_to_sql",
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        pillar=req.pillar,
        environment=req.environment,
        model=config.CLAUDE_MODEL,
    )

    return {"sql": result["text"], "environment": req.environment}


@router.post("/execute")
async def execute_sql(req: SQLExecuteRequest, request: Request):
    pool = request.app.state.db_pool

    # Validate read-only
    is_valid, error_msg = validate_read_only(req.sql)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Execute — use real Redshift if direct creds exist, regardless of REDSHIFT_MODE
    from connectors.redshift import _direct_creds
    if _direct_creds.get(req.environment) or config.REDSHIFT_MODE != "mock":
        result = await execute_real_query(
            req.sql, req.environment, req.max_rows, session_id=req.session_id
        )
    else:
        result = await execute_mock_query(req.sql, req.environment, req.max_rows)

    if "error" in result and result["error"]:
        raise HTTPException(status_code=400, detail=result["error"])

    await log_usage(
        pool,
        capability="sql_execute",
        environment=req.environment,
        query_text=req.sql,
        redshift_query_duration_ms=result.get("execution_time_ms"),
    )

    return result


@router.post("/optimize")
async def optimize_sql(req: SQLOptimizeRequest, request: Request):
    kb = request.app.state.kb
    pool = request.app.state.db_pool

    system_prompt = build_system_prompt(
        kb=kb,
        pillar=req.pillar,
        capability="sql_optimizer",
    )

    messages = [
        {
            "role": "user",
            "content": f"Optimize this Redshift SQL:\n\n```sql\n{req.sql}\n```",
        }
    ]
    # Direct call — no agent pipeline, just simple optimization
    try:
        import asyncio
        result_text = await asyncio.wait_for(
            claude.quick_completion(
                f"{system_prompt}\n\nOptimize this Redshift SQL:\n\n```sql\n{req.sql}\n```",
                max_tokens=2000,
                use_main_model=True,
            ),
            timeout=60,  # 60s max
        )
    except asyncio.TimeoutError:
        return {"analysis": "Optimization timed out (60s). Try a shorter query or simplify the SQL."}
    except Exception as e:
        return {"analysis": f"Optimization failed: {str(e)[:200]}"}

    return {"analysis": result_text}
