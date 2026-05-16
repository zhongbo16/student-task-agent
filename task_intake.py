import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from canvas_client import (
    CanvasAPIError,
    CanvasConfigError,
    get_all_assignments,
    has_canvas_api_token,
    has_canvas_base_url,
)
from db import (
    create_task_candidate,
    get_recent_quercus_items,
    is_course_archived,
    promote_candidate_to_task,
    rescore_all_active_tasks,
    update_task_from_external_candidate,
)
from urgency import calculate_urgency_score

TRUSTED_CONFIRMED_SOURCES = {
    "quercus_assignment",
    "quercus_calendar",
    "quercus_upcoming",
}
LOCAL_TIMEZONE = ZoneInfo("America/Toronto")


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
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def _date_value(value):
    cleaned = _clean_date(value)
    if not cleaned:
        return None
    return datetime.strptime(cleaned[:10], "%Y-%m-%d").date()


def _is_past_due(candidate, today=None):
    today = today or date.today()
    due_date = _date_value(candidate.get("due_at"))
    return due_date is not None and due_date < today


def _short_text_from_html(value):
    text = _clean_text(value)
    if not text:
        return None

    # Keep this intentionally lightweight; this is for notes, not full parsing.
    cleaned = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    cleaned = cleaned.replace("</p>", "\n").replace("<p>", "")
    while "<" in cleaned and ">" in cleaned:
        start = cleaned.find("<")
        end = cleaned.find(">", start)
        if end == -1:
            break
        cleaned = cleaned[:start] + cleaned[end + 1:]
    return cleaned.strip()[:800] or None


def make_candidate_hash(candidate: dict) -> str:
    external_source = _clean_text(candidate.get("external_source"))
    external_id = _clean_text(candidate.get("external_id"))
    if external_source and external_id:
        raw = f"external:{external_source}:{external_id}"
    else:
        raw = "|".join([
            _clean_text(candidate.get("title")) or "",
            _clean_text(candidate.get("course")) or "",
            _clean_date(candidate.get("due_at")) or "",
            _clean_text(candidate.get("source")) or "",
        ]).lower()

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def decide_recommended_status(candidate: dict) -> str:
    source = _clean_text(candidate.get("source"))
    confidence = (_clean_text(candidate.get("confidence")) or "").lower()
    title = _clean_text(candidate.get("title"))
    due_at = _clean_date(candidate.get("due_at"))

    if (
        source in TRUSTED_CONFIRMED_SOURCES
        and confidence == "high"
        and title
        and due_at
    ):
        return "confirmed"

    return "suggested"


def _score_candidate(candidate):
    score, label, reasons = calculate_urgency_score(candidate)
    candidate["urgency_score"] = score
    candidate["urgency_label"] = label
    candidate["urgency_reasons"] = reasons
    return candidate


def normalize_canvas_assignment_to_candidate(assignment: dict) -> dict:
    candidate = {
        "title": assignment.get("title") or "Untitled Canvas assignment",
        "course": assignment.get("course_name"),
        "task_type": "assignment",
        "source": "quercus_assignment",
        "confidence": "high" if _clean_date(assignment.get("due_at")) else "medium",
        "due_at": _clean_date(assignment.get("due_at")),
        "planned_date": None,
        "estimated_minutes": None,
        "priority": "medium",
        "notes": _short_text_from_html(assignment.get("description")),
        "source_url": assignment.get("external_url"),
        "source_snippet": None,
        "external_source": assignment.get("external_source") or "canvas_assignment",
        "external_id": (
            str(assignment.get("external_id"))
            if assignment.get("external_id") is not None
            else None
        ),
    }
    candidate["recommended_status"] = decide_recommended_status(candidate)
    candidate["candidate_hash"] = make_candidate_hash(candidate)
    return _score_candidate(candidate)


def normalize_quercus_item_to_candidate(item: dict) -> dict:
    item_type = item.get("item_type") or "quercus_item"
    source_by_type = {
        "assignment": "quercus_assignment",
        "calendar_event": "quercus_calendar",
        "upcoming_event": "quercus_upcoming",
        "todo_item": "quercus_todo",
        "announcement": "quercus_deep_read",
        "module_item": "quercus_deep_read",
        "syllabus": "quercus_deep_read",
    }
    source = source_by_type.get(item_type, "quercus_deep_read")
    confidence = "high" if source in TRUSTED_CONFIRMED_SOURCES and item.get("due_at") else "medium"

    candidate = {
        "title": item.get("title") or "Untitled Quercus item",
        "course": item.get("course_name"),
        "task_type": item_type,
        "source": source,
        "confidence": confidence,
        "due_at": _clean_date(item.get("due_at")),
        "planned_date": None,
        "estimated_minutes": None,
        "priority": "medium",
        "notes": _short_text_from_html(item.get("body_text")),
        "source_url": item.get("url"),
        "source_snippet": _short_text_from_html(item.get("body_text")),
        "external_source": item.get("external_source") or source,
        "external_id": (
            str(item.get("external_id")) if item.get("external_id") is not None else None
        ),
    }
    candidate["recommended_status"] = decide_recommended_status(candidate)
    candidate["candidate_hash"] = make_candidate_hash(candidate)
    return _score_candidate(candidate)


def _empty_summary():
    return {
        "candidates_found": 0,
        "confirmed_tasks_auto_created": 0,
        "suggested_tasks_created": 0,
        "pending_candidates_created": 0,
        "duplicates_skipped": 0,
        "skipped_archived_course": 0,
        "skipped_past_due": 0,
        "tasks_updated": 0,
        "tasks_rescored": 0,
        "errors": [],
    }


def _handle_candidate(candidate, summary):
    summary["candidates_found"] += 1
    if is_course_archived(candidate.get("course")):
        summary["skipped_archived_course"] += 1
        return

    if _is_past_due(candidate):
        summary["skipped_past_due"] += 1
        return

    updated_existing = update_task_from_external_candidate(candidate)
    if updated_existing:
        summary["tasks_updated"] += updated_existing
        summary["duplicates_skipped"] += updated_existing
        return

    candidate_id = create_task_candidate(candidate)
    if candidate_id is None:
        summary["duplicates_skipped"] += 1
        return

    if candidate.get("recommended_status") == "confirmed":
        task_id = promote_candidate_to_task(candidate_id, status="confirmed")
        if task_id:
            summary["confirmed_tasks_auto_created"] += 1
        else:
            summary["duplicates_skipped"] += 1
    else:
        summary["pending_candidates_created"] += 1


def run_auto_task_intake() -> dict:
    """
    Run local, explicit task intake.

    This does not call AI and does not write to Canvas. It only reads trusted
    local/Canvas sources that are already available to the app.
    """
    summary = _empty_summary()

    if has_canvas_base_url() and has_canvas_api_token():
        try:
            assignments, canvas_summary = get_all_assignments()
            for error in canvas_summary.get("errors", []):
                summary["errors"].append(error)
            for assignment in assignments:
                _handle_candidate(
                    normalize_canvas_assignment_to_candidate(assignment),
                    summary,
                )
        except (CanvasConfigError, CanvasAPIError) as error:
            summary["errors"].append(str(error))
    else:
        summary["errors"].append(
            "Canvas credentials are not configured, so Canvas assignment intake was skipped."
        )

    try:
        quercus_items = get_recent_quercus_items(limit=100)
    except Exception as error:
        quercus_items = []
        summary["errors"].append(f"Could not read Quercus item cache: {error}")

    for item in quercus_items:
        try:
            _handle_candidate(normalize_quercus_item_to_candidate(item), summary)
        except Exception as error:
            summary["errors"].append(
                f"Skipped one Quercus item during intake: {error}"
            )

    summary["tasks_rescored"] = rescore_all_active_tasks()
    return summary
