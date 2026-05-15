import sqlite3
from datetime import datetime

DB_PATH = "data/tasks.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            course TEXT,
            task_type TEXT,
            status TEXT,
            source TEXT,
            confidence TEXT,
            due_at TEXT,
            planned_date TEXT,
            estimated_minutes INTEGER,
            priority INTEGER,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def create_task(task):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO tasks (
            title, course, task_type, status, source, confidence,
            due_at, planned_date, estimated_minutes, priority, notes,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        task['title'], task.get('course'), task.get('task_type'), task.get('status', 'confirmed'),
        task.get('source', 'manual'), task.get('confidence', 'high'), task.get('due_at'),
        task.get('planned_date'), task.get('estimated_minutes'), task.get('priority'),
        task.get('notes'), now, now
    ))
    conn.commit()
    conn.close()

def get_all_tasks():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks')
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def update_task_status(task_id, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        UPDATE tasks
        SET status = ?, updated_at = ?
        WHERE id = ?
    ''', (status, now, task_id))
    conn.commit()
    conn.close()

def delete_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()