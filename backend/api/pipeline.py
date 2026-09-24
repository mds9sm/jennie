from fastapi import APIRouter, Request

from api.models import PipelineGenerateRequest
from config import config
from engine.claude_client import ClaudeClient
from engine.context import build_system_prompt
from tracking.logger import log_usage

router = APIRouter()
claude = ClaudeClient()

PIPELINE_INSTRUCTIONS = """
Generate a complete pipeline configuration. Return your response as a JSON object with these exact keys:
- "yaml_config": the full YAML configuration for the DAG
- "sql_files": an object with keys "create_table", "transform", "load", "refresh_view" each containing the SQL file content
- "explanation": a brief explanation of the pipeline design decisions

Wrap the JSON in ```json ``` code fences.
"""


@router.post("/generate")
async def generate_pipeline(req: PipelineGenerateRequest, request: Request):
    kb = request.app.state.kb
    pool = request.app.state.db_pool

    system_prompt = build_system_prompt(
        kb=kb,
        pillar=req.pillar,
        capability="pipeline_builder",
    )

    messages = [
        {
            "role": "user",
            "content": f"{PIPELINE_INSTRUCTIONS}\n\nPipeline description: {req.description}",
        }
    ]

    result = await claude.generate(system_prompt, messages, kb)

    await log_usage(
        pool,
        capability="pipeline_builder",
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        pillar=req.pillar,
        model=config.CLAUDE_MODEL,
    )

    # Try to parse structured output
    text = result["text"]
    import json
    import re

    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            return parsed
        except json.JSONDecodeError:
            pass

    return {
        "yaml_config": text,
        "sql_files": {},
        "explanation": "Could not parse structured output. Raw response returned as yaml_config.",
    }
