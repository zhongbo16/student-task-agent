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
    priority_score,
)
from urgency import calculate_urgency_score

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "daily_command.md"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TEXT_CHARS = 600
MAX_CONTEXT_TASKS = 20
MAX_MEMORY_VALUE_CHARS = 700


class DailyCommandConfigError(RuntimeError):
    """Raised when Daily Command cannot be configured safely."""


class DailyCommandResponseError(RuntimeError):
    """Raised when Daily Command returns output the app cannot parse."""

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
        raise DailyCommandConfigError(
            "OPENAI_API_KEY is missing. Add it to your .env file to use Daily Command."
        )

    try:
        from openai import OpenAI
    except ImportError as error:
        raise DailyCommandConfigError(
            "The openai package is missing. Run: pip install -r requirements.txt"
        ) from error

    return OpenAI(api_key=api_key)


def _read_prompt():
    if not PROMPT_PATH.exists():
        raise DailyCommandConfigError("Daily Command prompt file is missing.")
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
    if task.get("due_at") or task.get("planned_date"):
        return "dated"
    return "undated"


def _compact_task(task, current_date):
    urgency_score, urgency_label, urgency_reasons = calculate_urgency_score(
        task,
        current_date,
    )
    task_id = task.get("id")
    return {
        "id": str(task_id) if task_id is not None else None,
        "title": _truncate(task.get("title"), 240),
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
    }


def _compact_today_plan_item(item, current_date):
    task = item.get("task", {}) if isinstance(item, dict) else {}
    return {
        "task": _compact_task(task, current_date),
        "reason": _truncate(item.get("reason"), 300) if isinstance(item, dict) else None,
    }


def _compact_study_session(session):
    return {
        "task_id": (
            str(session.get("task_id")) if session.get("task_id") is not None else None
        ),
        "task_title": _truncate(session.get("task_title"), 220),
        "course": _truncate(session.get("course"), 120),
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
        "tomorrow_top_priority": _truncate(review.get("tomorrow_top_priority"), 240),
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
    }


def _compact_morning_checkin(checkin):
    if not checkin:
        return None

    return {
        "checkin_date": checkin.get("checkin_date"),
        "available_study_minutes": checkin.get("available_study_minutes"),
        "available_time_blocks": _truncate(checkin.get("available_time_blocks"), 700),
        "fixed_commitments": _truncate(checkin.get("fixed_commitments"), 700),
        "extra_commitments": _truncate(checkin.get("extra_commitments"), 700),
        "sleep_quality": checkin.get("sleep_quality"),
        "energy_level": checkin.get("energy_level"),
        "stress_level": checkin.get("stress_level"),
        "mood": _truncate(checkin.get("mood"), 160),
        "top_personal_priority": _truncate(
            checkin.get("top_personal_priority"),
            260,
        ),
        "avoiding_task": _truncate(checkin.get("avoiding_task"), 260),
        "hard_stop_time": checkin.get("hard_stop_time"),
        "notes": _truncate(checkin.get("notes"), 500),
    }


def _compact_personal_commitment(commitment):
    return {
        "id": str(commitment.get("id")) if commitment.get("id") is not None else None,
        "title": _truncate(commitment.get("title"), 220),
        "commitment_type": commitment.get("commitment_type"),
        "planned_date": commitment.get("planned_date"),
        "start_time": commitment.get("start_time"),
        "estimated_minutes": commitment.get("estimated_minutes"),
        "priority": commitment.get("priority"),
        "status": commitment.get("status"),
        "notes": _truncate(commitment.get("notes"), 260),
    }


def _active_task_sort_key(task, current_date):
    score, _, _ = calculate_urgency_score(task, current_date)
    due_at = task.get("due_at") or "9999-12-31"
    planned_date = task.get("planned_date") or "9999-12-31"
    return (
        -score,
        due_at,
        planned_date,
        -priority_score(task),
        task.get("title") or "",
    )


def _is_active_task(task):
    return task.get("status") not in ("done", "ignored")


def build_daily_command_context(
    tasks,
    today_plan,
    morning_checkin,
    personal_commitments,
    recent_study_sessions,
    recent_daily_reviews,
    active_memories,
    current_date,
):
    """
    Build a compact local context for Daily Command.

    This sends only decision-relevant local data. It does not include full PDFs,
    private database dumps, or raw course descriptions.
    """
    current_day = _parse_context_date(current_date)
    active_tasks = [task for task in tasks if _is_active_task(task)]
    ranked_active_tasks = sorted(
        active_tasks,
        key=lambda task: _active_task_sort_key(task, current_day),
    )

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
            "Use at most 3 main academic tasks.",
            "Fit the plan to the user's available time and commitments.",
        ],
        "counts": {
            "active_tasks": len(active_tasks),
            "today_plan_items": len(today_plan[:3]),
            "personal_commitments": len(personal_commitments),
            "recent_study_sessions": len(recent_sessions[:20]),
            "recent_daily_reviews": len(recent_daily_reviews[:7]),
            "active_memories": len(active_memories),
        },
        "morning_checkin": _compact_morning_checkin(morning_checkin),
        "personal_commitments": [
            _compact_personal_commitment(commitment)
            for commitment in personal_commitments
        ],
        "today_plan": [
            _compact_today_plan_item(item, current_day)
            for item in today_plan[:3]
        ],
        "top_active_tasks_by_urgency": [
            _compact_task(task, current_day)
            for task in ranked_active_tasks[:MAX_CONTEXT_TASKS]
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


def _clean_int(value):
    if value in (None, ""):
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _normalize_main_task(task):
    if not isinstance(task, dict):
        return None

    return {
        "task_id": (
            str(task.get("task_id")) if task.get("task_id") not in (None, "") else None
        ),
        "title": _truncate(task.get("title"), 240) or "Untitled task",
        "course": _truncate(task.get("course"), 120),
        "estimated_minutes": _clean_int(task.get("estimated_minutes")),
        "reason": _truncate(task.get("reason"), 500) or "Recommended for today.",
        "first_action": (
            _truncate(task.get("first_action"), 500)
            or "Work on the first concrete step for 25 minutes."
        ),
    }


def _normalize_personal_item(item):
    if not isinstance(item, dict):
        return None

    return {
        "commitment_id": (
            str(item.get("commitment_id"))
            if item.get("commitment_id") not in (None, "")
            else None
        ),
        "title": _truncate(item.get("title"), 220) or "Personal commitment",
        "time_advice": _truncate(item.get("time_advice"), 400) or "Keep it bounded.",
        "reason": _truncate(item.get("reason"), 400) or "Included from morning check-in.",
    }


def _normalize_time_block(block):
    if not isinstance(block, dict):
        return None

    return {
        "start_time": _truncate(block.get("start_time"), 20),
        "label": _truncate(block.get("label"), 120) or "Work block",
        "focus": _truncate(block.get("focus"), 300) or "Focused work",
        "minutes": _clean_int(block.get("minutes")),
        "notes": _truncate(block.get("notes"), 400) or "",
    }


def _normalize_daily_command(parsed):
    if not isinstance(parsed, dict):
        raise DailyCommandResponseError(
            "Daily Command returned JSON, but not an object."
        )

    main_tasks = []
    for task in parsed.get("main_tasks", []):
        normalized = _normalize_main_task(task)
        if normalized:
            main_tasks.append(normalized)

    personal_commitments = []
    for item in parsed.get("personal_commitments", []):
        normalized = _normalize_personal_item(item)
        if normalized:
            personal_commitments.append(normalized)

    time_blocks = []
    for block in parsed.get("time_blocks", []):
        normalized = _normalize_time_block(block)
        if normalized:
            time_blocks.append(normalized)

    avoid_doing = parsed.get("avoid_doing") or []
    if not isinstance(avoid_doing, list):
        avoid_doing = [avoid_doing]

    return {
        "executive_summary": (
            _truncate(parsed.get("executive_summary"), 900)
            or "No daily command summary was provided."
        ),
        "main_tasks": main_tasks[:3],
        "personal_commitments": personal_commitments[:6],
        "time_blocks": time_blocks[:10],
        "first_25_minute_action": (
            _truncate(parsed.get("first_25_minute_action"), 700)
            or "Start a 25-minute focus block on the highest priority task."
        ),
        "avoid_doing": [
            _truncate(item, 260) for item in avoid_doing[:6] if _truncate(item, 260)
        ],
        "risk_warning": _truncate(parsed.get("risk_warning"), 700),
        "schedule_advice": (
            _truncate(parsed.get("schedule_advice"), 900)
            or "Keep the plan small enough to actually finish."
        ),
        "end_of_day_review_prompt": (
            _truncate(parsed.get("end_of_day_review_prompt"), 500)
            or "What did you finish, what slipped, and what blocked you?"
        ),
    }


def generate_daily_command(context):
    """
    Call OpenAI only when the user explicitly requests a Daily Command.
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
                    "Generate today's Daily Command from this local context JSON:\n\n"
                    f"{json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise DailyCommandResponseError(
            "Daily Command returned invalid JSON. Try generating again.",
            raw_response=content,
        ) from error

    command = _normalize_daily_command(parsed)
    command["_raw_response"] = content
    return command


def format_daily_command_for_display(command):
    lines = [command.get("executive_summary") or ""]
    for index, task in enumerate(command.get("main_tasks") or [], start=1):
        lines.append(f"{index}. {task.get('title')}: {task.get('reason')}")
    lines.append(
        "First 25 minutes: "
        f"{command.get('first_25_minute_action') or 'Start the first work block.'}"
    )
    return "\n".join(line for line in lines if line)
