import hashlib
import html
import json
import os
import re
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from action_engine import build_confirmable_actions, count_ready_actions
from ai_chat import (
    AIChatConfigError,
    AIChatResponseError,
    build_chat_context,
    generate_chat_response,
    openai_api_key_status as ai_chat_api_key_status,
)
from ai_boss import (
    AIBossConfigError,
    AIBossResponseError,
    build_ai_boss_context,
    generate_ai_boss_briefing,
    has_openai_api_key,
)
from ai_parser import extract_tasks_from_text
from behavior_design import (
    BehaviorDesignConfigError,
    BehaviorDesignResponseError,
    behavior_updates_for_task,
    build_behavior_design_context,
    generate_behavior_design_plan,
    has_openai_api_key as has_behavior_design_api_key,
)
from canvas_client import (
    get_all_assignments,
    get_canvas_base_url,
    has_canvas_api_token,
    has_canvas_base_url,
)
from conversation_intake import (
    ConversationIntakeConfigError,
    ConversationIntakeResponseError,
    has_openai_api_key as has_conversation_intake_api_key,
    parse_conversation_message,
)
from daily_command import (
    DailyCommandConfigError,
    DailyCommandResponseError,
    build_daily_command_context,
    generate_daily_command,
    has_openai_api_key as has_daily_command_api_key,
)
from feedback_loop import evaluate_daily_command
from question_coach import (
    QuestionCoachConfigError,
    QuestionCoachResponseError,
    generate_checkin_questions,
    has_openai_api_key as has_question_coach_api_key,
)
from db import (
    archive_course,
    accept_task_update,
    auto_finish_past_due_tasks,
    clear_chat_history,
    complete_study_session,
    create_agent_memory,
    create_agent_memory_candidate,
    create_checkin_answer,
    create_command_center_message,
    create_or_update_morning_checkin,
    create_or_update_behavior_plan,
    create_or_update_daily_refresh_run,
    create_or_update_daily_review,
    create_personal_commitment,
    create_document,
    create_task,
    create_task_update,
    create_canvas_assignment_task,
    create_study_session_start,
    deactivate_agent_memory,
    export_daily_reviews_to_csv,
    get_active_study_session,
    get_active_agent_memory,
    get_all_tasks,
    get_recent_chat_messages,
    get_checkin_answers_by_date,
    get_daily_review_by_date,
    get_daily_command_review_by_command,
    get_daily_refresh_run_by_date,
    get_latest_daily_command,
    get_latest_ai_boss_briefing,
    get_behavior_plan_by_date,
    get_course_summaries,
    get_morning_checkin_by_date,
    get_pending_agent_memory_candidates,
    get_pending_task_updates,
    get_recent_command_center_messages,
    memory_exists,
    get_personal_commitments_for_date,
    get_task_candidates,
    get_recent_daily_commands,
    get_recent_daily_command_reviews,
    get_recent_ai_boss_briefings,
    get_recent_behavior_plans,
    get_recent_study_sessions,
    get_recent_daily_reviews,
    get_tasks_by_status,
    get_this_week_tasks,
    get_today_tasks,
    ignore_past_quercus_intake_items,
    init_db,
    promote_candidate_to_task,
    rescore_all_active_tasks,
    save_daily_command,
    save_chat_message,
    save_ai_boss_briefing,
    create_or_update_daily_command_review,
    mark_command_center_message_applied,
    promote_memory_candidate_to_memory,
    unarchive_course,
    update_agent_memory_candidate_decision,
    update_chat_message_metadata,
    update_task_fields,
    update_task_behavior_fields,
    update_personal_commitment_status,
    update_task_candidate_decision,
    update_task_update_status,
    update_task_status,
)
from file_parser import extract_text_from_pdf, get_file_metadata
from planner import generate_today_plan, sort_tasks_for_dashboard, task_indicators
from task_intake import run_auto_task_intake
from urgency import calculate_urgency_score

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "data" / "exports"
LOCAL_TIMEZONE = ZoneInfo("America/Toronto")

MAIN_MENU_OPTIONS = [
    "Add Material",
    "Review Suggestions",
    "Tasks",
    "Check Updates",
    "Settings",
]

EXPERIMENTAL_MENU_OPTIONS = [
    "AI Boss Chat",
    "Command Center",
    "Tasks",
    "Today",
    "This Week",
    "7-Day Timeline",
    "Today Plan",
    "Daily Command",
    "Behavior Design",
    "Feedback Loop",
    "AI Boss",
    "Task Intake",
    "Focus Session",
    "Daily Review",
    "Agent Memory",
    "Confirmed Tasks",
    "Suggested Tasks",
    "In Progress",
    "Completed",
    "Files / Syllabus Upload",
    "Quercus Sync",
    "Settings",
    "Memory",
    "Add Task",
    "All Tasks",
]

ADVANCED_MENU_OPTIONS = EXPERIMENTAL_MENU_OPTIONS

DOCUMENT_TYPES = [
    "syllabus",
    "announcement",
    "assignment instruction",
    "other",
]

STATUS_ACTIONS = {
    "suggested": [
        ("Confirm", "confirmed"),
        ("Ignore", "ignored"),
    ],
    "confirmed": [
        ("Start", "in_progress"),
        ("Mark Done", "done"),
    ],
    "in_progress": [
        ("Mark Done", "done"),
        ("Move Back to Confirmed", "confirmed"),
    ],
    "done": [
        ("Reopen", "confirmed"),
    ],
}

MEMORY_TYPES = [
    "preference",
    "pattern",
    "weakness",
    "strength",
    "rule",
    "goal",
    "course_context",
    "time_estimation",
    "avoidance",
    "management_style",
    "other",
]

MEMORY_SOURCES = [
    "manual",
    "study_sessions",
    "daily_reviews",
    "ai_summary_later",
    "system",
]

COMMITMENT_TYPES = [
    "gym",
    "class",
    "commute",
    "meal",
    "work",
    "social",
    "errand",
    "personal",
    "other",
]

DEFAULT_AGENT_MEMORIES = [
    {
        "memory_type": "management_style",
        "memory_key": "preferred_boss_style",
        "memory_value": (
            "User wants a direct AI boss style: clear instructions, some "
            "pressure, but not insulting."
        ),
        "confidence": "high",
        "source": "manual",
    },
    {
        "memory_type": "rule",
        "memory_key": "no_deadline_invention",
        "memory_value": (
            "The agent must never invent deadlines. If a deadline is unclear, "
            "ask for confirmation or mark confidence low."
        ),
        "confidence": "high",
        "source": "system",
    },
    {
        "memory_type": "rule",
        "memory_key": "suggested_tasks_need_confirmation",
        "memory_value": (
            "AI-extracted tasks should remain suggested until the user "
            "confirms them."
        ),
        "confidence": "high",
        "source": "system",
    },
    {
        "memory_type": "rule",
        "memory_key": "top_three_tasks",
        "memory_value": (
            "The agent should usually recommend at most three main tasks per "
            "day to avoid overwhelm."
        ),
        "confidence": "high",
        "source": "system",
    },
    {
        "memory_type": "rule",
        "memory_key": "ai_suggests_user_confirms",
        "memory_value": (
            "AI can suggest actions and priorities, but the user should "
            "confirm uncertain tasks before they become official commitments."
        ),
        "confidence": "high",
        "source": "system",
    },
    {
        "memory_type": "goal",
        "memory_key": "build_ai_execution_manager",
        "memory_value": (
            "The long-term product goal is to build an AI execution manager "
            "that helps the user plan, execute, review, and improve work "
            "habits over time."
        ),
        "confidence": "high",
        "source": "manual",
    },
]


def inject_calm_command_css():
    st.markdown(
        """
        <style>
        :root {
            --app-bg: #F7F7F2;
            --card-bg: #FFFFFF;
            --text-main: #1F2933;
            --text-secondary: #374151;
            --text-muted: #6B7280;
            --border: #E5E7EB;
            --primary: #2563EB;
            --secondary: #0F766E;
            --warning: #B45309;
            --critical: #B91C1C;
            --success: #15803D;
        }

        .stApp {
            background: var(--app-bg);
            color: var(--text-main);
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        [data-testid="stHeader"] {
            background: rgba(247, 247, 242, 0.92);
            backdrop-filter: blur(8px);
        }

        [data-testid="stAppViewContainer"] .main .block-container {
            max-width: 900px;
            padding-top: 2.25rem;
            padding-bottom: 3rem;
        }

        section[data-testid="stSidebar"] {
            background: #FFFFFF;
            border-right: 1px solid var(--border);
        }

        h1, h2, h3, h4 {
            color: var(--text-main);
            letter-spacing: 0;
        }

        p, li, label, [data-testid="stMarkdownContainer"] {
            color: var(--text-secondary);
            line-height: 1.55;
        }

        [data-testid="stCaptionContainer"],
        small {
            color: var(--text-muted);
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            box-shadow: 0 1px 2px rgba(31, 41, 51, 0.04);
        }

        .stButton > button {
            border-radius: 8px;
            min-height: 42px;
            font-weight: 650;
            border-color: var(--border);
        }

        .stButton > button[kind="primary"] {
            background: var(--primary);
            border-color: var(--primary);
            color: #FFFFFF;
        }

        .stTextInput input,
        .stTextArea textarea,
        [data-baseweb="select"] {
            border-radius: 8px;
        }

        div[data-testid="stMetric"] {
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
        }

        .calm-hero {
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.35rem 1.5rem;
            margin: 0.75rem 0 1rem;
        }

        .calm-eyebrow {
            color: var(--text-muted);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 0.45rem;
        }

        .calm-objective {
            color: var(--text-main);
            font-size: 1.32rem;
            font-weight: 760;
            line-height: 1.35;
            margin-bottom: 0.75rem;
        }

        .calm-first-action {
            border-left: 3px solid var(--primary);
            padding-left: 0.85rem;
            color: var(--text-secondary);
            font-size: 0.98rem;
            line-height: 1.55;
        }

        .calm-meta {
            color: var(--text-muted);
            font-size: 0.84rem;
            margin-top: 0.55rem;
        }

        .calm-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 0.18rem 0.55rem;
            font-size: 0.74rem;
            font-weight: 700;
            border: 1px solid var(--border);
            color: var(--text-muted);
            background: #F9FAFB;
        }

        .calm-badge-critical,
        .calm-badge-urgent {
            color: var(--critical);
            border-color: rgba(185, 28, 28, 0.2);
            background: rgba(185, 28, 28, 0.07);
        }

        .calm-badge-soon,
        .calm-badge-normal {
            color: var(--warning);
            border-color: rgba(180, 83, 9, 0.2);
            background: rgba(180, 83, 9, 0.07);
        }

        .calm-badge-low,
        .calm-badge-no_due_date {
            color: var(--text-muted);
            background: #F3F4F6;
        }

        .task-title-row {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.25rem;
        }

        .task-title-row h4 {
            margin: 0;
            font-size: 1rem;
            line-height: 1.35;
        }

        .task-card-meta {
            color: var(--text-muted);
            font-size: 0.86rem;
            margin: 0.25rem 0 0.75rem;
        }

        .chat-shell {
            min-height: 54vh;
            padding: 0.25rem 0 1rem;
        }

        .chat-context-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 0.75rem;
            margin: 0.5rem 0 0.75rem;
        }

        .chat-context-stat {
            background: #FFFFFF;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.75rem;
        }

        .chat-context-label {
            color: var(--text-muted);
            font-size: 0.74rem;
            font-weight: 750;
            text-transform: uppercase;
        }

        .chat-context-value {
            color: var(--text-main);
            font-size: 1.25rem;
            font-weight: 760;
        }

        .proposed-action-card {
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.8rem 0.9rem;
            margin: 0.5rem 0;
            background: #FFFFFF;
        }

        .detail-field {
            margin-bottom: 0.8rem;
        }

        .detail-label {
            color: var(--text-muted);
            font-size: 0.73rem;
            font-weight: 750;
            line-height: 1.25;
            margin-bottom: 0.18rem;
            text-transform: uppercase;
        }

        .detail-value {
            color: var(--text-secondary);
            font-size: 0.9rem;
            line-height: 1.45;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }

        .focus-timer {
            color: var(--text-main);
            font-size: 2.25rem;
            font-weight: 780;
            line-height: 1.1;
            margin: 0.2rem 0 1rem;
        }

        .timeline-day {
            color: var(--text-main);
            font-size: 0.96rem;
            font-weight: 750;
            margin: 0.25rem 0 0.4rem;
        }

        .timeline-item {
            border-left: 3px solid var(--border);
            padding: 0.35rem 0 0.35rem 0.75rem;
            margin: 0.35rem 0;
        }

        .timeline-item-critical,
        .timeline-item-urgent {
            border-left-color: var(--critical);
        }

        .timeline-item-soon,
        .timeline-item-normal {
            border-left-color: var(--warning);
        }

        .timeline-title {
            color: var(--text-main);
            font-weight: 700;
            line-height: 1.35;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def display_value(value):
    if value is None or value == "":
        return "-"
    return str(value)


def escape_html(value):
    return html.escape(display_value(value), quote=True)


def display_task_datetime(value):
    if not value:
        return "-"

    if isinstance(value, datetime):
        parsed = value
        include_time = bool(parsed.hour or parsed.minute or parsed.second)
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
        include_time = False
    else:
        text = str(value).strip()
        if not text:
            return "-"

        include_time = len(text) > 10 and (":" in text[10:] or "T" in text[10:])
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
                include_time = True
            except ValueError:
                try:
                    parsed = datetime.strptime(text[:10], "%Y-%m-%d")
                    include_time = False
                except ValueError:
                    return text

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(LOCAL_TIMEZONE)

    label = f"{parsed.strftime('%b')} {parsed.day}"
    if include_time:
        time_label = parsed.strftime("%I:%M %p").lstrip("0")
        return f"{label}, {time_label}"
    return label


def render_detail_field(container, label, value, formatter=None):
    shown_value = formatter(value) if formatter else display_value(value)
    container.markdown(
        (
            '<div class="detail-field">'
            f'<div class="detail-label">{escape_html(label)}</div>'
            f'<div class="detail-value">{escape_html(shown_value)}</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def task_meta_line(task):
    pieces = []
    if task.get("course"):
        pieces.append(task["course"])
    if task.get("due_at"):
        pieces.append(f"Due {display_task_datetime(task['due_at'])}")
    elif task.get("planned_date"):
        pieces.append(f"Planned {display_task_datetime(task['planned_date'])}")
    if task.get("estimated_minutes"):
        pieces.append(f"{task['estimated_minutes']} min")
    if task.get("status"):
        pieces.append(task["status"])
    return " | ".join(str(piece) for piece in pieces) or "No metadata yet"


def urgency_badge_html(label):
    label = str(label or "normal")
    badge_class = re.sub(r"[^a-z0-9_]+", "_", label.lower())
    return (
        f'<span class="calm-badge calm-badge-{badge_class}">'
        f'{html.escape(label)}</span>'
    )


def first_action_for_task(task):
    if task.get("first_action"):
        return task["first_action"]
    if task.get("next_action"):
        return task["next_action"]
    return "Open this task and write the exact next step."


def parse_timeline_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def timeline_day_label(day, today=None):
    today = today or date.today()
    if day == today:
        prefix = "Today"
    elif day == today + timedelta(days=1):
        prefix = "Tomorrow"
    else:
        prefix = day.strftime("%a")
    return f"{prefix} | {day.isoformat()}"


def timeline_entry_sort_key(entry):
    task = entry["task"]
    score, _, _ = calculate_urgency_score(task)
    kind_rank = 0 if entry["kind"] == "due" else 1
    return (
        -score,
        kind_rank,
        task.get("due_at") or task.get("planned_date") or "9999-12-31",
        -(int(task.get("priority") or 0)),
        task.get("title") or "",
    )


def build_7_day_timeline(tasks=None, today=None):
    today = today or date.today()
    tasks = tasks if tasks is not None else get_all_tasks()
    active_tasks = [
        task for task in tasks
        if task.get("status") not in ("done", "ignored")
    ]

    overdue = []
    day_entries = {
        today + timedelta(days=offset): []
        for offset in range(7)
    }
    for task in active_tasks:
        due_date = parse_timeline_date(task.get("due_at"))
        planned_date = parse_timeline_date(task.get("planned_date"))
        if due_date and due_date < today:
            overdue.append({"task": task, "kind": "overdue"})

        seen = set()
        for kind, task_date in (("due", due_date), ("planned", planned_date)):
            if task_date not in day_entries:
                continue
            key = (task.get("id"), kind, task_date)
            if key in seen:
                continue
            seen.add(key)
            day_entries[task_date].append({"task": task, "kind": kind})

    return {
        "overdue": sorted(overdue, key=timeline_entry_sort_key),
        "days": [
            {
                "date": day,
                "label": timeline_day_label(day, today),
                "entries": sorted(entries, key=timeline_entry_sort_key),
            }
            for day, entries in day_entries.items()
        ],
    }


def display_date(task):
    if task.get("due_at"):
        return f"Due: {display_task_datetime(task['due_at'])}"
    if task.get("planned_date"):
        return f"Planned: {display_task_datetime(task['planned_date'])}"
    return "No date"


def task_urgency(task):
    score = task.get("urgency_score")
    label = task.get("urgency_label")
    if label and score not in (None, ""):
        try:
            return float(score), label
        except (TypeError, ValueError):
            pass

    score, label, _ = calculate_urgency_score(task)
    return score, label


def display_datetime(value):
    if not value:
        return "-"

    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)

    return parsed.strftime("%Y-%m-%d %H:%M")


def elapsed_minutes_since(value):
    if not value:
        return 0

    try:
        start_time = datetime.fromisoformat(str(value))
    except ValueError:
        return 0

    elapsed_seconds = max(0, int((datetime.now() - start_time).total_seconds()))
    return elapsed_seconds // 60


def safe_filename(filename):
    name = Path(filename).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if safe_name in ("", ".", ".."):
        return "uploaded.pdf"
    return safe_name


def view_key(view_name):
    return view_name.lower().replace(" ", "_")


def get_tasks_for_view(view_name):
    if view_name == "Today":
        return get_today_tasks()
    if view_name == "This Week":
        return get_this_week_tasks()
    if view_name == "Confirmed Tasks":
        return get_tasks_by_status("confirmed")
    if view_name == "Suggested Tasks":
        return get_tasks_by_status("suggested")
    if view_name == "In Progress":
        return get_tasks_by_status("in_progress")
    if view_name == "Completed":
        return get_tasks_by_status("done")
    return get_all_tasks()


def empty_message_for_view(view_name):
    messages = {
        "Today": "Nothing due, planned, or overdue for today.",
        "This Week": "No active tasks due or planned in the next 7 days.",
        "Confirmed Tasks": "No confirmed tasks yet.",
        "Suggested Tasks": "No suggested tasks yet.",
        "In Progress": "No tasks are in progress right now.",
        "Completed": "No completed tasks yet.",
        "All Tasks": "No tasks available. Add your first task to get started.",
    }
    return messages.get(view_name, "No tasks available.")


def show_pending_message():
    message = st.session_state.pop("status_update_message", None)
    if message:
        st.success(message)


def parse_json_object(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def chat_action_id(action):
    raw = json.dumps(action or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def chat_action_args(action):
    args = (action or {}).get("args") or {}
    return args if isinstance(args, dict) else {}


def chat_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def chat_priority(value):
    if isinstance(value, str):
        mapped = {
            "highest": 5,
            "high": 5,
            "medium": 3,
            "normal": 3,
            "low": 1,
            "lowest": 1,
        }.get(value.strip().lower())
        if mapped:
            return mapped
    return max(1, min(5, chat_int(value, 3)))


def find_chat_task(args):
    task_id = args.get("task_id") or args.get("id")
    tasks = get_all_tasks()
    if task_id not in (None, ""):
        for task in tasks:
            if str(task.get("id")) == str(task_id):
                return task
        raise ValueError(f"Task id {task_id} was not found.")

    title = (args.get("title") or args.get("task_title") or "").strip().casefold()
    if not title:
        raise ValueError("The action needs a task_id or exact title.")

    matches = [
        task for task in tasks
        if (task.get("title") or "").strip().casefold() == title
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("Multiple tasks matched that title. Ask AI Boss to use task_id.")
    raise ValueError("No task matched that title.")


def apply_chat_create_task(args):
    title = display_value(args.get("title")).strip()
    if not title or title == "-":
        raise ValueError("create_task requires a title.")

    status = args.get("status")
    if status not in ("suggested", "confirmed", "in_progress"):
        status = "suggested"

    task_id = create_task({
        "title": title,
        "course": args.get("course"),
        "task_type": args.get("task_type") or args.get("type") or "task",
        "due_at": args.get("due_at"),
        "planned_date": args.get("planned_date"),
        "estimated_minutes": chat_int(args.get("estimated_minutes")),
        "priority": chat_priority(args.get("priority")),
        "status": status,
        "source": args.get("source") or "ai_boss_chat",
        "confidence": args.get("confidence") or "medium",
        "notes": args.get("notes"),
        "source_snippet": args.get("source_snippet"),
        "needs_review": 1 if status == "suggested" else 0,
    })
    return f"Created {status} task #{task_id}: {title}"


def apply_chat_update_task_status(args):
    task = find_chat_task(args)
    status = args.get("status") or args.get("new_status") or args.get("suggested_status")
    if status not in ("suggested", "confirmed", "ignored", "in_progress", "done"):
        raise ValueError("update_task_status requires a valid status.")
    update_task_status(task["id"], status)
    return f"Updated '{task['title']}' to {status}."


def apply_chat_start_focus_session(args):
    if get_active_study_session():
        return "Skipped: a focus session is already active."

    task = find_chat_task(args)
    planned_minutes = chat_int(args.get("planned_minutes"), 25)
    start_focus_session_for_task(task, planned_minutes=max(1, planned_minutes))
    return f"Started a {planned_minutes}-minute focus session for '{task['title']}'."


def apply_chat_end_focus_session(args):
    active_session = get_active_study_session()
    if not active_session:
        return "Skipped: there is no active focus session."

    completion_status = args.get("completion_status") or "partial"
    if completion_status not in ("completed", "partial", "not_completed", "blocked"):
        completion_status = "partial"
    completed_session = complete_study_session(
        active_session["id"],
        completion_status,
        args.get("blocker"),
        args.get("notes"),
    )
    task_id = completed_session.get("task_id")
    if task_id and completion_status == "completed":
        update_task_status(task_id, "done")
    elif task_id and completion_status in ("partial", "blocked"):
        update_task_status(task_id, "in_progress")
    return f"Ended focus session as {completion_status}."


def apply_chat_daily_review(args):
    review_date = args.get("review_date") or date.today().isoformat()
    create_or_update_daily_review({
        "review_date": review_date,
        "completed_summary": args.get("completed_summary"),
        "missed_tasks": args.get("missed_tasks"),
        "blockers": args.get("blockers"),
        "avoidance_notes": args.get("avoidance_notes"),
        "tomorrow_top_priority": args.get("tomorrow_top_priority"),
        "mood_energy": args.get("mood_energy") or "medium",
        "focus_rating": chat_int(args.get("focus_rating"), 3),
    })
    return f"Saved daily review for {review_date}."


def apply_chat_agent_memory(args):
    memory_id = create_agent_memory({
        "memory_type": args.get("memory_type") or "other",
        "memory_key": args.get("memory_key") or args.get("key"),
        "memory_value": args.get("memory_value") or args.get("value"),
        "confidence": args.get("confidence") or "medium",
        "source": args.get("source") or "ai_boss_chat",
    })
    return f"Saved agent memory #{memory_id}."


def apply_chat_ai_boss_briefing():
    current_date = date.today().isoformat()
    tasks = get_all_tasks()
    context = build_ai_boss_context(
        tasks=tasks,
        today_plan=generate_today_plan(tasks),
        recent_study_sessions=get_recent_study_sessions(limit=20),
        recent_daily_reviews=get_recent_daily_reviews(limit=7),
        active_memories=get_active_agent_memory(),
        current_date=current_date,
    )
    briefing = generate_ai_boss_briefing(context)
    raw_response = briefing.get("_raw_response")
    briefing_for_save = {
        key: value for key, value in briefing.items()
        if key != "_raw_response"
    }
    save_ai_boss_briefing(
        briefing_date=current_date,
        input_summary_json=json.dumps(context, ensure_ascii=False),
        output_json=json.dumps(briefing_for_save, ensure_ascii=False),
        raw_response=raw_response,
    )
    return "Generated and saved a new AI Boss briefing."


def execute_chat_action(action):
    action_type = (action or {}).get("action_type")
    args = chat_action_args(action)
    try:
        if action_type == "create_task":
            message = apply_chat_create_task(args)
        elif action_type == "update_task_status":
            message = apply_chat_update_task_status(args)
        elif action_type == "run_task_intake":
            summary = run_auto_task_intake()
            message = (
                "Ran Task Intake: "
                f"{summary.get('confirmed_tasks_auto_created', 0)} confirmed, "
                f"{summary.get('pending_candidates_created', 0)} pending, "
                f"{summary.get('tasks_updated', 0)} updated."
            )
        elif action_type == "run_quercus_sync":
            record = run_daily_quercus_refresh(trigger_source="ai_boss_chat")
            message = f"Ran Quercus refresh: {record.get('status')}."
        elif action_type == "start_focus_session":
            message = apply_chat_start_focus_session(args)
        elif action_type == "end_focus_session":
            message = apply_chat_end_focus_session(args)
        elif action_type == "save_daily_review":
            message = apply_chat_daily_review(args)
        elif action_type == "create_agent_memory":
            message = apply_chat_agent_memory(args)
        elif action_type == "generate_ai_boss_briefing":
            message = apply_chat_ai_boss_briefing()
        else:
            return {
                "status": "skipped",
                "message": f"Unsupported action type: {display_value(action_type)}",
            }
    except Exception as error:
        return {
            "status": "error",
            "message": str(error),
        }

    return {
        "status": "applied",
        "message": message,
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }


def render_chat_context_summary(context):
    counts = context.get("counts", {})
    visible_counts = [
        ("Active tasks", counts.get("active_tasks", 0)),
        ("Urgent context", counts.get("top_urgent_tasks", 0)),
        ("Pending candidates", counts.get("pending_candidates", 0)),
        ("Focus sessions", counts.get("recent_study_sessions", 0)),
        ("Daily reviews", counts.get("recent_daily_reviews", 0)),
        ("Memories", counts.get("active_memories", 0)),
    ]
    stat_html = "".join(
        (
            '<div class="chat-context-stat">'
            f'<div class="chat-context-label">{escape_html(label)}</div>'
            f'<div class="chat-context-value">{escape_html(value)}</div>'
            '</div>'
        )
        for label, value in visible_counts
    )
    st.markdown(
        f'<div class="chat-context-row">{stat_html}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "The chat receives compact task, focus, review, and memory summaries. "
        "It does not receive full PDFs, raw Quercus JSON, or the whole database."
    )


def render_proposed_actions(message_id, metadata, actions):
    if not actions:
        return

    action_results = metadata.get("action_results") or {}
    st.markdown("**Proposed Actions**")
    for index, action in enumerate(actions, start=1):
        action_id = chat_action_id(action)
        result = action_results.get(action_id)
        args_preview = json.dumps(
            action.get("args") or {},
            ensure_ascii=False,
            indent=2,
        )
        st.markdown(
            (
                '<div class="proposed-action-card">'
                f'<div class="detail-label">Proposed action {index}</div>'
                f'<div class="detail-value"><strong>{escape_html(action.get("action_type"))}</strong>'
                f' | risk: {escape_html(action.get("risk_level"))}'
                f' | confirmation: {escape_html(action.get("requires_confirmation"))}</div>'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
        st.code(args_preview, language="json")
        if result:
            status = result.get("status")
            message = result.get("message")
            if status == "applied":
                st.success(message)
            elif status == "error":
                st.error(message)
            else:
                st.info(message)
            continue

        st.caption("Nothing happens until you confirm this action.")
        if st.button(
            "Confirm and Execute",
            key=f"chat-action-{message_id}-{action_id}",
        ):
            result = execute_chat_action(action)
            updated_metadata = dict(metadata)
            updated_results = dict(action_results)
            updated_results[action_id] = result
            updated_metadata["action_results"] = updated_results
            update_chat_message_metadata(message_id, updated_metadata)
            st.rerun()


def render_chat_questions(questions):
    if not questions:
        return

    st.markdown("**Questions**")
    for question in questions:
        st.write(f"- {question}")


def render_ai_boss_chat_message(message):
    metadata = parse_json_object(message.get("metadata_json"))
    role = message.get("role")
    chat_role = role if role in ("user", "assistant") else "assistant"
    with st.chat_message(chat_role):
        st.write(message.get("content"))
        if role == "assistant":
            render_proposed_actions(
                message.get("id"),
                metadata,
                metadata.get("proposed_actions") or [],
            )
            render_chat_questions(metadata.get("questions") or [])


def render_ai_boss_chat():
    st.markdown("## AI Boss Chat")
    st.caption("Talk to the execution manager. MVP-16A is read-only: it can propose actions, but it cannot execute them.")

    key_present, key_message = ai_chat_api_key_status()
    if not key_present:
        st.warning(key_message)

    context = build_chat_context()
    with st.expander("Context used by AI", expanded=False):
        render_chat_context_summary(context)

    with st.container(border=True):
        st.markdown("### Talk to AI Boss")
        st.caption("Use this like a large command box. The agent can answer and propose actions, but it will not execute them yet.")
        with st.form("ai_boss_chat_form", clear_on_submit=True):
            message = st.text_area(
                "Message",
                placeholder=(
                    "Example: I have 2 hours, low energy, and I am avoiding "
                    "CLA task 2. What should I do first?"
                ),
                height=180,
                label_visibility="collapsed",
                disabled=not key_present,
            )
            submitted = st.form_submit_button(
                "Send to AI Boss",
                disabled=not key_present,
            )

        if submitted:
            message = (message or "").strip()
            if not message:
                st.warning("Write a message first.")
                return

            save_chat_message("user", message)
            recent_messages = get_recent_chat_messages(limit=30)
            context = build_chat_context()

            with st.spinner("AI Boss is reading the local context..."):
                try:
                    response = generate_chat_response(message, recent_messages, context)
                except (AIChatConfigError, ValueError) as error:
                    st.error(str(error))
                    return
                except AIChatResponseError as error:
                    st.error(str(error))
                    if error.raw_response:
                        st.text_area("Raw AI response", value=error.raw_response, height=220)
                    return
                except Exception:
                    st.error("Could not generate chat response. Check your OpenAI settings and try again.")
                    return

            metadata = {
                "proposed_actions": response.get("proposed_actions") or [],
                "questions": response.get("questions") or [],
                "context_counts": context.get("counts", {}),
            }
            save_chat_message("assistant", response.get("message"), metadata=metadata)
            st.rerun()

    messages = get_recent_chat_messages(limit=30)
    st.markdown('<div class="chat-shell">', unsafe_allow_html=True)
    if not messages:
        with st.chat_message("assistant"):
            st.write(
                "Tell me what is happening today: deadlines, energy, time, blockers, "
                "or what you are avoiding. I will give a direct next action and "
                "propose changes for later confirmation."
            )
    else:
        for message in messages:
            render_ai_boss_chat_message(message)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Clear Chat History", expanded=False):
        st.warning("This deletes local chat messages only. It does not delete tasks, reviews, memories, or Quercus data.")
        confirm_clear = st.checkbox("I understand this will clear local chat history.")
        if st.button("Clear Chat History", disabled=not confirm_clear):
            deleted = clear_chat_history()
            st.success(f"Cleared {deleted} chat messages.")
            st.rerun()


def render_task_fields(task):
    first_row = st.columns(4)
    render_detail_field(first_row[0], "Course", task.get("course"))
    render_detail_field(first_row[1], "Type", task.get("task_type"))
    render_detail_field(first_row[2], "Due", task.get("due_at"), display_task_datetime)
    render_detail_field(
        first_row[3],
        "Planned",
        task.get("planned_date"),
        display_task_datetime,
    )

    second_row = st.columns(4)
    render_detail_field(second_row[0], "Minutes", task.get("estimated_minutes"))
    render_detail_field(second_row[1], "Priority", task.get("priority"))
    render_detail_field(second_row[2], "Status", task.get("status"))
    render_detail_field(second_row[3], "Notes", task.get("notes"))

    urgency_score, urgency_label = task_urgency(task)
    urgency_row = st.columns(3)
    render_detail_field(urgency_row[0], "Urgency", urgency_label)
    render_detail_field(urgency_row[1], "Urgency Score", f"{urgency_score:.1f}")
    render_detail_field(urgency_row[2], "Needs Review", task.get("needs_review"))

    has_extraction_fields = (
        task.get("source") not in (None, "", "manual")
        or task.get("confidence")
        or task.get("source_snippet")
    )
    if has_extraction_fields:
        third_row = st.columns(3)
        render_detail_field(third_row[0], "Source", task.get("source"))
        render_detail_field(third_row[1], "Confidence", task.get("confidence"))
        render_detail_field(third_row[2], "Source Snippet", task.get("source_snippet"))

    behavior_fields = [
        task.get("first_action"),
        task.get("next_action"),
        task.get("behavior_prompt"),
        task.get("energy_level"),
        task.get("emotional_friction"),
        task.get("avoidance_risk"),
    ]
    if any(behavior_fields):
        st.markdown("**Behavior Design**")
        if task.get("first_action"):
            render_detail_field(st, "First action", task["first_action"])
        if task.get("next_action"):
            render_detail_field(st, "Next 25 minutes", task["next_action"])

        behavior_row = st.columns(4)
        render_detail_field(behavior_row[0], "Energy", task.get("energy_level"))
        render_detail_field(behavior_row[1], "Load", task.get("cognitive_load"))
        render_detail_field(
            behavior_row[2],
            "Friction",
            task.get("emotional_friction"),
        )
        render_detail_field(
            behavior_row[3],
            "Avoidance",
            task.get("avoidance_risk"),
        )
        if task.get("behavior_prompt"):
            render_detail_field(st, "Prompt", task["behavior_prompt"])


def render_status_actions(task, current_view):
    actions = STATUS_ACTIONS.get(task["status"], [])
    if not actions:
        return

    st.markdown("**Actions**")
    action_columns = st.columns(len(actions))
    key_prefix = f"{view_key(current_view)}-{task['id']}"

    for index, (label, next_status) in enumerate(actions):
        with action_columns[index]:
            if st.button(label, key=f"{key_prefix}-{next_status}"):
                update_task_status(task["id"], next_status)
                st.session_state.status_update_message = (
                    f"Updated '{task['title']}' to {next_status}."
                )
                st.rerun()


def can_focus_task(task):
    return task.get("status") not in ("done", "ignored")


def start_focus_session_for_task(task, planned_minutes=25):
    session_id = create_study_session_start(
        task["id"],
        task["title"],
        task.get("course"),
        planned_minutes,
    )
    if task.get("status") != "in_progress":
        update_task_status(task["id"], "in_progress")
    return session_id


def render_focus_action(task, current_view, button_type="secondary"):
    if not can_focus_task(task):
        return

    active_session = get_active_study_session()
    if active_session:
        st.caption("A focus session is already active.")
        return

    if st.button(
        "Start Focus",
        key=f"{view_key(current_view)}-{task['id']}-start-focus",
        type=button_type,
    ):
        try:
            start_focus_session_for_task(task)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.status_update_message = (
                f"Started a focus session for '{task['title']}'."
            )
            st.rerun()


def render_task_cards(tasks, current_view):
    if not tasks:
        st.info(empty_message_for_view(current_view))
        return

    for task in tasks:
        urgency_score, urgency_label = task_urgency(task)
        with st.container(border=True):
            st.markdown(
                (
                    '<div class="task-title-row">'
                    f'<h4>{escape_html(task["title"])}</h4>'
                    f'{urgency_badge_html(urgency_label)}'
                    '</div>'
                    f'<div class="task-card-meta">{escape_html(task_meta_line(task))}</div>'
                    f'<div class="calm-first-action">{escape_html(first_action_for_task(task))}</div>'
                ),
                unsafe_allow_html=True,
            )
            render_focus_action(task, current_view)
            with st.expander("Details"):
                indicators = task_indicators(task)
                if indicators:
                    st.caption(" | ".join(f"[{indicator}]" for indicator in indicators))
                st.caption(f"Urgency score: {urgency_score:.1f}")
                render_task_fields(task)
                render_status_actions(task, current_view)


def render_add_task_form():
    st.subheader("Add a New Task")
    with st.form("task_form"):
        title = st.text_input("Task Title", max_chars=100)
        course = st.text_input("Course Name")
        task_type = st.text_input("Task Type")
        due_at = st.date_input("Due Date")
        planned_date = st.date_input("Planned Date")
        estimated_minutes = st.number_input(
            "Estimated Minutes",
            min_value=1,
            value=60,
            step=15,
        )
        priority = st.slider("Priority (1 = lowest, 5 = highest)", 1, 5, value=3)
        notes = st.text_area("Additional Notes")
        submitted = st.form_submit_button("Submit")

        if submitted:
            task = {
                "title": title,
                "course": course,
                "task_type": task_type,
                "due_at": due_at,
                "planned_date": planned_date,
                "estimated_minutes": estimated_minutes,
                "priority": priority,
                "notes": notes,
            }
            try:
                create_task(task)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Task added successfully!")


def render_dashboard_view(view_name):
    st.subheader(view_name)
    tasks = sort_tasks_for_dashboard(get_tasks_for_view(view_name), view_name)
    render_task_cards(tasks, view_name)


def render_today_plan():
    st.subheader("Today Plan")
    recommendations = generate_today_plan(get_all_tasks(), max_tasks=3)

    if not recommendations:
        st.info("No active tasks to recommend for today.")
        return

    for index, recommendation in enumerate(recommendations, start=1):
        task = recommendation["task"]
        urgency_score, urgency_label = task_urgency(task)
        with st.container(border=True):
            st.markdown(f"### {index}. {display_value(task['title'])}")
            st.markdown(f"**Course:** {display_value(task['course'])}")
            st.markdown(
                f"**Estimated:** {display_value(task['estimated_minutes'])} min"
            )
            st.markdown(f"**Date:** {display_date(task)}")
            st.markdown(f"**Priority:** {display_value(task['priority'])}")
            st.markdown(f"**Status:** {display_value(task['status'])}")
            st.markdown(
                f"**Urgency:** {display_value(urgency_label)} "
                f"({urgency_score:.1f})"
            )
            st.markdown(f"**Reason:** {recommendation['reason']}")


def task_lookup_by_id(tasks):
    return {str(task["id"]): task for task in tasks if task.get("id") is not None}


def current_ai_boss_context():
    tasks = get_all_tasks()
    today_plan = generate_today_plan(tasks, max_tasks=3)
    recent_sessions = get_recent_study_sessions(limit=20)
    recent_reviews = get_recent_daily_reviews(limit=7)
    memories = get_active_agent_memory()

    context = build_ai_boss_context(
        tasks=tasks,
        today_plan=today_plan,
        recent_study_sessions=recent_sessions,
        recent_daily_reviews=recent_reviews,
        active_memories=memories,
        current_date=date.today().isoformat(),
    )
    return context, tasks


def parse_saved_ai_boss_briefing(record):
    if not record or not record.get("output_json"):
        return None

    try:
        return json.loads(record["output_json"])
    except json.JSONDecodeError:
        return None


def render_ai_boss_status(context):
    st.markdown("### Status")
    key_present = has_openai_api_key()
    st.markdown(f"**OPENAI_API_KEY configured:** {'Yes' if key_present else 'No'}")
    if not key_present:
        st.warning(
            "Add OPENAI_API_KEY to your .env file to generate an AI Boss briefing."
        )

    counts = context["counts"]
    columns = st.columns(4)
    columns[0].metric("Active Tasks", counts["active_tasks"])
    columns[1].metric("Study Sessions", counts["recent_study_sessions"])
    columns[2].metric("Daily Reviews", counts["recent_daily_reviews"])
    columns[3].metric("Active Memories", counts["active_memories"])


def render_ai_boss_task_card(task, task_lookup):
    task_id = task.get("task_id")
    existing_task = task_lookup.get(str(task_id)) if task_id else None

    with st.container(border=True):
        st.markdown(f"#### {display_value(task.get('title'))}")
        columns = st.columns(3)
        columns[0].markdown(f"**Course**  \n{display_value(task.get('course'))}")
        columns[1].markdown(
            "**Estimated**  \n"
            f"{display_value(task.get('estimated_minutes'))} min"
        )
        columns[2].markdown(f"**Task ID**  \n{display_value(task_id)}")

        if existing_task:
            columns = st.columns(3)
            columns[0].markdown(
                f"**Current Status**  \n{display_value(existing_task.get('status'))}"
            )
            columns[1].markdown(
                f"**Due**  \n{display_task_datetime(existing_task.get('due_at'))}"
            )
            columns[2].markdown(
                "**Planned**  \n"
                f"{display_task_datetime(existing_task.get('planned_date'))}"
            )

        st.markdown(f"**Reason**  \n{display_value(task.get('reason'))}")
        st.markdown(
            f"**First action**  \n{display_value(task.get('first_action'))}"
        )


def render_ai_boss_briefing(briefing, task_lookup):
    if not briefing:
        st.info("No AI Boss briefing to display yet.")
        return

    st.markdown("### Executive Summary")
    st.write(display_value(briefing.get("executive_summary")))

    st.markdown("### Top Tasks")
    top_tasks = briefing.get("top_tasks") or []
    if not top_tasks:
        st.info("No top tasks were returned.")
    for task in top_tasks[:3]:
        render_ai_boss_task_card(task, task_lookup)

    st.markdown("### First 25-Minute Action")
    st.write(display_value(briefing.get("first_25_minute_action")))

    avoid_doing = briefing.get("avoid_doing") or []
    if avoid_doing:
        st.markdown("### Avoid Doing")
        for item in avoid_doing:
            st.markdown(f"- {display_value(item)}")

    if briefing.get("avoidance_warning"):
        st.markdown("### Avoidance Warning")
        st.warning(briefing["avoidance_warning"])

    st.markdown("### Schedule Advice")
    st.write(display_value(briefing.get("schedule_advice")))

    st.markdown("### End-of-Day Check-In")
    st.write(display_value(briefing.get("end_of_day_check_in_question")))


def render_ai_boss_generate(context, task_lookup):
    st.markdown("### Generate Briefing")
    st.caption(
        "AI Boss only reads the compact local context shown by this page. "
        "It does not update tasks or touch Quercus."
    )

    key_present = has_openai_api_key()
    if st.button("Generate AI Boss Briefing", disabled=not key_present):
        with st.spinner("Generating AI Boss briefing..."):
            try:
                briefing = generate_ai_boss_briefing(context)
                raw_response = briefing.get("_raw_response")
                briefing_for_save = {
                    key: value for key, value in briefing.items()
                    if key != "_raw_response"
                }
                save_ai_boss_briefing(
                    briefing_date=context["current_date"],
                    input_summary_json=json.dumps(context, ensure_ascii=False),
                    output_json=json.dumps(briefing_for_save, ensure_ascii=False),
                    raw_response=raw_response,
                )
            except AIBossConfigError as error:
                st.error(str(error))
                return
            except AIBossResponseError as error:
                st.error(str(error))
                if error.raw_response:
                    st.text_area(
                        "Raw AI response",
                        value=error.raw_response,
                        height=240,
                    )
                return
            except Exception as error:
                st.error(f"Could not generate AI Boss briefing: {error}")
                return

        st.success("AI Boss briefing saved.")
        render_ai_boss_briefing(briefing_for_save, task_lookup)


def render_latest_ai_boss_briefing(task_lookup):
    st.markdown("### Latest Briefing")
    latest = get_latest_ai_boss_briefing(date.today().isoformat())
    if not latest:
        st.info("No AI Boss briefing saved for today yet.")
        return

    st.caption(
        f"Saved {display_datetime(latest['created_at'])} "
        f"for {latest['briefing_date']}."
    )
    briefing = parse_saved_ai_boss_briefing(latest)
    if not briefing:
        st.warning("The latest saved AI Boss briefing could not be parsed.")
        return
    render_ai_boss_briefing(briefing, task_lookup)


def render_recent_ai_boss_briefings():
    st.markdown("### Recent Briefings")
    briefings = get_recent_ai_boss_briefings(limit=7)
    if not briefings:
        st.info("No saved AI Boss briefings yet.")
        return

    for record in briefings:
        briefing = parse_saved_ai_boss_briefing(record)
        title = (
            f"{record['briefing_date']} - "
            f"{display_datetime(record['created_at'])}"
        )
        with st.expander(title):
            if not briefing:
                st.warning("This saved briefing could not be parsed.")
                continue
            st.markdown(f"**Summary**  \n{display_value(briefing.get('executive_summary'))}")
            st.markdown(
                "**First 25-minute action**  \n"
                f"{display_value(briefing.get('first_25_minute_action'))}"
            )


def render_ai_boss():
    st.subheader("AI Boss")
    st.info(
        "AI Boss v0 generates a daily execution briefing from your local tasks, "
        "Today Plan, focus sessions, daily reviews, and active agent memories. "
        "It can suggest priorities, but it does not automatically change tasks."
    )

    context, tasks = current_ai_boss_context()
    task_lookup = task_lookup_by_id(tasks)

    render_ai_boss_status(context)
    render_ai_boss_generate(context, task_lookup)
    render_latest_ai_boss_briefing(task_lookup)
    render_recent_ai_boss_briefings()


def parse_saved_behavior_plan(record):
    if not record or not record.get("output_json"):
        return None

    try:
        return json.loads(record["output_json"])
    except json.JSONDecodeError:
        return None


def current_behavior_design_context(plan_date, user_checkin_text=None):
    tasks = get_all_tasks()
    command_day = datetime.strptime(plan_date, "%Y-%m-%d").date()
    today_plan = generate_today_plan(tasks, max_tasks=3, today=command_day)
    ai_boss_record = get_latest_ai_boss_briefing(plan_date)
    ai_boss_briefing = parse_saved_ai_boss_briefing(ai_boss_record)
    recent_sessions = get_recent_study_sessions(limit=20)
    recent_reviews = get_recent_daily_reviews(limit=7)
    memories = get_active_agent_memory()

    context = build_behavior_design_context(
        tasks=tasks,
        today_plan=today_plan,
        ai_boss_briefing=ai_boss_briefing,
        recent_focus_sessions=recent_sessions,
        recent_daily_reviews=recent_reviews,
        active_memories=memories,
        current_date=plan_date,
        user_checkin_text=user_checkin_text,
    )
    return context, tasks


def behavior_plan_for_save(plan):
    return {
        key: value for key, value in plan.items()
        if key != "_raw_response"
    }


def save_behavior_plan(plan, context):
    raw_response = plan.get("_raw_response")
    plan_for_save = behavior_plan_for_save(plan)
    if_then_plans = [
        {
            "task_id": task.get("task_id"),
            "title": task.get("title"),
            "if_then_plan": task.get("if_then_plan"),
        }
        for task in plan_for_save.get("top_tasks", [])
    ]
    return create_or_update_behavior_plan({
        "plan_date": context["current_date"],
        "source": "behavior_design",
        "main_objective": plan_for_save.get("main_objective"),
        "full_plan_json": plan_for_save.get("top_tasks"),
        "minimum_viable_day_json": plan_for_save.get("minimum_viable_day"),
        "if_then_plans_json": if_then_plans,
        "woop_json": plan_for_save.get("woop"),
        "avoidance_warning": plan_for_save.get("avoidance_warning"),
        "planning_cap_minutes": plan_for_save.get("planning_cap_minutes"),
        "output_json": plan_for_save,
        "raw_response": raw_response,
    })


def render_behavior_task_card(task_plan, task_lookup, key_prefix):
    task_id = task_plan.get("task_id")
    existing_task = task_lookup.get(str(task_id)) if task_id else None

    with st.container(border=True):
        st.markdown(f"#### {display_value(task_plan.get('title'))}")
        columns = st.columns(4)
        columns[0].markdown(f"**Course**  \n{display_value(task_plan.get('course'))}")
        columns[1].markdown(
            f"**Energy**  \n{display_value(task_plan.get('energy_level'))}"
        )
        columns[2].markdown(
            f"**Load**  \n{display_value(task_plan.get('cognitive_load'))}"
        )
        columns[3].markdown(
            "**Avoidance**  \n"
            f"{display_value(task_plan.get('avoidance_risk'))}"
        )

        if existing_task:
            columns = st.columns(3)
            columns[0].markdown(
                f"**Status**  \n{display_value(existing_task.get('status'))}"
            )
            columns[1].markdown(
                f"**Due**  \n{display_task_datetime(existing_task.get('due_at'))}"
            )
            columns[2].markdown(
                f"**Urgency**  \n{display_value(existing_task.get('urgency_label'))}"
            )

        st.markdown(
            f"**Why this matters**  \n"
            f"{display_value(task_plan.get('why_this_matters'))}"
        )
        st.markdown(
            "**First action under 5 min**  \n"
            f"{display_value(task_plan.get('first_action_under_5_min'))}"
        )
        st.markdown(
            "**First 25-minute block**  \n"
            f"{display_value(task_plan.get('first_25_minute_block'))}"
        )
        st.markdown(
            f"**Stop condition**  \n{display_value(task_plan.get('stop_condition'))}"
        )
        st.markdown(
            f"**Likely obstacle**  \n{display_value(task_plan.get('likely_obstacle'))}"
        )
        if_then = task_plan.get("if_then_plan") or {}
        st.markdown(
            f"**If-then plan**  \nIf {display_value(if_then.get('if'))}, "
            f"then {display_value(if_then.get('then'))}."
        )

        if task_id and existing_task:
            if st.button(
                "Apply Behavior Design to Task",
                key=f"{key_prefix}-apply-behavior-{task_id}",
            ):
                update_task_behavior_fields(
                    task_id,
                    behavior_updates_for_task(task_plan),
                )
                st.success("Behavior fields applied to the task.")
                st.rerun()
        elif task_id:
            st.warning("This task id was not found in the current task list.")


def render_behavior_plan(plan, task_lookup, key_prefix="behavior-plan"):
    if not plan:
        st.info("No Behavior Design Plan to display yet.")
        return

    st.markdown("### Main Objective")
    st.write(display_value(plan.get("main_objective")))

    columns = st.columns(2)
    columns[0].metric("Planning Cap", f"{plan.get('planning_cap_minutes') or '-'} min")
    columns[1].metric("Mode", display_value(plan.get("mode")))

    st.markdown("### Top Tasks")
    top_tasks = plan.get("top_tasks") or []
    if not top_tasks:
        st.info("No behavior-designed tasks were returned.")
    for index, task_plan in enumerate(top_tasks[:3], start=1):
        render_behavior_task_card(
            task_plan,
            task_lookup,
            key_prefix=f"{key_prefix}-{index}",
        )

    woop = plan.get("woop") or {}
    st.markdown("### WOOP")
    woop_columns = st.columns(2)
    woop_columns[0].markdown(f"**Wish**  \n{display_value(woop.get('wish'))}")
    woop_columns[1].markdown(f"**Outcome**  \n{display_value(woop.get('outcome'))}")
    woop_columns = st.columns(2)
    woop_columns[0].markdown(
        f"**Obstacle**  \n{display_value(woop.get('obstacle'))}"
    )
    woop_columns[1].markdown(f"**Plan**  \n{display_value(woop.get('plan'))}")

    minimum_day = plan.get("minimum_viable_day") or {}
    st.markdown("### Minimum Viable Day")
    required = minimum_day.get("required") or []
    optional = minimum_day.get("optional") or []
    if required:
        st.markdown("**Required**")
        for item in required:
            st.markdown(f"- {display_value(item)}")
    if optional:
        st.markdown("**Optional**")
        for item in optional:
            st.markdown(f"- {display_value(item)}")
    st.markdown(
        "**Definition of success**  \n"
        f"{display_value(minimum_day.get('definition_of_success'))}"
    )

    avoid_items = plan.get("do_not_do_today") or []
    if avoid_items:
        st.markdown("### Do Not Do Today")
        for item in avoid_items:
            st.markdown(f"- {display_value(item)}")

    if plan.get("avoidance_warning"):
        st.markdown("### Avoidance Warning")
        st.warning(plan["avoidance_warning"])

    st.markdown("### End-of-Day Review Question")
    st.write(display_value(plan.get("end_of_day_review_question")))


def render_behavior_memory_candidates(plan, key_prefix="behavior-memory"):
    candidates = plan.get("memory_candidates") if plan else []
    if not candidates:
        return

    st.markdown("### Memory Candidates")
    st.caption("These are not saved automatically. Save only the ones you want.")
    for index, candidate in enumerate(candidates, start=1):
        with st.container(border=True):
            st.markdown(
                f"#### {display_value(candidate.get('memory_type'))}: "
                f"{display_value(candidate.get('memory_key'))}"
            )
            st.markdown(display_value(candidate.get("memory_value")))
            columns = st.columns(2)
            columns[0].markdown(
                f"**Confidence**  \n{display_value(candidate.get('confidence'))}"
            )
            columns[1].markdown(
                f"**Source**  \n{display_value(candidate.get('source'))}"
            )

            memory_type = candidate.get("memory_type") or "other"
            memory_key = candidate.get("memory_key")
            if memory_key and memory_exists(memory_type, memory_key):
                st.caption("This memory already exists.")
                continue

            columns = st.columns(2)
            with columns[0]:
                if st.button(
                    "Save to Agent Memory",
                    key=f"{key_prefix}-save-{index}",
                ):
                    create_agent_memory({
                        "memory_type": candidate.get("memory_type"),
                        "memory_key": candidate.get("memory_key"),
                        "memory_value": candidate.get("memory_value"),
                        "confidence": candidate.get("confidence") or "medium",
                        "source": candidate.get("source") or "behavior_design",
                        "is_active": 1,
                    })
                    st.success("Memory saved.")
                    st.rerun()
            with columns[1]:
                if st.button("Ignore", key=f"{key_prefix}-ignore-{index}"):
                    st.info("Ignored for this view. Nothing was saved.")


def render_behavior_generate(
    plan_date,
    user_checkin_text,
    key_prefix,
    button_label="Generate Behavior Design Plan",
):
    key_present = has_behavior_design_api_key()
    if not key_present:
        st.warning("Add OPENAI_API_KEY to your .env file to use Behavior Design.")

    if st.button(
        button_label,
        disabled=not key_present,
        key=f"{key_prefix}-generate",
    ):
        context, _ = current_behavior_design_context(plan_date, user_checkin_text)
        with st.spinner("Designing first actions..."):
            try:
                plan = generate_behavior_design_plan(context)
                save_behavior_plan(plan, context)
            except BehaviorDesignConfigError as error:
                st.error(str(error))
                return None
            except BehaviorDesignResponseError as error:
                st.error(str(error))
                if error.raw_response:
                    st.text_area(
                        "Raw AI response",
                        value=error.raw_response,
                        height=240,
                    )
                return None
            except Exception as error:
                st.error(f"Could not generate Behavior Design Plan: {error}")
                return None

        st.success("Behavior Design Plan saved.")
        return behavior_plan_for_save(plan)

    return None


def render_latest_behavior_plan(plan_date, task_lookup, key_prefix):
    latest = get_behavior_plan_by_date(plan_date)
    if not latest:
        st.info("No Behavior Design Plan saved for this date yet.")
        return None

    st.caption(
        f"Saved {display_datetime(latest['updated_at'])} for {latest['plan_date']}."
    )
    plan = parse_saved_behavior_plan(latest)
    if not plan:
        st.warning("The latest saved Behavior Design Plan could not be parsed.")
        return None

    render_behavior_plan(plan, task_lookup, key_prefix=key_prefix)
    render_behavior_memory_candidates(plan, key_prefix=f"{key_prefix}-memory")
    return plan


def render_recent_behavior_plans():
    st.markdown("### Recent Behavior Plans")
    plans = get_recent_behavior_plans(limit=7)
    if not plans:
        st.info("No saved Behavior Design Plans yet.")
        return

    for record in plans:
        plan = parse_saved_behavior_plan(record)
        title = (
            f"{record['plan_date']} - "
            f"{display_datetime(record['updated_at'])}"
        )
        with st.expander(title):
            if not plan:
                st.warning("This saved behavior plan could not be parsed.")
                continue
            st.markdown(
                f"**Objective**  \n{display_value(plan.get('main_objective'))}"
            )
            st.markdown(
                "**Minimum viable day**  \n"
                f"{display_value((plan.get('minimum_viable_day') or {}).get('definition_of_success'))}"
            )


def render_behavior_design():
    st.subheader("Behavior Design")
    st.info(
        "Behavior Design turns the plan into easier starting behaviors: first "
        "actions under 5 minutes, 25-minute blocks, if-then recovery plans, "
        "WOOP obstacle planning, and a minimum viable day. It does not update "
        "task status."
    )

    selected_date = st.date_input("Behavior plan date", value=date.today())
    plan_date = selected_date.isoformat()
    user_checkin_text = st.text_area(
        "Tell the AI Boss your current state",
        placeholder=(
            "Example: I have 2 hours, low energy, gym at 6pm, and I am "
            "avoiding STA457 because it feels unclear."
        ),
        height=120,
    )

    context, tasks = current_behavior_design_context(plan_date, user_checkin_text)
    task_lookup = task_lookup_by_id(tasks)

    st.markdown("### Status")
    columns = st.columns(5)
    columns[0].metric("Active Tasks", context["counts"]["active_tasks"])
    columns[1].metric("Today Tasks", context["counts"]["today_relevant_tasks"])
    columns[2].metric("Focus Sessions", context["counts"]["recent_focus_sessions"])
    columns[3].metric("Reviews", context["counts"]["recent_daily_reviews"])
    columns[4].metric("Avoidance Signals", context["counts"]["avoidance_signals"])

    generated_plan = render_behavior_generate(
        plan_date,
        user_checkin_text,
        key_prefix="behavior-page",
    )
    if generated_plan:
        render_behavior_plan(
            generated_plan,
            task_lookup,
            key_prefix="behavior-page-generated",
        )
        render_behavior_memory_candidates(
            generated_plan,
            key_prefix="behavior-page-generated-memory",
        )

    st.markdown("### Latest Behavior Plan")
    render_latest_behavior_plan(plan_date, task_lookup, key_prefix="behavior-page-latest")
    render_recent_behavior_plans()


def compact_proposal_dict(values):
    return {
        key: value for key, value in values.items()
        if value not in (None, "", [])
    }


def append_text(existing, addition):
    existing = str(existing or "").strip()
    addition = str(addition or "").strip()
    if not addition:
        return existing or None
    if not existing:
        return addition
    if addition.casefold() in existing.casefold():
        return existing
    return f"{existing}\n{addition}"


def merge_checkin_with_updates(command_date, updates):
    existing = get_morning_checkin_by_date(command_date) or {}
    merged = {
        "checkin_date": command_date,
        "available_study_minutes": existing.get("available_study_minutes"),
        "available_time_blocks": existing.get("available_time_blocks"),
        "fixed_commitments": existing.get("fixed_commitments"),
        "extra_commitments": existing.get("extra_commitments"),
        "sleep_quality": existing.get("sleep_quality"),
        "energy_level": existing.get("energy_level"),
        "stress_level": existing.get("stress_level"),
        "mood": existing.get("mood"),
        "top_personal_priority": existing.get("top_personal_priority"),
        "avoiding_task": existing.get("avoiding_task"),
        "hard_stop_time": existing.get("hard_stop_time"),
        "notes": existing.get("notes"),
    }
    append_fields = {
        "available_time_blocks",
        "fixed_commitments",
        "extra_commitments",
        "notes",
    }
    for key, value in updates.items():
        if value in (None, ""):
            continue
        if key in append_fields:
            merged[key] = append_text(merged.get(key), value)
        else:
            merged[key] = value
    return create_or_update_morning_checkin(merged)


def merge_daily_review_with_update(command_date, updates):
    existing = get_daily_review_by_date(command_date) or {}
    merged = {
        "review_date": command_date,
        "completed_summary": existing.get("completed_summary"),
        "missed_tasks": existing.get("missed_tasks"),
        "blockers": existing.get("blockers"),
        "avoidance_notes": existing.get("avoidance_notes"),
        "tomorrow_top_priority": existing.get("tomorrow_top_priority"),
        "mood_energy": existing.get("mood_energy"),
        "focus_rating": existing.get("focus_rating"),
    }
    append_fields = {
        "completed_summary",
        "missed_tasks",
        "blockers",
        "avoidance_notes",
    }
    for key, value in updates.items():
        if value in (None, ""):
            continue
        if key in append_fields:
            merged[key] = append_text(merged.get(key), value)
        else:
            merged[key] = value
    return create_or_update_daily_review(merged)


def proposal_has_content(proposal):
    if not proposal:
        return False
    morning_updates = compact_proposal_dict(
        proposal.get("morning_checkin_updates") or {}
    )
    daily_review_update = compact_proposal_dict(
        proposal.get("daily_review_update") or {}
    )
    return any([
        morning_updates,
        proposal.get("personal_commitments"),
        daily_review_update,
        proposal.get("memory_candidates"),
    ])


def apply_confirmable_action(action):
    action_type = action.get("action_type")
    payload = action.get("payload") or {}

    if action.get("status") != "ready":
        return "skipped"

    if action_type == "update_morning_checkin":
        merge_checkin_with_updates(
            payload.get("command_date"),
            payload.get("updates") or {},
        )
        return "applied"

    if action_type == "create_personal_commitment":
        commitment = payload.get("commitment") or {}
        create_personal_commitment({
            "title": commitment.get("title"),
            "commitment_type": commitment.get("commitment_type") or "other",
            "planned_date": commitment.get("planned_date") or payload.get("command_date"),
            "start_time": commitment.get("start_time"),
            "estimated_minutes": commitment.get("estimated_minutes"),
            "priority": commitment.get("priority") or 3,
            "status": "planned",
            "notes": commitment.get("notes"),
        })
        return "applied"

    if action_type == "update_daily_review":
        merge_daily_review_with_update(
            payload.get("command_date"),
            payload.get("updates") or {},
        )
        return "applied"

    if action_type == "update_task_status":
        task_id = payload.get("task_id")
        suggested_status = payload.get("suggested_status")
        if not task_id or not suggested_status:
            return "skipped"
        update_task_status(task_id, suggested_status)
        return "applied"

    if action_type == "create_memory_candidate":
        candidate = payload.get("candidate") or {}
        candidate_id = create_agent_memory_candidate({
            "memory_type": candidate.get("memory_type"),
            "memory_key": candidate.get("memory_key"),
            "memory_value": candidate.get("memory_value"),
            "confidence": candidate.get("confidence") or "medium",
            "source": "command_center",
            "evidence_json": json.dumps({
                "source": "command_center",
                "evidence": candidate.get("evidence"),
                "command_date": payload.get("command_date"),
            }, ensure_ascii=False),
            "decision_status": "pending",
        })
        return "applied" if candidate_id else "duplicate"

    return "skipped"


def apply_selected_actions(actions, selected_action_ids):
    selected_action_ids = set(selected_action_ids)
    result = {
        "applied": 0,
        "skipped": 0,
        "duplicates": 0,
    }
    for action in actions:
        if action["id"] not in selected_action_ids:
            continue
        status = apply_confirmable_action(action)
        if status == "applied":
            result["applied"] += 1
        elif status == "duplicate":
            result["duplicates"] += 1
        else:
            result["skipped"] += 1
    return result


def render_action_payload_preview(action):
    payload = action.get("payload") or {}
    action_type = action.get("action_type")

    if action_type == "update_morning_checkin":
        for key, value in (payload.get("updates") or {}).items():
            st.markdown(f"- **{key}:** {display_value(value)}")
    elif action_type == "create_personal_commitment":
        commitment = payload.get("commitment") or {}
        for key in ("title", "commitment_type", "planned_date", "start_time", "estimated_minutes"):
            st.markdown(f"- **{key}:** {display_value(commitment.get(key))}")
    elif action_type == "update_daily_review":
        for key, value in (payload.get("updates") or {}).items():
            st.markdown(f"- **{key}:** {display_value(value)}")
    elif action_type == "update_task_status":
        st.markdown(
            f"- **Task:** {display_value(payload.get('resolved_task_title') or payload.get('suggestion', {}).get('title'))}"
        )
        st.markdown(f"- **New status:** {display_value(payload.get('suggested_status'))}")
    elif action_type == "create_memory_candidate":
        candidate = payload.get("candidate") or {}
        st.markdown(f"- **Type:** {display_value(candidate.get('memory_type'))}")
        st.markdown(f"- **Key:** {display_value(candidate.get('memory_key'))}")
        st.markdown(f"- **Value:** {display_value(candidate.get('memory_value'))}")


def render_confirmable_actions(command_date, proposal):
    actions = build_confirmable_actions(proposal, command_date, get_all_tasks())
    st.markdown("### Confirmable Actions")
    if not actions:
        st.info("No database actions were proposed. Answer any clarification questions above.")
        return actions, []

    ready_count = count_ready_actions(actions)
    st.caption(
        f"{ready_count} action(s) are ready to apply. "
        "Actions that need attention are shown but disabled."
    )

    selected_action_ids = []
    with st.form("confirmable_actions_form"):
        for action in actions:
            ready = action.get("status") == "ready"
            with st.container(border=True):
                selected = st.checkbox(
                    action["label"],
                    value=ready,
                    disabled=not ready,
                    key=f"action-select-{action['id']}",
                )
                if selected and ready:
                    selected_action_ids.append(action["id"])

                if action.get("reason"):
                    st.caption(action["reason"])
                if not ready:
                    st.warning("Needs attention before it can be applied.")
                render_action_payload_preview(action)

        submitted = st.form_submit_button(
            "Apply Selected Actions",
            disabled=ready_count == 0,
        )

    return actions, selected_action_ids if submitted else None


def proposal_field_rows(values):
    return compact_proposal_dict(values or {}).items()


def render_conversation_proposal(proposal):
    if not proposal:
        return

    st.markdown("### AI Proposal")
    st.markdown(f"**Summary**  \n{display_value(proposal.get('summary'))}")
    st.markdown(f"**Confidence**  \n{display_value(proposal.get('confidence'))}")

    morning_updates = list(proposal_field_rows(
        proposal.get("morning_checkin_updates")
    ))
    if morning_updates:
        st.markdown("#### Morning Check-In Updates")
        for key, value in morning_updates:
            st.markdown(f"- **{key}:** {display_value(value)}")

    commitments = proposal.get("personal_commitments") or []
    if commitments:
        st.markdown("#### Personal Commitments")
        for commitment in commitments:
            with st.container(border=True):
                st.markdown(f"**{display_value(commitment.get('title'))}**")
                columns = st.columns(4)
                columns[0].markdown(
                    f"**Type**  \n{display_value(commitment.get('commitment_type'))}"
                )
                columns[1].markdown(
                    f"**Date**  \n{display_value(commitment.get('planned_date'))}"
                )
                columns[2].markdown(
                    f"**Start**  \n{display_value(commitment.get('start_time'))}"
                )
                columns[3].markdown(
                    "**Minutes**  \n"
                    f"{display_value(commitment.get('estimated_minutes'))}"
                )
                st.markdown(f"**Notes**  \n{display_value(commitment.get('notes'))}")

    daily_review_update = list(proposal_field_rows(
        proposal.get("daily_review_update")
    ))
    if daily_review_update:
        st.markdown("#### Daily Review Update")
        for key, value in daily_review_update:
            st.markdown(f"- **{key}:** {display_value(value)}")

    status_suggestions = proposal.get("task_status_suggestions") or []
    if status_suggestions:
        st.markdown("#### Task Status Suggestions")
        st.caption("These are suggestions only. They are not applied automatically.")
        for suggestion in status_suggestions:
            with st.container(border=True):
                st.markdown(f"**{display_value(suggestion.get('title'))}**")
                st.markdown(
                    "**Suggested status**  \n"
                    f"{display_value(suggestion.get('suggested_status'))}"
                )
                st.markdown(f"**Reason**  \n{display_value(suggestion.get('reason'))}")

    memory_candidates = proposal.get("memory_candidates") or []
    if memory_candidates:
        st.markdown("#### Memory Candidates")
        st.caption("These become pending memory candidates, not active memory.")
        for candidate in memory_candidates:
            with st.container(border=True):
                st.markdown(
                    f"**{display_value(candidate.get('memory_type'))}: "
                    f"{display_value(candidate.get('memory_key'))}**"
                )
                st.markdown(display_value(candidate.get("memory_value")))
                st.caption(display_value(candidate.get("evidence")))

    questions = proposal.get("clarification_questions") or []
    if questions:
        st.markdown("#### Clarification Questions")
        for question in questions:
            st.markdown(f"- {display_value(question)}")


def command_center_plan_snapshot(command_date):
    latest = get_latest_daily_command(command_date)
    command = parse_saved_daily_command(latest) if latest else None
    behavior_record = get_behavior_plan_by_date(command_date)
    behavior_plan = parse_saved_behavior_plan(behavior_record)
    return command, behavior_plan


def behavior_first_task(behavior_plan):
    if not behavior_plan:
        return None
    tasks = behavior_plan.get("top_tasks") or []
    return tasks[0] if tasks else None


def render_minimum_viable_day(behavior_plan):
    if not behavior_plan:
        return

    minimum_day = behavior_plan.get("minimum_viable_day") or {}
    required = minimum_day.get("required") or []
    definition = minimum_day.get("definition_of_success")
    if not required and not definition:
        return

    with st.expander("Minimum Viable Day", expanded=False):
        for item in required[:4]:
            st.markdown(f"- {display_value(item)}")
        if definition:
            st.caption(f"Success: {definition}")


def render_timeline_entry(entry, compact=False, key_prefix="timeline"):
    task = entry["task"]
    urgency_score, urgency_label = task_urgency(task)
    badge = urgency_badge_html(urgency_label)
    kind = entry.get("kind") or "task"
    css_label = re.sub(r"[^a-z0-9_]+", "_", str(urgency_label).lower())

    st.markdown(
        (
            f'<div class="timeline-item timeline-item-{css_label}">'
            '<div class="task-title-row">'
            f'<div class="timeline-title">{escape_html(task.get("title"))}</div>'
            f'{badge}'
            '</div>'
            f'<div class="task-card-meta">{escape_html(kind.title())} | '
            f'{escape_html(task_meta_line(task))}</div>'
            f'<div class="calm-first-action">{escape_html(first_action_for_task(task))}</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    if not compact:
        with st.expander("Details"):
            st.caption(f"Urgency score: {urgency_score:.1f}")
            render_task_fields(task)


def render_7_day_timeline(compact=False):
    timeline = build_7_day_timeline()
    overdue = timeline["overdue"]

    if compact:
        with st.expander("Next 7 Days", expanded=False):
            rendered = False
            if overdue:
                rendered = True
                st.warning(f"{len(overdue)} overdue task(s) need attention.")
                for entry in overdue[:2]:
                    render_timeline_entry(entry, compact=True)
                if len(overdue) > 2:
                    st.caption(f"+ {len(overdue) - 2} more overdue task(s).")

            for day in timeline["days"]:
                entries = day["entries"]
                if not entries:
                    continue
                rendered = True
                st.markdown(f'<div class="timeline-day">{day["label"]}</div>', unsafe_allow_html=True)
                for entry in entries[:3]:
                    render_timeline_entry(entry, compact=True)
                if len(entries) > 3:
                    st.caption(f"+ {len(entries) - 3} more.")
            if not rendered:
                st.caption("No active tasks due or planned in the next 7 days.")
        return

    st.subheader("7-Day Academic Timeline")
    st.info(
        "This is not a month calendar. It only shows overdue work and the next "
        "7 days so deadlines can influence today's execution plan."
    )
    if overdue:
        st.markdown("### Overdue")
        for entry in overdue:
            render_timeline_entry(entry, key_prefix="timeline-overdue")

    for day in timeline["days"]:
        st.markdown(f"### {day['label']}")
        if not day["entries"]:
            st.caption("No due or planned tasks.")
            continue
        for entry in day["entries"]:
            render_timeline_entry(
                entry,
                key_prefix=f"timeline-{day['date'].isoformat()}",
            )


def planning_cap_from_tasks(top_tasks):
    labels = [task_urgency(task)[1] for task in top_tasks]
    if "critical" in labels:
        return 5, "critical"
    if "urgent" in labels:
        return 10, "urgent"
    return 15, "normal"


def render_command_hero(command, behavior_plan, top_tasks, active_session):
    behavior_task = behavior_first_task(behavior_plan)
    objective = None
    first_action = None
    planning_cap, urgency_mode = planning_cap_from_tasks(top_tasks)
    if behavior_plan:
        objective = behavior_plan.get("main_objective")
        planning_cap = behavior_plan.get("planning_cap_minutes") or planning_cap
    if command and not objective:
        objective = command.get("executive_summary")
    if behavior_task:
        first_action = behavior_task.get("first_action_under_5_min")
    if command and not first_action:
        first_action = command.get("first_25_minute_action")
    if not objective:
        objective = "Tell me today's constraints, then generate a Daily Command."
    if not first_action and top_tasks:
        first_action = first_action_for_task(top_tasks[0])
    if not first_action:
        first_action = "Add or sync tasks, then start with one 25-minute block."

    if urgency_mode in ("critical", "urgent"):
        meta_text = (
            f"Planning is capped at {planning_cap} minutes. "
            "Do not keep organizing. Start the first action."
        )
        button_label = "Stop Planning. Start 25 Minutes."
    else:
        meta_text = (
            f"Planning is capped at {planning_cap} minutes. "
            "Start the first behavior when ready."
        )
        button_label = "Start First 25-Minute Focus"

    st.markdown(
        (
            '<div class="calm-hero">'
            "<div class=\"calm-eyebrow\">Today's Command</div>"
            f'<div class="calm-objective">{escape_html(objective)}</div>'
            f'<div class="calm-first-action">{escape_html(first_action)}</div>'
            f'<div class="calm-meta">{escape_html(meta_text)}</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    if urgency_mode in ("critical", "urgent"):
        st.warning(meta_text)

    if active_session:
        st.warning(
            "Active focus session: "
            f"{active_session['task_title']} "
            f"({elapsed_minutes_since(active_session['start_time'])} min elapsed)."
        )
        return

    if top_tasks:
        if st.button(
            button_label,
            key=f"command-center-primary-focus-{top_tasks[0]['id']}",
            type="primary",
        ):
            try:
                start_focus_session_for_task(top_tasks[0])
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Focus session started.")
                st.rerun()


def render_command_center_top_tasks(tasks):
    command_date = date.today().isoformat()
    command, behavior_plan = command_center_plan_snapshot(command_date)
    top_tasks = top_urgent_tasks(limit=3)
    active_session = get_active_study_session()

    render_command_hero(command, behavior_plan, top_tasks, active_session)
    render_daily_refresh_status()
    render_minimum_viable_day(behavior_plan)

    avoidance_warning = None
    if behavior_plan:
        avoidance_warning = behavior_plan.get("avoidance_warning")
    if not avoidance_warning and command:
        avoidance_warning = command.get("risk_warning")
    if avoidance_warning:
        st.warning(avoidance_warning)

    st.markdown("### Top 3 Tasks")
    if not top_tasks:
        st.info("No active tasks right now.")
        return

    for index, task in enumerate(top_tasks, start=1):
        urgency_score, urgency_label = task_urgency(task)
        with st.container(border=True):
            st.markdown(
                (
                    '<div class="task-title-row">'
                    f'<h4>{index}. {escape_html(task["title"])}</h4>'
                    f'{urgency_badge_html(urgency_label)}'
                    '</div>'
                    f'<div class="task-card-meta">{escape_html(task_meta_line(task))}</div>'
                    f'<div class="calm-first-action">{escape_html(first_action_for_task(task))}</div>'
                ),
                unsafe_allow_html=True,
            )
            if not active_session and index == 1:
                st.caption("Primary action is the button above.")
            with st.expander("Details"):
                st.caption(f"Urgency score: {urgency_score:.1f}")
                render_task_fields(task)

    render_7_day_timeline(compact=True)

    with st.expander("Daily Command and First Action Tools", expanded=False):
        if command:
            st.write(display_value(command.get("executive_summary")))
            st.caption(
                "First 25 minutes: "
                f"{display_value(command.get('first_25_minute_action'))}"
            )
        else:
            st.write(
                "No Daily Command yet. Tell me your constraints below, or use "
                "the tools here to generate one."
            )

def render_command_center_conversation(command_date, context):
    key_present = has_conversation_intake_api_key()
    if not key_present:
        st.warning("Add OPENAI_API_KEY to your .env file to use conversation intake.")

    render_command_center_chat_history(command_date)

    proposal = st.session_state.get("command_center_proposal")
    if proposal:
        with st.chat_message("assistant"):
            st.markdown("I prepared actions from your message. Review them before anything changes.")
            render_conversation_proposal(proposal)
            actions, selected_action_ids = render_confirmable_actions(
                command_date,
                proposal,
            )
            if selected_action_ids is not None:
                if not selected_action_ids:
                    st.info("No actions were selected.")
                else:
                    try:
                        result = apply_selected_actions(actions, selected_action_ids)
                    except ValueError as error:
                        st.error(str(error))
                        return
                    message_id = st.session_state.get("command_center_message_id")
                    if message_id and result["applied"] > 0:
                        mark_command_center_message_applied(message_id)
                    st.success(
                        "Action engine finished. "
                        f"Applied {result['applied']}, "
                        f"skipped {result['skipped']}, "
                        f"duplicates {result['duplicates']}."
                    )
                    st.session_state.pop("command_center_proposal", None)
                    st.session_state.pop("command_center_message_id", None)
                    st.rerun()
            if st.button("Discard Proposal"):
                st.session_state.pop("command_center_proposal", None)
                st.session_state.pop("command_center_message_id", None)
                st.rerun()

    message = st.chat_input(
        "Tell me what changed today...",
        disabled=not key_present,
    )
    if message:
        with st.chat_message("user"):
            st.write(message)
        recent_messages = get_recent_command_center_messages(command_date, limit=5)
        with st.spinner("Parsing message into a proposal..."):
            try:
                proposal = parse_conversation_message(
                    message,
                    context,
                    recent_messages=recent_messages,
                )
            except (ConversationIntakeConfigError, ValueError) as error:
                st.error(str(error))
                return
            except ConversationIntakeResponseError as error:
                st.error(str(error))
                if error.raw_response:
                    st.text_area(
                        "Raw AI response",
                        value=error.raw_response,
                        height=220,
                    )
                return
            except Exception as error:
                st.error(f"Could not parse message: {error}")
                return

        proposal_for_save = {
            key: value for key, value in proposal.items()
            if key != "_raw_response"
        }
        message_id = create_command_center_message(
            command_date,
            "user",
            message,
            proposal_json=json.dumps(proposal_for_save, ensure_ascii=False),
            applied=0,
        )
        st.session_state.command_center_proposal = proposal_for_save
        st.session_state.command_center_message_id = message_id
        st.rerun()


def render_command_center_chat_history(command_date):
    messages = list(reversed(get_recent_command_center_messages(command_date, limit=8)))
    if not messages:
        with st.chat_message("assistant"):
            st.write(
                "Tell me today's constraints, completed work, blockers, or what "
                "you want changed. I will propose actions first; you confirm."
            )
        return

    for message in messages:
        role = "user" if message["role"] == "user" else "assistant"
        with st.chat_message(role):
            st.write(message["content"])
            if message.get("proposal_json"):
                try:
                    proposal = json.loads(message["proposal_json"])
                except json.JSONDecodeError:
                    proposal = None
                if proposal:
                    status = "Applied" if message.get("applied") else "Not applied"
                    st.caption(f"Proposal: {display_value(proposal.get('summary'))} ({status})")


def render_command_center_quick_command(context, task_lookup):
    st.markdown("### Daily Command")
    render_daily_command_status(context)
    render_daily_command_generate(context, task_lookup)

    st.markdown("### First Actions")
    st.caption(
        "Behavior Design turns the Daily Command into smaller starting "
        "behaviors. It saves a plan, but it does not update tasks unless you "
        "apply a task's behavior fields."
    )
    generated_plan = render_behavior_generate(
        context["current_date"],
        user_checkin_text=None,
        key_prefix="command-center-behavior",
        button_label="Design First Actions",
    )
    if generated_plan:
        render_behavior_plan(
            generated_plan,
            task_lookup,
            key_prefix="command-center-behavior-generated",
        )
        render_behavior_memory_candidates(
            generated_plan,
            key_prefix="command-center-behavior-memory",
        )


def render_command_center():
    st.markdown("## Today")
    command_date = date.today().isoformat()
    context, tasks = current_daily_command_context(command_date)

    render_command_center_top_tasks(tasks)
    render_command_center_conversation(command_date, context)

    refreshed_context, refreshed_tasks = current_daily_command_context(command_date)
    refreshed_lookup = task_lookup_by_id(refreshed_tasks)
    with st.expander("Generate / Adjust Plan", expanded=False):
        render_command_center_quick_command(refreshed_context, refreshed_lookup)
        render_latest_daily_command(command_date, refreshed_lookup)


def checkin_text_value(checkin, key):
    if not checkin:
        return ""
    return checkin.get(key) or ""


def checkin_select_index(checkin, key):
    options = ["low", "medium", "high"]
    if not checkin or checkin.get(key) not in options:
        return 1
    return options.index(checkin[key])


def render_morning_checkin_form(command_date):
    st.markdown("### Morning Check-In")
    existing_checkin = get_morning_checkin_by_date(command_date)
    if existing_checkin:
        st.caption("A morning check-in already exists for this date. Saving updates it.")

    with st.form("morning_checkin_form"):
        available_study_minutes = st.number_input(
            "Available study minutes today",
            min_value=0,
            value=existing_checkin.get("available_study_minutes") or 180
            if existing_checkin else 180,
            step=15,
        )
        available_time_blocks = st.text_area(
            "When can you study today?",
            value=checkin_text_value(existing_checkin, "available_time_blocks"),
            placeholder="Example: 10:00-12:00, 15:00-17:30",
        )
        fixed_commitments = st.text_area(
            "Fixed commitments today",
            value=checkin_text_value(existing_checkin, "fixed_commitments"),
            placeholder="Classes, work, commute, appointments...",
        )
        extra_commitments = st.text_area(
            "Extra things you want to do today",
            value=checkin_text_value(existing_checkin, "extra_commitments"),
            placeholder="Gym, laundry, groceries, cleaning, social plans...",
        )

        columns = st.columns(3)
        sleep_quality = columns[0].selectbox(
            "Sleep quality",
            options=["low", "medium", "high"],
            index=checkin_select_index(existing_checkin, "sleep_quality"),
        )
        energy_level = columns[1].selectbox(
            "Energy level",
            options=["low", "medium", "high"],
            index=checkin_select_index(existing_checkin, "energy_level"),
        )
        stress_level = columns[2].selectbox(
            "Stress level",
            options=["low", "medium", "high"],
            index=checkin_select_index(existing_checkin, "stress_level"),
        )

        mood = st.text_input(
            "Mood",
            value=checkin_text_value(existing_checkin, "mood"),
            placeholder="Example: calm, anxious, tired, okay",
        )
        top_personal_priority = st.text_input(
            "One personal priority today",
            value=checkin_text_value(existing_checkin, "top_personal_priority"),
            placeholder="Example: go to the gym, call family, clean room",
        )
        avoiding_task = st.text_input(
            "What task are you most likely to avoid?",
            value=checkin_text_value(existing_checkin, "avoiding_task"),
        )
        hard_stop_time = st.text_input(
            "Hard stop time (HH:MM, optional)",
            value=checkin_text_value(existing_checkin, "hard_stop_time"),
            placeholder="Example: 22:30",
        )
        notes = st.text_area(
            "Anything else the agent should know?",
            value=checkin_text_value(existing_checkin, "notes"),
        )
        submitted = st.form_submit_button("Save Morning Check-In")

    if submitted:
        try:
            create_or_update_morning_checkin({
                "checkin_date": command_date,
                "available_study_minutes": available_study_minutes,
                "available_time_blocks": available_time_blocks,
                "fixed_commitments": fixed_commitments,
                "extra_commitments": extra_commitments,
                "sleep_quality": sleep_quality,
                "energy_level": energy_level,
                "stress_level": stress_level,
                "mood": mood,
                "top_personal_priority": top_personal_priority,
                "avoiding_task": avoiding_task,
                "hard_stop_time": hard_stop_time,
                "notes": notes,
            })
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Morning check-in saved.")


def render_add_personal_commitment(command_date):
    st.markdown("### Add Personal Commitment")
    with st.form("personal_commitment_form"):
        title = st.text_input(
            "Commitment title",
            placeholder="Example: Gym, groceries, laundry",
        )
        columns = st.columns(4)
        commitment_type = columns[0].selectbox(
            "Type",
            options=COMMITMENT_TYPES,
            index=COMMITMENT_TYPES.index("personal"),
        )
        start_time = columns[1].text_input(
            "Start time",
            placeholder="HH:MM",
        )
        estimated_minutes = columns[2].number_input(
            "Minutes",
            min_value=1,
            value=60,
            step=15,
        )
        priority = columns[3].slider("Priority", 1, 5, value=3)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Add Commitment")

    if submitted:
        try:
            create_personal_commitment({
                "title": title,
                "commitment_type": commitment_type,
                "planned_date": command_date,
                "start_time": start_time,
                "estimated_minutes": estimated_minutes,
                "priority": priority,
                "status": "planned",
                "notes": notes,
            })
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Personal commitment added.")
            st.rerun()


def render_personal_commitments(command_date):
    render_add_personal_commitment(command_date)
    st.markdown("### Today's Personal Commitments")
    commitments = get_personal_commitments_for_date(
        command_date,
        include_ignored=True,
    )
    if not commitments:
        st.info("No personal commitments added for this date yet.")
        return

    for commitment in commitments:
        with st.container(border=True):
            st.markdown(f"#### {display_value(commitment['title'])}")
            columns = st.columns(5)
            columns[0].markdown(
                f"**Type**  \n{display_value(commitment['commitment_type'])}"
            )
            columns[1].markdown(
                f"**Start**  \n{display_value(commitment['start_time'])}"
            )
            columns[2].markdown(
                f"**Minutes**  \n{display_value(commitment['estimated_minutes'])}"
            )
            columns[3].markdown(
                f"**Priority**  \n{display_value(commitment['priority'])}"
            )
            columns[4].markdown(
                f"**Status**  \n{display_value(commitment['status'])}"
            )
            st.markdown(f"**Notes**  \n{display_value(commitment['notes'])}")

            columns = st.columns(2)
            with columns[0]:
                if st.button(
                    "Mark Done",
                    key=f"commitment-done-{commitment['id']}",
                    disabled=commitment["status"] == "done",
                ):
                    update_personal_commitment_status(commitment["id"], "done")
                    st.success("Commitment marked done.")
                    st.rerun()
            with columns[1]:
                if st.button(
                    "Ignore",
                    key=f"commitment-ignore-{commitment['id']}",
                    disabled=commitment["status"] == "ignored",
                ):
                    update_personal_commitment_status(commitment["id"], "ignored")
                    st.success("Commitment ignored.")
                    st.rerun()


def render_saved_checkin_answers(command_date):
    answers = get_checkin_answers_by_date(command_date)
    if not answers:
        return

    st.markdown("#### Saved Q&A")
    for answer in answers[:5]:
        with st.container(border=True):
            st.markdown(f"**Q:** {display_value(answer['question'])}")
            st.markdown(f"**A:** {display_value(answer['answer'])}")
            if answer.get("reason"):
                st.caption(answer["reason"])


def render_question_coach(command_date, context):
    st.markdown("### AI Question Coach")
    st.caption(
        "This uses a compact context and asks at most 3 follow-up questions. "
        "It does not generate a plan or update tasks."
    )

    key_present = has_question_coach_api_key()
    if not key_present:
        st.warning("Add OPENAI_API_KEY to your .env file to use Question Coach.")

    state_key = f"question_coach_questions_{command_date}"
    existing_answers = get_checkin_answers_by_date(command_date)

    if st.button("Ask Follow-Up Questions", disabled=not key_present):
        with st.spinner("Finding the next useful questions..."):
            try:
                questions = generate_checkin_questions(
                    context,
                    existing_answers=existing_answers,
                    max_questions=3,
                )
            except QuestionCoachConfigError as error:
                st.error(str(error))
                return
            except QuestionCoachResponseError as error:
                st.error(str(error))
                if error.raw_response:
                    st.text_area(
                        "Raw AI response",
                        value=error.raw_response,
                        height=220,
                    )
                return
            except Exception as error:
                st.error(f"Could not generate follow-up questions: {error}")
                return

        st.session_state[state_key] = questions
        if not questions:
            st.info("Question Coach did not find any useful follow-up questions.")

    questions = st.session_state.get(state_key) or []
    if questions:
        with st.form(f"question_coach_answer_form_{command_date}"):
            answers = []
            for index, question in enumerate(questions, start=1):
                st.markdown(f"#### Question {index}")
                st.markdown(display_value(question["question"]))
                st.caption(display_value(question.get("reason")))
                answer = st.text_area(
                    "Answer",
                    key=f"question-coach-answer-{command_date}-{index}",
                )
                answers.append((question, answer))
            submitted = st.form_submit_button("Save Answers")

        if submitted:
            saved = 0
            for question, answer in answers:
                if not str(answer or "").strip():
                    continue
                create_checkin_answer({
                    "checkin_date": command_date,
                    "question": question["question"],
                    "answer": answer,
                    "reason": question.get("reason"),
                    "answer_type": question.get("answer_type"),
                    "source": "ai_question_coach",
                })
                saved += 1
            if saved:
                st.session_state.pop(state_key, None)
                st.success(f"Saved {saved} answer(s).")
                st.rerun()
            else:
                st.info("No answers were saved because all answer fields were empty.")

    render_saved_checkin_answers(command_date)


def current_daily_command_context(command_date):
    tasks = get_all_tasks()
    command_day = datetime.strptime(command_date, "%Y-%m-%d").date()
    today_plan = generate_today_plan(tasks, max_tasks=3, today=command_day)
    checkin = get_morning_checkin_by_date(command_date)
    commitments = get_personal_commitments_for_date(command_date)
    checkin_answers = get_checkin_answers_by_date(command_date)
    recent_sessions = get_recent_study_sessions(limit=20)
    recent_reviews = get_recent_daily_reviews(limit=7)
    memories = get_active_agent_memory()

    context = build_daily_command_context(
        tasks=tasks,
        today_plan=today_plan,
        morning_checkin=checkin,
        personal_commitments=commitments,
        checkin_answers=checkin_answers,
        recent_study_sessions=recent_sessions,
        recent_daily_reviews=recent_reviews,
        active_memories=memories,
        current_date=command_date,
    )
    return context, tasks


def render_daily_command_status(context):
    st.markdown("### Status")
    key_present = has_daily_command_api_key()
    st.markdown(f"**OPENAI_API_KEY configured:** {'Yes' if key_present else 'No'}")
    if not key_present:
        st.warning(
            "Add OPENAI_API_KEY to your .env file to generate a Daily Command."
        )
    if not context.get("morning_checkin"):
        st.warning("Save the Morning Check-In first so the plan has today's context.")

    counts = context["counts"]
    columns = st.columns(5)
    columns[0].metric("Active Tasks", counts["active_tasks"])
    columns[1].metric("Today Plan", counts["today_plan_items"])
    columns[2].metric("Commitments", counts["personal_commitments"])
    columns[3].metric("Q&A Answers", counts.get("checkin_answers", 0))
    columns[4].metric("Memories", counts["active_memories"])


def parse_saved_daily_command(record):
    if not record or not record.get("output_json"):
        return None

    try:
        return json.loads(record["output_json"])
    except json.JSONDecodeError:
        return None


def render_daily_command_task_card(task, task_lookup):
    task_id = task.get("task_id")
    existing_task = task_lookup.get(str(task_id)) if task_id else None

    with st.container(border=True):
        st.markdown(f"#### {display_value(task.get('title'))}")
        columns = st.columns(3)
        columns[0].markdown(f"**Course**  \n{display_value(task.get('course'))}")
        columns[1].markdown(
            "**Estimated**  \n"
            f"{display_value(task.get('estimated_minutes'))} min"
        )
        columns[2].markdown(f"**Task ID**  \n{display_value(task_id)}")

        if existing_task:
            columns = st.columns(3)
            columns[0].markdown(
                f"**Status**  \n{display_value(existing_task.get('status'))}"
            )
            columns[1].markdown(
                f"**Due**  \n{display_task_datetime(existing_task.get('due_at'))}"
            )
            columns[2].markdown(
                f"**Urgency**  \n{display_value(existing_task.get('urgency_label'))}"
            )

        st.markdown(f"**Reason**  \n{display_value(task.get('reason'))}")
        st.markdown(
            f"**First action**  \n{display_value(task.get('first_action'))}"
        )


def render_daily_command_output(command, task_lookup):
    if not command:
        st.info("No Daily Command to display yet.")
        return

    st.markdown("### Executive Summary")
    st.write(display_value(command.get("executive_summary")))

    st.markdown("### Main Tasks")
    main_tasks = command.get("main_tasks") or []
    if not main_tasks:
        st.info("No main tasks were returned.")
    for task in main_tasks[:3]:
        render_daily_command_task_card(task, task_lookup)

    commitments = command.get("personal_commitments") or []
    if commitments:
        st.markdown("### Personal Commitments")
        for item in commitments:
            with st.container(border=True):
                st.markdown(f"#### {display_value(item.get('title'))}")
                st.markdown(
                    f"**Time advice**  \n{display_value(item.get('time_advice'))}"
                )
                st.markdown(f"**Reason**  \n{display_value(item.get('reason'))}")

    time_blocks = command.get("time_blocks") or []
    if time_blocks:
        st.markdown("### Suggested Blocks")
        for block in time_blocks:
            with st.container(border=True):
                columns = st.columns(3)
                columns[0].markdown(
                    f"**Start**  \n{display_value(block.get('start_time'))}"
                )
                columns[1].markdown(f"**Label**  \n{display_value(block.get('label'))}")
                columns[2].markdown(
                    f"**Minutes**  \n{display_value(block.get('minutes'))}"
                )
                st.markdown(f"**Focus**  \n{display_value(block.get('focus'))}")
                st.markdown(f"**Notes**  \n{display_value(block.get('notes'))}")

    st.markdown("### First 25-Minute Action")
    st.write(display_value(command.get("first_25_minute_action")))

    avoid_doing = command.get("avoid_doing") or []
    if avoid_doing:
        st.markdown("### Avoid Doing")
        for item in avoid_doing:
            st.markdown(f"- {display_value(item)}")

    if command.get("risk_warning"):
        st.markdown("### Risk Warning")
        st.warning(command["risk_warning"])

    st.markdown("### Schedule Advice")
    st.write(display_value(command.get("schedule_advice")))

    st.markdown("### End-of-Day Review Prompt")
    st.write(display_value(command.get("end_of_day_review_prompt")))


def render_daily_command_generate(context, task_lookup):
    st.markdown("### Generate Daily Command")
    st.caption(
        "Daily Command uses your morning check-in, tasks, Today Plan, focus "
        "sessions, daily reviews, and active memories. It does not update tasks."
    )

    key_present = has_daily_command_api_key()
    ready = key_present and bool(context.get("morning_checkin"))
    if st.button("Generate Daily Command", disabled=not ready):
        with st.spinner("Generating Daily Command..."):
            try:
                command = generate_daily_command(context)
                raw_response = command.get("_raw_response")
                command_for_save = {
                    key: value for key, value in command.items()
                    if key != "_raw_response"
                }
                save_daily_command(
                    command_date=context["current_date"],
                    input_summary_json=json.dumps(context, ensure_ascii=False),
                    output_json=json.dumps(command_for_save, ensure_ascii=False),
                    raw_response=raw_response,
                )
            except DailyCommandConfigError as error:
                st.error(str(error))
                return
            except DailyCommandResponseError as error:
                st.error(str(error))
                if error.raw_response:
                    st.text_area(
                        "Raw AI response",
                        value=error.raw_response,
                        height=240,
                    )
                return
            except Exception as error:
                st.error(f"Could not generate Daily Command: {error}")
                return

        st.success("Daily Command saved.")
        render_daily_command_output(command_for_save, task_lookup)


def render_latest_daily_command(command_date, task_lookup):
    st.markdown("### Latest Daily Command")
    latest = get_latest_daily_command(command_date)
    if not latest:
        st.info("No Daily Command saved for this date yet.")
        return

    st.caption(
        f"Saved {display_datetime(latest['created_at'])} "
        f"for {latest['command_date']}."
    )
    command = parse_saved_daily_command(latest)
    if not command:
        st.warning("The latest saved Daily Command could not be parsed.")
        return
    render_daily_command_output(command, task_lookup)


def render_recent_daily_commands():
    st.markdown("### Recent Daily Commands")
    commands = get_recent_daily_commands(limit=7)
    if not commands:
        st.info("No saved Daily Commands yet.")
        return

    for record in commands:
        command = parse_saved_daily_command(record)
        title = (
            f"{record['command_date']} - "
            f"{display_datetime(record['created_at'])}"
        )
        with st.expander(title):
            if not command:
                st.warning("This saved Daily Command could not be parsed.")
                continue
            st.markdown(
                f"**Summary**  \n{display_value(command.get('executive_summary'))}"
            )
            st.markdown(
                "**First 25-minute action**  \n"
                f"{display_value(command.get('first_25_minute_action'))}"
            )


def render_daily_command():
    st.subheader("Daily Command")
    st.info(
        "Daily Command starts with a morning check-in, then creates a realistic "
        "plan for your school tasks and personal commitments. It only generates "
        "a plan when you click the button."
    )

    selected_date = st.date_input("Daily Command date", value=date.today())
    command_date = selected_date.isoformat()

    render_morning_checkin_form(command_date)
    render_personal_commitments(command_date)

    context, tasks = current_daily_command_context(command_date)
    task_lookup = task_lookup_by_id(tasks)

    render_question_coach(command_date, context)
    render_daily_command_status(context)
    render_daily_command_generate(context, task_lookup)
    render_latest_daily_command(command_date, task_lookup)
    render_recent_daily_commands()


def parse_json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def render_feedback_review(review):
    if not review:
        st.info("No feedback review to display yet.")
        return

    st.markdown("### Feedback Review")
    columns = st.columns(5)
    columns[0].metric("Score", f"{review['completion_score']:.1f}")
    columns[1].metric("Accuracy", display_value(review["planning_accuracy"]))
    columns[2].metric(
        "Main Tasks",
        f"{review['main_tasks_completed']}/{review['main_tasks_total']}",
    )
    columns[3].metric("Focus Minutes", review["focus_minutes"])
    columns[4].metric("Sessions", review["focus_sessions_count"])

    st.markdown(f"**Summary**  \n{display_value(review['feedback_summary'])}")

    avoidance_flags = parse_json_list(review.get("avoidance_flags"))
    if avoidance_flags:
        st.markdown("#### Avoidance Flags")
        for flag in avoidance_flags:
            st.markdown(f"- {display_value(flag)}")

    if review.get("time_estimation_notes"):
        st.markdown("#### Time Estimation Notes")
        st.write(review["time_estimation_notes"])

    if review.get("overload_warning"):
        st.markdown("#### Overload Warning")
        st.warning(review["overload_warning"])


def render_feedback_evaluator():
    st.markdown("### Evaluate Daily Command")
    st.caption(
        "This is rule-based. It compares a saved Daily Command with task status, "
        "focus sessions, and Daily Review. It does not call AI."
    )
    selected_date = st.date_input(
        "Command date to evaluate",
        value=date.today() - timedelta(days=1),
    )
    command_date = selected_date.isoformat()
    command_record = get_latest_daily_command(command_date)
    if not command_record:
        st.info("No Daily Command was saved for this date.")
        return

    existing_review = get_daily_command_review_by_command(command_record["id"])
    if existing_review:
        render_feedback_review(existing_review)

    if st.button("Evaluate This Daily Command"):
        daily_review = get_daily_review_by_date(command_date)
        result = evaluate_daily_command(
            command_record=command_record,
            tasks=get_all_tasks(),
            study_sessions=get_recent_study_sessions(limit=200),
            daily_review=daily_review,
            review_date=date.today().isoformat(),
        )
        saved_review = create_or_update_daily_command_review(result["review"])
        created_candidates = 0
        duplicate_candidates = 0
        for candidate in result["memory_candidates"]:
            if create_agent_memory_candidate(candidate):
                created_candidates += 1
            else:
                duplicate_candidates += 1

        st.success(
            "Feedback review saved. "
            f"Created {created_candidates} memory candidate(s), "
            f"skipped {duplicate_candidates} duplicate candidate(s)."
        )
        render_feedback_review(saved_review)


def render_memory_candidate_review():
    st.markdown("### Memory Candidates")
    candidates = get_pending_agent_memory_candidates()
    if not candidates:
        st.info("No pending memory candidates right now.")
        return

    for candidate in candidates:
        with st.container(border=True):
            st.markdown(
                f"#### {display_value(candidate['memory_type'])}: "
                f"{display_value(candidate['memory_key'])}"
            )
            st.markdown(display_value(candidate["memory_value"]))
            columns = st.columns(3)
            columns[0].markdown(
                f"**Confidence**  \n{display_value(candidate['confidence'])}"
            )
            columns[1].markdown(f"**Source**  \n{display_value(candidate['source'])}")
            columns[2].markdown(
                f"**Created**  \n{display_datetime(candidate['created_at'])}"
            )

            if candidate.get("evidence_json"):
                with st.expander("Evidence"):
                    st.code(candidate["evidence_json"], language="json")

            columns = st.columns(2)
            with columns[0]:
                if st.button(
                    "Accept as Agent Memory",
                    key=f"accept-memory-candidate-{candidate['id']}",
                ):
                    memory_id = promote_memory_candidate_to_memory(candidate["id"])
                    if memory_id:
                        st.success("Memory candidate accepted.")
                    else:
                        st.info("Memory already exists or candidate could not be promoted.")
                    st.rerun()
            with columns[1]:
                if st.button(
                    "Ignore Candidate",
                    key=f"ignore-memory-candidate-{candidate['id']}",
                ):
                    update_agent_memory_candidate_decision(candidate["id"], "ignored")
                    st.success("Memory candidate ignored.")
                    st.rerun()


def render_recent_feedback_reviews():
    st.markdown("### Recent Feedback Reviews")
    reviews = get_recent_daily_command_reviews(limit=7)
    if not reviews:
        st.info("No feedback reviews saved yet.")
        return

    for review in reviews:
        with st.expander(
            f"{review['command_date']} - score {review['completion_score']:.1f}"
        ):
            render_feedback_review(review)


def render_feedback_loop():
    st.subheader("Feedback Loop")
    st.info(
        "Feedback Loop compares the Daily Command against what actually happened. "
        "It can suggest memory candidates, but you decide whether they become "
        "active Agent Memory."
    )
    render_feedback_evaluator()
    render_memory_candidate_review()
    render_recent_feedback_reviews()


def normalize_match_text(value):
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    return " ".join(text.split())


def date_key(value):
    parsed = parse_timeline_date(value)
    return parsed.isoformat() if parsed else None


def task_similarity(left, right):
    left_text = normalize_match_text(left)
    right_text = normalize_match_text(right)
    if not left_text or not right_text:
        return 0
    return SequenceMatcher(None, left_text, right_text).ratio()


def find_possible_task_match(candidate, tasks, threshold=0.78):
    candidate_title = candidate.get("title")
    candidate_course = normalize_match_text(candidate.get("course"))
    candidate_type = normalize_match_text(candidate.get("task_type"))
    best_match = None
    best_score = 0

    for task in tasks:
        title_score = task_similarity(candidate_title, task.get("title"))
        if candidate_course and normalize_match_text(task.get("course")) == candidate_course:
            title_score += 0.08
        if candidate_type and normalize_match_text(task.get("task_type")) == candidate_type:
            title_score += 0.04
        if title_score > best_score:
            best_score = title_score
            best_match = task

    if best_match and best_score >= threshold:
        return best_match, min(best_score, 1.0)
    return None, best_score


def v0_task_payload(task, document_type, notes_prefix=None):
    notes = task.get("notes")
    if notes_prefix:
        notes = f"{notes_prefix}\n{notes}" if notes else notes_prefix

    return {
        "title": task.get("title"),
        "course": task.get("course"),
        "task_type": task.get("task_type") or "other",
        "due_at": task.get("due_at"),
        "weight": task.get("weight"),
        "planned_date": None,
        "estimated_minutes": task.get("estimated_minutes"),
        "priority": task.get("priority") or 3,
        "status": "suggested",
        "source": document_type,
        "confidence": task.get("confidence") or "low",
        "notes": notes,
        "source_snippet": task.get("source_snippet"),
        "needs_review": 1,
    }


def extract_suggestions_from_material(raw_text, document_type):
    with st.spinner("Extracting task suggestions..."):
        return extract_tasks_from_text(raw_text, source=document_type)


def save_material_document(title, document_type, raw_text, filename=None, file_type=None):
    return create_document({
        "title": title or filename or f"{document_type.title()} material",
        "document_type": document_type,
        "raw_text": raw_text,
        "filename": filename,
        "file_type": file_type,
    })


def v0_status_counts():
    tasks = get_all_tasks()
    return {
        "pending_suggestions": sum(
            1 for task in tasks if task.get("status") == "suggested"
        ),
        "confirmed_tasks": sum(
            1 for task in tasks if task.get("status") in ("confirmed", "in_progress")
        ),
        "pending_updates": len(get_pending_task_updates()),
    }


def render_v0_status_metrics():
    counts = v0_status_counts()
    columns = st.columns(3)
    columns[0].metric("Pending suggestions", counts["pending_suggestions"])
    columns[1].metric("Confirmed tasks", counts["confirmed_tasks"])
    columns[2].metric("Pending updates", counts["pending_updates"])


def render_suggestion_summary(task):
    visible_fields = [
        ("Course", task.get("course")),
        ("Type", task.get("task_type")),
        ("Due", display_task_datetime(task.get("due_at"))),
    ]
    if task.get("weight"):
        visible_fields.append(("Weight", task.get("weight")))

    columns = st.columns(len(visible_fields))
    for index, (label, value) in enumerate(visible_fields):
        columns[index].markdown(f"**{label}**  \n{display_value(value)}")

    with st.expander("Why AI suggested this"):
        detail_columns = st.columns(3)
        detail_columns[0].markdown(
            f"**Confidence**  \n{display_value(task.get('confidence'))}"
        )
        detail_columns[1].markdown(
            f"**Status**  \n{display_value(task.get('status'))}"
        )
        detail_columns[2].markdown(
            f"**Source**  \n{display_value(task.get('source'))}"
        )
        if task.get("notes"):
            st.markdown(f"**Notes**  \n{display_value(task.get('notes'))}")
        st.markdown(
            f"**Source snippet**  \n{display_value(task.get('source_snippet'))}"
        )


def render_manual_task_fallback():
    with st.expander("Add one task manually"):
        with st.form("manual-v0-task-form"):
            title = st.text_input("Task title")
            course = st.text_input("Course")
            task_type = st.text_input("Task type")
            due_at = st.date_input("Due date")
            submitted = st.form_submit_button("Create Confirmed Task")

        if submitted:
            if not title.strip():
                st.warning("Task title is required.")
                return

            try:
                create_task({
                    "title": title,
                    "course": course,
                    "task_type": task_type,
                    "due_at": due_at,
                    "status": "confirmed",
                    "source": "manual",
                })
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Confirmed task created. Open Tasks to see it.")
                if st.button("Open Tasks", key="manual-task-open-tasks"):
                    st.session_state.pending_nav = "Tasks"
                    st.rerun()


def render_suggestion_edit_form(task):
    with st.expander("Edit"):
        with st.form(f"edit-suggestion-{task['id']}"):
            title = st.text_input("Title", value=task.get("title") or "")
            course = st.text_input("Course", value=task.get("course") or "")
            task_type = st.text_input("Task type", value=task.get("task_type") or "")
            due_at = st.text_input(
                "Due date",
                value=task.get("due_at") or "",
                placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM",
            )
            weight = st.text_input("Weight", value=task.get("weight") or "")
            confidence = st.selectbox(
                "Confidence",
                options=["high", "medium", "low"],
                index=["high", "medium", "low"].index(
                    task.get("confidence") if task.get("confidence") in ("high", "medium", "low") else "medium"
                ),
            )
            notes = st.text_area("Reason / Notes", value=task.get("notes") or "")
            source_snippet = st.text_area(
                "Source snippet",
                value=task.get("source_snippet") or "",
            )
            submitted = st.form_submit_button("Save Edit")

        if submitted:
            try:
                update_task_fields(
                    task["id"],
                    {
                        "title": title,
                        "course": course,
                        "task_type": task_type,
                        "due_at": due_at,
                        "weight": weight,
                        "confidence": confidence,
                        "notes": notes,
                        "source_snippet": source_snippet,
                    },
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Suggestion updated.")
                st.rerun()


def render_review_suggestions():
    st.subheader("Review Suggestions")
    st.caption(
        "AI suggestions are not official tasks yet. Confirm, edit, or "
        "ignore each one."
    )
    suggestions = sort_tasks_for_dashboard(get_tasks_by_status("suggested"), "All Tasks")
    if not suggestions:
        st.info("No suggestions waiting for review. Add course material to extract tasks.")
        if st.button("Add Material", key="empty-review-add-material"):
            st.session_state.pending_nav = "Add Material"
            st.rerun()
        return

    for task in suggestions:
        with st.container(border=True):
            st.markdown(f"### {display_value(task.get('title'))}")
            render_suggestion_summary(task)
            render_suggestion_edit_form(task)
            columns = st.columns(2)
            with columns[0]:
                if st.button("Confirm Task", key=f"v0-confirm-{task['id']}", type="primary"):
                    update_task_status(task["id"], "confirmed")
                    st.success("Task confirmed.")
                    st.rerun()
            with columns[1]:
                if st.button("Ignore", key=f"v0-ignore-{task['id']}"):
                    update_task_status(task["id"], "ignored")
                    st.success("Suggestion ignored.")
                    st.rerun()


def render_add_material():
    st.subheader("Turn course material into reviewable tasks")
    st.caption(
        "Upload a syllabus, assignment sheet, or announcement. The app will "
        "extract possible tasks, then you confirm what should go into your "
        "dashboard."
    )
    render_v0_status_metrics()

    document_type = st.selectbox("Material type", DOCUMENT_TYPES)
    title = st.text_input("Title", placeholder="Example: STA457 syllabus")
    uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])
    pasted_text = st.text_area(
        "Or paste course material",
        placeholder="Paste syllabus, announcement, or assignment instructions here...",
        height=240,
    )

    if st.button("Extract Task Suggestions", type="primary"):
        raw_text = (pasted_text or "").strip()
        filename = None
        file_type = None

        if uploaded_file is not None:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            saved_path = UPLOAD_DIR / safe_filename(uploaded_file.name)
            saved_path.write_bytes(uploaded_file.getbuffer())
            filename = uploaded_file.name
            file_type = "pdf"
            try:
                raw_text = extract_text_from_pdf(saved_path)
            except Exception as error:
                st.error(f"Could not read this PDF: {error}")
                return

        if not raw_text:
            st.warning("Upload a PDF or paste material first.")
            return

        document_id = save_material_document(
            title=title,
            document_type=document_type,
            raw_text=raw_text,
            filename=filename,
            file_type=file_type,
        )

        try:
            extracted_tasks = extract_suggestions_from_material(raw_text, document_type)
        except Exception as error:
            st.error(f"Could not extract suggestions: {error}")
            return

        saved_count = 0
        duplicate_count = 0
        existing_tasks = get_all_tasks()
        for task in extracted_tasks:
            match, score = find_possible_task_match(task, existing_tasks)
            if match and date_key(match.get("due_at")) == date_key(task.get("due_at")):
                duplicate_count += 1
                continue

            notes_prefix = f"Document #{document_id}"
            if match:
                notes_prefix += (
                    f"\nPossible duplicate of task #{match['id']} "
                    f"({score:.0%} title match)."
                )
            create_task(v0_task_payload(task, document_type, notes_prefix))
            saved_count += 1

        st.success(
            f"Created {saved_count} suggestions. Review them before adding "
            "them to your task dashboard."
            + (f" Skipped {duplicate_count} likely duplicates." if duplicate_count else "")
        )
        if saved_count:
            if st.button("Review Suggestions", key="after-extraction-review"):
                st.session_state.pending_nav = "Review Suggestions"
                st.rerun()

    render_manual_task_fallback()


def active_confirmed_tasks():
    return [
        task for task in get_all_tasks()
        if task.get("status") in ("confirmed", "in_progress")
    ]


def v0_tasks_for_view(view_name):
    tasks = active_confirmed_tasks()
    today = date.today()

    if view_name == "Today":
        tasks = [
            task for task in tasks
            if (
                date_key(task.get("due_at")) == today.isoformat()
                or date_key(task.get("planned_date")) == today.isoformat()
                or (
                    parse_timeline_date(task.get("due_at"))
                    and parse_timeline_date(task.get("due_at")) < today
                )
            )
        ]
    elif view_name == "This Week":
        end_date = today + timedelta(days=7)
        tasks = [
            task for task in tasks
            if (
                parse_timeline_date(task.get("due_at"))
                and today <= parse_timeline_date(task.get("due_at")) <= end_date
            )
            or (
                parse_timeline_date(task.get("planned_date"))
                and today <= parse_timeline_date(task.get("planned_date")) <= end_date
            )
        ]
    elif view_name == "Done":
        tasks = get_tasks_by_status("done")

    return sort_tasks_for_dashboard(tasks, view_name)


def render_due_date_editor(task, view_name):
    with st.expander("Edit due date"):
        with st.form(f"edit-due-date-{view_key(view_name)}-{task['id']}"):
            due_at = st.text_input(
                "Due date",
                value=task.get("due_at") or "",
                placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM. Leave blank to clear.",
            )
            submitted = st.form_submit_button("Save Due Date")

        if submitted:
            try:
                update_task_fields(task["id"], {"due_at": due_at})
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Due date updated.")
                st.rerun()


def render_v0_task_cards(tasks, view_name):
    if not tasks:
        if not active_confirmed_tasks() or view_name == "All Tasks":
            st.info("No confirmed tasks yet. Review AI suggestions to build your task dashboard.")
        else:
            st.info(
                "No confirmed tasks in this view. Review Suggestions is where "
                "new AI-detected tasks become official."
            )
        if st.button("Review Suggestions", key=f"empty-tasks-review-{view_name}"):
            st.session_state.pending_nav = "Review Suggestions"
            st.rerun()
        return

    for task in tasks:
        with st.container(border=True):
            st.markdown(f"### {display_value(task.get('title'))}")
            visible_fields = [
                ("Course", task.get("course")),
                ("Type", task.get("task_type")),
                ("Due", display_task_datetime(task.get("due_at"))),
                ("Status", task.get("status")),
            ]
            if task.get("weight"):
                visible_fields.insert(3, ("Weight", task.get("weight")))

            columns = st.columns(len(visible_fields))
            for index, (label, value) in enumerate(visible_fields):
                columns[index].markdown(f"**{label}**  \n{display_value(value)}")
            with st.expander("Details"):
                if task.get("source_snippet"):
                    st.markdown("**Source snippet**")
                    st.write(task["source_snippet"])
                render_task_fields(task)
            render_due_date_editor(task, view_name)
            if task.get("status") == "done":
                if st.button("Reopen", key=f"v0-reopen-{task['id']}"):
                    update_task_status(task["id"], "confirmed")
                    st.rerun()
            else:
                if st.button("Mark Done", key=f"v0-done-{task['id']}", type="primary"):
                    update_task_status(task["id"], "done")
                    st.rerun()


def render_v0_tasks():
    st.subheader("Tasks")
    st.caption("These are confirmed tasks you approved.")
    view_name = st.radio(
        "View",
        options=["Today", "This Week", "All Tasks", "Done"],
        horizontal=True,
        label_visibility="collapsed",
    )
    render_v0_task_cards(v0_tasks_for_view(view_name), view_name)


def render_pending_task_updates():
    updates = get_pending_task_updates()
    if not updates:
        st.info(
            "No pending updates. This page is for later announcements or "
            "changed course material that might add tasks or change deadlines."
        )
        return

    for update in updates:
        with st.container(border=True):
            st.markdown(f"### Matched existing task: {display_value(update.get('task_title'))}")
            columns = st.columns(4)
            columns[0].markdown(f"**Course**  \n{display_value(update.get('task_course'))}")
            columns[1].markdown(f"**Current due**  \n{display_task_datetime(update.get('old_due_at'))}")
            columns[2].markdown(f"**Proposed due**  \n{display_task_datetime(update.get('new_due_at'))}")
            columns[3].markdown(f"**Confidence**  \n{display_value(update.get('confidence'))}")
            st.markdown(f"**Reason**  \n{display_value(update.get('reason'))}")
            st.markdown(f"**Source snippet**  \n{display_value(update.get('source_snippet'))}")

            with st.expander("Edit Proposed Date"):
                edited_due = st.text_input(
                    "New due date",
                    value=update.get("new_due_at") or "",
                    key=f"edit-update-due-{update['id']}",
                    placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM",
                )
                if st.button("Accept Edited Deadline Update", key=f"accept-edited-update-{update['id']}"):
                    if accept_task_update(update["id"], edited_due):
                        st.success("Task deadline updated.")
                        st.rerun()
                    st.error("Could not accept this update.")

            actions = st.columns(2)
            with actions[0]:
                if st.button("Accept Deadline Update", key=f"accept-update-{update['id']}", type="primary"):
                    if accept_task_update(update["id"]):
                        st.success("Task deadline updated.")
                        st.rerun()
                    st.error("Could not accept this update.")
            with actions[1]:
                if st.button("Ignore Update", key=f"ignore-update-{update['id']}"):
                    update_task_update_status(update["id"], "ignored")
                    st.success("Update ignored.")
                    st.rerun()


def render_check_updates():
    st.subheader("Check for Course Updates")
    st.caption(
        "Paste a new announcement or updated course material. The app will flag "
        "new tasks and possible deadline changes. Nothing changes until you "
        "approve it."
    )
    title = st.text_input("Update title", placeholder="Example: Week 4 announcement")
    raw_text = st.text_area("Announcement or updated material", height=260)

    if st.button("Check for New Tasks or Deadline Changes", type="primary"):
        raw_text = (raw_text or "").strip()
        if not raw_text:
            st.warning("Paste announcement text first.")
            return

        document_id = save_material_document(
            title=title or "Course update",
            document_type="announcement",
            raw_text=raw_text,
            file_type="text",
        )
        try:
            extracted_tasks = extract_suggestions_from_material(raw_text, "announcement")
        except Exception as error:
            st.error(f"Could not check this update: {error}")
            return

        confirmed_tasks = active_confirmed_tasks()
        new_count = 0
        update_count = 0
        duplicate_count = 0
        for task in extracted_tasks:
            match, score = find_possible_task_match(task, confirmed_tasks)
            old_due = match.get("due_at") if match else None
            new_due = task.get("due_at")
            if match and new_due and date_key(old_due) != date_key(new_due):
                create_task_update({
                    "task_id": match["id"],
                    "document_id": document_id,
                    "old_due_at": old_due,
                    "new_due_at": new_due,
                    "source_snippet": task.get("source_snippet"),
                    "confidence": task.get("confidence") or "medium",
                    "reason": (
                        f"Possible deadline change from announcement "
                        f"({score:.0%} title match)."
                    ),
                })
                update_count += 1
            elif match:
                duplicate_count += 1
            else:
                create_task(v0_task_payload(
                    task,
                    "announcement",
                    f"New task suggestion from document #{document_id}.",
                ))
                new_count += 1

        st.success(
            f"Found {new_count} new task suggestions, "
            f"{update_count} possible deadline updates, "
            f"and {duplicate_count} likely duplicates."
        )

    st.markdown("### Pending Updates")
    render_pending_task_updates()


def file_extraction_key(filename, extracted_text):
    digest = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()
    return f"{filename}:{digest}"


def save_extracted_tasks(tasks):
    saved_count = 0
    for task in tasks:
        create_task(task)
        saved_count += 1
    return saved_count


def render_extracted_task_review(tasks):
    if not tasks:
        st.info("No suggested tasks were found in this PDF.")
        return

    st.markdown("### Extracted Suggested Tasks")
    for index, task in enumerate(tasks, start=1):
        with st.container(border=True):
            st.markdown(f"#### {index}. {display_value(task.get('title'))}")
            columns = st.columns(3)
            columns[0].markdown(f"**Course**  \n{display_value(task.get('course'))}")
            columns[1].markdown(f"**Type**  \n{display_value(task.get('task_type'))}")
            columns[2].markdown(
                f"**Confidence**  \n{display_value(task.get('confidence'))}"
            )

            columns = st.columns(3)
            columns[0].markdown(
                f"**Due**  \n{display_task_datetime(task.get('due_at'))}"
            )
            columns[1].markdown(
                f"**Minutes**  \n{display_value(task.get('estimated_minutes'))}"
            )
            columns[2].markdown(
                f"**Priority**  \n{display_value(task.get('priority'))}"
            )

            st.markdown(f"**Notes**  \n{display_value(task.get('notes'))}")
            st.markdown(
                f"**Source Snippet**  \n{display_value(task.get('source_snippet'))}"
            )


def render_file_upload():
    st.subheader("Files / Syllabus Upload")
    uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])

    if uploaded_file is None:
        st.info("Upload a syllabus or course PDF to preview its extracted text.")
        return

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / safe_filename(uploaded_file.name)
    saved_path.write_bytes(uploaded_file.getbuffer())

    try:
        metadata = get_file_metadata(saved_path)
        extracted_text = extract_text_from_pdf(saved_path)
    except Exception as error:
        st.error(f"Could not read this PDF: {error}")
        return

    preview = extracted_text[:3000]
    extraction_key = file_extraction_key(metadata["filename"], extracted_text)

    st.success("PDF uploaded successfully.")
    st.markdown(f"**Filename:** {metadata['filename']}")
    st.markdown(f"**File size:** {metadata['file_size']:,} bytes")
    st.markdown(f"**Pages:** {metadata['page_count']}")
    st.text_area(
        "Extracted text preview",
        value=preview or "No extractable text found in this PDF.",
        height=300,
    )

    if not extracted_text:
        st.warning("This PDF has no extractable text, so AI extraction is disabled.")
        return

    extraction_cache = st.session_state.setdefault("syllabus_extractions", {})
    saved_extractions = st.session_state.setdefault("saved_extraction_keys", [])

    if st.button("Extract Suggested Tasks"):
        if extraction_key in extraction_cache:
            extracted_tasks = extraction_cache[extraction_key]
            st.info("Using cached extraction results for this PDF.")
        else:
            with st.spinner("Extracting suggested tasks from syllabus text..."):
                try:
                    extracted_tasks = extract_tasks_from_text(
                        extracted_text,
                        source="syllabus",
                    )
                except Exception as error:
                    st.error(f"Could not extract suggested tasks: {error}")
                    return
            extraction_cache[extraction_key] = extracted_tasks

        st.session_state.latest_extraction_key = extraction_key
        st.session_state.latest_extracted_tasks = extracted_tasks

        if not extracted_tasks:
            st.info("No suggested tasks were found in this PDF.")
        elif extraction_key in saved_extractions:
            st.info("These suggested tasks were already saved in this session.")
        else:
            saved_count = save_extracted_tasks(extracted_tasks)
            saved_extractions.append(extraction_key)
            st.success(
                f"Saved {saved_count} suggested tasks. "
                "Review them on the Suggested Tasks page."
            )

    if st.session_state.get("latest_extraction_key") == extraction_key:
        render_extracted_task_review(
            st.session_state.get("latest_extracted_tasks", [])
        )


def render_quercus_sync():
    st.subheader("Quercus Sync")
    st.info(
        "This sync is read-only. It imports assignments from Quercus/Canvas "
        "into your local task database."
    )

    base_url_configured = has_canvas_base_url()
    token_present = has_canvas_api_token()
    base_url = get_canvas_base_url()

    st.markdown(
        f"**CANVAS_BASE_URL configured:** "
        f"{'Yes' if base_url_configured else 'No'}"
    )
    if base_url_configured:
        st.markdown(f"**Canvas base URL:** {base_url}")
    st.markdown(f"**CANVAS_API_TOKEN present:** {'Yes' if token_present else 'No'}")

    if not base_url_configured:
        st.warning("Add CANVAS_BASE_URL to your .env file before syncing.")
    if not token_present:
        st.warning(
            "Add CANVAS_API_TOKEN to your .env file before syncing. "
            "The token is used only for read-only Canvas API requests."
        )

    if st.button(
        "Sync Assignments",
        disabled=not (base_url_configured and token_present),
    ):
        with st.spinner("Fetching assignments from Quercus/Canvas..."):
            assignments, summary = get_all_assignments()

        new_tasks_created = 0
        duplicates_skipped = 0
        for assignment in assignments:
            if create_canvas_assignment_task(assignment):
                new_tasks_created += 1
            else:
                duplicates_skipped += 1

        st.markdown("### Sync Summary")
        st.markdown(f"**Courses found:** {summary['courses_found']}")
        st.markdown(f"**Assignments found:** {summary['assignments_found']}")
        st.markdown(f"**New tasks created:** {new_tasks_created}")
        st.markdown(f"**Duplicates skipped:** {duplicates_skipped}")

        if summary["errors"]:
            for error in summary["errors"]:
                st.error(error)
        elif summary["assignments_found"] == 0:
            st.info(
                "No assignments were found for the active courses returned by Canvas."
            )
        else:
            st.success("Quercus/Canvas assignment sync finished.")


def render_intake_summary(summary):
    st.markdown("### Intake Summary")
    columns = st.columns(7)
    columns[0].metric("Candidates Found", summary["candidates_found"])
    columns[1].metric(
        "Confirmed Created",
        summary["confirmed_tasks_auto_created"],
    )
    columns[2].metric("Suggested Created", summary["suggested_tasks_created"])
    columns[3].metric("Pending", summary["pending_candidates_created"])
    columns[4].metric("Duplicates", summary["duplicates_skipped"])
    columns[5].metric("Archived Skipped", summary.get("skipped_archived_course", 0))
    columns[6].metric("Past Due Skipped", summary.get("skipped_past_due", 0))
    st.markdown(f"**Tasks rescored:** {summary['tasks_rescored']}")

    if summary["errors"]:
        for error in summary["errors"]:
            st.warning(error)


def parse_refresh_json(value, default):
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    return parsed


def daily_refresh_status_label(record):
    if not record:
        return "Not synced today"
    status = record.get("status") or "-"
    updated_at = display_datetime(record.get("updated_at"))
    return f"{status} at {updated_at}"


def run_daily_quercus_refresh(trigger_source="manual"):
    refresh_date = date.today().isoformat()
    if not (has_canvas_base_url() and has_canvas_api_token()):
        return create_or_update_daily_refresh_run({
            "refresh_date": refresh_date,
            "status": "skipped",
            "trigger_source": trigger_source,
            "summary": {
                "message": "Canvas credentials are not configured.",
            },
            "errors": [
                "Add CANVAS_BASE_URL and CANVAS_API_TOKEN to .env to enable daily refresh."
            ],
        })

    try:
        summary = run_auto_task_intake()
        cleanup = ignore_past_quercus_intake_items(date.today())
        summary["past_quercus_cleanup"] = cleanup
        errors = summary.get("errors") or []
        status = "completed" if not errors else "completed_with_warnings"
    except Exception as error:
        summary = {}
        errors = [str(error)]
        status = "failed"

    return create_or_update_daily_refresh_run({
        "refresh_date": refresh_date,
        "status": status,
        "trigger_source": trigger_source,
        "summary": summary,
        "errors": errors,
    })


def maybe_run_daily_quercus_refresh():
    if os.environ.get("STUDENT_TASK_AGENT_DISABLE_AUTO_REFRESH") == "1":
        return

    refresh_date = date.today().isoformat()
    session_key = f"daily_refresh_checked_{refresh_date}"
    if st.session_state.get(session_key):
        return

    st.session_state[session_key] = True
    if not (has_canvas_base_url() and has_canvas_api_token()):
        return
    if get_daily_refresh_run_by_date(refresh_date):
        return

    with st.spinner("Refreshing Quercus assignments for today..."):
        run_daily_quercus_refresh(trigger_source="auto_app_start")


def render_daily_refresh_status():
    refresh_date = date.today().isoformat()
    record = get_daily_refresh_run_by_date(refresh_date)

    with st.expander("Quercus Refresh", expanded=False):
        st.caption(
            "Runs at most once per day when the app opens. It reads Quercus, "
            "runs Auto Task Intake, skips old due dates, prevents duplicates, "
            "and rescales urgency. It never writes to Quercus."
        )

        columns = st.columns(3)
        columns[0].markdown(
            f"**Canvas URL**  \n{'Configured' if has_canvas_base_url() else 'Missing'}"
        )
        columns[1].markdown(
            f"**Canvas Token**  \n{'Present' if has_canvas_api_token() else 'Missing'}"
        )
        columns[2].markdown(f"**Today**  \n{daily_refresh_status_label(record)}")

        if record:
            summary = parse_refresh_json(record.get("summary_json"), {})
            errors = parse_refresh_json(record.get("errors_json"), [])
            if summary:
                st.markdown("**Latest summary**")
                summary_columns = st.columns(4)
                summary_columns[0].metric(
                    "Confirmed",
                    summary.get("confirmed_tasks_auto_created", 0),
                )
                summary_columns[1].metric(
                    "Pending",
                    summary.get("pending_candidates_created", 0),
                )
                summary_columns[2].metric(
                    "Duplicates",
                    summary.get("duplicates_skipped", 0),
                )
                summary_columns[3].metric(
                    "Rescored",
                    summary.get("tasks_rescored", 0),
                )
            for error in errors:
                st.warning(error)

        disabled = not (has_canvas_base_url() and has_canvas_api_token())
        if st.button("Sync Now", disabled=disabled):
            with st.spinner("Refreshing Quercus and task intake..."):
                run_daily_quercus_refresh(trigger_source="manual")
            st.success("Daily refresh finished.")
            st.rerun()


def render_task_intake_controls():
    st.markdown("### Auto Intake Controls")
    st.info(
        "Auto Intake discovers tasks from trusted sources, scores urgency, "
        "and inserts clear trusted tasks as confirmed while keeping uncertain "
        "items pending for review. It does not call AI automatically."
    )
    st.caption(
        "For now, Auto Intake runs only when you click the button. Later, a "
        "deployed version can run scheduled sync automatically."
    )

    if st.button("Run Auto Task Intake"):
        with st.spinner("Running auto task intake..."):
            summary = run_auto_task_intake()
        st.session_state.latest_intake_summary = summary
        st.success("Auto Task Intake finished.")

    if st.session_state.get("latest_intake_summary"):
        render_intake_summary(st.session_state.latest_intake_summary)


def render_past_quercus_cleanup():
    st.markdown("### Past Quercus Cleanup")
    st.caption(
        "Auto Intake now skips Quercus/Canvas items with due dates before today. "
        "Use this only if you want to hide old Quercus imports that were already "
        "created before this rule existed."
    )

    if st.button("Ignore Past Quercus Imports"):
        result = ignore_past_quercus_intake_items(date.today())
        st.success(
            "Cleanup finished. "
            f"Ignored {result['tasks_ignored']} old tasks and "
            f"{result['candidates_ignored']} old pending candidates."
        )
        st.rerun()


def render_course_archive():
    st.markdown("### Course Archive")
    st.caption(
        "Archive old or irrelevant courses so their active tasks and pending "
        "candidates stop appearing in plans. This does not delete raw data."
    )

    summaries = get_course_summaries()
    if not summaries:
        st.info("No courses found yet.")
        return

    for summary in summaries:
        with st.container(border=True):
            title = summary["course_name"]
            if summary["archived"]:
                title = f"{title} (archived)"
            st.markdown(f"#### {display_value(title)}")

            columns = st.columns(5)
            columns[0].metric("Active", summary["active_tasks"])
            columns[1].metric("Pending", summary["pending_candidates"])
            columns[2].metric("Ignored", summary["ignored_tasks"])
            columns[3].metric("Done", summary["done_tasks"])
            columns[4].metric("Total", summary["total_tasks"])

            if summary["archived"]:
                if st.button(
                    "Unarchive Course",
                    key=f"unarchive-course-{summary['course_key']}",
                ):
                    unarchive_course(summary["course_name"])
                    st.success(
                        f"Unarchived {summary['course_name']}. "
                        "Previously ignored tasks stay ignored."
                    )
                    st.rerun()
            else:
                if st.button(
                    "Archive Course",
                    key=f"archive-course-{summary['course_key']}",
                ):
                    result = archive_course(
                        summary["course_name"],
                        reason="Archived manually from Task Intake.",
                    )
                    st.success(
                        f"Archived {result['course_name']}. "
                        f"Ignored {result['tasks_ignored']} active tasks and "
                        f"{result['candidates_ignored']} pending candidates."
                    )
                    st.rerun()


def render_candidate_fields(candidate):
    columns = st.columns(4)
    columns[0].markdown(f"**Course**  \n{display_value(candidate['course'])}")
    columns[1].markdown(f"**Source**  \n{display_value(candidate['source'])}")
    columns[2].markdown(
        f"**Confidence**  \n{display_value(candidate['confidence'])}"
    )
    columns[3].markdown(
        f"**Due**  \n{display_task_datetime(candidate['due_at'])}"
    )

    columns = st.columns(4)
    columns[0].markdown(
        f"**Urgency**  \n{display_value(candidate['urgency_label'])}"
    )
    columns[1].markdown(
        f"**Score**  \n{display_value(candidate['urgency_score'])}"
    )
    columns[2].markdown(
        "**Recommended**  \n"
        f"{display_value(candidate['recommended_status'])}"
    )
    columns[3].markdown(
        f"**Type**  \n{display_value(candidate['task_type'])}"
    )

    st.markdown(f"**Notes**  \n{display_value(candidate['notes'])}")
    if candidate.get("source_url"):
        st.markdown(f"**Source URL**  \n{candidate['source_url']}")


def candidate_option_label(candidate):
    due = candidate.get("due_at") or "no due date"
    course = candidate.get("course") or "No course"
    source = candidate.get("source") or "-"
    return f"{candidate['title']} | {course} | {source} | {due}"


def candidate_filter_options(candidates, key):
    values = sorted({
        candidate.get(key) or ("No course" if key == "course" else "")
        for candidate in candidates
    })
    values = [value for value in values if value]
    prefix = "All courses" if key == "course" else "All sources"
    return [prefix, *values]


def filtered_pending_candidates():
    all_candidates = get_task_candidates(decision_status="pending")
    if not all_candidates:
        return [], [], "All courses", "All sources", "Any due date"

    course_filter = st.selectbox(
        "Candidate course filter",
        options=candidate_filter_options(all_candidates, "course"),
        key="candidate-course-filter",
    )
    source_filter = st.selectbox(
        "Candidate source filter",
        options=candidate_filter_options(all_candidates, "source"),
        key="candidate-source-filter",
    )
    due_filter = st.selectbox(
        "Candidate due date filter",
        options=[
            "Any due date",
            "No due date",
            "Due today or earlier",
            "Future due date",
        ],
        key="candidate-due-filter",
    )
    query_due_filter = None if due_filter == "Any due date" else due_filter
    candidates = get_task_candidates(
        decision_status="pending",
        course=course_filter,
        source=source_filter,
        due_filter=query_due_filter,
    )
    return candidates, all_candidates, course_filter, source_filter, due_filter


def render_batch_candidate_actions(candidates):
    if not candidates:
        return

    candidate_lookup = {candidate["id"]: candidate for candidate in candidates}
    selected_ids = st.multiselect(
        "Select candidates for batch action",
        options=list(candidate_lookup.keys()),
        format_func=lambda candidate_id: candidate_option_label(
            candidate_lookup[candidate_id]
        ),
        key="batch-candidate-selection",
    )
    if not selected_ids:
        return

    columns = st.columns(3)
    with columns[0]:
        if st.button("Batch Accept as Confirmed"):
            created = 0
            skipped = 0
            for candidate_id in selected_ids:
                if promote_candidate_to_task(
                    candidate_id,
                    status="confirmed",
                    allow_untrusted_confirm=True,
                ):
                    created += 1
                else:
                    skipped += 1
            st.success(f"Created {created} confirmed tasks. Skipped {skipped}.")
            st.rerun()
    with columns[1]:
        if st.button("Batch Accept as Suggested"):
            created = 0
            skipped = 0
            for candidate_id in selected_ids:
                if promote_candidate_to_task(candidate_id, status="suggested"):
                    created += 1
                else:
                    skipped += 1
            st.success(f"Created {created} suggested tasks. Skipped {skipped}.")
            st.rerun()
    with columns[2]:
        if st.button("Batch Ignore"):
            for candidate_id in selected_ids:
                update_task_candidate_decision(candidate_id, "ignored")
            st.success(f"Ignored {len(selected_ids)} candidates.")
            st.rerun()


def render_pending_task_candidates():
    st.markdown("### Pending Task Candidates")
    candidates, all_candidates, _, _, _ = filtered_pending_candidates()
    if not all_candidates:
        st.info("No pending task candidates right now.")
        return
    if not candidates:
        st.info("No candidates match the current filters.")
        return

    st.caption(f"Showing {len(candidates)} of {len(all_candidates)} pending candidates.")
    render_batch_candidate_actions(candidates)

    for candidate in candidates:
        with st.container(border=True):
            st.markdown(f"#### {display_value(candidate['title'])}")
            render_candidate_fields(candidate)

            columns = st.columns(3)
            with columns[0]:
                if st.button(
                    "Accept as Confirmed",
                    key=f"candidate-confirmed-{candidate['id']}",
                ):
                    task_id = promote_candidate_to_task(
                        candidate["id"],
                        status="confirmed",
                        allow_untrusted_confirm=True,
                    )
                    if task_id:
                        st.success("Candidate accepted as confirmed task.")
                    else:
                        st.info(
                            "Candidate was not promoted, likely because it is "
                            "not trusted enough or already exists."
                        )
                    st.rerun()
            with columns[1]:
                if st.button(
                    "Accept as Suggested",
                    key=f"candidate-suggested-{candidate['id']}",
                ):
                    task_id = promote_candidate_to_task(
                        candidate["id"],
                        status="suggested",
                    )
                    if task_id:
                        st.success("Candidate accepted as suggested task.")
                    else:
                        st.info("Candidate was not promoted because it already exists.")
                    st.rerun()
            with columns[2]:
                if st.button("Ignore", key=f"candidate-ignore-{candidate['id']}"):
                    update_task_candidate_decision(candidate["id"], "ignored")
                    st.success("Candidate ignored.")
                    st.rerun()


def top_urgent_tasks(limit=10):
    tasks = [
        task for task in get_all_tasks()
        if task.get("status") not in ("done", "ignored")
    ]
    return sorted(
        tasks,
        key=lambda task: (
            -task_urgency(task)[0],
            task.get("due_at") or "9999-12-31",
            -(int(task.get("priority") or 0)),
            task.get("title") or "",
        ),
    )[:limit]


def render_top_urgent_tasks():
    st.markdown("### Top Urgent Tasks")
    tasks = top_urgent_tasks(limit=10)
    if not tasks:
        st.info("No active tasks to score yet.")
        return

    for task in tasks:
        urgency_score, urgency_label = task_urgency(task)
        with st.container(border=True):
            st.markdown(f"#### {display_value(task['title'])}")
            columns = st.columns(4)
            columns[0].markdown(f"**Course**  \n{display_value(task['course'])}")
            columns[1].markdown(
                f"**Due**  \n{display_task_datetime(task['due_at'])}"
            )
            columns[2].markdown(
                f"**Planned**  \n{display_task_datetime(task['planned_date'])}"
            )
            columns[3].markdown(
                f"**Priority**  \n{display_value(task['priority'])}"
            )

            columns = st.columns(3)
            columns[0].markdown(f"**Status**  \n{display_value(task['status'])}")
            columns[1].markdown(f"**Urgency**  \n{display_value(urgency_label)}")
            columns[2].markdown(f"**Score**  \n{urgency_score:.1f}")


def render_rescore_tasks():
    st.markdown("### Rescore Tasks")
    if st.button("Rescore All Active Tasks"):
        count = rescore_all_active_tasks()
        st.success(f"Rescored {count} active tasks.")
        st.rerun()


def render_task_intake():
    st.subheader("Task Intake")
    render_task_intake_controls()
    render_past_quercus_cleanup()
    render_course_archive()
    render_pending_task_candidates()
    render_top_urgent_tasks()
    render_rescore_tasks()


def task_option_label(task):
    course = task.get("course") or "No course"
    status = task.get("status") or "-"
    return f"{task['title']} | {course} | {status}"


def active_tasks():
    return [
        task for task in get_all_tasks()
        if task.get("status") not in ("done", "ignored")
    ]


def get_task_by_id(task_id):
    if task_id in (None, ""):
        return None
    task_id = int(task_id)
    for task in get_all_tasks():
        if int(task.get("id") or 0) == task_id:
            return task
    return None


def render_session_summary(session):
    task = get_task_by_id(session.get("task_id"))
    first_action = first_action_for_task(task) if task else "Stay with the current task."
    elapsed = elapsed_minutes_since(session["start_time"])
    st.markdown(
        (
            '<div class="calm-hero">'
            '<div class="calm-eyebrow">Focus Session</div>'
            f'<div class="calm-objective">{escape_html(session["task_title"])}</div>'
            f'<div class="focus-timer">{elapsed} min</div>'
            f'<div class="calm-first-action">{escape_html(first_action)}</div>'
            f'<div class="calm-meta">Course: {escape_html(session.get("course"))} | '
            f'Started {escape_html(display_datetime(session.get("start_time")))} | '
            f'Planned {escape_html(session.get("planned_minutes"))} min</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def render_start_focus_session():
    tasks = active_tasks()
    if not tasks:
        st.info("No active tasks are available for a focus session.")
        return

    task_lookup = {task["id"]: task for task in tasks}
    selected_task_id = st.selectbox(
        "Task",
        options=list(task_lookup.keys()),
        format_func=lambda task_id: task_option_label(task_lookup[task_id]),
    )
    planned_minutes = st.number_input(
        "Planned minutes",
        min_value=1,
        value=25,
        step=5,
    )

    if st.button("Start Focus Session", type="primary"):
        task = task_lookup[selected_task_id]
        try:
            start_focus_session_for_task(task, planned_minutes)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Focus session started.")
            st.rerun()


def render_end_focus_session(active_session):
    render_session_summary(active_session)

    with st.form("end_focus_session_form"):
        completion_status = st.selectbox(
            "Completion status",
            options=["completed", "partial", "not_completed", "blocked"],
        )
        blocker = st.text_input("Blocker")
        notes = st.text_area("Notes")
        mark_done = False
        if completion_status == "completed":
            mark_done = st.checkbox("Mark task as done", value=True)

        submitted = st.form_submit_button("End Session")

    if submitted:
        try:
            completed_session = complete_study_session(
                active_session["id"],
                completion_status,
                blocker,
                notes,
            )
            task_id = active_session.get("task_id")
            if task_id and completion_status == "completed" and mark_done:
                update_task_status(task_id, "done")
            elif task_id and completion_status in (
                "partial",
                "not_completed",
                "blocked",
            ):
                update_task_status(task_id, "in_progress")
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(
                "Focus session ended. "
                f"Actual time: {display_value(completed_session['actual_minutes'])} min."
            )
            st.rerun()


def render_recent_study_sessions():
    st.markdown("### Recent Sessions")
    sessions = get_recent_study_sessions(limit=20)
    if not sessions:
        st.info("No study sessions logged yet.")
        return

    for session in sessions:
        with st.container(border=True):
            st.markdown(f"**{display_value(session['task_title'])}**")
            columns = st.columns(4)
            columns[0].markdown(f"**Course**  \n{display_value(session['course'])}")
            columns[1].markdown(
                f"**Actual**  \n{display_value(session['actual_minutes'])} min"
            )
            columns[2].markdown(
                "**Status**  \n"
                f"{display_value(session['completion_status'])}"
            )
            columns[3].markdown(
                f"**Created**  \n{display_datetime(session['created_at'])}"
            )

            columns = st.columns(2)
            columns[0].markdown(
                f"**Blocker**  \n{display_value(session['blocker'])}"
            )
            columns[1].markdown(f"**Notes**  \n{display_value(session['notes'])}")


def render_focus_session():
    st.subheader("Focus Session")
    active_session = get_active_study_session()

    if active_session:
        render_end_focus_session(active_session)
    else:
        st.markdown("### Start Session")
        render_start_focus_session()

    with st.expander("Recent Sessions", expanded=False):
        render_recent_study_sessions()


def today_task_summary():
    today = date.today().isoformat()
    tasks = get_all_tasks()
    completed_today = [
        task for task in tasks
        if task.get("status") == "done"
        and str(task.get("updated_at") or "").startswith(today)
    ]
    in_progress = [
        task for task in tasks
        if task.get("status") == "in_progress"
    ]
    overdue = [
        task for task in tasks
        if task.get("status") not in ("done", "ignored")
        and task.get("due_at")
        and task["due_at"] < today
    ]
    recent_focus_today = [
        session for session in get_recent_study_sessions(limit=20)
        if str(session.get("created_at") or "").startswith(today)
    ]

    return {
        "completed_today": len(completed_today),
        "in_progress": len(in_progress),
        "overdue": len(overdue),
        "active_session": get_active_study_session(),
        "focus_sessions_today": len(recent_focus_today),
    }


def render_today_task_summary():
    summary = today_task_summary()
    st.markdown("### Today's Task Summary")
    columns = st.columns(4)
    columns[0].metric("Completed Today", summary["completed_today"])
    columns[1].metric("In Progress", summary["in_progress"])
    columns[2].metric("Overdue", summary["overdue"])
    columns[3].metric("Focus Sessions", summary["focus_sessions_today"])

    if summary["active_session"]:
        st.info(
            "A focus session is currently active for "
            f"{summary['active_session']['task_title']}."
        )


def review_text_value(review, key):
    if not review:
        return ""
    return review.get(key) or ""


def review_mood_index(review):
    moods = ["low", "medium", "high"]
    if not review or review.get("mood_energy") not in moods:
        return 1
    return moods.index(review["mood_energy"])


def render_daily_review_form():
    st.markdown("### Today's Review")
    selected_date = st.date_input("Review date", value=date.today())
    review_date = selected_date.isoformat()
    existing_review = get_daily_review_by_date(review_date)

    if existing_review:
        st.caption("A review already exists for this date. Saving will update it.")

    with st.form("daily_review_form"):
        completed_summary = st.text_area(
            "What did you complete today?",
            value=review_text_value(existing_review, "completed_summary"),
        )
        missed_tasks = st.text_area(
            "What did you miss or postpone?",
            value=review_text_value(existing_review, "missed_tasks"),
        )
        blockers = st.text_area(
            "What blocked you?",
            value=review_text_value(existing_review, "blockers"),
        )
        avoidance_notes = st.text_area(
            "Did you avoid anything important?",
            value=review_text_value(existing_review, "avoidance_notes"),
        )
        tomorrow_top_priority = st.text_input(
            "What is tomorrow's top priority?",
            value=review_text_value(existing_review, "tomorrow_top_priority"),
        )
        mood_energy = st.selectbox(
            "Mood / energy",
            options=["low", "medium", "high"],
            index=review_mood_index(existing_review),
        )
        focus_rating = st.slider(
            "Focus rating",
            min_value=1,
            max_value=5,
            value=existing_review.get("focus_rating") or 3
            if existing_review else 3,
        )
        submitted = st.form_submit_button("Save Daily Review")

    if submitted:
        try:
            create_or_update_daily_review({
                "review_date": review_date,
                "completed_summary": completed_summary,
                "missed_tasks": missed_tasks,
                "blockers": blockers,
                "avoidance_notes": avoidance_notes,
                "tomorrow_top_priority": tomorrow_top_priority,
                "mood_energy": mood_energy,
                "focus_rating": focus_rating,
            })
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Daily review saved.")


def render_recent_daily_reviews():
    st.markdown("### Recent Reviews")
    reviews = get_recent_daily_reviews(limit=14)
    if not reviews:
        st.info("No daily reviews saved yet.")
        return

    for review in reviews:
        with st.container(border=True):
            st.markdown(f"#### {display_value(review['review_date'])}")
            columns = st.columns(2)
            columns[0].markdown(
                "**Completed**  \n"
                f"{display_value(review['completed_summary'])}"
            )
            columns[1].markdown(
                "**Missed / Postponed**  \n"
                f"{display_value(review['missed_tasks'])}"
            )

            columns = st.columns(2)
            columns[0].markdown(
                f"**Blockers**  \n{display_value(review['blockers'])}"
            )
            columns[1].markdown(
                "**Avoidance Notes**  \n"
                f"{display_value(review['avoidance_notes'])}"
            )

            columns = st.columns(3)
            columns[0].markdown(
                "**Tomorrow Priority**  \n"
                f"{display_value(review['tomorrow_top_priority'])}"
            )
            columns[1].markdown(
                f"**Mood / Energy**  \n{display_value(review['mood_energy'])}"
            )
            columns[2].markdown(
                f"**Focus Rating**  \n{display_value(review['focus_rating'])}"
            )


def render_daily_review_export():
    if st.button("Export Daily Reviews CSV"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = EXPORT_DIR / f"daily_reviews_{timestamp}.csv"
        try:
            exported_path = export_daily_reviews_to_csv(output_path)
        except Exception as error:
            st.error(f"Could not export daily reviews: {error}")
        else:
            st.success(f"Exported daily reviews to {exported_path}")


def render_daily_review():
    st.subheader("Daily Review")
    render_today_task_summary()
    render_daily_review_form()
    with st.expander("Export and Recent Reviews", expanded=False):
        render_daily_review_export()
        render_recent_daily_reviews()


def render_agent_memory_info():
    st.info(
        "Agent Memory stores long-term patterns, preferences, goals, and "
        "rules. Raw data remains in tasks, focus sessions, and daily reviews. "
        "Future AI Boss features can use both raw data and active memories, "
        "but this page does not call AI or generate memories automatically."
    )


def render_add_agent_memory():
    st.markdown("### Add Memory")
    with st.form("agent_memory_form"):
        memory_type = st.selectbox("Memory type", options=MEMORY_TYPES)
        memory_key = st.text_input("Memory key")
        memory_value = st.text_area("Memory value")
        confidence = st.selectbox(
            "Confidence",
            options=["high", "medium", "low"],
            index=1,
        )
        source = st.selectbox("Source", options=MEMORY_SOURCES)
        submitted = st.form_submit_button("Save Memory")

    if submitted:
        try:
            create_agent_memory({
                "memory_type": memory_type,
                "memory_key": memory_key,
                "memory_value": memory_value,
                "confidence": confidence,
                "source": source,
                "is_active": 1,
            })
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Agent memory saved.")
            st.rerun()


def render_active_agent_memory():
    st.markdown("### Active Memories")
    memories = get_active_agent_memory()
    if not memories:
        st.info("No active agent memories yet.")
        return

    for memory in memories:
        with st.container(border=True):
            st.markdown(
                f"#### {display_value(memory['memory_type'])}: "
                f"{display_value(memory['memory_key'])}"
            )
            st.markdown(display_value(memory["memory_value"]))

            columns = st.columns(3)
            columns[0].markdown(
                f"**Confidence**  \n{display_value(memory['confidence'])}"
            )
            columns[1].markdown(f"**Source**  \n{display_value(memory['source'])}")
            columns[2].markdown(
                f"**Updated**  \n{display_datetime(memory['updated_at'])}"
            )

            if st.button("Deactivate", key=f"deactivate-memory-{memory['id']}"):
                deactivate_agent_memory(memory["id"])
                st.success("Agent memory deactivated.")
                st.rerun()


def seed_default_agent_memories():
    created_count = 0
    skipped_count = 0
    for memory in DEFAULT_AGENT_MEMORIES:
        if memory_exists(memory["memory_type"], memory["memory_key"]):
            skipped_count += 1
            continue

        create_agent_memory(memory)
        created_count += 1

    return created_count, skipped_count


def render_seed_agent_memory():
    st.markdown("### Seed Default AI Boss Memories")
    if st.button("Seed Default AI Boss Memories"):
        created_count, skipped_count = seed_default_agent_memories()
        st.success(
            f"Created {created_count} default memories. "
            f"Skipped {skipped_count} existing memories."
        )
        st.rerun()


def render_agent_memory():
    st.subheader("Agent Memory")
    render_agent_memory_info()
    render_add_agent_memory()
    render_active_agent_memory()
    render_seed_agent_memory()


def render_tasks_workspace():
    st.subheader("Tasks")
    task_view = st.radio(
        "Task view",
        options=["Today", "This Week", "Confirmed Tasks", "Suggested Tasks", "All Tasks"],
        horizontal=True,
        label_visibility="collapsed",
    )
    render_dashboard_view(task_view)


def render_memory_workspace():
    st.subheader("Memory")
    memory_view = st.radio(
        "Memory view",
        options=["Agent Memory", "Feedback Loop", "Daily Review"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if memory_view == "Agent Memory":
        render_agent_memory()
    elif memory_view == "Feedback Loop":
        render_feedback_loop()
    else:
        render_daily_review()


def render_settings_workspace():
    st.subheader("Settings")
    st.caption("Course Task Inbox keeps the main workflow small and review-first.")

    st.markdown("### Connections")
    key_present, key_message = ai_chat_api_key_status()
    columns = st.columns(1)
    columns[0].metric("OpenAI Key", "Yes" if key_present else "No")
    if not key_present:
        st.info(key_message)
    st.caption(
        "OpenAI is only required for Add Material extraction and Check Updates. "
        "Reviewing suggestions, confirming, editing, ignoring, and viewing "
        "tasks all work locally without an API key."
    )

    st.markdown("### Product Scope")
    st.write(
        "The main app is now focused on adding course material, reviewing AI "
        "suggestions, keeping confirmed tasks, and approving deadline updates."
    )

    with st.expander("Developer / Experimental", expanded=False):
        show_experimental = st.checkbox("Show hidden experimental pages")
        if not show_experimental:
            st.caption(
                "Hidden pages are preserved for development only. They are not "
                "part of the v0 Course Task Inbox workflow."
            )
            return

        st.warning(
            "Experimental pages may contain older non-v0 workflows. Use them "
            "only for development."
        )
        status_columns = st.columns(2)
        status_columns[0].metric("Canvas URL", "Yes" if has_canvas_base_url() else "No")
        status_columns[1].metric("Canvas Token", "Yes" if has_canvas_api_token() else "No")
        experimental_options = [
            option for option in EXPERIMENTAL_MENU_OPTIONS
            if option != "Settings"
        ]
        choice = st.selectbox("Experimental page", experimental_options)
        render_advanced_choice(choice)


def render_advanced_workspace():
    st.subheader("Advanced")
    choice = st.selectbox("Advanced page", ADVANCED_MENU_OPTIONS)
    render_advanced_choice(choice)


def render_advanced_choice(choice):
    if choice == "Command Center":
        render_command_center()
    elif choice == "Tasks":
        render_tasks_workspace()
    elif choice == "Settings":
        render_settings_workspace()
    elif choice == "Memory":
        render_memory_workspace()
    elif choice == "Daily Command":
        render_daily_command()
    elif choice == "7-Day Timeline":
        render_7_day_timeline()
    elif choice == "Behavior Design":
        render_behavior_design()
    elif choice == "Feedback Loop":
        render_feedback_loop()
    elif choice == "Today Plan":
        render_today_plan()
    elif choice == "AI Boss":
        render_ai_boss()
    elif choice == "Task Intake":
        render_task_intake()
    elif choice == "Focus Session":
        render_focus_session()
    elif choice == "Daily Review":
        render_daily_review()
    elif choice == "Agent Memory":
        render_agent_memory()
    elif choice == "Files / Syllabus Upload":
        render_file_upload()
    elif choice == "Quercus Sync":
        render_quercus_sync()
    elif choice == "Add Task":
        render_add_task_form()
    else:
        render_dashboard_view(choice)


def main():
    st.set_page_config(
        page_title="Course Task Inbox",
        page_icon="ST",
        layout="centered",
    )
    inject_calm_command_css()
    st.title("Course Task Inbox")

    init_db()
    auto_finished_count = auto_finish_past_due_tasks()
    if auto_finished_count:
        st.info(
            f"Automatically finished {auto_finished_count} past-due task(s). "
            "Reason saved: user did not specify a reason."
        )
    show_pending_message()

    pending_nav = st.session_state.pop("pending_nav", None)
    if pending_nav in MAIN_MENU_OPTIONS:
        st.session_state.main_menu = pending_nav

    choice = st.sidebar.radio(
        "Menu",
        MAIN_MENU_OPTIONS,
        key="main_menu",
        label_visibility="collapsed",
    )

    if choice == "Add Material":
        render_add_material()
    elif choice == "Review Suggestions":
        render_review_suggestions()
    elif choice == "Tasks":
        render_v0_tasks()
    elif choice == "Check Updates":
        render_check_updates()
    else:
        render_settings_workspace()


if __name__ == "__main__":
    main()
