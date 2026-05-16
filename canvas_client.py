import os
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


def get_assignments(course_id: int | str) -> list[dict]:
    assignments = canvas_get(
        f"/api/v1/courses/{course_id}/assignments",
        params={"per_page": 100},
    )
    return assignments if isinstance(assignments, list) else []


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
