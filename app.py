import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

from action_engine import build_confirmable_actions, count_ready_actions
from ai_boss import (
    AIBossConfigError,
    AIBossResponseError,
    build_ai_boss_context,
    generate_ai_boss_briefing,
    has_openai_api_key,
)
from ai_parser import extract_tasks_from_text
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
    complete_study_session,
    create_agent_memory,
    create_agent_memory_candidate,
    create_checkin_answer,
    create_command_center_message,
    create_or_update_morning_checkin,
    create_or_update_daily_review,
    create_personal_commitment,
    create_task,
    create_canvas_assignment_task,
    create_study_session_start,
    deactivate_agent_memory,
    export_daily_reviews_to_csv,
    get_active_study_session,
    get_active_agent_memory,
    get_all_tasks,
    get_checkin_answers_by_date,
    get_daily_review_by_date,
    get_daily_command_review_by_command,
    get_latest_daily_command,
    get_latest_ai_boss_briefing,
    get_course_summaries,
    get_morning_checkin_by_date,
    get_pending_agent_memory_candidates,
    get_recent_command_center_messages,
    memory_exists,
    get_personal_commitments_for_date,
    get_task_candidates,
    get_recent_daily_commands,
    get_recent_daily_command_reviews,
    get_recent_ai_boss_briefings,
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
    save_ai_boss_briefing,
    create_or_update_daily_command_review,
    mark_command_center_message_applied,
    promote_memory_candidate_to_memory,
    unarchive_course,
    update_agent_memory_candidate_decision,
    update_personal_commitment_status,
    update_task_candidate_decision,
    update_task_status,
)
from file_parser import extract_text_from_pdf, get_file_metadata
from planner import generate_today_plan, sort_tasks_for_dashboard, task_indicators
from task_intake import run_auto_task_intake
from urgency import calculate_urgency_score

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "data" / "exports"

MENU_OPTIONS = [
    "Command Center",
    "Daily Command",
    "Feedback Loop",
    "Today Plan",
    "AI Boss",
    "Task Intake",
    "Focus Session",
    "Daily Review",
    "Agent Memory",
    "Today",
    "This Week",
    "Confirmed Tasks",
    "Suggested Tasks",
    "In Progress",
    "Completed",
    "Files / Syllabus Upload",
    "Quercus Sync",
    "Add Task",
    "All Tasks",
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


def display_value(value):
    if value is None or value == "":
        return "-"
    return str(value)


def display_date(task):
    if task.get("due_at"):
        return f"Due: {task['due_at']}"
    if task.get("planned_date"):
        return f"Planned: {task['planned_date']}"
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


def render_task_fields(task):
    first_row = st.columns(4)
    first_row[0].markdown(f"**Course**  \n{display_value(task['course'])}")
    first_row[1].markdown(f"**Type**  \n{display_value(task['task_type'])}")
    first_row[2].markdown(f"**Due**  \n{display_value(task['due_at'])}")
    first_row[3].markdown(f"**Planned**  \n{display_value(task['planned_date'])}")

    second_row = st.columns(4)
    second_row[0].markdown(
        f"**Minutes**  \n{display_value(task['estimated_minutes'])}"
    )
    second_row[1].markdown(f"**Priority**  \n{display_value(task['priority'])}")
    second_row[2].markdown(f"**Status**  \n{display_value(task['status'])}")
    second_row[3].markdown(f"**Notes**  \n{display_value(task['notes'])}")

    urgency_score, urgency_label = task_urgency(task)
    urgency_row = st.columns(3)
    urgency_row[0].markdown(
        f"**Urgency**  \n{display_value(urgency_label)}"
    )
    urgency_row[1].markdown(
        f"**Urgency Score**  \n{urgency_score:.1f}"
    )
    urgency_row[2].markdown(
        f"**Needs Review**  \n{display_value(task.get('needs_review'))}"
    )

    has_extraction_fields = (
        task.get("source") not in (None, "", "manual")
        or task.get("confidence")
        or task.get("source_snippet")
    )
    if has_extraction_fields:
        third_row = st.columns(3)
        third_row[0].markdown(f"**Source**  \n{display_value(task.get('source'))}")
        third_row[1].markdown(
            f"**Confidence**  \n{display_value(task.get('confidence'))}"
        )
        third_row[2].markdown(
            f"**Source Snippet**  \n{display_value(task.get('source_snippet'))}"
        )


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


def render_focus_action(task, current_view):
    if not can_focus_task(task):
        return

    active_session = get_active_study_session()
    if active_session:
        st.caption("A focus session is already active.")
        return

    if st.button(
        "Start Focus",
        key=f"{view_key(current_view)}-{task['id']}-start-focus",
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
        with st.container(border=True):
            st.markdown(f"### {display_value(task['title'])}")
            indicators = task_indicators(task)
            if indicators:
                st.caption(" | ".join(f"[{indicator}]" for indicator in indicators))
            render_task_fields(task)
            render_status_actions(task, current_view)
            render_focus_action(task, current_view)


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
                f"**Due**  \n{display_value(existing_task.get('due_at'))}"
            )
            columns[2].markdown(
                "**Planned**  \n"
                f"{display_value(existing_task.get('planned_date'))}"
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


def render_command_center_top_tasks(tasks):
    st.markdown("### Now")
    latest = get_latest_daily_command(date.today().isoformat())
    if latest:
        command = parse_saved_daily_command(latest)
        if command:
            st.markdown(f"**Daily Command:** {display_value(command.get('executive_summary'))}")
            st.caption(
                "First 25 minutes: "
                f"{display_value(command.get('first_25_minute_action'))}"
            )
    else:
        st.info("No Daily Command saved for today yet.")

    active_session = get_active_study_session()
    if active_session:
        st.warning(
            "Active focus session: "
            f"{active_session['task_title']} "
            f"({elapsed_minutes_since(active_session['start_time'])} min elapsed)."
        )

    st.markdown("### Top Tasks")
    top_tasks = top_urgent_tasks(limit=3)
    if not top_tasks:
        st.info("No active tasks right now.")
        return

    for index, task in enumerate(top_tasks, start=1):
        urgency_score, urgency_label = task_urgency(task)
        with st.container(border=True):
            st.markdown(f"#### {index}. {display_value(task['title'])}")
            columns = st.columns(4)
            columns[0].markdown(f"**Course**  \n{display_value(task['course'])}")
            columns[1].markdown(f"**Due**  \n{display_value(task['due_at'])}")
            columns[2].markdown(f"**Status**  \n{display_value(task['status'])}")
            columns[3].markdown(
                f"**Urgency**  \n{display_value(urgency_label)} ({urgency_score:.1f})"
            )
            if not active_session and st.button(
                "Start Focus",
                key=f"command-center-start-focus-{task['id']}",
            ):
                try:
                    start_focus_session_for_task(task)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success("Focus session started.")
                    st.rerun()


def render_command_center_conversation(command_date, context):
    st.markdown("### Conversation Intake")
    st.caption(
        "Tell the AI what is happening. It will create a proposal first; you "
        "choose whether to apply it."
    )

    key_present = has_conversation_intake_api_key()
    if not key_present:
        st.warning("Add OPENAI_API_KEY to your .env file to use conversation intake.")

    with st.form("command_center_message_form"):
        message = st.text_area(
            "Message",
            placeholder=(
                "Example: I slept 5 hours, feel tired, have class at 2, "
                "gym at 6, and can study 2 hours. I finished the CLA reading."
            ),
            height=140,
        )
        submitted = st.form_submit_button("Analyze Message", disabled=not key_present)

    if submitted:
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
        st.success("Proposal ready. Review it before applying.")

    proposal = st.session_state.get("command_center_proposal")
    if proposal:
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


def render_command_center_history(command_date):
    messages = get_recent_command_center_messages(command_date, limit=8)
    if not messages:
        return

    st.markdown("### Recent Conversation")
    for message in messages:
        with st.expander(
            f"{display_datetime(message['created_at'])} - "
            f"{display_value(message['role'])}"
        ):
            st.write(message["content"])
            if message.get("proposal_json"):
                st.caption("Proposal saved with this message.")
            if message.get("applied"):
                st.success("Applied")


def render_command_center_quick_command(context, task_lookup):
    st.markdown("### Daily Command")
    render_daily_command_status(context)
    render_daily_command_generate(context, task_lookup)


def render_command_center():
    st.subheader("Command Center")
    st.info(
        "This is the main daily入口: talk naturally, review the AI proposal, "
        "then apply only what you approve."
    )
    command_date = date.today().isoformat()
    context, tasks = current_daily_command_context(command_date)
    task_lookup = task_lookup_by_id(tasks)

    render_command_center_top_tasks(tasks)
    render_command_center_conversation(command_date, context)

    refreshed_context, refreshed_tasks = current_daily_command_context(command_date)
    refreshed_lookup = task_lookup_by_id(refreshed_tasks)
    render_command_center_quick_command(refreshed_context, refreshed_lookup)
    render_latest_daily_command(command_date, refreshed_lookup)
    render_command_center_history(command_date)


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
                f"**Due**  \n{display_value(existing_task.get('due_at'))}"
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
            columns[0].markdown(f"**Due**  \n{display_value(task.get('due_at'))}")
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
    columns[3].markdown(f"**Due**  \n{display_value(candidate['due_at'])}")

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
            columns[1].markdown(f"**Due**  \n{display_value(task['due_at'])}")
            columns[2].markdown(
                f"**Planned**  \n{display_value(task['planned_date'])}"
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


def render_session_summary(session):
    st.markdown(f"**Task:** {display_value(session['task_title'])}")
    st.markdown(f"**Course:** {display_value(session['course'])}")
    st.markdown(f"**Started:** {display_datetime(session['start_time'])}")
    st.markdown(f"**Planned:** {display_value(session['planned_minutes'])} min")
    st.markdown(f"**Elapsed:** about {elapsed_minutes_since(session['start_time'])} min")


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

    if st.button("Start Focus Session"):
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
        st.markdown("### Active Session")
        render_end_focus_session(active_session)
    else:
        st.markdown("### Start Session")
        render_start_focus_session()

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


def main():
    st.title("Student Task Manager")

    init_db()
    show_pending_message()

    choice = st.sidebar.selectbox("Menu", MENU_OPTIONS)

    if choice == "Command Center":
        render_command_center()
    elif choice == "Daily Command":
        render_daily_command()
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


if __name__ == "__main__":
    main()
