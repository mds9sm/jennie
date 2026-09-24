"""
Agent Runner — executes sub-agents and the principal orchestrator.

Each sub-agent is a separate Claude/Bedrock API call with:
- Focused system prompt (~2-3K chars)
- Scoped tools (only relevant ones)
- Independent tool use loop
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

from config import config
from catalog.loader import KnowledgeBase

from engine.agents.prompts import (
    PRINCIPAL_PROMPT,
    DATA_EXPERT_PROMPT,
    REDSHIFT_EXPERT_PROMPT,
)
from engine.agents.tools import (
    PRINCIPAL_TOOLS,
    DATA_EXPERT_TOOLS,
    REDSHIFT_EXPERT_TOOLS,
)

logger = logging.getLogger("genie.agents")

# ── Question Classifier ──────────────────────────────────────────────────────
# Cheap Haiku call to classify question type BEFORE spinning up the full principal.
# This lets us: skip tools for conversational, skip experts for DATA, answer
# definitions from inline context, and route investigations directly to experts.

CLASSIFY_PROMPT = """Classify this user question into exactly ONE category. Reply with ONLY the category name, nothing else.

Categories:
- DATA — needs SQL query, table lookup, or data retrieval (e.g., "how many users", "show me DAU", "what's the trend")
- METRIC — needs DOMO metric analysis or dashboard data (e.g., "engagement depth trend", "north star metrics")
- DEFINITION — asks what a term/metric means, how it's calculated, business context (e.g., "what is activation rate", "how is churn defined")
- INVESTIGATION — needs deep debugging: DAG failures, pipeline tracing, rendered SQL analysis, why data looks wrong
- MODELING — Redshift design: distkey/sortkey, query optimization, table design, schema advice
- CONVERSATIONAL — greeting, thanks, meta-question about the app, follow-up acknowledgment

Question: {question}
Category:"""

VALID_CATEGORIES = {"DATA", "METRIC", "DEFINITION", "INVESTIGATION", "MODELING", "CONVERSATIONAL"}


async def _classify_question(client, model_haiku: str, question: str) -> str:
    """Classify a question using a cheap, fast Haiku call (~50 tokens, <500ms)."""
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=model_haiku,
                max_tokens=20,
                messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(question=question[:500])}],
            ),
            timeout=5,  # hard cap — if classifier is slow, skip it
        )
        category = response.content[0].text.strip().upper()
        # Validate — fall through to DATA if unrecognized
        if category in VALID_CATEGORIES:
            logger.info("Classified question as: %s", category)
            return category
        logger.warning("Classifier returned unknown category: %s — defaulting to DATA", category)
        return "DATA"
    except Exception as e:
        logger.warning("Classifier failed (%s) — defaulting to DATA", str(e)[:100])
        return "DATA"


# Sub-agent registry
from engine.agents.kb_agent import KB_AGENT_PROMPT, KB_AGENT_TOOLS

EXPERTS = {
    "ask_data_expert": {
        "prompt": DATA_EXPERT_PROMPT,
        "tools": DATA_EXPERT_TOOLS,
        "label": "Data Expert",
    },
    "ask_redshift_expert": {
        "prompt": REDSHIFT_EXPERT_PROMPT,
        "tools": REDSHIFT_EXPERT_TOOLS,
        "label": "Redshift Expert",
    },
    # Knowledge Expert removed — glossary + pillar context now inline in every request
    "ask_kb_expert": {
        "prompt": KB_AGENT_PROMPT,
        "tools": KB_AGENT_TOOLS,
        "label": "KB Expert",
    },
}


async def _execute_tool(tool_name: str, tool_input: dict, kb: KnowledgeBase) -> dict:
    """Execute a data tool. Delegates to tools_executor (shared with MCP server)."""
    from engine.tools_executor import execute_tool
    return await execute_tool(tool_name, tool_input, kb)


async def _run_sub_agent(
    client,
    model: str,
    expert_name: str,
    question: str,
    kb: KnowledgeBase,
    user_context: str = "",
    event_emitter: asyncio.Queue | None = None,
) -> str:
    """Run a sub-agent: separate Claude call with focused prompt + scoped tools.

    If event_emitter is provided, tool calls are pushed as events so the frontend
    can show sub-agent investigation steps in real time.
    """
    expert = EXPERTS[expert_name]
    label = expert["label"]
    logger.info("Sub-agent %s: %s", label, question[:80])

    # Build system prompt: expert domain + KB summary + user context
    context_parts = [expert["prompt"]]

    # ── Key tables WITH columns (so sub-agents can write SQL without get_table_detail) ──
    tables = kb.catalog.get("tables", [])
    if tables:
        if expert_name == "ask_redshift_expert":
            # Redshift Expert: top 20 tables with columns + profile data
            lines = ["\n## Key Tables (write SQL directly — columns shown)"]
            for t in tables[:20]:
                key = f"prd_dw.{t.get('schema','')}.{t.get('name','')}"
                cols = [c.get("name", "") for c in t.get("columns", [])[:12]]
                col_str = ", ".join(cols)
                if len(t.get("columns", [])) > 12:
                    col_str += f" +{len(t['columns'])-12}"
                lines.append(f"`{key}`: {col_str}")
            context_parts.append("\n".join(lines))
        elif expert_name == "ask_data_expert":
            # Data Expert: top 15 tables with columns (needs columns to write SQL in investigations)
            lines = ["\n## Key Tables (reference for SQL — columns shown)"]
            for t in tables[:15]:
                key = f"prd_dw.{t.get('schema','')}.{t.get('name','')}"
                cols = [c.get("name", "") for c in t.get("columns", [])[:10]]
                desc = t.get("ai_description") or t.get("description") or ""
                lines.append(f"`{key}`: {', '.join(cols)}")
                if desc:
                    lines.append(f"  → {desc[:120]}")
            context_parts.append("\n".join(lines))
        else:
            # Other experts: compact table list
            table_list = ", ".join(f"{t['schema']}.{t['name']}" for t in tables[:30])
            context_parts.append(f"\nAvailable tables: {table_list}")

    if kb.transforms_index:
        context_parts.append(f"\n{len(kb.transforms_index)} transforms in knowledge base.")

    # ── DOMO metrics with names (so sub-agents can find specific metrics) ──
    domo_catalog = getattr(kb, "domo_catalog", [])
    if domo_catalog:
        s3_enriched = sum(1 for m in domo_catalog if m.get("s3_metadata") and m["s3_metadata"].get("columns"))
        if expert_name == "ask_data_expert":
            # Data Expert gets metric names (its primary domain)
            lines = [f"\n## DOMO Metrics ({len(domo_catalog)} total, {s3_enriched} with S3 data)"]
            for m in domo_catalog[:15]:
                name = m.get("name", "")
                pillar_name = m.get("pillar", "")
                ds_id = m.get("domo_dataset_id", "")
                lines.append(f"- `{name}` ({pillar_name}){f' ds:{ds_id}' if ds_id else ''}")
            lines.append("Use get_view_detail for SQL, analyze_domo_dataset for data.")
            context_parts.append("\n".join(lines))
        else:
            pillars = {}
            for m in domo_catalog:
                p = m.get("pillar", "")
                if p:
                    pillars[p] = pillars.get(p, 0) + 1
            pillar_str = ", ".join(f"{p}: {c}" for p, c in sorted(pillars.items(), key=lambda x: -x[1]))
            context_parts.append(
                f"\n## DOMO Catalog: {len(domo_catalog)} metrics, {s3_enriched} with S3 data. "
                f"Pillars: {pillar_str or 'untagged'}."
            )

    # ── Glossary definitions (shared with all sub-agents for cross-referencing) ──
    if kb.glossary:
        sorted_terms = sorted(kb.glossary.items(),
            key=lambda x: (0 if x[1].get("status") in ("merged", "approved") else 1, x[0])
            if isinstance(x[1], dict) else (1, x[0]))
        glossary_lines = ["\n## Business Definitions (for cross-reference)"]
        for key, g in sorted_terms[:10]:
            if isinstance(g, dict):
                term = g.get("term", key)
                defn = g.get("definition", "")[:150]
                if defn:
                    glossary_lines.append(f"- **{term}**: {defn}")
        if len(glossary_lines) > 1:
            context_parts.append("\n".join(glossary_lines))

    # ── Table profiles (row counts, types, profiling data) ──
    table_profiles = getattr(kb, "table_profiles", {})
    if table_profiles:
        if expert_name == "ask_redshift_expert":
            profile_lines = ["\n## Table Profiles (real row counts and profiling data)"]
            for key, p in sorted(table_profiles.items(), key=lambda x: -(x[1].get("row_count") or 0))[:30]:
                row_str = f"{p['row_count']:,}" if p.get("row_count") else "?"
                type_str = p.get("type", "?")
                profile_lines.append(f"- `{key}`: {row_str} rows, type={type_str}")
                if p.get("profile") and isinstance(p["profile"], dict):
                    cols = p["profile"].get("columns", {})
                    if cols:
                        col_summary = ", ".join(
                            f"{cn}({cd.get('classification','?')})"
                            for cn, cd in list(cols.items())[:8]
                        )
                        profile_lines.append(f"  Columns: {col_summary}")
            context_parts.append("\n".join(profile_lines))
        else:
            size_lines = ["\n## Table Sizes (for query cost awareness)"]
            for key, p in sorted(table_profiles.items(), key=lambda x: -(x[1].get("row_count") or 0))[:15]:
                row_str = f"{p['row_count']:,}" if p.get("row_count") else "?"
                size_lines.append(f"- `{key}`: {row_str} rows ({p.get('type', '?')})")
            context_parts.append("\n".join(size_lines))

    # Inject user context so expert adapts to the user
    if user_context:
        context_parts.append(f"\n## User Context\n{user_context}")

    # ── KB coverage + knowledge sources (from KB object, not local files) ──
    if kb.coverage and isinstance(kb.coverage, dict):
        coverage_lines = ["\n## KB Coverage"]
        for env, cov in kb.coverage.items():
            if isinstance(cov, dict) and "by_type" in cov:
                total = cov.get("total_active_dags", 0)
                sql_count = cov.get("sql_extracted", 0)
                meta_count = cov.get("metadata_only", 0)
                coverage_lines.append(f"**{env}**: {total} DAGs — {sql_count} with SQL, {meta_count} metadata-only")
        if len(coverage_lines) > 1:
            context_parts.append("\n".join(coverage_lines))

    if kb.mwaa_environments and isinstance(kb.mwaa_environments, dict):
        env_lines = ["\n## MWAA Environments"]
        for env_name, meta in kb.mwaa_environments.items():
            if isinstance(meta, dict):
                env_lines.append(f"**{env_name}**: class={meta.get('environment_class','?')}, "
                                f"airflow={meta.get('airflow_version','?')}, "
                                f"workers={meta.get('min_workers','?')}-{meta.get('max_workers','?')}")
        if len(env_lines) > 1:
            context_parts.append("\n".join(env_lines))

    # KB improvement instruction for all sub-agents
    context_parts.append("""
## Knowledge Gap Reporting
If you cannot fully answer because of missing data in the KB, note what's missing at the end of your response.
Format: "KB_GAP: [description of what's missing and how to fix it]"
Examples: "KB_GAP: No column descriptions for fact.cut_session_master — need COMMENT ON or glossary entry"
Only include when there's a real gap. The principal agent will surface these to the user.""")

    # Use structured system blocks with prompt caching — expert prompt is static,
    # context varies per call but is cached across the sub-agent's own iterations
    system_prompt_blocks = [
        {
            "type": "text",
            "text": expert["prompt"],
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "\n".join(context_parts[1:]),  # KB context (skip prompt, already first block)
            "cache_control": {"type": "ephemeral"},
        },
    ]
    messages = [{"role": "user", "content": question}]
    tools = expert["tools"]

    # Tool use loop (max 5 iterations for sub-agents)
    for _ in range(5):
        kwargs = dict(
            model=model,
            max_tokens=4096,
            system=system_prompt_blocks,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        response = await client.messages.create(**kwargs)

        # Collect text and tool calls
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)
                logger.info("  Sub-agent tool call: %s(%s)", block.name, str(block.input)[:100])

        logger.info("  Sub-agent iteration done: %d tool calls, stop=%s, text=%d chars",
                    len(tool_calls), response.stop_reason, sum(len(t) for t in text_parts))

        if not tool_calls or response.stop_reason != "tool_use":
            return "\n".join(text_parts)

        # Execute tools — emit events if emitter provided (real-time sub-agent visibility)
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tc in tool_calls:
            if event_emitter:
                await event_emitter.put({
                    "type": "tool_call",
                    "tool": tc.name,
                    "input": tc.input,
                    "expert": label,
                })
            result = await _execute_tool(tc.name, tc.input, kb)
            if event_emitter:
                await event_emitter.put({
                    "type": "tool_result",
                    "tool": tc.name,
                    "result": result,
                    "expert": label,
                })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": json.dumps(result, default=str)[:4000],  # cap tool result size
            })
        messages.append({"role": "user", "content": tool_results})

    result = "\n".join(text_parts) if text_parts else ""
    if not result:
        return "(Expert could not complete the investigation within the allowed iterations. Try a more specific question.)"
    return result


async def run_principal_agent(
    client,
    model_fast: str,
    model_heavy: str,
    system_prompt: str,
    messages: list[dict],
    kb: KnowledgeBase,
) -> AsyncGenerator[dict, None]:
    """
    Run the principal agent with sub-agent delegation.

    Model strategy (tiered):
    - model_fast (Sonnet): principal routing, tool calls, sub-agents — speed + cost
    - model_heavy (Opus): forced synthesis when limits hit — quality for complex answers

    The principal uses PRINCIPAL_TOOLS which includes ask_*_expert tools.
    When it calls a sub-agent tool, we run a separate Claude call for that expert.
    """
    start = time.time()
    total_input_tokens = 0
    total_output_tokens = 0

    # Combine principal prompt with user-specific context
    # Use structured system blocks with prompt caching — static parts are cached
    # across all iterations (principal prompt + KB context are identical every call)
    full_system = [
        {
            "type": "text",
            "text": PRINCIPAL_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        },
    ]

    # Extract user context to pass to sub-agents (persona, custom rules, pillar, etc.)
    user_context = system_prompt

    working_messages = list(messages)

    logger.info("Principal using fast=%s, heavy=%s", model_fast, model_heavy)

    # ── Classify the question type with a cheap Haiku call ──
    # This determines which tools the principal gets and how many iterations to allow.
    user_question = ""
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg.get("content"), str):
            user_question = last_msg["content"]
        elif isinstance(last_msg.get("content"), list):
            for block in last_msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    user_question = block.get("text", "")
                    break

    # ── "Continue" detection — skip classifier, resume investigation ──
    _continue_phrases = {"continue", "continue investigating", "keep going", "go on", "continue from where you left off"}
    is_continue = user_question.strip().lower().rstrip(".!") in _continue_phrases

    if is_continue:
        category = "INVESTIGATION"
        logger.info("Detected 'continue' — resuming as INVESTIGATION")
        yield {"type": "status", "content": "Continuing investigation..."}
        # Inject continuation instruction into messages
        # The conversation history already has the previous response with findings summary
        working_messages[-1] = {
            "role": "user",
            "content": (
                "Continue investigating from where you left off. "
                "Review the conversation above — your previous response was cut short. "
                "Focus on aspects you haven't covered yet. "
                "Do NOT repeat findings you already shared. "
                "Use tools to dig deeper into unresolved questions."
            ),
        }
    else:
        # Haiku model ID for classifier (cheap + fast)
        if "bedrock" in model_fast.lower() or "us.anthropic" in model_fast:
            model_haiku = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        else:
            model_haiku = "claude-haiku-4-5-20251001"

        category = await _classify_question(client, model_haiku, user_question)
        yield {"type": "status", "content": f"Category: {category.lower()}"}

    # Adjust tools and limits based on category
    if category == "CONVERSATIONAL":
        # No tools needed — respond directly
        tools_for_principal = []
        max_iterations = 1
        # Override system prompt to prevent hallucinated SQL/data
        full_system = [
            {
                "type": "text",
                "text": (
                    "You are Genie, your data platform assistant. "
                    "This is a conversational message (greeting, thanks, meta-question, or follow-up acknowledgment).\n\n"
                    "**STRICT RULES:**\n"
                    "- Do NOT generate SQL queries or data results\n"
                    "- Do NOT simulate tool calls or fabricate data\n"
                    "- Do NOT reference specific numbers, metrics, or statistics unless the user provided them\n"
                    "- Reply naturally and concisely (2-3 sentences)\n"
                    "- If asked about app features, guide to: Chat, Workbench, Glossary, Lineage, Tasks, Reports, or Settings\n"
                    "- If the user wants data, tell them to ask a specific data question"
                ),
                "cache_control": {"type": "ephemeral"},
            },
        ]
    elif category == "DEFINITION":
        # Inline context should suffice — only search if needed, no expert delegation
        from engine.agents.tools import _pick
        tools_for_principal = _pick(["search_tables", "search_transforms", "execute_query"])
        max_iterations = 3
    elif category in ("DATA", "METRIC"):
        # Direct tools + DOMO analysis, no experts unless retry fails
        tools_for_principal = PRINCIPAL_TOOLS
        max_iterations = 6
    elif category == "INVESTIGATION":
        # Full toolset including experts
        tools_for_principal = PRINCIPAL_TOOLS
        max_iterations = 8
    elif category == "MODELING":
        # Direct to redshift expert
        tools_for_principal = PRINCIPAL_TOOLS
        max_iterations = 4
    else:
        tools_for_principal = PRINCIPAL_TOOLS
        max_iterations = 8

    MAX_TOTAL_TIME = 180  # 3 min total max
    MAX_TOTAL_TOKENS = 150000  # Rich context = ~6K per call, 8 iterations = ~48K just for context
    for iteration in range(max_iterations):
        if time.time() - start > MAX_TOTAL_TIME:
            yield {"type": "text", "content": "\n\n*Time limit reached. Summarizing findings.*\n"}
            break
        if total_input_tokens + total_output_tokens > MAX_TOTAL_TOKENS:
            break

        kwargs = dict(
            model=model_fast,  # Sonnet for routing + tool selection
            max_tokens=4096,
            system=full_system,
            messages=working_messages,
        )
        if tools_for_principal:
            kwargs["tools"] = tools_for_principal

        response = await client.messages.create(**kwargs)

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        if not tool_calls or response.stop_reason != "tool_use":
            # Final response — stream the text to the user
            for text in text_parts:
                yield {"type": "text", "content": text}
            break

        # Intermediate iteration (has tool calls) — send reasoning to step trail, not message
        if text_parts:
            # Extract a short summary for the step trail (first sentence or 80 chars)
            reasoning = " ".join(text_parts).strip()
            if reasoning:
                summary = reasoning.split(".")[0][:100]
                if summary:
                    yield {"type": "status", "content": summary}

        # Execute tool calls (sub-agents can run in parallel!)
        working_messages.append({"role": "assistant", "content": response.content})

        # Separate sub-agent calls from direct tools
        sub_agent_calls = [(tc, tc.name, tc.input) for tc in tool_calls if tc.name in EXPERTS]
        direct_calls = [(tc, tc.name, tc.input) for tc in tool_calls if tc.name not in EXPERTS]

        tool_results = []

        # Run sub-agents in parallel — with event streaming for real-time tool visibility
        if sub_agent_calls:
            yield {"type": "status", "content": f"Consulting {len(sub_agent_calls)} expert(s)..."}

            # Shared event queue — sub-agents push tool_call/tool_result events here
            sub_event_queue: asyncio.Queue = asyncio.Queue()

            async def run_expert(tc, name, inp):
                yield_label = EXPERTS[name]["label"]
                try:
                    result = await asyncio.wait_for(
                        _run_sub_agent(client, model_fast, name, inp["question"], kb, user_context,
                                       event_emitter=sub_event_queue),
                        timeout=120,  # 2 min max per sub-agent
                    )
                except asyncio.TimeoutError:
                    result = f"(Expert timed out after 120s — question may be too broad. Try a more specific question.)"
                    logger.warning("Sub-agent %s timed out", name)
                return tc.id, yield_label, result

            tasks = [run_expert(tc, name, inp) for tc, name, inp in sub_agent_calls]
            expert_results = await asyncio.gather(*tasks)

            # Drain sub-agent events (tool calls + results) — show investigation trail
            while not sub_event_queue.empty():
                try:
                    evt = sub_event_queue.get_nowait()
                    yield evt  # tool_call and tool_result events from sub-agents
                except asyncio.QueueEmpty:
                    break

            for tool_use_id, expert_label, result in expert_results:
                yield {"type": "expert_response", "expert": expert_label, "content": result[:200]}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result[:6000],  # cap size
                })

        # Run direct tools (execute_query etc.) — emit tool_call BEFORE executing
        for tc, name, inp in direct_calls:
            yield {"type": "tool_call", "tool": name, "input": inp}
            result = await _execute_tool(name, inp, kb)
            yield {"type": "tool_result", "tool": name, "result": result}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": json.dumps(result, default=str)[:4000],
            })

        working_messages.append({"role": "user", "content": tool_results})

    # If we exited the loop because of limits (not natural stop), force synthesis.
    # Skip for CONVERSATIONAL — the response is already complete, no synthesis needed.
    # Also skip if the last response had no tool calls (natural completion that just hit iteration limit).
    hit_token_limit = total_input_tokens + total_output_tokens > MAX_TOTAL_TOKENS
    hit_iteration_limit = iteration >= max_iterations - 1
    hit_time_limit = time.time() - start > MAX_TOTAL_TIME
    natural_stop = (category == "CONVERSATIONAL") or (not tool_calls and not hit_token_limit and not hit_time_limit)

    if (hit_token_limit or hit_iteration_limit or hit_time_limit) and not natural_stop:
        limit_reason = "token budget" if hit_token_limit else "time limit" if hit_time_limit else "investigation depth limit"
        logger.warning("Principal hit %s — forcing synthesis (tokens: %d, time: %.0fs, iterations: %d)",
                      limit_reason, total_input_tokens + total_output_tokens, time.time() - start, iteration + 1)
        working_messages.append({"role": "user", "content": [
            {"type": "text", "text": (
                f"You've reached the {limit_reason}. Based on everything you found so far:\n"
                "1. Provide your complete answer and recommendations NOW\n"
                "2. Do not make any more tool calls\n"
                "3. At the end, add this note:\n"
                "---\n"
                f"*I've summarized my findings so far (reached {limit_reason}). "
                "If you'd like me to continue investigating from where I left off, "
                "just reply 'continue' or ask a specific follow-up question.*"
            )}
        ]})
        try:
            # Use Opus for synthesis — this is where quality matters
            logger.info("Using heavy model (%s) for forced synthesis", model_heavy)
            final_response = await client.messages.create(
                model=model_heavy,
                max_tokens=4096,
                system=full_system,
                messages=working_messages,
            )
            total_input_tokens += final_response.usage.input_tokens
            total_output_tokens += final_response.usage.output_tokens
            for block in final_response.content:
                if block.type == "text":
                    yield {"type": "text", "content": block.text}
        except Exception as e:
            yield {"type": "text", "content": f"\n\n*⚠️ Could not complete synthesis: {str(e)[:200]}*"}

    elapsed = time.time() - start
    logger.info("Principal done: %.1fs, %d in + %d out tokens (fast=%s, heavy=%s)",
               elapsed, total_input_tokens, total_output_tokens, model_fast, model_heavy)
    yield {
        "type": "done",
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "elapsed_seconds": round(elapsed, 2),
        "model_fast": model_fast,
        "model_heavy": model_heavy,
    }
