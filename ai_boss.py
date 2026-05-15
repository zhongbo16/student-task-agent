import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from planner import (
    estimated_minutes,
    is_due_this_week,
    is_due_today,
    is_overdue,
    is_planned_today,
    parse_task_date,
    priority_score,
)
from urgency import calculate_urgency_score

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "ai_boss.md"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_CONTEXT_TASKS_PER_GROUP = 12
MAX_MEMORY_VALUE_CHARS = 700
MAX_TEXT_CHARS = 500


class AIBossConfigError(RuntimeError):
    """Raised when AI Boss cannot be configured safely."""


class AIBossResponseError(RuntimeError):
    """Raised when AI Boss returns a response the app cannot parse."""

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
    _load_env_file()
    return bool(os.environ.get("OPENAI_API_KEY"))


def _openai_client():
    _load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AIBossConfigError(
            "OPENAI_API_KEY is missing. Add it to your .env file to use AI Boss."
        )

    try:
        from openai import OpenAI
    except ImportError as error:
        raise AIBossConfigError(
            "The openai package is missing. Run: pip install -r requirements.txt"
        ) from error

    return OpenAI(api_key=api_key)


def _read_prompt():
    if not PROMPT_PATH.exists():
        raise AIBossConfigError("AI Boss prompt file is missing.")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(value, max_chars=MAX_TEXT_CHARS):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _parse_context_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def _date_label(task, current_date):
    if is_overdue(task, current_date):
        return "overdue"
    if is_due_today(task, current_date):
        return "due_today"
    if is_planned_today(task, current_date):
        return "planned_today"
    if is_due_this_week(task, current_date):
        return "due_soon"
    if parse_task_date(task.get("due_at")) or parse_task_date(task.get("planned_date")):
        return "dated"
    return "undated"


def _compact_task(task, current_date):
    task_id = task.get("id")
    urgency_score, urgency_label, urgency_reasons = calculate_urgency_score(
        task,
        current_date,
    )
    return {
        "id": str(task_id) if task_id is not None else None,
        "title": _truncate(task.get("title"), 220),
        "course": _truncate(task.get("course"), 120),
        "task_type": _truncate(task.get("task_type"), 80),
        "status": task.get("status"),
        "source": task.get("source"),
        "confidence": task.get("confidence"),
        "due_at": task.get("due_at"),
        "planned_date": task.get("planned_date"),
        "date_label": _date_label(task, current_date),
        "estimated_minutes": estimated_minutes(task),
        "priority": priority_score(task) or None,
        "urgency_score": task.get("urgency_score") or urgency_score,
        "urgency_label": task.get("urgency_label") or urgency_label,
        "urgency_reasons": urgency_reasons[:6],
        "notes": _truncate(task.get("notes"), 260),
        "updated_at": task.get("updated_at"),
    }


def _compact_today_plan_item(item, current_date):
    task = item.get("task", {}) if isinstance(item, dict) else {}
    return {
        "task": _compact_task(task, current_date),
        "reason": _truncate(item.get("reason"), 260) if isinstance(item, dict) else None,
    }


def _compact_study_session(session):
    return {
        "task_id": (
            str(session.get("task_id")) if session.get("task_id") is not None else None
        ),
        "task_title": _truncate(session.get("task_title"), 220),
        "course": _truncate(session.get("course"), 120),
        "start_time": session.get("start_time"),
        "end_time": session.get("end_time"),
        "planned_minutes": session.get("planned_minutes"),
        "actual_minutes": session.get("actual_minutes"),
        "completion_status": session.get("completion_status"),
        "blocker": _truncate(session.get("blocker"), 260),
        "notes": _truncate(session.get("notes"), 260),
        "created_at": session.get("created_at"),
    }


def _compact_daily_review(review):
    return {
        "review_date": review.get("review_date"),
        "completed_summary": _truncate(review.get("completed_summary"), 360),
        "missed_tasks": _truncate(review.get("missed_tasks"), 360),
        "blockers": _truncate(review.get("blockers"), 360),
        "avoidance_notes": _truncate(review.get("avoidance_notes"), 360),
        "tomorrow_top_priority": _truncate(review.get("tomorrow_top_priority"), 220),
        "mood_energy": review.get("mood_energy"),
        "focus_rating": review.get("focus_rating"),
    }


def _compact_memory(memory):
    return {
        "memory_type": memory.get("memory_type"),
        "memory_key": _truncate(memory.get("memory_key"), 160),
        "memory_value": _truncate(memory.get("memory_value"), MAX_MEMORY_VALUE_CHARS),
        "confidence": memory.get("confidence"),
        "source": memory.get("source"),
        "updated_at": memory.get("updated_at"),
    }


def _limit_tasks(tasks, current_date, max_items=MAX_CONTEXT_TASKS_PER_GROUP):
    compacted = [_compact_task(task, current_date) for task in tasks[:max_items]]
    return compacted


def _is_active_task(task):
    return task.get("status") not in ("done", "ignored")


def _is_suggested_important(task, current_date):
    if task.get("status") != "suggested":
        return False
    if priority_score(task) >= 4:
        return True
    return (
        is_overdue(task, current_date)
        or is_due_today(task, current_date)
        or is_planned_today(task, current_date)
        or is_due_this_week(task, current_date)
    )


def build_ai_boss_context(
    tasks,
    today_plan,
    recent_study_sessions,
    recent_daily_reviews,
    active_memories,
    current_date,
):
    """
    Build a compact local-data context for AI Boss.

    This intentionally sends only recent and decision-relevant data, not the
    entire database, full PDF text, or full course descriptions.
    """
    current_day = _parse_context_date(current_date)
    active_tasks = [task for task in tasks if _is_active_task(task)]

    overdue_tasks = [task for task in active_tasks if is_overdue(task, current_day)]
    due_today_tasks = [task for task in active_tasks if is_due_today(task, current_day)]
    planned_today_tasks = [
        task for task in active_tasks if is_planned_today(task, current_day)
    ]
    due_soon_tasks = [
        task for task in active_tasks if is_due_this_week(task, current_day)
    ]
    in_progress_tasks = [
        task for task in active_tasks if task.get("status") == "in_progress"
    ]
    high_priority_confirmed_tasks = [
        task for task in active_tasks
        if task.get("status") == "confirmed" and priority_score(task) >= 5
    ]
    suggested_important_tasks = [
        task for task in active_tasks if _is_suggested_important(task, current_day)
    ]

    seven_days_ago = current_day - timedelta(days=7)
    recent_sessions = []
    for session in recent_study_sessions[:20]:
        created_at = str(session.get("created_at") or "")[:10]
        created_date = _parse_context_date(created_at) if created_at else None
        if created_date is None or created_date >= seven_days_ago:
            recent_sessions.append(session)
    if not recent_sessions:
        recent_sessions = recent_study_sessions[:20]

    return {
        "current_date": current_day.isoformat(),
        "guardrails": [
            "Do not invent tasks or deadlines.",
            "Do not automatically change task statuses.",
            "Suggested tasks are unconfirmed until the user confirms them.",
            "Recommend at most 3 main tasks.",
        ],
        "counts": {
            "active_tasks": len(active_tasks),
            "overdue_tasks": len(overdue_tasks),
            "due_today_tasks": len(due_today_tasks),
            "planned_today_tasks": len(planned_today_tasks),
            "due_soon_tasks": len(due_soon_tasks),
            "in_progress_tasks": len(in_progress_tasks),
            "active_memories": len(active_memories),
            "recent_study_sessions": len(recent_sessions[:20]),
            "recent_daily_reviews": len(recent_daily_reviews[:7]),
        },
        "task_groups": {
            "overdue": _limit_tasks(overdue_tasks, current_day),
            "due_today": _limit_tasks(due_today_tasks, current_day),
            "planned_today": _limit_tasks(planned_today_tasks, current_day),
            "due_next_7_days": _limit_tasks(due_soon_tasks, current_day),
            "in_progress": _limit_tasks(in_progress_tasks, current_day),
            "high_priority_confirmed": _limit_tasks(
                high_priority_confirmed_tasks,
                current_day,
            ),
            "important_suggested": _limit_tasks(
                suggested_important_tasks,
                current_day,
            ),
        },
        "today_plan": [
            _compact_today_plan_item(item, current_day)
            for item in today_plan[:3]
        ],
        "recent_study_sessions": [
            _compact_study_session(session) for session in recent_sessions[:20]
        ],
        "recent_daily_reviews": [
            _compact_daily_review(review) for review in recent_daily_reviews[:7]
        ],
        "active_agent_memory": [
            _compact_memory(memory) for memory in active_memories
        ],
    }


def _normalize_top_task(task):
    if not isinstance(task, dict):
        return None

    estimated = task.get("estimated_minutes")
    try:
        estimated = int(estimated) if estimated not in (None, "") else None
    except (TypeError, ValueError):
        estimated = None

    return {
        "task_id": (
            str(task.get("task_id")) if task.get("task_id") not in (None, "") else None
        ),
        "title": _truncate(task.get("title"), 240) or "Untitled task",
        "course": _truncate(task.get("course"), 120),
        "estimated_minutes": estimated,
        "reason": _truncate(task.get("reason"), 500) or "Recommended by AI Boss.",
        "first_action": (
            _truncate(task.get("first_action"), 500)
            or "Start with a clear 25-minute work block."
        ),
    }


def _normalize_briefing(parsed):
    if not isinstance(parsed, dict):
        raise AIBossResponseError("AI Boss returned JSON, but not an object.")

    top_tasks = []
    for task in parsed.get("top_tasks", []):
        normalized = _normalize_top_task(task)
        if normalized:
            top_tasks.append(normalized)

    avoid_doing = parsed.get("avoid_doing") or []
    if not isinstance(avoid_doing, list):
        avoid_doing = [avoid_doing]

    return {
        "executive_summary": (
            _truncate(parsed.get("executive_summary"), 900)
            or "No executive summary was provided."
        ),
        "top_tasks": top_tasks[:3],
        "first_25_minute_action": (
            _truncate(parsed.get("first_25_minute_action"), 700)
            or "Pick the highest priority task and work for 25 minutes."
        ),
        "avoid_doing": [
            _truncate(item, 240) for item in avoid_doing[:5] if _truncate(item, 240)
        ],
        "avoidance_warning": _truncate(parsed.get("avoidance_warning"), 700),
        "schedule_advice": (
            _truncate(parsed.get("schedule_advice"), 900)
            or "Use a short, focused work block before adjusting the plan."
        ),
        "end_of_day_check_in_question": (
            _truncate(parsed.get("end_of_day_check_in_question"), 500)
            or "What did you finish, and what blocked you today?"
        ),
    }


def generate_ai_boss_briefing(context):
    """
    Call OpenAI only when the user explicitly requests a briefing.

    Returns structured briefing JSON. The internal _raw_response key is included
    so the UI can save/debug the exact model response without printing secrets.
    """
    client = _openai_client()
    prompt = _read_prompt()
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Generate today's AI Boss execution briefing from this "
                    "local context JSON:\n\n"
                    f"{json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise AIBossResponseError(
            "AI Boss returned invalid JSON. Try generating again.",
            raw_response=content,
        ) from error

    briefing = _normalize_briefing(parsed)
    briefing["_raw_response"] = content
    return briefing


def format_ai_boss_briefing_for_display(briefing):
    top_tasks = briefing.get("top_tasks") or []
    lines = [briefing.get("executive_summary") or ""]
    for index, task in enumerate(top_tasks, start=1):
        lines.append(f"{index}. {task.get('title')}: {task.get('reason')}")
    lines.append(
        "First 25 minutes: "
        f"{briefing.get('first_25_minute_action') or 'Start with task one.'}"
    )
    return "\n".join(line for line in lines if line)
