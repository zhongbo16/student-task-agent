import streamlit as st
from db import init_db, create_task, get_all_tasks

def main():
    st.title("Student Task Manager")

    # Initialize the database
    init_db()

    # Sidebar for navigation
    menu = ["Add Task", "View Tasks"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Add Task":
        st.subheader("Add a New Task")
        with st.form("task_form"):
            title = st.text_input("Task Title", max_chars=100)
            course = st.text_input("Course Name")
            task_type = st.text_input("Task Type")
            due_at = st.date_input("Due Date")
            planned_date = st.date_input("Planned Date")
            estimated_minutes = st.number_input("Estimated Minutes", min_value=1)
            priority = st.slider("Priority", 1, 5)
            notes = st.text_area("Additional Notes")
            submitted = st.form_submit_button("Submit")

            if submitted:
                task = {
                    'title': title,
                    'course': course,
                    'task_type': task_type,
                    'due_at': str(due_at),
                    'planned_date': str(planned_date),
                    'estimated_minutes': estimated_minutes,
                    'priority': priority,
                    'notes': notes
                }
                create_task(task)
                st.success("Task added successfully!")

    elif choice == "View Tasks":
        st.subheader("All Tasks")
        tasks = get_all_tasks()
        if tasks:
            for task in tasks:
                st.write(task)
        else:
            st.info("No tasks available.")

if __name__ == "__main__":
    main()