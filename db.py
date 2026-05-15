import csv
import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from models import TASK_COLUMNS, VALID_STATUSES, normalize_task

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "tasks.db"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"
VALID_COMPLETION_STATUSES = ("completed", "partial", "not_completed", "blocked")
VALID_MOOD_ENERGY = ("low", "medium", "high")
VALID_MEMORY_TYPES = (
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
)
VALID_MEMORY_CONFIDENCES = ("high", "medium", "low")


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
            source TEXT NOT NULL DEFAULT 'manual',
            confidence TEXT CHECK (
                confidence IS NULL OR confidence IN ('high', 'medium', 'low')
            ),
            notes TEXT,
            source_snippet TEXT,
            external_id TEXT,
            external_source TEXT,
            external_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')


def _create_study_sessions_table(cursor):
    allowed_statuses = "', '".join(VALID_COMPLETION_STATUSES)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            task_title TEXT,
            course TEXT,
            start_time TEXT,
            end_time TEXT,
            planned_minutes INTEGER CHECK (
                planned_minutes IS NULL OR planned_minutes > 0
            ),
            actual_minutes INTEGER CHECK (
                actual_minutes IS NULL OR actual_minutes >= 0
            ),
            completion_status TEXT CHECK (
                completion_status IS NULL
                OR completion_status IN ('{allowed_statuses}')
            ),
            blocker TEXT,
            notes TEXT,
            created_at TEXT
        )
    ''')


def _create_daily_reviews_table(cursor):
    allowed_moods = "', '".join(VALID_MOOD_ENERGY)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS daily_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_date TEXT NOT NULL UNIQUE,
            completed_summary TEXT,
            missed_tasks TEXT,
            blockers TEXT,
            avoidance_notes TEXT,
            tomorrow_top_priority TEXT,
            mood_energy TEXT CHECK (
                mood_energy IS NULL OR mood_energy IN ('{allowed_moods}')
            ),
            focus_rating INTEGER CHECK (
                focus_rating IS NULL OR focus_rating BETWEEN 1 AND 5
            ),
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_agent_memory_table(cursor):
    allowed_types = "', '".join(VALID_MEMORY_TYPES)
    allowed_confidences = "', '".join(VALID_MEMORY_CONFIDENCES)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS agent_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL CHECK (
                memory_type IN ('{allowed_types}')
            ),
            memory_key TEXT NOT NULL,
            memory_value TEXT NOT NULL,
            confidence TEXT CHECK (
                confidence IS NULL
                OR confidence IN ('{allowed_confidences}')
            ),
            source TEXT,
            is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT,
            updated_at TEXT
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


def _database_needs_backup_before_init():
    if not DB_PATH.exists():
        return False

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        tasks_exists = _table_exists(cursor, "tasks")
        tasks_need_migration = (
            tasks_exists
            and (
                _table_columns(cursor, "tasks") != list(TASK_COLUMNS)
                or not _status_schema_is_current(cursor)
            )
        )
        daily_reviews_missing = not _table_exists(cursor, "daily_reviews")
        agent_memory_missing = not _table_exists(cursor, "agent_memory")
        return tasks_need_migration or daily_reviews_missing or agent_memory_missing


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

    source_expr = "'manual'"
    if "source" in legacy_columns:
        source_expr = "COALESCE(NULLIF(TRIM(source), ''), 'manual')"

    confidence_expr = "NULL"
    if "confidence" in legacy_columns:
        confidence_expr = (
            "CASE WHEN confidence IN ('high', 'medium', 'low') "
            "THEN confidence ELSE NULL END"
        )

    cursor.execute(f'''
        INSERT INTO tasks (
            id, title, course, task_type, due_at, planned_date,
            estimated_minutes, priority, status, source, confidence, notes,
            source_snippet, external_id, external_source, external_url,
            created_at, updated_at
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
            {source_expr},
            {confidence_expr},
            {text_expr("notes")},
            {text_expr("source_snippet")},
            {text_expr("external_id")},
            {text_expr("external_source")},
            {text_expr("external_url")},
            {created_at_expr},
            {updated_at_expr}
        FROM tasks_legacy
    ''')
    cursor.execute("DROP TABLE tasks_legacy")


TASK_SELECT = '''
    SELECT id, title, course, task_type, due_at, planned_date,
           estimated_minutes, priority, status, source, confidence, notes,
           source_snippet, external_id, external_source, external_url,
           created_at, updated_at
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
    if _database_needs_backup_before_init():
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        if not _table_exists(cursor, "tasks"):
            _create_tasks_table(cursor)
        else:
            _migrate_tasks_table(cursor, _table_columns(cursor, "tasks"))
        _create_study_sessions_table(cursor)
        conn.commit()

    init_daily_reviews_table(create_backup=False)
    init_agent_memory_table(create_backup=False)


def backup_database():
    if not DB_PATH.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"tasks_backup_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return str(backup_path)


def init_daily_reviews_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    daily_reviews_missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            daily_reviews_missing = not _table_exists(cursor, "daily_reviews")

    if daily_reviews_missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_daily_reviews_table(cursor)
        conn.commit()


def init_agent_memory_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    agent_memory_missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            agent_memory_missing = not _table_exists(cursor, "agent_memory")

    if agent_memory_missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_agent_memory_table(cursor)
        conn.commit()


def create_task(task):
    task = normalize_task(task)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (
                title, course, task_type, due_at, planned_date,
                estimated_minutes, priority, status, source, confidence, notes,
                source_snippet, external_id, external_source, external_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task["title"],
            task["course"],
            task["task_type"],
            task["due_at"],
            task["planned_date"],
            task["estimated_minutes"],
            task["priority"],
            task["status"],
            task["source"],
            task["confidence"],
            task["notes"],
            task["source_snippet"],
            task["external_id"],
            task["external_source"],
            task["external_url"],
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


def task_exists_by_external_id(external_source, external_id):
    if not external_source or not external_id:
        return False

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT 1
            FROM tasks
            WHERE external_source = ? AND external_id = ?
            LIMIT 1
            ''',
            (str(external_source), str(external_id)),
        )
        return cursor.fetchone() is not None


def _canvas_due_date(value):
    if not value:
        return None

    text = str(value).strip()
    candidate = text[:10]
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def create_canvas_assignment_task(assignment):
    external_source = assignment.get("external_source") or "canvas_assignment"
    external_id = assignment.get("external_id")
    if not external_id:
        return False

    if task_exists_by_external_id(external_source, external_id):
        return False

    external_url = assignment.get("external_url")
    notes = "Imported from Quercus/Canvas."
    if external_url:
        notes = f"{notes} Link: {external_url}"

    create_task({
        "title": assignment.get("title") or "Untitled Canvas assignment",
        "course": assignment.get("course_name"),
        "task_type": "assignment",
        "due_at": _canvas_due_date(assignment.get("due_at")),
        "planned_date": None,
        "estimated_minutes": None,
        "priority": 3,
        "status": "confirmed",
        "source": "quercus_assignment",
        "confidence": "high",
        "notes": notes,
        "source_snippet": None,
        "external_id": str(external_id) if external_id is not None else None,
        "external_source": external_source,
        "external_url": external_url,
    })
    return True


def _fetch_study_session(where_clause="", params=()):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, task_id, task_title, course, start_time, end_time,
                   planned_minutes, actual_minutes, completion_status,
                   blocker, notes, created_at
            FROM study_sessions
            {where_clause}
            ''',
            params,
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def _fetch_study_sessions(where_clause="", params=()):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, task_id, task_title, course, start_time, end_time,
                   planned_minutes, actual_minutes, completion_status,
                   blocker, notes, created_at
            FROM study_sessions
            {where_clause}
            ''',
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


def get_active_study_session():
    return _fetch_study_session(
        "WHERE end_time IS NULL ORDER BY start_time DESC LIMIT 1"
    )


def create_study_session_start(task_id, task_title, course, planned_minutes):
    planned_minutes = int(planned_minutes)
    if planned_minutes <= 0:
        raise ValueError("Planned minutes must be greater than 0.")

    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            '''
            SELECT id
            FROM study_sessions
            WHERE end_time IS NULL
            LIMIT 1
            '''
        )
        if cursor.fetchone() is not None:
            raise ValueError("A focus session is already active.")

        cursor.execute(
            '''
            INSERT INTO study_sessions (
                task_id, task_title, course, start_time, end_time,
                planned_minutes, actual_minutes, completion_status,
                blocker, notes, created_at
            ) VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, ?)
            ''',
            (
                task_id,
                task_title,
                course,
                now,
                planned_minutes,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def _actual_minutes(start_time, end_time):
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except (TypeError, ValueError):
        return None

    elapsed_seconds = max(0, int((end - start).total_seconds()))
    return elapsed_seconds // 60


def complete_study_session(session_id, completion_status, blocker, notes):
    if completion_status not in VALID_COMPLETION_STATUSES:
        raise ValueError(
            "Completion status must be one of: "
            f"{', '.join(VALID_COMPLETION_STATUSES)}"
        )

    session = _fetch_study_session(
        "WHERE id = ? AND end_time IS NULL LIMIT 1",
        (session_id,),
    )
    if session is None:
        raise ValueError("No active focus session was found for this session id.")

    end_time = datetime.now().isoformat(timespec="seconds")
    actual_minutes = _actual_minutes(session["start_time"], end_time)

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE study_sessions
            SET end_time = ?,
                actual_minutes = ?,
                completion_status = ?,
                blocker = ?,
                notes = ?
            WHERE id = ? AND end_time IS NULL
            ''',
            (
                end_time,
                actual_minutes,
                completion_status,
                blocker,
                notes,
                session_id,
            ),
        )
        conn.commit()

    return _fetch_study_session("WHERE id = ? LIMIT 1", (session_id,))


def get_recent_study_sessions(limit=20):
    limit = max(1, int(limit))
    return _fetch_study_sessions(
        '''
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        ''',
        (limit,),
    )


def get_study_sessions_for_task(task_id):
    return _fetch_study_sessions(
        '''
        WHERE task_id = ?
        ORDER BY created_at DESC, id DESC
        ''',
        (task_id,),
    )


def _clean_review_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_review_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    datetime.strptime(text, "%Y-%m-%d")
    return text


def _clean_focus_rating(value):
    if value in (None, ""):
        return None

    rating = int(value)
    if rating < 1 or rating > 5:
        raise ValueError("Focus rating must be between 1 and 5.")
    return rating


def _normalize_daily_review(review):
    review_date = _clean_review_date(review.get("review_date"))
    mood_energy = _clean_review_text(review.get("mood_energy"))
    if mood_energy:
        mood_energy = mood_energy.lower()
        if mood_energy not in VALID_MOOD_ENERGY:
            raise ValueError(
                f"Mood / energy must be one of: {', '.join(VALID_MOOD_ENERGY)}."
            )

    return {
        "review_date": review_date,
        "completed_summary": _clean_review_text(review.get("completed_summary")),
        "missed_tasks": _clean_review_text(review.get("missed_tasks")),
        "blockers": _clean_review_text(review.get("blockers")),
        "avoidance_notes": _clean_review_text(review.get("avoidance_notes")),
        "tomorrow_top_priority": _clean_review_text(
            review.get("tomorrow_top_priority")
        ),
        "mood_energy": mood_energy,
        "focus_rating": _clean_focus_rating(review.get("focus_rating")),
    }


def create_or_update_daily_review(review):
    review = _normalize_daily_review(review)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO daily_reviews (
                review_date, completed_summary, missed_tasks, blockers,
                avoidance_notes, tomorrow_top_priority, mood_energy,
                focus_rating, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_date) DO UPDATE SET
                completed_summary = excluded.completed_summary,
                missed_tasks = excluded.missed_tasks,
                blockers = excluded.blockers,
                avoidance_notes = excluded.avoidance_notes,
                tomorrow_top_priority = excluded.tomorrow_top_priority,
                mood_energy = excluded.mood_energy,
                focus_rating = excluded.focus_rating,
                updated_at = excluded.updated_at
            ''',
            (
                review["review_date"],
                review["completed_summary"],
                review["missed_tasks"],
                review["blockers"],
                review["avoidance_notes"],
                review["tomorrow_top_priority"],
                review["mood_energy"],
                review["focus_rating"],
                now,
                now,
            ),
        )
        conn.commit()

    return get_daily_review_by_date(review["review_date"])


def get_daily_review_by_date(review_date):
    review_date = _clean_review_date(review_date)
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, review_date, completed_summary, missed_tasks, blockers,
                   avoidance_notes, tomorrow_top_priority, mood_energy,
                   focus_rating, created_at, updated_at
            FROM daily_reviews
            WHERE review_date = ?
            LIMIT 1
            ''',
            (review_date,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_daily_reviews(limit=14):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, review_date, completed_summary, missed_tasks, blockers,
                   avoidance_notes, tomorrow_top_priority, mood_energy,
                   focus_rating, created_at, updated_at
            FROM daily_reviews
            ORDER BY review_date DESC, updated_at DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_daily_review(review_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM daily_reviews WHERE id = ?", (review_id,))
        conn.commit()


def export_daily_reviews_to_csv(output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    reviews = get_recent_daily_reviews(limit=10_000)
    fieldnames = [
        "id",
        "review_date",
        "completed_summary",
        "missed_tasks",
        "blockers",
        "avoidance_notes",
        "tomorrow_top_priority",
        "mood_energy",
        "focus_rating",
        "created_at",
        "updated_at",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reviews)

    return str(output_path)


def _clean_memory_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_memory_type(value):
    memory_type = _clean_memory_text(value)
    if not memory_type:
        raise ValueError("Memory type is required.")

    memory_type = memory_type.lower()
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(
            f"Memory type must be one of: {', '.join(VALID_MEMORY_TYPES)}."
        )
    return memory_type


def _clean_memory_confidence(value):
    confidence = _clean_memory_text(value)
    if not confidence:
        return None

    confidence = confidence.lower()
    if confidence not in VALID_MEMORY_CONFIDENCES:
        raise ValueError(
            "Confidence must be one of: "
            f"{', '.join(VALID_MEMORY_CONFIDENCES)}."
        )
    return confidence


def _clean_is_active(value):
    if value in (None, ""):
        return 1

    return 1 if int(value) else 0


def _normalize_agent_memory(memory):
    memory_key = _clean_memory_text(memory.get("memory_key"))
    if not memory_key:
        raise ValueError("Memory key is required.")

    memory_value = _clean_memory_text(memory.get("memory_value"))
    if not memory_value:
        raise ValueError("Memory value is required.")

    return {
        "memory_type": _clean_memory_type(memory.get("memory_type")),
        "memory_key": memory_key,
        "memory_value": memory_value,
        "confidence": _clean_memory_confidence(memory.get("confidence")),
        "source": _clean_memory_text(memory.get("source")) or "manual",
        "is_active": _clean_is_active(memory.get("is_active", 1)),
    }


def _fetch_agent_memories(where_clause="", params=()):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, memory_type, memory_key, memory_value, confidence,
                   source, is_active, created_at, updated_at
            FROM agent_memory
            {where_clause}
            ''',
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


def create_agent_memory(memory):
    memory = _normalize_agent_memory(memory)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO agent_memory (
                memory_type, memory_key, memory_value, confidence,
                source, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                memory["memory_type"],
                memory["memory_key"],
                memory["memory_value"],
                memory["confidence"],
                memory["source"],
                memory["is_active"],
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_active_agent_memory():
    return _fetch_agent_memories(
        '''
        WHERE is_active = 1
        ORDER BY memory_type ASC, updated_at DESC, id DESC
        '''
    )


def get_agent_memory_by_type(memory_type):
    memory_type = _clean_memory_type(memory_type)
    return _fetch_agent_memories(
        '''
        WHERE is_active = 1 AND memory_type = ?
        ORDER BY updated_at DESC, id DESC
        ''',
        (memory_type,),
    )


def update_agent_memory(memory_id, updates):
    allowed_fields = {
        "memory_type",
        "memory_key",
        "memory_value",
        "confidence",
        "source",
        "is_active",
    }
    safe_updates = {
        key: value for key, value in updates.items()
        if key in allowed_fields
    }
    if not safe_updates:
        return None

    current = _fetch_agent_memories("WHERE id = ? LIMIT 1", (memory_id,))
    if not current:
        return None

    merged = dict(current[0])
    merged.update(safe_updates)
    normalized = _normalize_agent_memory(merged)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE agent_memory
            SET memory_type = ?,
                memory_key = ?,
                memory_value = ?,
                confidence = ?,
                source = ?,
                is_active = ?,
                updated_at = ?
            WHERE id = ?
            ''',
            (
                normalized["memory_type"],
                normalized["memory_key"],
                normalized["memory_value"],
                normalized["confidence"],
                normalized["source"],
                normalized["is_active"],
                now,
                memory_id,
            ),
        )
        conn.commit()

    result = _fetch_agent_memories("WHERE id = ? LIMIT 1", (memory_id,))
    return result[0] if result else None


def deactivate_agent_memory(memory_id):
    return update_agent_memory(memory_id, {"is_active": 0})


def delete_agent_memory(memory_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM agent_memory WHERE id = ?", (memory_id,))
        conn.commit()


def memory_exists(memory_type, memory_key):
    memory_type = _clean_memory_type(memory_type)
    memory_key = _clean_memory_text(memory_key)
    if not memory_key:
        return False

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT 1
            FROM agent_memory
            WHERE is_active = 1
              AND memory_type = ?
              AND memory_key = ?
            LIMIT 1
            ''',
            (memory_type, memory_key),
        )
        return cursor.fetchone() is not None


def delete_task(task_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
