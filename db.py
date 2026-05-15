import csv
import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from models import TASK_COLUMNS, VALID_STATUSES, normalize_task
from urgency import VALID_URGENCY_LABELS

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
VALID_CANDIDATE_DECISIONS = (
    "pending",
    "auto_created",
    "accepted",
    "ignored",
    "duplicate",
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tasks_table(cursor, table_name="tasks"):
    allowed_statuses = "', '".join(VALID_STATUSES)
    allowed_urgency_labels = "', '".join(VALID_URGENCY_LABELS)
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
            urgency_score REAL DEFAULT 0,
            urgency_label TEXT CHECK (
                urgency_label IS NULL
                OR urgency_label IN ('{allowed_urgency_labels}')
            ),
            auto_created INTEGER DEFAULT 0 CHECK (auto_created IN (0, 1)),
            needs_review INTEGER DEFAULT 0 CHECK (needs_review IN (0, 1)),
            last_scored_at TEXT,
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


def _create_ai_boss_briefings_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_boss_briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            briefing_date TEXT NOT NULL,
            input_summary_json TEXT,
            output_json TEXT,
            raw_response TEXT,
            created_at TEXT
        )
    ''')


def _create_task_candidates_table(cursor):
    allowed_confidences = "', '".join(VALID_MEMORY_CONFIDENCES)
    allowed_urgency_labels = "', '".join(VALID_URGENCY_LABELS)
    allowed_decisions = "', '".join(VALID_CANDIDATE_DECISIONS)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS task_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_hash TEXT UNIQUE,
            title TEXT NOT NULL,
            course TEXT,
            task_type TEXT,
            source TEXT,
            confidence TEXT CHECK (
                confidence IS NULL
                OR confidence IN ('{allowed_confidences}')
            ),
            due_at TEXT,
            planned_date TEXT,
            estimated_minutes INTEGER CHECK (
                estimated_minutes IS NULL OR estimated_minutes > 0
            ),
            priority TEXT,
            notes TEXT,
            source_url TEXT,
            source_snippet TEXT,
            external_source TEXT,
            external_id TEXT,
            urgency_score REAL DEFAULT 0,
            urgency_label TEXT CHECK (
                urgency_label IS NULL
                OR urgency_label IN ('{allowed_urgency_labels}')
            ),
            recommended_status TEXT CHECK (
                recommended_status IS NULL
                OR recommended_status IN ('suggested', 'confirmed')
            ),
            decision_status TEXT DEFAULT 'pending' CHECK (
                decision_status IN ('{allowed_decisions}')
            ),
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
        ai_boss_briefings_missing = not _table_exists(cursor, "ai_boss_briefings")
        task_candidates_missing = not _table_exists(cursor, "task_candidates")
        return (
            tasks_need_migration
            or daily_reviews_missing
            or agent_memory_missing
            or ai_boss_briefings_missing
            or task_candidates_missing
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

    source_expr = "'manual'"
    if "source" in legacy_columns:
        source_expr = "COALESCE(NULLIF(TRIM(source), ''), 'manual')"

    confidence_expr = "NULL"
    if "confidence" in legacy_columns:
        confidence_expr = (
            "CASE WHEN confidence IN ('high', 'medium', 'low') "
            "THEN confidence ELSE NULL END"
        )

    urgency_score_expr = "0"
    if "urgency_score" in legacy_columns:
        urgency_score_expr = "COALESCE(urgency_score, 0)"

    urgency_label_expr = "NULL"
    if "urgency_label" in legacy_columns:
        allowed_labels = "', '".join(VALID_URGENCY_LABELS)
        urgency_label_expr = (
            f"CASE WHEN urgency_label IN ('{allowed_labels}') "
            "THEN urgency_label ELSE NULL END"
        )

    auto_created_expr = "0"
    if "auto_created" in legacy_columns:
        auto_created_expr = "CASE WHEN auto_created = 1 THEN 1 ELSE 0 END"

    needs_review_expr = (
        "CASE WHEN "
        f"{status_expr} = 'suggested' "
        "THEN 1 ELSE 0 END"
    )
    if "needs_review" in legacy_columns:
        needs_review_expr = "CASE WHEN needs_review = 1 THEN 1 ELSE 0 END"

    cursor.execute(f'''
        INSERT INTO tasks (
            id, title, course, task_type, due_at, planned_date,
            estimated_minutes, priority, status, source, confidence, notes,
            source_snippet, external_id, external_source, external_url,
            urgency_score, urgency_label, auto_created, needs_review,
            last_scored_at,
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
            {urgency_score_expr},
            {urgency_label_expr},
            {auto_created_expr},
            {needs_review_expr},
            {text_expr("last_scored_at")},
            {created_at_expr},
            {updated_at_expr}
        FROM tasks_legacy
    ''')
    cursor.execute("DROP TABLE tasks_legacy")


TASK_SELECT = '''
    SELECT id, title, course, task_type, due_at, planned_date,
           estimated_minutes, priority, status, source, confidence, notes,
           source_snippet, external_id, external_source, external_url,
           urgency_score, urgency_label, auto_created, needs_review,
           last_scored_at,
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


def add_task_urgency_columns_if_missing(cursor=None):
    def add_columns(active_cursor):
        columns = set(_table_columns(active_cursor, "tasks"))
        if "urgency_score" not in columns:
            active_cursor.execute(
                "ALTER TABLE tasks ADD COLUMN urgency_score REAL DEFAULT 0"
            )
        if "urgency_label" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN urgency_label TEXT")
        if "auto_created" not in columns:
            active_cursor.execute(
                "ALTER TABLE tasks ADD COLUMN auto_created INTEGER DEFAULT 0"
            )
        if "needs_review" not in columns:
            active_cursor.execute(
                "ALTER TABLE tasks ADD COLUMN needs_review INTEGER DEFAULT 0"
            )
        if "last_scored_at" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN last_scored_at TEXT")

    if cursor is not None:
        add_columns(cursor)
        return

    with closing(_connect()) as conn:
        active_cursor = conn.cursor()
        add_columns(active_cursor)
        conn.commit()


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
        add_task_urgency_columns_if_missing(cursor)
        _create_study_sessions_table(cursor)
        _create_task_candidates_table(cursor)
        conn.commit()

    init_daily_reviews_table(create_backup=False)
    init_agent_memory_table(create_backup=False)
    init_ai_boss_briefings_table(create_backup=False)
    score_unscored_active_tasks()


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


def init_ai_boss_briefings_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ai_boss_briefings_missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            ai_boss_briefings_missing = not _table_exists(
                cursor,
                "ai_boss_briefings",
            )

    if ai_boss_briefings_missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_ai_boss_briefings_table(cursor)
        conn.commit()


def create_task(task):
    task = normalize_task(task)
    now = datetime.now().isoformat(timespec="seconds")
    if not task.get("urgency_label"):
        from urgency import calculate_urgency_score

        urgency_score, urgency_label, _ = calculate_urgency_score(task)
        task["urgency_score"] = urgency_score
        task["urgency_label"] = urgency_label
        task["last_scored_at"] = now
    elif not task.get("last_scored_at"):
        task["last_scored_at"] = now

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (
                title, course, task_type, due_at, planned_date,
                estimated_minutes, priority, status, source, confidence, notes,
                source_snippet, external_id, external_source, external_url,
                urgency_score, urgency_label, auto_created, needs_review,
                last_scored_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            task["urgency_score"],
            task["urgency_label"],
            task["auto_created"],
            task["needs_review"],
            task["last_scored_at"],
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
    needs_review = 1 if status == "suggested" else 0
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks
            SET status = ?, needs_review = ?, updated_at = ?
            WHERE id = ?
        ''', (status, needs_review, now, task_id))
        conn.commit()

    updated_task = _fetch_tasks("WHERE id = ?", (task_id,))
    if updated_task:
        from urgency import calculate_urgency_score

        urgency_score, urgency_label, _ = calculate_urgency_score(updated_task[0])
        update_task_urgency(task_id, urgency_score, urgency_label)


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
        "auto_created": 1,
        "needs_review": 0,
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


def save_ai_boss_briefing(
    briefing_date,
    input_summary_json,
    output_json,
    raw_response=None,
):
    briefing_date = _clean_review_date(briefing_date)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO ai_boss_briefings (
                briefing_date, input_summary_json, output_json,
                raw_response, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ''',
            (
                briefing_date,
                input_summary_json,
                output_json,
                raw_response,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_latest_ai_boss_briefing(briefing_date=None):
    params = ()
    where_clause = ""
    if briefing_date:
        where_clause = "WHERE briefing_date = ?"
        params = (_clean_review_date(briefing_date),)

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, briefing_date, input_summary_json, output_json,
                   raw_response, created_at
            FROM ai_boss_briefings
            {where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            ''',
            params,
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_ai_boss_briefings(limit=7):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, briefing_date, input_summary_json, output_json,
                   raw_response, created_at
            FROM ai_boss_briefings
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_task_urgency(task_id, urgency_score, urgency_label):
    if urgency_label not in VALID_URGENCY_LABELS:
        raise ValueError(
            f"Urgency label must be one of: {', '.join(VALID_URGENCY_LABELS)}."
        )

    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE tasks
            SET urgency_score = ?,
                urgency_label = ?,
                last_scored_at = ?
            WHERE id = ?
            ''',
            (float(urgency_score), urgency_label, now, task_id),
        )
        conn.commit()


def rescore_all_active_tasks():
    from urgency import calculate_urgency_score

    tasks = [
        task for task in get_all_tasks()
        if task.get("status") not in ("done", "ignored")
    ]
    for task in tasks:
        urgency_score, urgency_label, _ = calculate_urgency_score(task)
        update_task_urgency(task["id"], urgency_score, urgency_label)
    return len(tasks)


def score_unscored_active_tasks():
    from urgency import calculate_urgency_score

    tasks = [
        task for task in get_all_tasks()
        if task.get("status") not in ("done", "ignored")
        and (
            not task.get("last_scored_at")
            or not task.get("urgency_label")
        )
    ]
    for task in tasks:
        urgency_score, urgency_label, _ = calculate_urgency_score(task)
        update_task_urgency(task["id"], urgency_score, urgency_label)
    return len(tasks)


def _clean_candidate_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _clean_candidate_date(value):
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    candidate = text[:10]
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def _clean_candidate_minutes(value):
    if value in (None, ""):
        return None

    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None

    return minutes if minutes > 0 else None


def _normalize_candidate(candidate):
    title = _clean_candidate_text(candidate.get("title"))
    if not title:
        raise ValueError("Candidate title is required.")

    confidence = _clean_candidate_text(candidate.get("confidence"))
    if confidence:
        confidence = confidence.lower()
        if confidence not in VALID_MEMORY_CONFIDENCES:
            confidence = "low"

    urgency_label = _clean_candidate_text(candidate.get("urgency_label"))
    if urgency_label and urgency_label not in VALID_URGENCY_LABELS:
        urgency_label = None

    decision_status = (
        _clean_candidate_text(candidate.get("decision_status")) or "pending"
    )
    if decision_status not in VALID_CANDIDATE_DECISIONS:
        decision_status = "pending"

    recommended_status = _clean_candidate_text(candidate.get("recommended_status"))
    if recommended_status not in ("suggested", "confirmed"):
        recommended_status = "suggested"

    urgency_score = candidate.get("urgency_score")
    try:
        urgency_score = float(urgency_score)
    except (TypeError, ValueError):
        urgency_score = 0.0

    return {
        "candidate_hash": _clean_candidate_text(candidate.get("candidate_hash")),
        "title": title,
        "course": _clean_candidate_text(candidate.get("course")),
        "task_type": _clean_candidate_text(candidate.get("task_type")),
        "source": _clean_candidate_text(candidate.get("source")),
        "confidence": confidence,
        "due_at": _clean_candidate_date(candidate.get("due_at")),
        "planned_date": _clean_candidate_date(candidate.get("planned_date")),
        "estimated_minutes": _clean_candidate_minutes(
            candidate.get("estimated_minutes")
        ),
        "priority": _clean_candidate_text(candidate.get("priority")),
        "notes": _clean_candidate_text(candidate.get("notes")),
        "source_url": _clean_candidate_text(candidate.get("source_url")),
        "source_snippet": _clean_candidate_text(candidate.get("source_snippet")),
        "external_source": _clean_candidate_text(candidate.get("external_source")),
        "external_id": _clean_candidate_text(candidate.get("external_id")),
        "urgency_score": urgency_score,
        "urgency_label": urgency_label,
        "recommended_status": recommended_status,
        "decision_status": decision_status,
    }


def create_task_candidate(candidate):
    candidate = _normalize_candidate(candidate)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT OR IGNORE INTO task_candidates (
                candidate_hash, title, course, task_type, source, confidence,
                due_at, planned_date, estimated_minutes, priority, notes,
                source_url, source_snippet, external_source, external_id,
                urgency_score, urgency_label, recommended_status,
                decision_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                candidate["candidate_hash"],
                candidate["title"],
                candidate["course"],
                candidate["task_type"],
                candidate["source"],
                candidate["confidence"],
                candidate["due_at"],
                candidate["planned_date"],
                candidate["estimated_minutes"],
                candidate["priority"],
                candidate["notes"],
                candidate["source_url"],
                candidate["source_snippet"],
                candidate["external_source"],
                candidate["external_id"],
                candidate["urgency_score"],
                candidate["urgency_label"],
                candidate["recommended_status"],
                candidate["decision_status"],
                now,
                now,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return cursor.lastrowid


def _fetch_task_candidates(where_clause="", params=()):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, candidate_hash, title, course, task_type, source,
                   confidence, due_at, planned_date, estimated_minutes,
                   priority, notes, source_url, source_snippet, external_source,
                   external_id, urgency_score, urgency_label,
                   recommended_status, decision_status, created_at, updated_at
            FROM task_candidates
            {where_clause}
            ''',
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


def get_pending_task_candidates():
    return _fetch_task_candidates(
        '''
        WHERE decision_status = 'pending'
        ORDER BY urgency_score DESC, due_at ASC, created_at DESC
        '''
    )


def get_task_candidate(candidate_id):
    candidates = _fetch_task_candidates("WHERE id = ? LIMIT 1", (candidate_id,))
    return candidates[0] if candidates else None


def update_task_candidate_decision(candidate_id, decision_status):
    if decision_status not in VALID_CANDIDATE_DECISIONS:
        raise ValueError(
            "Candidate decision must be one of: "
            f"{', '.join(VALID_CANDIDATE_DECISIONS)}."
        )

    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE task_candidates
            SET decision_status = ?, updated_at = ?
            WHERE id = ?
            ''',
            (decision_status, now, candidate_id),
        )
        conn.commit()


def task_exists_by_signature(source, title, course=None, due_at=None):
    title = _clean_candidate_text(title)
    if not title:
        return False

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT 1
            FROM tasks
            WHERE COALESCE(source, '') = COALESCE(?, '')
              AND LOWER(TRIM(title)) = LOWER(TRIM(?))
              AND COALESCE(course, '') = COALESCE(?, '')
              AND COALESCE(due_at, '') = COALESCE(?, '')
            LIMIT 1
            ''',
            (
                _clean_candidate_text(source),
                title,
                _clean_candidate_text(course) or "",
                _clean_candidate_date(due_at) or "",
            ),
        )
        return cursor.fetchone() is not None


def _candidate_priority_for_task(value):
    if value in (None, ""):
        return 3

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
        return 3


def promote_candidate_to_task(candidate_id, status="suggested"):
    candidate = get_task_candidate(candidate_id)
    if not candidate:
        return None

    if status == "confirmed" and candidate.get("recommended_status") != "confirmed":
        status = "suggested"
    if status not in ("suggested", "confirmed"):
        status = "suggested"

    if (
        candidate.get("external_source")
        and candidate.get("external_id")
        and task_exists_by_external_id(
            candidate["external_source"],
            candidate["external_id"],
        )
    ):
        update_task_candidate_decision(candidate_id, "duplicate")
        return None

    if task_exists_by_signature(
        candidate.get("source"),
        candidate.get("title"),
        candidate.get("course"),
        candidate.get("due_at"),
    ):
        update_task_candidate_decision(candidate_id, "duplicate")
        return None

    notes = candidate.get("notes")
    if candidate.get("source_url"):
        url_note = f"Source: {candidate['source_url']}"
        notes = f"{notes}\n{url_note}" if notes else url_note

    task_id = create_task({
        "title": candidate["title"],
        "course": candidate.get("course"),
        "task_type": candidate.get("task_type"),
        "due_at": candidate.get("due_at"),
        "planned_date": candidate.get("planned_date"),
        "estimated_minutes": candidate.get("estimated_minutes"),
        "priority": _candidate_priority_for_task(candidate.get("priority")),
        "status": status,
        "source": candidate.get("source") or "task_intake",
        "confidence": candidate.get("confidence"),
        "notes": notes,
        "source_snippet": candidate.get("source_snippet"),
        "external_id": candidate.get("external_id"),
        "external_source": candidate.get("external_source"),
        "external_url": candidate.get("source_url"),
        "urgency_score": candidate.get("urgency_score") or 0,
        "urgency_label": candidate.get("urgency_label"),
        "auto_created": 1 if status == "confirmed" else 0,
        "needs_review": 1 if status == "suggested" else 0,
    })
    update_task_candidate_decision(
        candidate_id,
        "auto_created" if status == "confirmed" else "accepted",
    )
    return task_id


def get_recent_quercus_items(limit=100):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        if not _table_exists(cursor, "quercus_items"):
            return []

        cursor.execute(
            '''
            SELECT id, external_id, external_source, course_id, course_name,
                   item_type, title, body_text, url, due_at, posted_at,
                   workflow_state, raw_json, created_at, updated_at,
                   last_seen_at
            FROM quercus_items
            ORDER BY last_seen_at DESC, updated_at DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_task(task_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
