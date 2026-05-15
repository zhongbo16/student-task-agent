import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from models import TASK_COLUMNS, VALID_STATUSES, normalize_task

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "tasks.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tasks_table(cursor, table_name="tasks"):
    allowed_statuses = "', '".join(VALID_STATUSES)
    cursor.execute(f'''
        CREATE TABLE {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            course TEXT,
            task_type TEXT,
            due_at TEXT,
            planned_date TEXT,
            estimated_minutes INTEGER CHECK (
                estimated_minutes IS NULL OR estimated_minutes > 0
            ),
            priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
            status TEXT NOT NULL DEFAULT 'confirmed' CHECK (
                status IN ('{allowed_statuses}')
            ),
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')


def _table_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row["name"] for row in cursor.fetchall()]


def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _table_sql(cursor, table_name):
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    row = cursor.fetchone()
    return row["sql"] if row else ""


def _status_schema_is_current(cursor):
    sql = _table_sql(cursor, "tasks")
    return (
        "DEFAULT 'confirmed'" in sql
        and all(f"'{status}'" in sql for status in VALID_STATUSES)
    )


def _migrate_tasks_table(cursor, existing_columns):
    expected_columns = list(TASK_COLUMNS)
    if existing_columns == expected_columns and _status_schema_is_current(cursor):
        return

    legacy_columns = set(existing_columns)
    now = datetime.now().isoformat(timespec="seconds")

    cursor.execute("ALTER TABLE tasks RENAME TO tasks_legacy")
    _create_tasks_table(cursor)

    def text_expr(column_name):
        if column_name in legacy_columns:
            return f"NULLIF(TRIM({column_name}), '')"
        return "NULL"

    status_expr = "'confirmed'"
    if "status" in legacy_columns:
        allowed = "', '".join(VALID_STATUSES)
        status_expr = (
            f"CASE "
            f"WHEN status = 'todo' THEN 'confirmed' "
            f"WHEN status IN ('{allowed}') THEN status "
            f"ELSE 'confirmed' END"
        )

    priority_expr = "3"
    if "priority" in legacy_columns:
        priority_expr = (
            "CASE WHEN priority BETWEEN 1 AND 5 THEN priority ELSE 3 END"
        )

    estimated_minutes_expr = "NULL"
    if "estimated_minutes" in legacy_columns:
        estimated_minutes_expr = (
            "CASE WHEN estimated_minutes > 0 THEN estimated_minutes ELSE NULL END"
        )

    title_expr = "'Untitled task'"
    if "title" in legacy_columns:
        title_expr = "COALESCE(NULLIF(TRIM(title), ''), 'Untitled task')"

    id_expr = "NULL"
    if "id" in legacy_columns:
        id_expr = "id"

    created_at_expr = f"'{now}'"
    if "created_at" in legacy_columns:
        created_at_expr = f"COALESCE(created_at, '{now}')"

    updated_at_expr = f"'{now}'"
    if "updated_at" in legacy_columns:
        updated_at_expr = f"COALESCE(updated_at, '{now}')"

    cursor.execute(f'''
        INSERT INTO tasks (
            id, title, course, task_type, due_at, planned_date,
            estimated_minutes, priority, status, notes, created_at, updated_at
        )
        SELECT
            {id_expr},
            {title_expr},
            {text_expr("course")},
            {text_expr("task_type")},
            {text_expr("due_at")},
            {text_expr("planned_date")},
            {estimated_minutes_expr},
            {priority_expr},
            {status_expr},
            {text_expr("notes")},
            {created_at_expr},
            {updated_at_expr}
        FROM tasks_legacy
    ''')
    cursor.execute("DROP TABLE tasks_legacy")


TASK_SELECT = '''
    SELECT id, title, course, task_type, due_at, planned_date,
           estimated_minutes, priority, status, notes, created_at, updated_at
    FROM tasks
'''

TASK_ORDER_BY = '''
    ORDER BY
        CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
        due_at ASC,
        priority DESC,
        created_at DESC
'''


def _fetch_tasks(where_clause="", params=()):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(f"{TASK_SELECT} {where_clause} {TASK_ORDER_BY}", params)
        return [dict(row) for row in cursor.fetchall()]


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        if not _table_exists(cursor, "tasks"):
            _create_tasks_table(cursor)
        else:
            _migrate_tasks_table(cursor, _table_columns(cursor, "tasks"))
        conn.commit()


def create_task(task):
    task = normalize_task(task)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (
                title, course, task_type, due_at, planned_date,
                estimated_minutes, priority, status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task["title"],
            task["course"],
            task["task_type"],
            task["due_at"],
            task["planned_date"],
            task["estimated_minutes"],
            task["priority"],
            task["status"],
            task["notes"],
            now,
            now,
        ))
        conn.commit()
        return cursor.lastrowid


def get_all_tasks():
    return _fetch_tasks()


def get_tasks_by_status(status):
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(VALID_STATUSES)}")

    return _fetch_tasks("WHERE status = ?", (status,))


def get_today_tasks():
    today = date.today().isoformat()
    return _fetch_tasks(
        '''
        WHERE status NOT IN ('done', 'ignored')
          AND (
              due_at = ?
              OR planned_date = ?
              OR (due_at IS NOT NULL AND due_at < ?)
          )
        ''',
        (today, today, today),
    )


def get_this_week_tasks():
    today = date.today()
    start_date = today.isoformat()
    end_date = (today + timedelta(days=7)).isoformat()

    return _fetch_tasks(
        '''
        WHERE status NOT IN ('done', 'ignored')
          AND (
              (due_at IS NOT NULL AND due_at BETWEEN ? AND ?)
              OR (planned_date IS NOT NULL AND planned_date BETWEEN ? AND ?)
          )
        ''',
        (start_date, end_date, start_date, end_date),
    )


def update_task_status(task_id, status):
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(VALID_STATUSES)}")

    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks
            SET status = ?, updated_at = ?
            WHERE id = ?
        ''', (status, now, task_id))
        conn.commit()


def delete_task(task_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
