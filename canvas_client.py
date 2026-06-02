import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parent
LOCAL_TIMEZONE = ZoneInfo("America/Toronto")


class CanvasConfigError(RuntimeError):
    pass


class CanvasAPIError(RuntimeError):
    pass


class CanvasUnauthorizedError(CanvasAPIError):
    pass


def load_env_file():
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


def get_canvas_base_url():
    load_env_file()
    base_url = os.environ.get("CANVAS_BASE_URL", "").strip()
    return base_url.rstrip("/")


def has_canvas_base_url():
    return bool(get_canvas_base_url())


def has_canvas_api_token():
    load_env_file()
    return bool(os.environ.get("CANVAS_API_TOKEN", "").strip())


def get_canvas_headers() -> dict:
    load_env_file()
    token = os.environ.get("CANVAS_API_TOKEN", "").strip()
    if not token:
        raise CanvasConfigError(
            "CANVAS_API_TOKEN is missing. Add it to your .env file."
        )

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _canvas_url(path):
    if path.startswith("http://") or path.startswith("https://"):
        return path

    base_url = get_canvas_base_url()
    if not base_url:
        raise CanvasConfigError(
            "CANVAS_BASE_URL is missing. Add it to your .env file."
        )

    return urljoin(f"{base_url}/", path.lstrip("/"))


def _next_link(response):
    link_header = response.headers.get("Link", "")
    if not link_header:
        return None

    cleaned_header = link_header.rstrip(">").replace(">,", ",")
    for link in requests.utils.parse_header_links(cleaned_header):
        if link.get("rel") == "next" and link.get("url"):
            return link["url"]

    return None


def _friendly_http_error(response):
    if response.status_code in (401, 403):
        raise CanvasUnauthorizedError("Canvas token may be invalid or expired.")

    raise CanvasAPIError(
        f"Canvas API request failed with status {response.status_code}."
    )


def canvas_get(path: str, params: dict | None = None) -> list | dict:
    headers = get_canvas_headers()
    url = _canvas_url(path)
    next_params = params
    combined_results = []
    saw_list_response = False

    while url:
        try:
            response = requests.get(
                url,
                headers=headers,
                params=next_params,
                timeout=20,
            )
        except requests.RequestException as error:
            raise CanvasAPIError(f"Canvas network error: {error}") from error

        next_params = None
        if response.status_code >= 400:
            _friendly_http_error(response)

        try:
            payload = response.json()
        except ValueError as error:
            raise CanvasAPIError(
                "Canvas returned a response that was not JSON."
            ) from error

        if isinstance(payload, list):
            saw_list_response = True
            combined_results.extend(payload)
            url = _next_link(response)
        else:
            return payload

    return combined_results if saw_list_response else []


def get_courses() -> list[dict]:
    courses = canvas_get(
        "/api/v1/courses",
        params={
            "enrollment_state": "active",
            "include[]": ["term"],
            "per_page": 100,
        },
    )
    return courses if isinstance(courses, list) else []


def get_courses_with_total_scores() -> list[dict]:
    courses = canvas_get(
        "/api/v1/courses",
        params={
            "enrollment_state": "active",
            "include[]": [
                "term",
                "total_scores",
                "current_grading_period_scores",
            ],
            "per_page": 100,
        },
    )
    return courses if isinstance(courses, list) else []


def get_assignments(course_id: int | str) -> list[dict]:
    assignments = canvas_get(
        f"/api/v1/courses/{course_id}/assignments",
        params={"per_page": 100},
    )
    return assignments if isinstance(assignments, list) else []


def get_course_submissions(course_id: int | str) -> list[dict]:
    submissions = canvas_get(
        f"/api/v1/courses/{course_id}/students/submissions",
        params={
            "include[]": [
                "submission_comments",
                "rubric_assessment",
                "assignment",
            ],
            "order": "graded_at",
            "order_direction": "descending",
            "per_page": 100,
        },
    )
    return submissions if isinstance(submissions, list) else []


def _course_name(course):
    return (
        course.get("name")
        or course.get("course_code")
        or str(course.get("id", "Unknown course"))
    )


def _local_canvas_datetime(value):
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(LOCAL_TIMEZONE)

    if parsed.hour or parsed.minute:
        return parsed.strftime("%Y-%m-%d %H:%M")
    return parsed.date().isoformat()


def _plain_text(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _first_enrollment(course):
    enrollments = course.get("enrollments") or []
    if not enrollments:
        return {}
    return enrollments[0] or {}


def _normalize_course_grade(course):
    enrollment = _first_enrollment(course)
    term = course.get("term") or {}
    return {
        "course_id": str(course.get("id")) if course.get("id") is not None else None,
        "course": _course_name(course),
        "term": term.get("name") or "",
        "grade": (
            enrollment.get("computed_current_grade")
            or enrollment.get("computed_final_grade")
            or enrollment.get("current_grade")
            or enrollment.get("final_grade")
        ),
        "grade_percent": (
            enrollment.get("computed_current_score")
            or enrollment.get("computed_final_score")
            or enrollment.get("current_score")
            or enrollment.get("final_score")
        ),
        "grade_type": "current",
    }


def _submission_comments_text(submission):
    comments = submission.get("submission_comments") or []
    pieces = []
    for comment in comments:
        text = _plain_text(comment.get("comment"))
        if not text:
            continue
        author = comment.get("author_name") or "Instructor"
        created_at = _local_canvas_datetime(comment.get("created_at"))
        prefix = f"{author}"
        if created_at:
            prefix += f" ({created_at})"
        pieces.append(f"{prefix}: {text}")
    return "\n".join(pieces) or None


def _normalize_submission_feedback(submission, course):
    assignment = submission.get("assignment") or {}
    assignment_id = submission.get("assignment_id") or assignment.get("id")
    user_id = submission.get("user_id") or "self"
    external_id = f"{course.get('id')}:{assignment_id}:{user_id}"
    rubric = submission.get("rubric_assessment")
    points_possible = assignment.get("points_possible")
    return {
        "external_id": external_id,
        "external_source": "canvas_submission",
        "course_id": str(course.get("id")),
        "course_name": _course_name(course),
        "assignment_id": str(assignment_id) if assignment_id is not None else None,
        "assignment_title": (
            assignment.get("name")
            or assignment.get("title")
            or f"Assignment {assignment_id}"
        ),
        "grade": submission.get("grade"),
        "score": submission.get("score"),
        "points_possible": points_possible,
        "graded_at": _local_canvas_datetime(submission.get("graded_at")),
        "submitted_at": _local_canvas_datetime(submission.get("submitted_at")),
        "posted_at": _local_canvas_datetime(submission.get("posted_at")),
        "late": 1 if submission.get("late") else 0,
        "missing": 1 if submission.get("missing") else 0,
        "excused": 1 if submission.get("excused") else 0,
        "workflow_state": submission.get("workflow_state"),
        "html_url": submission.get("html_url") or assignment.get("html_url"),
        "feedback_text": _submission_comments_text(submission),
        "rubric_json": json.dumps(rubric, ensure_ascii=False) if rubric else None,
        "raw_json": json.dumps(submission, ensure_ascii=False),
    }


def _has_grade_feedback(submission):
    return any(
        submission.get(key) not in (None, "", [])
        for key in (
            "grade",
            "score",
            "graded_at",
            "submission_comments",
            "rubric_assessment",
        )
    )


def _normalize_assignment(assignment, course):
    assignment_id = assignment.get("id")
    return {
        "external_id": str(assignment_id) if assignment_id is not None else None,
        "external_source": "canvas_assignment",
        "external_url": assignment.get("html_url"),
        "course_id": str(course.get("id")),
        "course_name": _course_name(course),
        "title": assignment.get("name") or "Untitled Canvas assignment",
        "due_at": _local_canvas_datetime(assignment.get("due_at")),
        "description": assignment.get("description"),
    }


def get_all_assignments() -> tuple[list[dict], dict]:
    summary = {
        "courses_found": 0,
        "assignments_found": 0,
        "errors": [],
    }
    normalized_assignments = []

    try:
        courses = get_courses()
    except (CanvasConfigError, CanvasAPIError) as error:
        summary["errors"].append(str(error))
        return normalized_assignments, summary

    summary["courses_found"] = len(courses)

    for course in courses:
        course_id = course.get("id")
        if course_id is None:
            summary["errors"].append("Skipped one course because it had no Canvas id.")
            continue

        try:
            assignments = get_assignments(course_id)
        except (CanvasConfigError, CanvasAPIError) as error:
            summary["errors"].append(f"{_course_name(course)}: {error}")
            continue

        summary["assignments_found"] += len(assignments)
        for assignment in assignments:
            normalized_assignments.append(_normalize_assignment(assignment, course))

    return normalized_assignments, summary


def get_all_grade_feedback() -> tuple[list[dict], list[dict], dict]:
    summary = {
        "courses_found": 0,
        "course_grades_found": 0,
        "grade_items_found": 0,
        "errors": [],
    }
    course_grades = []
    grade_items = []

    try:
        courses = get_courses_with_total_scores()
    except (CanvasConfigError, CanvasAPIError) as error:
        summary["errors"].append(str(error))
        return course_grades, grade_items, summary

    summary["courses_found"] = len(courses)

    for course in courses:
        course_id = course.get("id")
        if course_id is None:
            summary["errors"].append("Skipped one course because it had no Canvas id.")
            continue

        course_grade = _normalize_course_grade(course)
        if course_grade.get("grade") or course_grade.get("grade_percent") is not None:
            course_grades.append(course_grade)

        try:
            submissions = get_course_submissions(course_id)
        except (CanvasConfigError, CanvasAPIError) as error:
            summary["errors"].append(f"{_course_name(course)}: {error}")
            continue

        for submission in submissions:
            if _has_grade_feedback(submission):
                grade_items.append(_normalize_submission_feedback(submission, course))

    summary["course_grades_found"] = len(course_grades)
    summary["grade_items_found"] = len(grade_items)
    return course_grades, grade_items, summary
