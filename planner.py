from datetime import date, datetime, timedelta

from urgency import calculate_urgency_score

INACTIVE_STATUSES = {"done", "ignored"}


def parse_task_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def priority_score(task):
    value = task.get("priority")
    if value is None or value == "":
        return 0

    if isinstance(value, str):
        text_value = value.strip().lower()
        text_priorities = {
            "high": 5,
            "medium": 3,
            "low": 1,
        }
        if text_value in text_priorities:
            return text_priorities[text_value]

    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 0


def estimated_minutes(task):
    value = task.get("estimated_minutes")
    if value is None or value == "":
        return None

    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None

    if minutes <= 0:
        return None

    return minutes


def is_overdue(task, today=None):
    today = today or date.today()
    due_date = parse_task_date(task.get("due_at"))
    return due_date is not None and due_date < today


def is_due_today(task, today=None):
    today = today or date.today()
    return parse_task_date(task.get("due_at")) == today


def is_planned_today(task, today=None):
    today = today or date.today()
    return parse_task_date(task.get("planned_date")) == today


def is_due_this_week(task, today=None):
    today = today or date.today()
    due_date = parse_task_date(task.get("due_at"))
    if due_date is None:
        return False

    return today < due_date <= today + timedelta(days=7)


def has_any_date(task):
    return (
        parse_task_date(task.get("due_at")) is not None
        or parse_task_date(task.get("planned_date")) is not None
    )


def task_sort_key(task, today=None):
    today = today or date.today()
    priority = priority_score(task)
    minutes = estimated_minutes(task)
    due_date = parse_task_date(task.get("due_at"))
    planned_date = parse_task_date(task.get("planned_date"))
    earliest_date = min(
        [task_date for task_date in (due_date, planned_date) if task_date],
        default=date.max,
    )

    if is_overdue(task, today):
        date_rank = 0
    elif is_due_today(task, today):
        date_rank = 1
    elif is_planned_today(task, today):
        date_rank = 2
    elif is_due_this_week(task, today):
        date_rank = 3
    elif has_any_date(task):
        date_rank = 4
    else:
        date_rank = 5

    return (
        date_rank,
        -priority,
        minutes if minutes is not None else 10_000,
        earliest_date,
        task.get("title") or "",
    )


def urgency_score_value(task, today=None):
    stored_score = task.get("urgency_score")
    if stored_score not in (None, ""):
        try:
            return float(stored_score)
        except (TypeError, ValueError):
            pass

    score, _, _ = calculate_urgency_score(task, today)
    return score


def updated_sort_key(task):
    value = task.get("updated_at") or ""
    try:
        updated_at = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        updated_at = datetime.min

    return updated_at


def sort_tasks_for_dashboard(tasks, view_name, today=None):
    if view_name == "Completed":
        return sorted(tasks, key=updated_sort_key, reverse=True)

    return sorted(
        tasks,
        key=lambda task: (
            -urgency_score_value(task, today),
            task_sort_key(task, today),
        ),
    )


def task_indicators(task, today=None):
    today = today or date.today()
    indicators = []

    if is_overdue(task, today):
        indicators.append("Overdue")
    if is_due_today(task, today):
        indicators.append("Due today")
    if is_planned_today(task, today):
        indicators.append("Planned today")
    if priority_score(task) >= 5:
        indicators.append("High priority")

    urgency_label = task.get("urgency_label")
    if urgency_label:
        indicators.append(f"Urgency: {urgency_label}")

    return indicators


def recommendation_reason(task, today=None):
    today = today or date.today()
    reasons = []

    if is_overdue(task, today):
        reasons.append("overdue")
    elif is_due_today(task, today):
        reasons.append("due today")
    elif is_planned_today(task, today):
        reasons.append("planned for today")
    elif is_due_this_week(task, today):
        reasons.append("due this week")

    if priority_score(task) >= 5:
        reasons.append("high priority")

    if task.get("status") == "in_progress":
        reasons.append("already in progress")

    minutes = estimated_minutes(task)
    if minutes is not None and minutes <= 90:
        reasons.append("reasonable to finish today")

    source = task.get("source") or "manual"
    if source == "manual" and not reasons:
        reasons.append("manual task")

    if not reasons:
        reasons.append("active task")

    return "Recommended because it is " + " and ".join(reasons) + "."


def reasonable_time_rank(task):
    minutes = estimated_minutes(task)
    if minutes is None:
        return 2
    if minutes <= 90:
        return 0
    if minutes <= 150:
        return 1
    return 3


def today_plan_sort_key(task, today=None):
    today = today or date.today()

    return (
        -urgency_score_value(task, today),
        not is_overdue(task, today),
        not is_due_today(task, today),
        not is_planned_today(task, today),
        not is_due_this_week(task, today),
        -priority_score(task),
        task.get("status") != "in_progress",
        (task.get("source") or "manual") != "manual",
        reasonable_time_rank(task),
        task_sort_key(task, today),
    )


def generate_today_plan(tasks, max_tasks=3, today=None):
    today = today or date.today()
    active_tasks = [
        task for task in tasks
        if task.get("status") not in INACTIVE_STATUSES
    ]
    ranked_tasks = sorted(
        active_tasks,
        key=lambda task: today_plan_sort_key(task, today),
    )

    return [
        {
            "task": task,
            "reason": recommendation_reason(task, today),
        }
        for task in ranked_tasks[:max_tasks]
    ]
