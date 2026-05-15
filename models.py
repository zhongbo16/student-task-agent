from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

VALID_STATUSES = ("suggested", "confirmed", "ignored", "in_progress", "done")
VALID_CONFIDENCES = ("high", "medium", "low")

TASK_COLUMNS = (
    "id",
    "title",
    "course",
    "task_type",
    "due_at",
    "planned_date",
    "estimated_minutes",
    "priority",
    "status",
    "source",
    "confidence",
    "notes",
    "source_snippet",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class Task:
    title: str
    course: Optional[str] = None
    task_type: Optional[str] = None
    due_at: Optional[str] = None
    planned_date: Optional[str] = None
    estimated_minutes: Optional[int] = None
    priority: int = 3
    status: str = "confirmed"
    source: str = "manual"
    confidence: Optional[str] = None
    notes: Optional[str] = None
    source_snippet: Optional[str] = None


def _clean_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_date(value):
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    datetime.strptime(text, "%Y-%m-%d")
    return text


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

    return {
        "title": title,
        "course": _clean_text(task.get("course")),
        "task_type": _clean_text(task.get("task_type")),
        "due_at": _clean_date(task.get("due_at")),
        "planned_date": _clean_date(task.get("planned_date")),
        "estimated_minutes": estimated_minutes,
        "priority": priority,
        "status": status,
        "source": _clean_text(task.get("source")) or "manual",
        "confidence": confidence,
        "notes": _clean_text(task.get("notes")),
        "source_snippet": _clean_text(task.get("source_snippet")),
    }
