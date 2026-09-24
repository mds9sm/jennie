from fastapi import APIRouter, Request

from api.models import ImpactAnalyzeRequest
from config import config
from engine.claude_client import ClaudeClient
from engine.context import build_system_prompt
from tracking.logger import log_usage

router = APIRouter()
claude = ClaudeClient()


@router.post("/analyze")
async def analyze_impact(req: ImpactAnalyzeRequest, request: Request):
    kb = request.app.state.kb
    pool = request.app.state.db_pool

    system_prompt = build_system_prompt(
        kb=kb,
        pillar=req.pillar,
        capability="impact_analysis",
    )

    messages = [
        {
            "role": "user",
            "content": f"Analyze the impact of this change: {req.change_description}",
        }
    ]

    result = await claude.generate(system_prompt, messages, kb)

    await log_usage(
        pool,
        capability="impact_analysis",
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        pillar=req.pillar,
        model=config.CLAUDE_MODEL,
    )

    return {"report": result["text"]}
