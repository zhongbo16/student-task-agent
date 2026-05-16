import json
import os
from datetime import date
from pathlib import Path

from db import (
    get_active_agent_memory,
    get_all_tasks,
    get_latest_ai_boss_briefing,
    get_pending_task_candidates,
    get_recent_daily_reviews,
    get_recent_study_sessions,
)
from planner import (
    is_due_today,
    is_overdue,
    is_planned_today,
)
from urgency import calculate_urgency_score

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "ai_boss_chat.md"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TEXT_CHARS = 600
MAX_CONTEXT_ITEMS = 10


class AIChatConfigError(RuntimeError):
    pass


class AIChatResponseError(RuntimeError):
    def __init__(self, message, raw_response=None):
        super().__init__(message)
        self.raw_response = raw_response


def _load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def has_openai_api_key():
    configured, _ = openai_api_key_status()
    return configured


def openai_api_key_status():
    _load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False, "OPENAI_API_KEY is missing. Add it to your .env file to use AI Boss Chat."
    if not api_key.startswith("sk-"):
        return False, "OPENAI_API_KEY does not look like an OpenAI key. It should usually start with sk-. Check your .env file."
    return True, "OPENAI_API_KEY is configured."


def _openai_client():
    _load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AIChatConfigError(
            "OPENAI_API_KEY is missing. Add it to your .env file to use AI Boss Chat."
        )
    if not api_key.startswith("sk-"):
        raise AIChatConfigError(
            "OPENAI_API_KEY does not look like an OpenAI API key. It should usually start with sk-. Check your .env file."
        )

    try:
        from openai import OpenAI
    except ImportError as error:
        raise AIChatConfigError(
            "The openai package is missing. Run: pip install -r requirements.txt"
        ) from error

    return OpenAI(api_key=api_key)


def _truncate(value, max_chars=MAX_TEXT_CHARS):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _active_tasks():
    return [
        task for task in get_all_tasks()
        if task.get("status") not in ("done", "ignored")
    ]


def _task_score(task):
    try:
        return float(task.get("urgency_score") or calculate_urgency_score(task)[0])
    except (TypeError, ValueError):
        return calculate_urgency_score(task)[0]


def _compact_task(task):
    score, label, reasons = calculate_urgency_score(task)
    return {
        "id": task.get("id"),
        "title": _truncate(task.get("title"), 220),
        "course": _truncate(task.get("course"), 120),
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "source": task.get("source"),
        "confidence": task.get("confidence"),
        "due_at": task.get("due_at"),
        "planned_date": task.get("planned_date"),
        "estimated_minutes": task.get("estimated_minutes"),
        "priority": task.get("priority"),
        "urgency_score": task.get("urgency_score") or score,
        "urgency_label": task.get("urgency_label") or label,
        "urgency_reasons": reasons[:6],
        "first_action": _truncate(task.get("first_action"), 280),
        "notes": _truncate(task.get("notes"), 240),
    }


def _compact_candidate(candidate):
    return {
        "id": candidate.get("id"),
        "title": _truncate(candidate.get("title"), 220),
        "course": _truncate(candidate.get("course"), 120),
        "source": candidate.get("source"),
        "confidence": candidate.get("confidence"),
        "due_at": candidate.get("due_at"),
        "urgency_score": candidate.get("urgency_score"),
        "urgency_label": candidate.get("urgency_label"),
        "recommended_status": candidate.get("recommended_status"),
        "notes": _truncate(candidate.get("notes"), 240),
    }


def _compact_session(session):
    return {
        "task_id": session.get("task_id"),
        "task_title": _truncate(session.get("task_title"), 220),
        "course": _truncate(session.get("course"), 120),
        "actual_minutes": session.get("actual_minutes"),
        "completion_status": session.get("completion_status"),
        "blocker": _truncate(session.get("blocker"), 220),
        "notes": _truncate(session.get("notes"), 220),
        "created_at": session.get("created_at"),
    }


def _compact_review(review):
    return {
        "review_date": review.get("review_date"),
        "completed_summary": _truncate(review.get("completed_summary"), 260),
        "missed_tasks": _truncate(review.get("missed_tasks"), 260),
        "blockers": _truncate(review.get("blockers"), 260),
        "avoidance_notes": _truncate(review.get("avoidance_notes"), 260),
        "tomorrow_top_priority": _truncate(review.get("tomorrow_top_priority"), 180),
        "mood_energy": review.get("mood_energy"),
        "focus_rating": review.get("focus_rating"),
    }


def _compact_memory(memory):
    return {
        "memory_type": memory.get("memory_type"),
        "memory_key": _truncate(memory.get("memory_key"), 140),
        "memory_value": _truncate(memory.get("memory_value"), 420),
        "confidence": memory.get("confidence"),
        "source": memory.get("source"),
    }


def _latest_briefing_summary():
    record = get_latest_ai_boss_briefing()
    if not record:
        return None

    try:
        output = json.loads(record.get("output_json") or "{}")
    except json.JSONDecodeError:
        output = {}

    return {
        "briefing_date": record.get("briefing_date"),
        "executive_summary": _truncate(output.get("executive_summary"), 500),
        "first_25_minute_action": _truncate(
            output.get("first_25_minute_action"),
            300,
        ),
        "created_at": record.get("created_at"),
    }


def build_chat_context():
    current_date = date.today()
    tasks = _active_tasks()
    sorted_tasks = sorted(
        tasks,
        key=lambda task: (
            -_task_score(task),
            task.get("due_at") or "9999-12-31",
            task.get("title") or "",
        ),
    )
    overdue_tasks = [task for task in tasks if is_overdue(task, current_date)]
    due_today_tasks = [task for task in tasks if is_due_today(task, current_date)]
    planned_today_tasks = [
        task for task in tasks if is_planned_today(task, current_date)
    ]
    in_progress_tasks = [
        task for task in tasks if task.get("status") == "in_progress"
    ]
    pending_candidates = get_pending_task_candidates()
    recent_sessions = get_recent_study_sessions(limit=20)
    recent_reviews = get_recent_daily_reviews(limit=7)
    active_memories = get_active_agent_memory()

    return {
        "current_date": current_date.isoformat(),
        "guardrails": [
            "Read-only chat mode.",
            "Do not invent tasks or deadlines.",
            "Do not modify local data.",
            "All proposed actions require user confirmation later.",
        ],
        "counts": {
            "active_tasks": len(tasks),
            "top_urgent_tasks": min(len(sorted_tasks), MAX_CONTEXT_ITEMS),
            "overdue_tasks": len(overdue_tasks),
            "due_today_tasks": len(due_today_tasks),
            "planned_today_tasks": len(planned_today_tasks),
            "in_progress_tasks": len(in_progress_tasks),
            "pending_candidates": len(pending_candidates),
            "recent_study_sessions": min(len(recent_sessions), 10),
            "recent_daily_reviews": min(len(recent_reviews), 7),
            "active_memories": len(active_memories),
        },
        "top_urgent_tasks": [
            _compact_task(task) for task in sorted_tasks[:MAX_CONTEXT_ITEMS]
        ],
        "overdue_tasks": [
            _compact_task(task) for task in overdue_tasks[:MAX_CONTEXT_ITEMS]
        ],
        "due_today_tasks": [
            _compact_task(task) for task in due_today_tasks[:MAX_CONTEXT_ITEMS]
        ],
        "planned_today_tasks": [
            _compact_task(task) for task in planned_today_tasks[:MAX_CONTEXT_ITEMS]
        ],
        "in_progress_tasks": [
            _compact_task(task) for task in in_progress_tasks[:MAX_CONTEXT_ITEMS]
        ],
        "pending_task_candidates": [
            _compact_candidate(candidate)
            for candidate in pending_candidates[:MAX_CONTEXT_ITEMS]
        ],
        "recent_study_sessions": [
            _compact_session(session) for session in recent_sessions[:10]
        ],
        "recent_daily_reviews": [
            _compact_review(review) for review in recent_reviews[:7]
        ],
        "active_agent_memory": [
            _compact_memory(memory) for memory in active_memories[:20]
        ],
        "latest_ai_boss_briefing": _latest_briefing_summary(),
    }


def load_chat_system_prompt():
    if not PROMPT_PATH.exists():
        raise AIChatConfigError("AI Boss Chat prompt file is missing.")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _compact_recent_messages(recent_messages):
    compacted = []
    for message in recent_messages[-12:]:
        role = message.get("role")
        if role not in ("user", "assistant", "system"):
            continue
        compacted.append({
            "role": role,
            "content": _truncate(message.get("content"), 900),
        })
    return compacted


def _normalize_action(action):
    if not isinstance(action, dict):
        return None

    risk_level = action.get("risk_level")
    if risk_level not in ("low", "medium", "high"):
        risk_level = "medium"

    args = action.get("args")
    if not isinstance(args, dict):
        args = {}

    return {
        "action_type": _truncate(action.get("action_type"), 80) or "unknown",
        "risk_level": risk_level,
        "requires_confirmation": True,
        "args": args,
    }


def _normalize_response(parsed):
    if not isinstance(parsed, dict):
        raise AIChatResponseError("AI Boss Chat returned JSON, but not an object.")

    actions = []
    for action in parsed.get("proposed_actions") or []:
        normalized = _normalize_action(action)
        if normalized:
            actions.append(normalized)

    questions = parsed.get("questions") or []
    if not isinstance(questions, list):
        questions = [questions]

    return {
        "message": (
            _truncate(parsed.get("message"), 1600)
            or "I need a little more context before I can give a useful command."
        ),
        "proposed_actions": actions[:6],
        "questions": [
            _truncate(question, 240)
            for question in questions[:4]
            if _truncate(question, 240)
        ],
    }


def generate_chat_response(user_message, recent_messages, context):
    cleaned_message = _truncate(user_message, 4000)
    if not cleaned_message:
        raise ValueError("Message is required.")

    client = _openai_client()
    prompt = load_chat_system_prompt()
    model = os.environ.get("AI_CHAT_MODEL") or os.environ.get(
        "OPENAI_MODEL",
        DEFAULT_MODEL,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Compact local app context JSON:\n"
                        f"{json.dumps(context, ensure_ascii=False)}\n\n"
                        "Recent chat messages JSON:\n"
                        f"{json.dumps(_compact_recent_messages(recent_messages), ensure_ascii=False)}\n\n"
                        f"User message:\n{cleaned_message}"
                    ),
                },
            ],
        )
    except Exception as error:
        error_name = error.__class__.__name__.lower()
        error_text = str(error).lower()
        if (
            "authentication" in error_name
            or "invalid_api_key" in error_text
            or "incorrect api key" in error_text
        ):
            raise AIChatConfigError(
                "OpenAI rejected OPENAI_API_KEY. Check that .env contains a valid OpenAI key, not the Canvas URL or Canvas token."
            ) from error
        if "rate" in error_name:
            raise AIChatResponseError(
                "OpenAI rate limit was reached. Wait a moment and try again."
            ) from error
        raise AIChatResponseError(
            "OpenAI request failed. Check your model, network, or API key settings and try again."
        ) from error

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise AIChatResponseError(
            "AI Boss Chat returned invalid JSON. Try again.",
            raw_response=content,
        ) from error

    result = _normalize_response(parsed)
    result["_raw_response"] = content
    return result
