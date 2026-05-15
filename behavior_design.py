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
PROMPT_PATH = BASE_DIR / "prompts" / "behavior_design.md"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TEXT_CHARS = 600
MAX_CONTEXT_TASKS = 12
MAX_MEMORY_VALUE_CHARS = 700

VALID_ENERGY_LEVELS = ("low", "medium", "high")
VALID_COGNITIVE_LOADS = ("shallow", "medium", "deep")
VALID_FRICTIONS = ("low", "medium", "high")
VALID_AVOIDANCE_RISKS = ("low", "medium", "high", "unknown")
VALID_MODES = ("full_day", "minimum_viable_day", "recovery_day")
VALID_MEMORY_TYPES = (
    "pattern",
    "weakness",
    "strength",
    "rule",
    "preference",
    "time_estimation",
    "avoidance",
    "course_context",
    "other",
)
VALID_CONFIDENCES = ("high", "medium", "low")


class BehaviorDesignConfigError(RuntimeError):
    """Raised when Behavior Design cannot be configured safely."""


class BehaviorDesignResponseError(RuntimeError):
    """Raised when Behavior Design output cannot be parsed."""

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
        raise BehaviorDesignConfigError(
            "OPENAI_API_KEY is missing. Add it to your .env file to use Behavior Design."
        )

    try:
        from openai import OpenAI
    except ImportError as error:
        raise BehaviorDesignConfigError(
            "The openai package is missing. Run: pip install -r requirements.txt"
        ) from error

    return OpenAI(api_key=api_key)


def _read_prompt():
    if not PROMPT_PATH.exists():
        raise BehaviorDesignConfigError("Behavior Design prompt file is missing.")
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
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def _active_task(task):
    return task.get("status") not in ("done", "ignored")


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
    score, label, reasons = calculate_urgency_score(task, current_date)
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
        "urgency_score": task.get("urgency_score") or score,
        "urgency_label": task.get("urgency_label") or label,
        "urgency_reasons": reasons[:6],
        "first_action": _truncate(task.get("first_action"), 240),
        "next_action": _truncate(task.get("next_action"), 240),
        "avoidance_risk": task.get("avoidance_risk"),
        "notes": _truncate(task.get("notes"), 260),
        "updated_at": task.get("updated_at"),
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


def _compact_ai_boss_briefing(briefing):
    if not briefing:
        return None
    return {
        "executive_summary": _truncate(briefing.get("executive_summary"), 700),
        "top_tasks": [
            {
                "task_id": item.get("task_id"),
                "title": _truncate(item.get("title"), 220),
                "course": _truncate(item.get("course"), 120),
                "reason": _truncate(item.get("reason"), 300),
                "first_action": _truncate(item.get("first_action"), 300),
            }
            for item in (briefing.get("top_tasks") or [])[:3]
            if isinstance(item, dict)
        ],
        "first_25_minute_action": _truncate(
            briefing.get("first_25_minute_action"),
            500,
        ),
        "avoid_doing": [
            _truncate(item, 220)
            for item in (briefing.get("avoid_doing") or [])[:5]
            if _truncate(item, 220)
        ],
        "avoidance_warning": _truncate(briefing.get("avoidance_warning"), 500),
    }


def _task_sort_key(task, current_date):
    score, _, _ = calculate_urgency_score(task, current_date)
    return (
        -score,
        task.get("due_at") or "9999-12-31",
        task.get("planned_date") or "9999-12-31",
        -priority_score(task),
        task.get("title") or "",
    )


def _recent_sessions(sessions, current_date):
    seven_days_ago = current_date - timedelta(days=7)
    recent = []
    for session in sessions[:20]:
        created_at = str(session.get("created_at") or "")[:10]
        created_date = _parse_context_date(created_at) if created_at else None
        if created_date is None or created_date >= seven_days_ago:
            recent.append(session)
    return recent or sessions[:20]


def _planning_cap_minutes(active_tasks, current_date):
    labels = []
    scores = []
    for task in active_tasks:
        score, label, _ = calculate_urgency_score(task, current_date)
        labels.append(task.get("urgency_label") or label)
        scores.append(score)

    if "critical" in labels or any(score >= 120 for score in scores):
        return 5
    if "urgent" in labels or any(score >= 90 for score in scores):
        return 10
    return 15


def detect_simple_avoidance_patterns(tasks, recent_focus_sessions, recent_daily_reviews):
    """
    Return deterministic avoidance signals backed by local data.
    """
    current_date = date.today()
    active_tasks = [task for task in tasks if _active_task(task)]
    focus_task_ids = {
        str(session.get("task_id"))
        for session in recent_focus_sessions
        if session.get("task_id") is not None
    }
    focus_titles = {
        str(session.get("task_title") or "").strip().casefold()
        for session in recent_focus_sessions
        if session.get("task_title")
    }

    signals = []
    for task in sorted(active_tasks, key=lambda item: _task_sort_key(item, current_date)):
        score, label, reasons = calculate_urgency_score(task, current_date)
        task_id = str(task.get("id")) if task.get("id") is not None else None
        title_key = str(task.get("title") or "").strip().casefold()
        touched = (task_id in focus_task_ids) or (title_key in focus_titles)
        if label in ("critical", "urgent") and not touched:
            signals.append({
                "signal": "urgent_task_without_recent_focus",
                "task_id": task_id,
                "title": task.get("title"),
                "urgency_label": label,
                "urgency_score": score,
                "reason": "High-urgency task has no recent focus session.",
                "evidence": reasons[:5],
            })
        if is_overdue(task, current_date) and not touched:
            signals.append({
                "signal": "overdue_task_without_recent_focus",
                "task_id": task_id,
                "title": task.get("title"),
                "urgency_label": label,
                "urgency_score": score,
                "reason": "Overdue task has no recent focus session.",
                "evidence": reasons[:5],
            })
        if len(signals) >= 5:
            break

    for review in recent_daily_reviews[:7]:
        avoidance_notes = str(review.get("avoidance_notes") or "").strip()
        if avoidance_notes:
            signals.append({
                "signal": "daily_review_mentions_avoidance",
                "review_date": review.get("review_date"),
                "reason": "Daily Review contains avoidance notes.",
                "evidence": _truncate(avoidance_notes, 260),
            })

    blocker_counts = {}
    for session in recent_focus_sessions[:20]:
        blocker = str(session.get("blocker") or "").strip().casefold()
        if not blocker:
            continue
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    repeated_blockers = [
        blocker for blocker, count in blocker_counts.items()
        if count >= 2
    ][:3]
    for blocker in repeated_blockers:
        signals.append({
            "signal": "repeated_focus_blocker",
            "reason": "Same blocker appears in multiple focus sessions.",
            "evidence": blocker,
        })

    return {
        "signals": signals[:8],
        "count": min(len(signals), 8),
    }


def build_behavior_design_context(
    tasks,
    today_plan,
    ai_boss_briefing,
    recent_focus_sessions,
    recent_daily_reviews,
    active_memories,
    current_date,
    user_checkin_text=None,
):
    """
    Build compact context for behavior design from local execution data.
    """
    current_day = _parse_context_date(current_date)
    active_tasks = [task for task in tasks if _active_task(task)]
    ranked_tasks = sorted(
        active_tasks,
        key=lambda task: _task_sort_key(task, current_day),
    )
    recent_sessions = _recent_sessions(recent_focus_sessions, current_day)
    avoidance = detect_simple_avoidance_patterns(
        active_tasks,
        recent_sessions,
        recent_daily_reviews,
    )

    today_tasks = [
        task for task in active_tasks
        if is_overdue(task, current_day)
        or is_due_today(task, current_day)
        or is_planned_today(task, current_day)
        or is_due_this_week(task, current_day)
    ]
    in_progress = [
        task for task in active_tasks if task.get("status") == "in_progress"
    ]

    planning_cap = _planning_cap_minutes(active_tasks, current_day)

    return {
        "current_date": current_day.isoformat(),
        "user_checkin_text": _truncate(user_checkin_text, 1200),
        "planning_cap_minutes": planning_cap,
        "guardrails": [
            "Use only provided data.",
            "Do not invent tasks or deadlines.",
            "Do not change task statuses automatically.",
            "Recommend at most 3 main tasks.",
            "Every main task needs a first action under 5 minutes.",
            "Use high standards and low shame.",
        ],
        "counts": {
            "active_tasks": len(active_tasks),
            "today_relevant_tasks": len(today_tasks),
            "in_progress_tasks": len(in_progress),
            "today_plan_items": len(today_plan[:3]),
            "recent_focus_sessions": len(recent_sessions[:20]),
            "recent_daily_reviews": len(recent_daily_reviews[:7]),
            "active_memories": len(active_memories),
            "avoidance_signals": avoidance["count"],
        },
        "top_urgent_tasks": [
            _compact_task(task, current_day)
            for task in ranked_tasks[:MAX_CONTEXT_TASKS]
        ],
        "today_relevant_tasks": [
            _compact_task(task, current_day)
            for task in sorted(today_tasks, key=lambda task: _task_sort_key(task, current_day))[:8]
        ],
        "in_progress_tasks": [
            _compact_task(task, current_day)
            for task in sorted(in_progress, key=lambda task: _task_sort_key(task, current_day))[:6]
        ],
        "today_plan": [
            _compact_today_plan_item(item, current_day)
            for item in today_plan[:3]
        ],
        "current_ai_boss_briefing": _compact_ai_boss_briefing(ai_boss_briefing),
        "recent_focus_sessions": [
            _compact_study_session(session) for session in recent_sessions[:20]
        ],
        "recent_daily_reviews": [
            _compact_daily_review(review) for review in recent_daily_reviews[:7]
        ],
        "active_agent_memory": [
            _compact_memory(memory) for memory in active_memories
        ],
        "deterministic_avoidance_signals": avoidance,
    }


def _clean_choice(value, valid_values, default):
    text = _truncate(value, 80)
    if not text:
        return default
    text = text.lower()
    return text if text in valid_values else default


def _clean_int(value, default=None, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _normalize_if_then(value):
    value = value if isinstance(value, dict) else {}
    return {
        "if": _truncate(value.get("if"), 260) or "If I feel stuck",
        "then": _truncate(value.get("then"), 260) or "Then I will write the blocker.",
    }


def _normalize_top_task(task):
    if not isinstance(task, dict):
        return None

    return {
        "task_id": (
            str(task.get("task_id")) if task.get("task_id") not in (None, "") else None
        ),
        "title": _truncate(task.get("title"), 240) or "Untitled task",
        "course": _truncate(task.get("course"), 120),
        "why_this_matters": (
            _truncate(task.get("why_this_matters"), 500)
            or "This task moves the plan forward."
        ),
        "energy_level": _clean_choice(
            task.get("energy_level"),
            VALID_ENERGY_LEVELS,
            "medium",
        ),
        "cognitive_load": _clean_choice(
            task.get("cognitive_load"),
            VALID_COGNITIVE_LOADS,
            "medium",
        ),
        "emotional_friction": _clean_choice(
            task.get("emotional_friction"),
            VALID_FRICTIONS,
            "medium",
        ),
        "avoidance_risk": _clean_choice(
            task.get("avoidance_risk"),
            VALID_AVOIDANCE_RISKS,
            "unknown",
        ),
        "first_action_under_5_min": (
            _truncate(task.get("first_action_under_5_min"), 500)
            or "Open the task material and write the exact next question."
        ),
        "first_25_minute_block": (
            _truncate(task.get("first_25_minute_block"), 600)
            or "Work on the first concrete step for 25 minutes."
        ),
        "stop_condition": (
            _truncate(task.get("stop_condition"), 400)
            or "Stop after 25 minutes and record what changed."
        ),
        "likely_obstacle": (
            _truncate(task.get("likely_obstacle"), 400)
            or "The next step may feel unclear."
        ),
        "if_then_plan": _normalize_if_then(task.get("if_then_plan")),
    }


def _normalize_string_list(value, max_items=6, max_chars=260):
    if not isinstance(value, list):
        value = [value] if value else []
    return [
        _truncate(item, max_chars)
        for item in value[:max_items]
        if _truncate(item, max_chars)
    ]


def _normalize_woop(value):
    value = value if isinstance(value, dict) else {}
    return {
        "wish": _truncate(value.get("wish"), 360) or "Make progress today.",
        "outcome": _truncate(value.get("outcome"), 360) or "The plan moves forward.",
        "obstacle": _truncate(value.get("obstacle"), 360) or "The task feels unclear.",
        "plan": _truncate(value.get("plan"), 500) or "If stuck, write the blocker.",
    }


def _normalize_minimum_viable_day(value):
    value = value if isinstance(value, dict) else {}
    return {
        "required": _normalize_string_list(value.get("required"), max_items=5),
        "optional": _normalize_string_list(value.get("optional"), max_items=5),
        "definition_of_success": (
            _truncate(value.get("definition_of_success"), 500)
            or "One 25-minute focus session and one honest review."
        ),
    }


def _normalize_memory_candidate(candidate):
    if not isinstance(candidate, dict):
        return None

    memory_type = _clean_choice(candidate.get("memory_type"), VALID_MEMORY_TYPES, "other")
    memory_key = _truncate(candidate.get("memory_key"), 120)
    memory_value = _truncate(candidate.get("memory_value"), 700)
    if not memory_key or not memory_value:
        return None

    return {
        "memory_type": memory_type,
        "memory_key": memory_key,
        "memory_value": memory_value,
        "confidence": _clean_choice(
            candidate.get("confidence"),
            VALID_CONFIDENCES,
            "medium",
        ),
        "source": _truncate(candidate.get("source"), 80) or "behavior_design",
    }


def _normalize_plan(parsed):
    if not isinstance(parsed, dict):
        raise BehaviorDesignResponseError(
            "Behavior Design returned JSON, but not an object."
        )

    top_tasks = []
    for task in parsed.get("top_tasks", []):
        normalized = _normalize_top_task(task)
        if normalized:
            top_tasks.append(normalized)

    memory_candidates = []
    for candidate in parsed.get("memory_candidates", []):
        normalized = _normalize_memory_candidate(candidate)
        if normalized:
            memory_candidates.append(normalized)

    return {
        "main_objective": (
            _truncate(parsed.get("main_objective"), 700)
            or "Make the next useful behavior easy to start."
        ),
        "planning_cap_minutes": _clean_int(
            parsed.get("planning_cap_minutes"),
            default=10,
            minimum=5,
            maximum=30,
        ),
        "mode": _clean_choice(parsed.get("mode"), VALID_MODES, "minimum_viable_day"),
        "top_tasks": top_tasks[:3],
        "woop": _normalize_woop(parsed.get("woop")),
        "minimum_viable_day": _normalize_minimum_viable_day(
            parsed.get("minimum_viable_day")
        ),
        "avoidance_warning": _truncate(parsed.get("avoidance_warning"), 700),
        "do_not_do_today": _normalize_string_list(
            parsed.get("do_not_do_today"),
            max_items=6,
        ),
        "end_of_day_review_question": (
            _truncate(parsed.get("end_of_day_review_question"), 500)
            or "What did you start, what blocked you, and what is the next action?"
        ),
        "memory_candidates": memory_candidates[:5],
    }


def generate_behavior_design_plan(context):
    """
    Call OpenAI only when the user explicitly requests a behavior plan.
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
                    "Create today's Behavior Design Plan from this local "
                    "context JSON:\n\n"
                    f"{json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise BehaviorDesignResponseError(
            "Behavior Design returned invalid JSON. Try generating again.",
            raw_response=content,
        ) from error

    plan = _normalize_plan(parsed)
    plan["_raw_response"] = content
    return plan


def behavior_updates_for_task(task_plan):
    if not isinstance(task_plan, dict):
        return {}

    if_then = task_plan.get("if_then_plan") or {}
    behavior_prompt = (
        f"If {if_then.get('if')}, then {if_then.get('then')}. "
        f"Stop condition: {task_plan.get('stop_condition')}"
    )
    return {
        "first_action": task_plan.get("first_action_under_5_min"),
        "next_action": task_plan.get("first_25_minute_block"),
        "energy_level": task_plan.get("energy_level"),
        "cognitive_load": task_plan.get("cognitive_load"),
        "emotional_friction": task_plan.get("emotional_friction"),
        "avoidance_risk": task_plan.get("avoidance_risk"),
        "behavior_prompt": behavior_prompt,
    }


def apply_behavior_design_to_tasks(plan):
    """
    Apply behavior fields only. This never changes task status.
    """
    from db import update_task_behavior_fields

    result = {
        "updated": 0,
        "skipped": 0,
    }
    for task_plan in plan.get("top_tasks") or []:
        task_id = task_plan.get("task_id")
        if not task_id:
            result["skipped"] += 1
            continue

        rowcount = update_task_behavior_fields(
            task_id,
            behavior_updates_for_task(task_plan),
        )
        if rowcount:
            result["updated"] += 1
        else:
            result["skipped"] += 1
    return result
