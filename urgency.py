from datetime import date, datetime, timedelta

VALID_URGENCY_LABELS = (
    "critical",
    "urgent",
    "soon",
    "normal",
    "low",
    "no_due_date",
)

INACTIVE_STATUSES = {"done", "ignored"}


def _parse_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _priority_points(value):
    if value in (None, ""):
        return 0, None

    if isinstance(value, str):
        text_value = value.strip().lower()
        text_priorities = {
            "highest": 25,
            "high": 25,
            "medium": 10,
            "normal": 10,
            "low": 0,
            "lowest": 0,
        }
        if text_value in text_priorities:
            return text_priorities[text_value], text_value

    try:
        priority = int(value)
    except (TypeError, ValueError):
        return 0, None

    points_by_priority = {
        5: 25,
        4: 18,
        3: 10,
        2: 5,
        1: 0,
    }
    priority = max(1, min(5, priority))
    return points_by_priority[priority], str(priority)


def _estimated_minutes(value):
    if value in (None, ""):
        return None

    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None

    return minutes if minutes > 0 else None


def _source_points(source):
    source = (source or "").strip().lower()
    source_scores = {
        "quercus_assignment": 20,
        "canvas_assignment": 20,
        "quercus_calendar": 15,
        "quercus_upcoming": 15,
        "quercus_todo": 10,
        "syllabus": 5,
        "ai_suggested": 3,
        "manual": 10,
    }
    return source_scores.get(source, 0)


def _label_for_score(score, has_due_date):
    if score >= 120:
        return "critical"
    if score >= 90:
        return "urgent"
    if score >= 60:
        return "soon"
    if score >= 30:
        return "normal"
    if not has_due_date:
        return "no_due_date"
    if score > 0:
        return "low"
    return "low"


def calculate_urgency_score(task_or_candidate: dict, today: date | None = None):
    """
    Return urgency_score, urgency_label, and human-readable reasons.

    The score is rule-based. It never invents dates; unclear dates simply count
    as missing dates.
    """
    today = today or date.today()
    score = 0.0
    reasons = []

    status = (task_or_candidate.get("status") or "").strip().lower()
    if status in INACTIVE_STATUSES:
        return 0.0, "low", ["inactive task"]

    due_date = _parse_date(task_or_candidate.get("due_at"))
    planned_date = _parse_date(task_or_candidate.get("planned_date"))

    if due_date:
        if due_date < today:
            score += 100
            reasons.append("overdue")
        elif due_date == today:
            score += 90
            reasons.append("due today")
        elif due_date == today + timedelta(days=1):
            score += 75
            reasons.append("due tomorrow")
        elif today + timedelta(days=2) <= due_date <= today + timedelta(days=3):
            score += 60
            reasons.append("due in 2-3 days")
        elif today + timedelta(days=4) <= due_date <= today + timedelta(days=7):
            score += 45
            reasons.append("due this week")
        elif today + timedelta(days=8) <= due_date <= today + timedelta(days=14):
            score += 25
            reasons.append("due in 8-14 days")
    else:
        score += 5
        reasons.append("no due date")

    if planned_date == today:
        score += 30
        reasons.append("planned today")
    elif planned_date == today + timedelta(days=1):
        score += 15
        reasons.append("planned tomorrow")

    priority_points, priority_label = _priority_points(task_or_candidate.get("priority"))
    score += priority_points
    if priority_points >= 25:
        reasons.append("high priority")
    elif priority_points >= 10:
        reasons.append("medium priority")

    if status == "in_progress":
        score += 25
        reasons.append("in progress")
    elif status == "confirmed":
        score += 10
        reasons.append("confirmed")

    confidence = (task_or_candidate.get("confidence") or "").strip().lower()
    if confidence == "high":
        score += 10
        reasons.append("high confidence")
    elif confidence == "medium":
        score += 5
        reasons.append("medium confidence")

    source = task_or_candidate.get("source") or task_or_candidate.get("external_source")
    source_points = _source_points(source)
    score += source_points
    if source_points >= 15:
        reasons.append("trusted Quercus source")
    elif source_points >= 10:
        reasons.append("trusted source")
    elif source_points > 0:
        reasons.append("supporting source")

    minutes = _estimated_minutes(task_or_candidate.get("estimated_minutes"))
    if minutes is not None and minutes <= 60:
        score += 5
        reasons.append("short task")
    elif minutes is not None and minutes > 180:
        score -= 5
        reasons.append("large task")

    label = _label_for_score(score, due_date is not None)
    return round(max(0.0, score), 2), label, reasons
