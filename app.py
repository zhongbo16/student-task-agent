import re
from pathlib import Path

import streamlit as st

from db import (
    create_task,
    get_all_tasks,
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

MENU_OPTIONS = [
    "Today Plan",
    "Today",
    "This Week",
    "Confirmed Tasks",
    "Suggested Tasks",
    "In Progress",
    "Completed",
    "Files / Syllabus Upload",
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

    st.success("PDF uploaded successfully.")
    st.markdown(f"**Filename:** {metadata['filename']}")
    st.markdown(f"**File size:** {metadata['file_size']:,} bytes")
    st.markdown(f"**Pages:** {metadata['page_count']}")
    st.text_area(
        "Extracted text preview",
        value=preview or "No extractable text found in this PDF.",
        height=300,
    )


def main():
    st.title("Student Task Manager")

    init_db()
    show_pending_message()

    choice = st.sidebar.selectbox("Menu", MENU_OPTIONS)

    if choice == "Today Plan":
        render_today_plan()
    elif choice == "Files / Syllabus Upload":
        render_file_upload()
    elif choice == "Add Task":
        render_add_task_form()
    else:
        render_dashboard_view(choice)


if __name__ == "__main__":
    main()
