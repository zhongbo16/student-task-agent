from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

VALID_STATUSES = ("suggested", "confirmed", "ignored", "in_progress", "done")
VALID_CONFIDENCES = ("high", "medium", "low")
LOCAL_TIMEZONE = ZoneInfo("America/Toronto")

TASK_COLUMNS = (
    "id",
    "title",
    "course",
    "task_type",
    "due_at",
    "weight",
    "planned_date",
    "estimated_minutes",
    "priority",
    "status",
    "source",
    "confidence",
    "notes",
    "source_snippet",
    "external_id",
    "external_source",
    "external_url",
    "urgency_score",
    "urgency_label",
    "auto_created",
    "needs_review",
    "last_scored_at",
    "first_action",
    "next_action",
    "energy_level",
    "cognitive_load",
    "emotional_friction",
    "avoidance_risk",
    "behavior_prompt",
    "last_behavior_designed_at",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class Task:
    title: str
    course: Optional[str] = None
    task_type: Optional[str] = None
    due_at: Optional[str] = None
    weight: Optional[str] = None
    planned_date: Optional[str] = None
    estimated_minutes: Optional[int] = None
    priority: int = 3
    status: str = "confirmed"
    source: str = "manual"
    confidence: Optional[str] = None
    notes: Optional[str] = None
    source_snippet: Optional[str] = None
    external_id: Optional[str] = None
    external_source: Optional[str] = None
    external_url: Optional[str] = None
    urgency_score: float = 0
    urgency_label: Optional[str] = None
    auto_created: int = 0
    needs_review: int = 0
    last_scored_at: Optional[str] = None
    first_action: Optional[str] = None
    next_action: Optional[str] = None
    energy_level: Optional[str] = None
    cognitive_load: Optional[str] = None
    emotional_friction: Optional[str] = None
    avoidance_risk: Optional[str] = None
    behavior_prompt: Optional[str] = None
    last_behavior_designed_at: Optional[str] = None


def _clean_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_date(value):
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(LOCAL_TIMEZONE)
        if parsed.hour or parsed.minute:
            return parsed.strftime("%Y-%m-%d %H:%M")
        return parsed.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None

    if parsed is not None:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(LOCAL_TIMEZONE)
        if parsed.hour or parsed.minute:
            return parsed.strftime("%Y-%m-%d %H:%M")
        return parsed.date().isoformat()

    candidate = text[:10]
    datetime.strptime(candidate, "%Y-%m-%d")
    return candidate


def normalize_task(task):
    title = _clean_text(task.get("title"))
    if not title:
        raise ValueError("Task title is required.")

    priority = int(task.get("priority") or 3)
    if priority < 1 or priority > 5:
        raise ValueError("Priority must be between 1 and 5.")

    estimated_minutes = task.get("estimated_minutes")
    if estimated_minutes in (None, ""):
        estimated_minutes = None
    else:
        estimated_minutes = int(estimated_minutes)
        if estimated_minutes <= 0:
            raise ValueError("Estimated minutes must be greater than 0.")

    status = _clean_text(task.get("status")) or "confirmed"
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(VALID_STATUSES)}.")

    confidence = _clean_text(task.get("confidence"))
    if confidence:
        confidence = confidence.lower()
        if confidence not in VALID_CONFIDENCES:
            raise ValueError(
                f"Confidence must be one of: {', '.join(VALID_CONFIDENCES)}."
            )

    urgency_score = task.get("urgency_score")
    if urgency_score in (None, ""):
        urgency_score = 0
    else:
        urgency_score = float(urgency_score)

    auto_created = task.get("auto_created")
    auto_created = 1 if auto_created not in (None, "", 0, "0", False) else 0

    needs_review = task.get("needs_review")
    if needs_review in (None, ""):
        needs_review = 1 if status == "suggested" else 0
    else:
        needs_review = 1 if needs_review not in (0, "0", False) else 0

    return {
        "title": title,
        "course": _clean_text(task.get("course")),
        "task_type": _clean_text(task.get("task_type")),
        "due_at": _clean_date(task.get("due_at")),
        "weight": _clean_text(task.get("weight")),
        "planned_date": _clean_date(task.get("planned_date")),
        "estimated_minutes": estimated_minutes,
        "priority": priority,
        "status": status,
        "source": _clean_text(task.get("source")) or "manual",
        "confidence": confidence,
        "notes": _clean_text(task.get("notes")),
        "source_snippet": _clean_text(task.get("source_snippet")),
        "external_id": _clean_text(task.get("external_id")),
        "external_source": _clean_text(task.get("external_source")),
        "external_url": _clean_text(task.get("external_url")),
        "urgency_score": urgency_score,
        "urgency_label": _clean_text(task.get("urgency_label")),
        "auto_created": auto_created,
        "needs_review": needs_review,
        "last_scored_at": _clean_text(task.get("last_scored_at")),
    }
