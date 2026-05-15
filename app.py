import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from ai_parser import extract_tasks_from_text
from canvas_client import (
    get_all_assignments,
    get_canvas_base_url,
    has_canvas_api_token,
    has_canvas_base_url,
)
from db import (
    complete_study_session,
    create_agent_memory,
    create_or_update_daily_review,
    create_task,
    create_canvas_assignment_task,
    create_study_session_start,
    deactivate_agent_memory,
    export_daily_reviews_to_csv,
    get_active_study_session,
    get_active_agent_memory,
    get_all_tasks,
    get_daily_review_by_date,
    memory_exists,
    get_recent_study_sessions,
    get_recent_daily_reviews,
    get_tasks_by_status,
    get_this_week_tasks,
    get_today_tasks,
    init_db,
    update_task_status,
)
from file_parser import extract_text_from_pdf, get_file_metadata
from planner import generate_today_plan, sort_tasks_for_dashboard, task_indicators

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "data" / "exports"

MENU_OPTIONS = [
    "Today Plan",
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
        with st.container(border=True):
            st.markdown(f"### {index}. {display_value(task['title'])}")
            st.markdown(f"**Course:** {display_value(task['course'])}")
            st.markdown(
                f"**Estimated:** {display_value(task['estimated_minutes'])} min"
            )
            st.markdown(f"**Date:** {display_date(task)}")
            st.markdown(f"**Priority:** {display_value(task['priority'])}")
            st.markdown(f"**Status:** {display_value(task['status'])}")
            st.markdown(f"**Reason:** {recommendation['reason']}")


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

    if choice == "Today Plan":
        render_today_plan()
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
