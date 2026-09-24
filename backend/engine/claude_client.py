import json
import logging
import time
from typing import AsyncGenerator

import anthropic

from config import config
from catalog.loader import KnowledgeBase
from catalog.search import search_tables, search_transforms, get_table_detail
from catalog.lineage import get_lineage
from connectors.mock_redshift import execute_mock_query
from connectors.redshift import execute_real_query
from engine.tools import GENIE_TOOLS

logger = logging.getLogger("genie.claude")


def _create_client():
    """Create the appropriate Anthropic client based on AI_PROVIDER config."""
    if config.AI_PROVIDER == "bedrock":
        from anthropic import AsyncAnthropicBedrock
        bedrock_env = config.BEDROCK_SSO_ENV  # only use this environment (default: np)

        try:
            from connectors.credential_store import credential_store
            for sid, session in credential_store._sessions.items():
                creds = session.get_credentials(bedrock_env)
                if creds:
                    logger.info("Using %s SSO creds for Bedrock (session=%s, %dmin remaining)",
                               bedrock_env, sid, creds.minutes_remaining)
                    return AsyncAnthropicBedrock(
                        aws_access_key=creds.access_key_id,
                        aws_secret_key=creds.secret_access_key,
                        aws_session_token=creds.session_token,
                        aws_region=config.BEDROCK_REGION,
                    )
        except Exception as e:
            logger.warning("Could not use %s SSO creds for Bedrock: %s", bedrock_env, e)

        # Fall back to default AWS credential chain (~/.aws)
        logger.info("No %s SSO creds for Bedrock — using default AWS chain", bedrock_env)
        return AsyncAnthropicBedrock(aws_region=config.BEDROCK_REGION)
    else:
        return anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


class ClaudeClient:
    def __init__(self):
        self._provider = config.AI_PROVIDER
        self.client = _create_client()
        self._update_models()

    def _update_models(self):
        """Set model IDs based on provider."""
        if config.AI_PROVIDER == "bedrock":
            self.model = config.BEDROCK_MODEL           # Opus — for final synthesis
            self.model_fast = config.BEDROCK_MODEL_FAST  # Sonnet — for routing + sub-agents
        else:
            self.model = config.CLAUDE_MODEL
            self.model_fast = config.CLAUDE_MODEL_FAST

    def _ensure_client(self):
        """Re-create client if provider changed or if Bedrock needs fresh creds."""
        needs_recreate = self._provider != config.AI_PROVIDER

        # For Bedrock, always recreate to pick up latest SSO creds
        if config.AI_PROVIDER == "bedrock":
            needs_recreate = True

        if needs_recreate:
            self._provider = config.AI_PROVIDER
            self.client = _create_client()
            self._update_models()
            logger.info("Client created for provider: %s model: %s (fast: %s)",
                       self._provider, self.model, self.model_fast)

    async def quick_completion(self, prompt: str, max_tokens: int = 500, use_main_model: bool = False) -> str:
        """Lightweight non-streaming completion for internal tasks."""
        self._ensure_client()
        if use_main_model:
            model = self.model  # Use the configured main model (Opus/Sonnet)
        elif config.AI_PROVIDER == "bedrock":
            model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        else:
            model = self.model

        resp = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text if resp.content else ""

    async def chat_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        kb: KnowledgeBase,
    ) -> AsyncGenerator[dict, None]:
        """Stream a chat response using principal + sub-agent architecture."""
        self._ensure_client()

        from engine.agents.runner import run_principal_agent

        async for event in run_principal_agent(
            client=self.client,
            model_fast=self.model_fast,   # Sonnet — routing, tool calls, sub-agents
            model_heavy=self.model,       # Opus — final synthesis
            system_prompt=system_prompt,
            messages=messages,
            kb=kb,
        ):
            yield event

    async def _chat_stream_legacy(
        self,
        system_prompt: str,
        messages: list[dict],
        kb: KnowledgeBase,
    ) -> AsyncGenerator[dict, None]:
        """Legacy: monolithic chat with all tools. Kept as fallback."""
        start = time.time()
        total_input_tokens = 0
        total_output_tokens = 0

        self._ensure_client()
        working_messages = list(messages)

        while True:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=working_messages,
                tools=GENIE_TOOLS,
                stream=False,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Process content blocks
            tool_use_blocks = []
            for block in response.content:
                if block.type == "text":
                    yield {"type": "text", "content": block.text}
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)
                    yield {
                        "type": "tool_call",
                        "tool": block.name,
                        "input": block.input,
                    }

            # If no tool use, we're done
            if response.stop_reason != "tool_use" or not tool_use_blocks:
                break

            # Execute tools and continue conversation
            working_messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_block in tool_use_blocks:
                result = await self._execute_tool(tool_block.name, tool_block.input, kb)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps(result),
                    }
                )
                yield {"type": "tool_result", "tool": tool_block.name, "result": result}

            working_messages.append({"role": "user", "content": tool_results})

        elapsed = time.time() - start
        yield {
            "type": "done",
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        kb: KnowledgeBase,
    ) -> dict:
        """Non-streaming generation with tool use loop. Returns final text."""
        full_text = []
        token_info = {}

        async for event in self.chat_stream(system_prompt, messages, kb):
            if event["type"] == "text":
                full_text.append(event["content"])
            elif event["type"] == "done":
                token_info = event

        return {
            "text": "".join(full_text),
            "input_tokens": token_info.get("input_tokens", 0),
            "output_tokens": token_info.get("output_tokens", 0),
        }

    async def _execute_tool(
        self, tool_name: str, tool_input: dict, kb: KnowledgeBase
    ) -> dict:
        """Execute a tool call against the local knowledge base."""
        if tool_name == "search_tables":
            return search_tables(kb, tool_input["keyword"])
        elif tool_name == "search_transforms":
            return search_transforms(kb, tool_input["keyword"])
        elif tool_name == "get_table_detail":
            return get_table_detail(kb, tool_input["table_name"])
        elif tool_name == "get_table_lineage":
            return get_lineage(
                kb,
                tool_input["table_name"],
                tool_input.get("direction", "both"),
            )
        elif tool_name == "get_transform_detail":
            from catalog.search import get_transform_detail as get_td
            return get_td(kb, tool_input["dag_id"])
        elif tool_name == "get_view_detail":
            detail = kb.get_view_detail(tool_input["view_name"])
            if detail:
                return detail
            # Try fuzzy match from metrics
            from rapidfuzz import fuzz, process
            names = [m["name"] for m in kb.metrics]
            if names:
                matches = process.extract(tool_input["view_name"], names, scorer=fuzz.WRatio, limit=1, score_cutoff=50)
                if matches:
                    detail = kb.get_view_detail(matches[0][0])
                    if detail:
                        return detail
            return {"error": f"View '{tool_input['view_name']}' not found"}
        elif tool_name == "glossary_lookup":
            return self._glossary_lookup(kb, tool_input["term"])
        elif tool_name == "execute_query":
            return await self._execute_query(
                tool_input["sql"],
                tool_input.get("environment", "np"),
            )
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _execute_query(self, sql: str, environment: str = "np") -> dict:
        """Execute a query. Uses real Redshift if creds available, else mock."""
        try:
            # Use real Redshift if direct creds exist, regardless of REDSHIFT_MODE
            from connectors.redshift import _direct_creds
            if _direct_creds.get(environment) or config.REDSHIFT_MODE != "mock":
                result = await execute_real_query(
                    sql, environment, config.QUERY_MAX_ROWS
                )
            else:
                result = await execute_mock_query(
                    sql, environment, config.QUERY_MAX_ROWS
                )
            return result
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            return {"error": str(e)}

    def _glossary_lookup(self, kb: KnowledgeBase, term: str) -> dict:
        from catalog.search import search_glossary

        results = search_glossary(kb, term)
        if not results:
            return {"error": f"No glossary entry found for '{term}'"}
        return results[0] if len(results) == 1 else {"matches": results}
