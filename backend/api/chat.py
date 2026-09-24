import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from api.models import ChatRequest
from config import config
from engine.claude_client import ClaudeClient
from engine.context import build_system_prompt
from tracking.logger import log_usage

logger = logging.getLogger("genie.chat")
router = APIRouter()
claude = ClaudeClient()

# ---------------------------------------------------------------------------
# Conversation summarization
# ---------------------------------------------------------------------------

# Threshold: summarize when history exceeds this many messages
SUMMARIZE_THRESHOLD = 10
# Keep this many recent messages in full (the rest get summarized)
KEEP_RECENT = 6

_summary_cache: dict[str, str] = {}  # chat_session_id -> summary
# Cap the cache — it is keyed by session and the pod runs for weeks.
_MAX_SUMMARY_CACHE = 500


async def _summarize_messages(messages: list[dict], session_id: str | None) -> list[dict]:
    """If history is long, compress older messages into a summary + keep recent ones."""
    if len(messages) <= SUMMARIZE_THRESHOLD:
        return messages

    # Split: old messages to summarize, recent to keep verbatim
    old_messages = messages[:-KEEP_RECENT]
    recent_messages = messages[-KEEP_RECENT:]

    # Check cache
    cache_key = session_id or ""
    old_hash = str(len(old_messages))  # simple invalidation
    cached = _summary_cache.get(cache_key)
    if cached and cached.startswith(f"[{old_hash}]"):
        summary_text = cached[len(f"[{old_hash}]"):]
    else:
        # Build summary using a lightweight prompt
        summary_prompt = (
            "Summarize this conversation concisely for context continuity. "
            "Include: key topics discussed, decisions made, tables/pipelines/terms mentioned, "
            "any user preferences stated, and unresolved questions. "
            "Be factual and compact — max 300 words."
        )
        summary_messages = [{"role": m["role"], "content": m["content"][:500]} for m in old_messages]
        conversation_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in summary_messages
        )

        try:
            summary_text = await claude.quick_completion(
                f"{summary_prompt}\n\n---\n{conversation_text}"
            )
            if len(_summary_cache) >= _MAX_SUMMARY_CACHE:
                # Drop the oldest half — summaries are cheap to regenerate.
                for stale_key in list(_summary_cache)[: _MAX_SUMMARY_CACHE // 2]:
                    _summary_cache.pop(stale_key, None)
            _summary_cache[cache_key] = f"[{old_hash}]{summary_text}"
            logger.info("Summarized %d messages into %d chars for session %s",
                       len(old_messages), len(summary_text), session_id)
        except Exception as e:
            logger.warning("Summarization failed, using truncated history: %s", e)
            # Fallback: just keep recent messages
            return recent_messages

    # Prepend summary as a system-like user message
    summary_msg = {
        "role": "user",
        "content": f"[Previous conversation summary — {len(old_messages)} messages]\n{summary_text}\n[End summary — continuing conversation below]"
    }
    # Add a fake assistant ack so the alternation is correct
    ack_msg = {
        "role": "assistant",
        "content": "Understood, I have the context from our earlier conversation. Continuing."
    }

    return [summary_msg, ack_msg] + recent_messages


async def _load_user_settings(pool, session_id: str | None, user_id: str | None = None) -> dict | None:
    """Load settings by authenticated user_id only. No session_id fallback (prevents cross-user leak)."""
    if user_id:
        row = await pool.fetchrow("SELECT * FROM user_settings WHERE user_id = $1", user_id)
        if row:
            return dict(row)
    return None


# Background chat tasks — keyed by session_id.
# Holds a strong reference to each asyncio task: create_task() alone only keeps a
# weak one, so a response still being generated could be garbage-collected the
# moment the client disconnected.
_background_chats: dict[str, dict] = {}
# Drop finished entries once the tracker grows past this (bounded memory in a
# pod that stays up for weeks).
_MAX_TRACKED_CHATS = 200


def _prune_background_chats() -> None:
    if len(_background_chats) <= _MAX_TRACKED_CHATS:
        return
    for sid in [k for k, v in _background_chats.items() if v.get("done")]:
        _background_chats.pop(sid, None)
        if len(_background_chats) <= _MAX_TRACKED_CHATS:
            break


@router.post("/chat/background-status/{session_id}")
async def chat_background_status(session_id: str):
    """Check if a background chat is still running."""
    entry = _background_chats.get(session_id)
    if not entry:
        return {"running": False, "has_response": False}
    return {"running": not entry.get("done", False), "has_response": bool(entry.get("response"))}


async def _get_cross_session_context(pool, user_id: str) -> str | None:
    """Fetch recent session topics for cross-session memory."""
    if not user_id or user_id == "anonymous":
        return None
    try:
        rows = await pool.fetch("""
            SELECT title, pillar, updated_at
            FROM chat_sessions
            WHERE user_id = $1 AND updated_at > NOW() - INTERVAL '7 days'
            ORDER BY updated_at DESC
            LIMIT 5
        """, user_id)
        if not rows:
            return None
        lines = ["## Recent Conversations (this user's past 7 days)"]
        for r in rows:
            pillar_tag = f" [{r['pillar']}]" if r.get("pillar") else ""
            lines.append(f"- {r['title'][:120]}{pillar_tag}")
        lines.append("Use this context to understand what the user has been working on. Don't repeat past answers — build on them.")
        return "\n".join(lines)
    except Exception:
        return None


async def _get_dynamic_sql_patterns(pool) -> list[dict] | None:
    """Fetch top saved queries by usage for dynamic SQL patterns."""
    try:
        rows = await pool.fetch("""
            SELECT name, sql FROM saved_queries
            WHERE is_public = true AND use_count > 0
            ORDER BY use_count DESC
            LIMIT 5
        """)
        return [dict(r) for r in rows] if rows else None
    except Exception:
        return None


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    kb = request.app.state.kb
    pool = request.app.state.db_pool

    chat_user_id = _get_user_id(request)
    user_settings = await _load_user_settings(pool, req.session_id, chat_user_id)

    # Fetch cross-session memory and dynamic patterns in parallel
    cross_session_ctx, dynamic_patterns = await asyncio.gather(
        _get_cross_session_context(pool, chat_user_id),
        _get_dynamic_sql_patterns(pool),
    )

    system_prompt = build_system_prompt(
        kb=kb,
        pillar=req.pillar,
        environment=req.environment,
        capability="chat",
        user_settings=user_settings,
        dynamic_sql_patterns=dynamic_patterns,
        cross_session_context=cross_session_ctx,
    )

    # Build user message — handle text attachments and image attachments
    has_images = any(att.is_image and att.base64 for att in req.attachments)
    text_attachments = [att for att in req.attachments if not att.is_image and att.content]
    image_attachments = [att for att in req.attachments if att.is_image and att.base64]

    if has_images:
        # Multimodal: build content blocks array (images + text)
        content_blocks = []
        for img in image_attachments:
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.media_type or "image/png",
                    "data": img.base64,
                },
            })
        # Add text attachments + user message
        text_parts = []
        for att in text_attachments:
            text_parts.append(f"--- Attached file: {att.filename} ---\n{att.content[:8000]}")
        text_parts.append(req.message or "What do you see in this image?")
        content_blocks.append({"type": "text", "text": "\n\n".join(text_parts)})
        user_content = content_blocks
    elif text_attachments:
        attachment_text = "\n\n".join(
            f"--- Attached file: {att.filename} ---\n{att.content[:8000]}"
            for att in text_attachments
        )
        user_content = f"{attachment_text}\n\n--- User question ---\n{req.message}"
    else:
        user_content = req.message

    # Build messages with summarization for long conversations
    raw_history = list(req.conversation_history)
    raw_history.append({"role": "user", "content": user_content})
    messages = await _summarize_messages(raw_history, req.session_id)

    was_summarized = len(raw_history) > SUMMARIZE_THRESHOLD
    context_info = {
        "total_messages": len(raw_history),
        "sent_messages": len(messages),
        "summarized": was_summarized,
    }

    # Run AI in background task — continues even if client disconnects
    event_queue: asyncio.Queue = asyncio.Queue()
    chat_session_id = req.session_id or ""
    tracked: dict | None = None  # set below, once the task exists

    async def _run_ai():
        """Background task that generates the response and saves it."""
        full_response = ""
        try:
            await event_queue.put({"event": "context", "data": json.dumps(context_info)})
            async for event in claude.chat_stream(system_prompt, messages, kb):
                if event["type"] == "text":
                    full_response += event["content"]
                    await event_queue.put({"event": "text", "data": json.dumps({"content": event["content"]})})
                elif event["type"] == "tool_call":
                    await event_queue.put({"event": "tool_call", "data": json.dumps({"tool": event["tool"], "input": event["input"]})})
                elif event["type"] == "tool_result":
                    await event_queue.put({"event": "tool_result", "data": json.dumps({"tool": event["tool"], "result": event["result"]})})
                elif event["type"] == "status":
                    await event_queue.put({"event": "status", "data": json.dumps({"content": event["content"]})})
                elif event["type"] == "expert_response":
                    pass
                elif event["type"] == "done":
                    # Log with the fast model since most tokens go through Sonnet
                    model_used = event.get("model_fast") or (config.BEDROCK_MODEL if config.AI_PROVIDER == "bedrock" else config.CLAUDE_MODEL)
                    await log_usage(
                        pool, capability="chat",
                        input_tokens=event["input_tokens"], output_tokens=event["output_tokens"],
                        pillar=req.pillar, environment=req.environment,
                        model=model_used,
                        user_id=chat_user_id,
                    )
                    await _auto_create_gap_tickets(pool, full_response, chat_user_id)
                    await _auto_capture_corrections(pool, full_response, chat_user_id)
                    await event_queue.put({"event": "done", "data": json.dumps(event)})
        except Exception as e:
            error_msg = str(e)
            if "expired" in error_msg.lower() or "security token" in error_msg.lower():
                error_msg = "AWS SSO session expired. Please reconnect in Settings → Connection."
            elif "credit balance" in error_msg.lower():
                error_msg = "Anthropic API credits depleted. Switch to Bedrock."
            elif "PermissionDenied" in error_msg or "403" in error_msg:
                error_msg = "Access denied. Check AI provider permissions."
            else:
                error_msg = f"Chat error: {error_msg[:200]}"
            full_response += f"\n\n**Error:** {error_msg}"
            await event_queue.put({"event": "text", "data": json.dumps({"content": f"\n\n**Error:** {error_msg}"})})
            await event_queue.put({"event": "done", "data": json.dumps({"input_tokens": 0, "output_tokens": 0, "elapsed_seconds": 0})})
        finally:
            if tracked is not None:
                tracked["response"] = full_response

            # Save response to session (works even if client disconnected)
            if full_response and chat_session_id:
                try:
                    all_messages = list(req.conversation_history) + [
                        {"role": "user", "content": req.message},
                        {"role": "assistant", "content": full_response},
                    ]
                    title = req.message[:100]
                    await pool.execute("""
                        INSERT INTO chat_sessions (id, user_id, pillar, title, messages, updated_at)
                        VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
                        ON CONFLICT (id) DO UPDATE SET messages = $5::jsonb, updated_at = NOW()
                    """, chat_session_id, chat_user_id, req.pillar, title, json.dumps(all_messages))
                except Exception:
                    pass

            # Notify if client likely disconnected (unconsumed events in queue)
            if full_response and chat_user_id != "anonymous" and event_queue.qsize() > 0:
                try:
                    from api.notifications import create_notification
                    await create_notification(
                        pool, chat_user_id, "chat_complete",
                        "Chat response ready",
                        f"Your question has been answered: {req.message[:80]}",
                        f"/?session={chat_session_id}",
                    )
                except Exception:
                    pass

            await event_queue.put(None)  # Signal end

    # Start background task. Track it so (a) the event loop keeps a strong
    # reference until it finishes and (b) /chat/background-status can answer
    # truthfully after the client reconnects.
    task = asyncio.create_task(_run_ai())
    if chat_session_id:
        tracked = {"task": task, "done": False, "response": ""}
        _background_chats[chat_session_id] = tracked

        def _mark_done(_t: asyncio.Task) -> None:
            # Mark this task's own entry — a second request on the same session
            # replaces the map entry, and must not be reported done by the first.
            tracked["done"] = True
            _prune_background_chats()

        task.add_done_callback(_mark_done)

    async def event_generator():
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield event

    return EventSourceResponse(event_generator())


import re

_KB_GAP_PATTERN = re.compile(r"💡\s*KB\s*Improvement:\s*(.+?)(?:\n|$)", re.IGNORECASE)


async def _auto_create_gap_tickets(pool, response_text: str, user_id: str):
    """Parse KB improvement suggestions from agent response and auto-create tickets."""
    gaps = _KB_GAP_PATTERN.findall(response_text)
    if not gaps:
        return

    for gap_desc in gaps[:3]:  # max 3 per response to avoid spam
        gap_desc = gap_desc.strip()
        if len(gap_desc) < 10:
            continue

        # Check for duplicate (same title in last 24h)
        existing = await pool.fetchval(
            """SELECT id FROM feedback_tickets
               WHERE title = $1 AND created_at > NOW() - INTERVAL '24 hours'""",
            gap_desc[:200],
        )
        if existing:
            continue

        # Auto-assign to first admin
        admin_row = await pool.fetchrow(
            "SELECT email FROM users WHERE role = 'admin' AND is_active = true ORDER BY id LIMIT 1"
        )
        assigned = admin_row["email"] if admin_row else None

        # Determine category
        category = "kb_gap"
        if "glossary" in gap_desc.lower() or "definition" in gap_desc.lower():
            category = "glossary"
        elif "column" in gap_desc.lower() or "table" in gap_desc.lower():
            category = "data"
        elif "dag" in gap_desc.lower() or "pipeline" in gap_desc.lower() or "mwaa" in gap_desc.lower():
            category = "pipeline"

        try:
            await pool.execute("""
                INSERT INTO feedback_tickets (title, description, status, priority, category,
                                              created_by, assigned_to)
                VALUES ($1, $2, 'open', 'low', $3, $4, $5)
            """,
                gap_desc[:200],
                f"Auto-detected by AI agent during chat.\n\nFull suggestion: {gap_desc}",
                category,
                f"agent (user:{user_id})",
                assigned,
            )
            logger.info("Auto-created KB gap ticket: %s", gap_desc[:80])
        except Exception as e:
            logger.warning("Failed to auto-create gap ticket: %s", e)


_CORRECTION_PATTERN = re.compile(
    r"📝\s*Correction:\s*(.+?)\s*[—–-]\s*(.+?)→\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


async def _auto_capture_corrections(pool, response_text: str, user_id: str):
    """Parse correction markers from agent response and create glossary draft updates."""
    corrections = _CORRECTION_PATTERN.findall(response_text)
    if not corrections:
        return

    for term, was_wrong, correct_def in corrections[:3]:
        term = term.strip()
        was_wrong = was_wrong.strip()
        correct_def = correct_def.strip()

        if len(term) < 2 or len(correct_def) < 5:
            continue

        # Check if glossary entry already exists (shared dedup logic)
        from api.glossary_review import find_existing_entry
        existing = await find_existing_entry(pool, term)

        if existing:
            # Check for duplicate correction in last 24h
            dup = await pool.fetchval(
                """SELECT id FROM glossary_entries
                   WHERE LOWER(term) = LOWER($1) AND created_by_type = 'chat_correction'
                   AND created_at > NOW() - INTERVAL '24 hours'""",
                term,
            )
            if dup:
                continue

            # Create an update draft linked to the original
            try:
                correction_note = f"Correction from chat. Previous: {was_wrong}. Original entry #{existing['id']} ({existing.get('workflow_state', existing.get('status', '?'))})."
                await pool.execute("""
                    INSERT INTO glossary_entries
                        (term, term_key, definition, status, created_by, created_by_type,
                         expert_notes, sources)
                    VALUES ($1, LOWER($1), $2, 'draft', $3, 'chat_correction', $4, $5::jsonb)
                """,
                    term,
                    correct_def,
                    f"auto (user:{user_id})",
                    correction_note,
                    json.dumps([{"type": "chat_correction", "user": user_id, "was": was_wrong}]),
                )
                logger.info("Created glossary correction draft: %s", term)
            except Exception as e:
                logger.warning("Failed to create correction draft: %s", e)
        else:
            # New term — create draft entry
            try:
                await pool.execute("""
                    INSERT INTO glossary_entries
                        (term, term_key, definition, status, created_by, created_by_type,
                         expert_notes, sources)
                    VALUES ($1, LOWER($1), $2, 'draft', $3, 'chat_correction', $4, $5::jsonb)
                """,
                    term,
                    correct_def,
                    f"auto (user:{user_id})",
                    f"New term from chat. User said: {was_wrong} → {correct_def}",
                    json.dumps([{"type": "chat_correction", "user": user_id}]),
                )
                logger.info("Created new glossary entry from correction: %s", term)
            except Exception as e:
                logger.warning("Failed to create correction entry: %s", e)

    # Create review task assigned to the correcting user + notify them
    if corrections:
        terms = ", ".join(c[0].strip() for c in corrections[:3])
        try:
            # Task assigned to the user who made the correction (self-review)
            await pool.execute("""
                INSERT INTO feedback_tickets (title, description, status, priority, category,
                                              created_by, assigned_to)
                VALUES ($1, $2, 'open', 'high', 'glossary', $3, $4)
            """,
                f"Review your correction: {terms}"[:200],
                f"You corrected these definitions during chat. Please review and approve the glossary drafts:\n\n"
                + "\n".join(f"- **{c[0].strip()}**: {c[1].strip()} → {c[2].strip()}" for c in corrections[:3])
                + "\n\nGo to Glossary → filter by 'draft' to review.",
                f"agent (user:{user_id})",
                user_id,  # assigned to the corrector, not admin
            )
        except Exception:
            pass

        # Notification to the correcting user
        try:
            from api.notifications import create_notification
            await create_notification(
                pool, user_id, "glossary_correction",
                f"Your correction to '{terms}' is ready for review",
                f"Review and approve your glossary correction for: {terms}",
                "/glossary?status=draft",
            )
        except Exception:
            pass

        # Also notify admins so they're aware
        try:
            from api.notifications import notify_all_admins
            await notify_all_admins(
                pool, "glossary_correction",
                f"Glossary correction by {user_id}: {terms}",
                f"User corrected: {terms}. Draft entries created for review.",
                "/glossary?status=draft",
            )
        except Exception:
            pass


def _get_user_id(request: Request) -> str:
    """Get user_id from auth token, or fallback."""
    from api.users import get_current_user
    user = get_current_user(request)
    if user and user.get("user_id"):
        return str(user["user_id"])
    return "anonymous"


@router.post("/chat/extract-file")
async def extract_file_text(request: Request):
    """Extract text from an uploaded file for chat attachment. Returns extracted text."""
    from fastapi import UploadFile, File
    import io

    form = await request.form()
    file = form.get("file")
    if not file:
        from fastapi import HTTPException
        raise HTTPException(400, "No file uploaded")

    content = await file.read()
    filename = file.filename or "unknown"

    # Reuse glossary's text extraction logic. PDF/docx parsing is CPU-bound and
    # can take seconds on a large file — run it in a worker thread so it never
    # stalls the event loop for every other request.
    from api.glossary_review import _extract_text_from_file
    text = await asyncio.to_thread(_extract_text_from_file, content, filename)

    return {
        "filename": filename,
        "size": len(content),
        "extracted_length": len(text),
        "content": text[:12000],  # cap at 12K chars for chat context
        "truncated": len(text) > 12000,
    }


@router.post("/chat/sessions")
async def save_session(request: Request):
    body = await request.json()
    pool = request.app.state.db_pool
    session_id = body.get("session_id", str(uuid.uuid4()))
    messages = body.get("messages", [])
    pillar = body.get("pillar")
    title = messages[0]["content"][:100] if messages else "New session"
    user_id = _get_user_id(request)

    await pool.execute(
        """
        INSERT INTO chat_sessions (id, user_id, pillar, title, messages, updated_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
        ON CONFLICT (id) DO UPDATE SET
            messages = $5::jsonb,
            updated_at = NOW()
        """,
        session_id,
        user_id,
        pillar,
        title,
        json.dumps(messages),
    )
    return {"session_id": session_id}


@router.get("/chat/sessions")
async def list_sessions(request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    rows = await pool.fetch(
        """
        SELECT id, pillar, title, created_at, updated_at
        FROM chat_sessions
        WHERE user_id = $1 AND updated_at > NOW() - INTERVAL '30 days'
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        user_id,
    )
    return [dict(r) for r in rows]


@router.put("/chat/sessions/{session_id}/title")
async def rename_session(session_id: str, request: Request):
    """Rename a chat session."""
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        from fastapi import HTTPException
        raise HTTPException(400, "Title required")
    await pool.execute(
        "UPDATE chat_sessions SET title = $3, updated_at = NOW() WHERE id = $1 AND user_id = $2",
        session_id, user_id, title[:200],
    )
    return {"status": "renamed"}


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """Delete a chat session. Users can only delete their own."""
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    result = await pool.execute(
        "DELETE FROM chat_sessions WHERE id = $1 AND user_id = $2",
        session_id, user_id,
    )
    # asyncpg returns the command tag ("DELETE 0" when nothing matched) — don't
    # report success for a session that doesn't exist or isn't the caller's.
    if result == "DELETE 0":
        from fastapi import HTTPException
        raise HTTPException(404, "Session not found")
    return {"status": "deleted"}


@router.get("/chat/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    pool = request.app.state.db_pool
    user_id = _get_user_id(request)
    row = await pool.fetchrow(
        "SELECT * FROM chat_sessions WHERE id = $1 AND user_id = $2",
        session_id, user_id,
    )
    if not row:
        return {"error": "Session not found"}
    result = dict(row)
    result["messages"] = json.loads(result["messages"]) if isinstance(result["messages"], str) else result["messages"]
    return result


@router.get("/chat/shared/{session_id}")
async def get_shared_session(session_id: str, request: Request):
    """Get a chat session for read-only sharing. Any authenticated user can view."""
    pool = request.app.state.db_pool
    row = await pool.fetchrow(
        "SELECT id, pillar, title, messages, created_at, updated_at, user_id FROM chat_sessions WHERE id = $1",
        session_id,
    )
    if not row:
        return {"error": "Session not found"}
    result = dict(row)
    result["messages"] = json.loads(result["messages"]) if isinstance(result["messages"], str) else result["messages"]
    # Get owner name
    owner = await pool.fetchrow("SELECT name, email FROM users WHERE id::text = $1", str(result.get("user_id", "")))
    result["owner_name"] = owner["name"] if owner else "Unknown"
    result["owner_email"] = owner["email"] if owner else ""
    result["shared"] = True  # flag that this is a shared view
    return result
