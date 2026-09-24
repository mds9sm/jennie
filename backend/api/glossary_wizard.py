import json
import logging
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config import config
from engine.claude_client import ClaudeClient

logger = logging.getLogger("genie.glossary_wizard")

router = APIRouter()
_claude = ClaudeClient()


class WizardStartRequest(BaseModel):
    term: str | None = None
    session_id: str | None = None
    persona: str = "engineer"  # engineer, analytics_engineer, analyst, ml_engineer, new_member, executive
    trigger_reason: str = "user_initiated"


class WizardAnswer(BaseModel):
    question_id: int
    value: str  # text answer, selected option, "yes"/"no", or "yes:<text>"


class WizardSubmitRequest(BaseModel):
    wizard_id: str
    answers: list[WizardAnswer]
    session_id: str | None = None


# In-memory wizard state (keyed by wizard_id)
_wizard_sessions: dict[str, dict] = {}


PERSONA_CONTEXT = {
    "engineer": {
        "role": "Data Engineer",
        "strength": "knows tables, SQL, pipelines, and infrastructure",
        "weakness": "may not know the business meaning executives care about",
        "question_focus": "technical details: source tables, SQL formulas, DAG names, data freshness, refresh frequency",
    },
    "analytics_engineer": {
        "role": "Analytics Engineer",
        "strength": "knows data modeling, SQL, and metric definitions",
        "weakness": "may not know downstream dashboard usage or executive context",
        "question_focus": "metric calculation logic, data model relationships, view SQL, aggregation patterns",
    },
    "analyst": {
        "role": "Data Analyst",
        "strength": "knows how metrics are used in reports and dashboards",
        "weakness": "may not know pipeline internals or exact SQL",
        "question_focus": "business meaning, how the metric is used, which dashboards show it, what decisions it drives",
    },
    "ml_engineer": {
        "role": "ML Engineer",
        "strength": "knows feature engineering and model inputs",
        "weakness": "may not know business metric definitions or dashboard context",
        "question_focus": "feature relevance, data freshness, update frequency, data types, null handling",
    },
    "new_member": {
        "role": "New Team Member",
        "strength": "fresh perspective, may know industry-standard definitions",
        "weakness": "doesn't know organization-specific conventions yet",
        "question_focus": "plain-language understanding, what they've heard from teammates, any documentation they've found",
    },
    "executive": {
        "role": "Executive / Business Leader",
        "strength": "knows what the metric means for the business, who watches it, what decisions it drives",
        "weakness": "does not know SQL, table names, or pipeline details — DO NOT ask technical questions",
        "question_focus": "business definition, which team owns it, what 'good' looks like, how often they review it, what actions they take when it changes",
    },
}


def _build_question_prompt(term: str | None, glossary_terms: list[str], persona: str = "engineer") -> str:
    existing = ", ".join(glossary_terms[:50]) if glossary_terms else "none loaded"
    term_clause = f'The user wants to define or correct the term: "{term}".' if term else "The user wants to contribute a new glossary term (they haven't specified which yet)."

    p = PERSONA_CONTEXT.get(persona, PERSONA_CONTEXT["engineer"])

    return f"""You are a glossary contribution wizard for a data analytics platform in the organization.
{term_clause}

The user's role is: {p['role']}
- They likely know: {p['strength']}
- They likely don't know: {p['weakness']}
- Focus your questions on: {p['question_focus']}

IMPORTANT: Tailor question complexity and vocabulary to this role. Do NOT ask an executive about SQL or table names. Do NOT ask an engineer about dashboard layout or executive meetings.

Existing glossary terms include: {existing}

Generate exactly 5 smart questions to help THIS user contribute what they know about this term.
Each question must have:
- "id": sequential integer 1-5
- "text": the question text (appropriate for the user's role)
- "type": one of "select", "yes_no", "yes_no_text", "text"
- For "select" type: include "options" array with 3-8 options
- For "yes_no_text" type: include "follow_up_on": "yes"
- For "text" type: optionally include "placeholder" string

Return ONLY a valid JSON array of question objects, no markdown fences or explanation."""


def _build_synthesis_prompt(questions: list[dict], answers: list[dict], term: str | None) -> str:
    qa_text = ""
    for q in questions:
        answer = next((a for a in answers if a["question_id"] == q["id"]), None)
        answer_val = answer["value"] if answer else "(no answer)"
        qa_text += f"Q{q['id']}: {q['text']}\nA: {answer_val}\n\n"

    return f"""You are a glossary entry synthesizer for a data analytics platform in the organization.

Based on the following questionnaire answers, create a structured glossary entry.
{f'The term being defined is: "{term}"' if term else "Determine the term name from the answers."}

Questionnaire:
{qa_text}

Return ONLY a valid JSON object with these fields:
- "term": string (the term name)
- "definition": string (clear, concise business definition, 1-3 sentences)
- "formula": string or null (SQL formula if applicable)
- "source_table": string or null (e.g., "analytics.onboarding_kpi_detail")
- "pillar": string or null (business pillar)
- "notes": string or null (any additional context)

No markdown fences or explanation, just the JSON object."""


@router.post("/wizard/start")
async def wizard_start(req: WizardStartRequest, request: Request):
    kb = request.app.state.kb
    glossary_terms = list(kb.glossary.keys()) if kb.glossary else []

    _claude._ensure_client()
    prompt = _build_question_prompt(req.term, glossary_terms, req.persona)

    response = await _claude.client.messages.create(
        model=_claude.model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()

    try:
        questions = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback questions
        questions = [
            {"id": 1, "text": "Is this term related to an existing metric?", "type": "select", "options": ["Activation Rate", "Churn", "DAU", "Other", "It's a new concept"]},
            {"id": 2, "text": "Which pillar does this term belong to?", "type": "select", "options": ["Onboard", "Trigger Return", "Makeable Content", "Content Matching", "Design & Make", "Marketing", "Platform", "Cross-pillar"]},
            {"id": 3, "text": "In your own words, what does this term mean?", "type": "text"},
            {"id": 4, "text": "Is there a SQL formula or calculation?", "type": "yes_no_text", "follow_up_on": "yes"},
            {"id": 5, "text": "Which source table produces this metric?", "type": "text", "placeholder": "e.g., analytics.onboarding_kpi_detail"},
        ]

    wizard_id = str(uuid.uuid4())
    _wizard_sessions[wizard_id] = {
        "term": req.term,
        "questions": questions,
        "session_id": req.session_id,
        "trigger_reason": req.trigger_reason,
    }

    # Log wizard start as usage event
    pool = request.app.state.db_pool
    try:
        await pool.execute(
            """
            INSERT INTO usage_events (user_id, capability, pillar, environment, input_tokens, output_tokens, estimated_cost, model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            req.session_id or "local-dev",
            "glossary_wizard",
            None,
            None,
            response.usage.input_tokens,
            response.usage.output_tokens,
            0,
            config.CLAUDE_MODEL,
        )
    except Exception as e:
        logger.error("Failed to log wizard start usage: %s", e)

    return {"wizard_id": wizard_id, "questions": questions}


@router.post("/wizard/submit")
async def wizard_submit(req: WizardSubmitRequest, request: Request):
    session = _wizard_sessions.get(req.wizard_id)
    if not session:
        return {"error": "Wizard session not found or expired"}

    questions = session["questions"]
    term = session["term"]
    answers = [{"question_id": a.question_id, "value": a.value} for a in req.answers]

    _claude._ensure_client()
    prompt = _build_synthesis_prompt(questions, answers, term)

    response = await _claude.client.messages.create(
        model=_claude.model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()

    try:
        entry = json.loads(raw_text)
    except json.JSONDecodeError:
        entry = {
            "term": term or "Unknown",
            "definition": "Could not synthesize — please review answers manually.",
            "formula": None,
            "source_table": None,
            "pillar": None,
            "notes": json.dumps(answers),
        }

    # Store in glossary_entries as user-created draft
    pool = request.app.state.db_pool
    term_name = entry.get("term", term or "Unknown")
    term_key = term_name.lower().replace(" ", "_").replace("-", "_")
    created_by = req.session_id or "local-dev"

    try:
        await pool.execute("""
            INSERT INTO glossary_entries (
                term_key, term, definition, formula, source_tables, dimensions,
                status, workflow_state, auto_generated, created_by, created_by_type,
                expert_notes
            ) VALUES ($1, $2, $3, $4, $5::jsonb, '[]'::jsonb,
                'draft', 'draft', false, $6, 'user', $7)
            ON CONFLICT (term_key) DO UPDATE SET
                definition = $3, formula = $4, source_tables = $5::jsonb,
                expert_notes = $7, updated_at = NOW()
            WHERE glossary_entries.workflow_state = 'draft'
        """,
            term_key, term_name,
            entry.get("definition", ""),
            entry.get("formula"),
            json.dumps([entry["source_table"]] if entry.get("source_table") else []),
            created_by,
            entry.get("notes"),
        )

        # Log history
        await pool.execute("""
            INSERT INTO glossary_history (entry_id, action, actor, new_value)
            SELECT id, 'created', $2, 'Created via AI Wizard'
            FROM glossary_entries WHERE term_key = $1
        """, term_key, created_by)
    except Exception as e:
        logger.error("Failed to store wizard entry: %s", e)

    # Log usage
    try:
        await pool.execute(
            """
            INSERT INTO usage_events (user_id, capability, pillar, environment, input_tokens, output_tokens, estimated_cost, model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            req.session_id or "local-dev",
            "glossary_wizard",
            entry.get("pillar"),
            None,
            response.usage.input_tokens,
            response.usage.output_tokens,
            0,
            config.CLAUDE_MODEL,
        )
    except Exception as e:
        logger.error("Failed to log wizard submit usage: %s", e)

    # Clean up session
    _wizard_sessions.pop(req.wizard_id, None)

    return {"entry": entry, "status": "submitted"}
