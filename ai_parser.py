import json
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAX_TEXT_CHARS = 30_000
DEFAULT_MODEL = "gpt-4o-mini"
VALID_CONFIDENCES = {"high", "medium", "low"}


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


def _openai_client():
    _load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your .env file.")

    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError(
            "The openai package is missing. Run: pip install -r requirements.txt"
        ) from error

    return OpenAI(api_key=api_key)


def _clean_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_date(value):
    text = _clean_text(value)
    if not text or text.lower() in {"none", "null", "n/a", "unknown"}:
        return None

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _clean_int(value):
    if value in (None, ""):
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def _clean_priority(value):
    if value in (None, ""):
        return None

    if isinstance(value, str):
        priority_map = {
            "highest": 5,
            "high": 5,
            "medium": 3,
            "normal": 3,
            "low": 1,
            "lowest": 1,
        }
        mapped = priority_map.get(value.strip().lower())
        if mapped:
            return mapped

    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return None


def _normalize_ai_task(task, source):
    confidence = (_clean_text(task.get("confidence")) or "low").lower()
    if confidence not in VALID_CONFIDENCES:
        confidence = "low"

    return {
        "title": _clean_text(task.get("title")) or "Untitled syllabus task",
        "course": _clean_text(task.get("course")),
        "task_type": _clean_text(task.get("task_type")),
        "status": "suggested",
        "source": source,
        "confidence": confidence,
        "due_at": _clean_date(task.get("due_at")),
        "planned_date": _clean_date(task.get("planned_date")),
        "estimated_minutes": _clean_int(task.get("estimated_minutes")),
        "priority": _clean_priority(task.get("priority")),
        "notes": _clean_text(task.get("notes")),
        "source_snippet": _clean_text(task.get("source_snippet")),
    }


def _parse_response_json(content):
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise RuntimeError("AI response was not valid JSON.") from error

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        tasks = parsed.get("tasks", [])
        return tasks if isinstance(tasks, list) else []

    return []


def extract_tasks_from_text(text, source="syllabus"):
    cleaned_text = _clean_text(text)
    if not cleaned_text:
        return []

    client = _openai_client()
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    prompt_text = cleaned_text[:MAX_TEXT_CHARS]
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract possible student tasks from syllabus text. "
                    "Return only structured JSON with a top-level tasks array. "
                    "Never invent deadlines. Use null when a date is unclear. "
                    "Every task status must be suggested."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract possible assignments, exams, quizzes, readings, "
                    "project milestones, participation requirements, and tutorial "
                    "preparation tasks from this syllabus text.\n\n"
                    "Return JSON in this shape:\n"
                    "{\n"
                    '  "tasks": [\n'
                    "    {\n"
                    '      "title": "string",\n'
                    '      "course": "string or null",\n'
                    '      "task_type": "assignment|exam|quiz|reading|project|participation|tutorial_preparation|other",\n'
                    '      "status": "suggested",\n'
                    '      "source": "syllabus",\n'
                    '      "confidence": "high|medium|low",\n'
                    '      "due_at": "YYYY-MM-DD or null",\n'
                    '      "planned_date": "YYYY-MM-DD or null",\n'
                    '      "estimated_minutes": "integer or null",\n'
                    '      "priority": "1-5 integer or null",\n'
                    '      "notes": "string or null",\n'
                    '      "source_snippet": "short supporting quote or null"\n'
                    "    }\n"
                    "  ]\n"
                    "}\n\n"
                    "Rules:\n"
                    "- Do not invent deadlines.\n"
                    "- If a date is unclear, use null.\n"
                    "- Use high confidence only when the task and date/details are clear.\n"
                    "- Use medium or low confidence for vague tasks.\n"
                    "- Do not include administrative notes that are not student tasks.\n\n"
                    f"Syllabus text:\n{prompt_text}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    raw_tasks = _parse_response_json(content)
    return [
        _normalize_ai_task(task, source)
        for task in raw_tasks
        if isinstance(task, dict)
    ]
