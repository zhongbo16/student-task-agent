import csv
import hashlib
import json
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
VALID_COMMITMENT_STATUSES = ("planned", "done", "ignored")
VALID_COMMITMENT_TYPES = (
    "gym",
    "class",
    "commute",
    "meal",
    "work",
    "social",
    "errand",
    "personal",
    "other",
)
VALID_MEMORY_CANDIDATE_DECISIONS = ("pending", "accepted", "ignored", "duplicate")
VALID_BEHAVIOR_ENERGY_LEVELS = ("low", "medium", "high")
VALID_COGNITIVE_LOADS = ("shallow", "medium", "deep")
VALID_BEHAVIOR_FRICTIONS = ("low", "medium", "high")
VALID_AVOIDANCE_RISKS = ("low", "medium", "high", "unknown")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tasks_table(cursor, table_name="tasks"):
    allowed_statuses = "', '".join(VALID_STATUSES)
    allowed_urgency_labels = "', '".join(VALID_URGENCY_LABELS)
    allowed_energy_levels = "', '".join(VALID_BEHAVIOR_ENERGY_LEVELS)
    allowed_cognitive_loads = "', '".join(VALID_COGNITIVE_LOADS)
    allowed_friction_levels = "', '".join(VALID_BEHAVIOR_FRICTIONS)
    allowed_avoidance_risks = "', '".join(VALID_AVOIDANCE_RISKS)
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
            first_action TEXT,
            next_action TEXT,
            energy_level TEXT CHECK (
                energy_level IS NULL
                OR energy_level IN ('{allowed_energy_levels}')
            ),
            cognitive_load TEXT CHECK (
                cognitive_load IS NULL
                OR cognitive_load IN ('{allowed_cognitive_loads}')
            ),
            emotional_friction TEXT CHECK (
                emotional_friction IS NULL
                OR emotional_friction IN ('{allowed_friction_levels}')
            ),
            avoidance_risk TEXT CHECK (
                avoidance_risk IS NULL
                OR avoidance_risk IN ('{allowed_avoidance_risks}')
            ),
            behavior_prompt TEXT,
            last_behavior_designed_at TEXT,
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


def _create_behavior_plans_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS behavior_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL UNIQUE,
            source TEXT,
            main_objective TEXT,
            full_plan_json TEXT,
            minimum_viable_day_json TEXT,
            if_then_plans_json TEXT,
            woop_json TEXT,
            avoidance_warning TEXT,
            planning_cap_minutes INTEGER,
            output_json TEXT,
            raw_response TEXT,
            created_at TEXT,
            updated_at TEXT
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


def _create_course_archives_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS course_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_key TEXT NOT NULL UNIQUE,
            course_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
            reason TEXT,
            archived_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_morning_checkins_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS morning_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkin_date TEXT NOT NULL UNIQUE,
            available_study_minutes INTEGER CHECK (
                available_study_minutes IS NULL OR available_study_minutes >= 0
            ),
            available_time_blocks TEXT,
            fixed_commitments TEXT,
            extra_commitments TEXT,
            sleep_quality TEXT,
            energy_level TEXT,
            stress_level TEXT,
            mood TEXT,
            top_personal_priority TEXT,
            avoiding_task TEXT,
            hard_stop_time TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_personal_commitments_table(cursor):
    allowed_statuses = "', '".join(VALID_COMMITMENT_STATUSES)
    allowed_types = "', '".join(VALID_COMMITMENT_TYPES)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS personal_commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            commitment_type TEXT CHECK (
                commitment_type IS NULL
                OR commitment_type IN ('{allowed_types}')
            ),
            planned_date TEXT,
            start_time TEXT,
            estimated_minutes INTEGER CHECK (
                estimated_minutes IS NULL OR estimated_minutes > 0
            ),
            priority INTEGER DEFAULT 3 CHECK (
                priority IS NULL OR priority BETWEEN 1 AND 5
            ),
            status TEXT DEFAULT 'planned' CHECK (
                status IN ('{allowed_statuses}')
            ),
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_daily_commands_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_date TEXT NOT NULL,
            input_summary_json TEXT,
            output_json TEXT,
            raw_response TEXT,
            created_at TEXT
        )
    ''')


def _create_daily_command_reviews_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_command_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_id INTEGER NOT NULL UNIQUE,
            command_date TEXT NOT NULL,
            review_date TEXT NOT NULL,
            completion_score REAL DEFAULT 0,
            planning_accuracy TEXT,
            main_tasks_completed INTEGER DEFAULT 0,
            main_tasks_total INTEGER DEFAULT 0,
            focus_minutes INTEGER DEFAULT 0,
            focus_sessions_count INTEGER DEFAULT 0,
            avoidance_flags TEXT,
            time_estimation_notes TEXT,
            overload_warning TEXT,
            feedback_summary TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_agent_memory_candidates_table(cursor):
    allowed_types = "', '".join(VALID_MEMORY_TYPES)
    allowed_confidences = "', '".join(VALID_MEMORY_CONFIDENCES)
    allowed_decisions = "', '".join(VALID_MEMORY_CANDIDATE_DECISIONS)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS agent_memory_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_hash TEXT UNIQUE,
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
            evidence_json TEXT,
            decision_status TEXT DEFAULT 'pending' CHECK (
                decision_status IN ('{allowed_decisions}')
            ),
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_checkin_answers_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS checkin_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkin_date TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            reason TEXT,
            answer_type TEXT,
            source TEXT DEFAULT 'ai_question_coach',
            created_at TEXT,
            updated_at TEXT
        )
    ''')


def _create_command_center_messages_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS command_center_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_date TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            proposal_json TEXT,
            applied INTEGER DEFAULT 0 CHECK (applied IN (0, 1)),
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
        course_archives_missing = not _table_exists(cursor, "course_archives")
        morning_checkins_missing = not _table_exists(cursor, "morning_checkins")
        personal_commitments_missing = not _table_exists(
            cursor,
            "personal_commitments",
        )
        daily_commands_missing = not _table_exists(cursor, "daily_commands")
        behavior_plans_missing = not _table_exists(cursor, "behavior_plans")
        daily_command_reviews_missing = not _table_exists(
            cursor,
            "daily_command_reviews",
        )
        agent_memory_candidates_missing = not _table_exists(
            cursor,
            "agent_memory_candidates",
        )
        checkin_answers_missing = not _table_exists(cursor, "checkin_answers")
        command_center_messages_missing = not _table_exists(
            cursor,
            "command_center_messages",
        )
        return (
            tasks_need_migration
            or daily_reviews_missing
            or agent_memory_missing
            or ai_boss_briefings_missing
            or task_candidates_missing
            or course_archives_missing
            or morning_checkins_missing
            or personal_commitments_missing
            or daily_commands_missing
            or behavior_plans_missing
            or daily_command_reviews_missing
            or agent_memory_candidates_missing
            or checkin_answers_missing
            or command_center_messages_missing
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

    def choice_expr(column_name, valid_values):
        if column_name not in legacy_columns:
            return "NULL"
        allowed = "', '".join(valid_values)
        return (
            f"CASE WHEN {column_name} IN ('{allowed}') "
            f"THEN {column_name} ELSE NULL END"
        )

    cursor.execute(f'''
        INSERT INTO tasks (
            id, title, course, task_type, due_at, planned_date,
            estimated_minutes, priority, status, source, confidence, notes,
            source_snippet, external_id, external_source, external_url,
            urgency_score, urgency_label, auto_created, needs_review,
            last_scored_at, first_action, next_action, energy_level,
            cognitive_load, emotional_friction, avoidance_risk,
            behavior_prompt, last_behavior_designed_at,
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
            {text_expr("first_action")},
            {text_expr("next_action")},
            {choice_expr("energy_level", VALID_BEHAVIOR_ENERGY_LEVELS)},
            {choice_expr("cognitive_load", VALID_COGNITIVE_LOADS)},
            {choice_expr("emotional_friction", VALID_BEHAVIOR_FRICTIONS)},
            {choice_expr("avoidance_risk", VALID_AVOIDANCE_RISKS)},
            {text_expr("behavior_prompt")},
            {text_expr("last_behavior_designed_at")},
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
           last_scored_at, first_action, next_action, energy_level,
           cognitive_load, emotional_friction, avoidance_risk,
           behavior_prompt, last_behavior_designed_at,
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


def add_task_behavior_columns_if_missing(cursor=None):
    def add_columns(active_cursor):
        columns = set(_table_columns(active_cursor, "tasks"))
        if "first_action" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN first_action TEXT")
        if "next_action" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN next_action TEXT")
        if "energy_level" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN energy_level TEXT")
        if "cognitive_load" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN cognitive_load TEXT")
        if "emotional_friction" not in columns:
            active_cursor.execute(
                "ALTER TABLE tasks ADD COLUMN emotional_friction TEXT"
            )
        if "avoidance_risk" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN avoidance_risk TEXT")
        if "behavior_prompt" not in columns:
            active_cursor.execute("ALTER TABLE tasks ADD COLUMN behavior_prompt TEXT")
        if "last_behavior_designed_at" not in columns:
            active_cursor.execute(
                "ALTER TABLE tasks ADD COLUMN last_behavior_designed_at TEXT"
            )

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
        add_task_behavior_columns_if_missing(cursor)
        _create_study_sessions_table(cursor)
        _create_task_candidates_table(cursor)
        _create_course_archives_table(cursor)
        _create_morning_checkins_table(cursor)
        _create_personal_commitments_table(cursor)
        _create_daily_commands_table(cursor)
        _create_behavior_plans_table(cursor)
        _create_daily_command_reviews_table(cursor)
        _create_agent_memory_candidates_table(cursor)
        _create_checkin_answers_table(cursor)
        _create_command_center_messages_table(cursor)
        conn.commit()

    init_daily_reviews_table(create_backup=False)
    init_agent_memory_table(create_backup=False)
    init_ai_boss_briefings_table(create_backup=False)
    init_morning_checkins_table(create_backup=False)
    init_personal_commitments_table(create_backup=False)
    init_daily_commands_table(create_backup=False)
    init_behavior_plans_table(create_backup=False)
    init_daily_command_reviews_table(create_backup=False)
    init_agent_memory_candidates_table(create_backup=False)
    init_checkin_answers_table(create_backup=False)
    init_command_center_messages_table(create_backup=False)
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


def init_morning_checkins_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "morning_checkins")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_morning_checkins_table(cursor)
        conn.commit()


def init_personal_commitments_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "personal_commitments")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_personal_commitments_table(cursor)
        conn.commit()


def init_daily_commands_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "daily_commands")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_daily_commands_table(cursor)
        conn.commit()


def init_behavior_plans_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "behavior_plans")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_behavior_plans_table(cursor)
        conn.commit()


def init_daily_command_reviews_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "daily_command_reviews")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_daily_command_reviews_table(cursor)
        conn.commit()


def init_agent_memory_candidates_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "agent_memory_candidates")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_agent_memory_candidates_table(cursor)
        conn.commit()


def init_checkin_answers_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "checkin_answers")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_checkin_answers_table(cursor)
        conn.commit()


def init_command_center_messages_table(create_backup=True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    missing = True
    if DB_PATH.exists():
        with closing(_connect()) as conn:
            cursor = conn.cursor()
            missing = not _table_exists(cursor, "command_center_messages")

    if missing and create_backup:
        backup_database()

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        _create_command_center_messages_table(cursor)
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


def _clean_optional_int(value, minimum=None, maximum=None):
    if value in (None, ""):
        return None

    number = int(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"Value must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"Value must be at most {maximum}.")
    return number


def _clean_time_text(value):
    text = _clean_review_text(value)
    if not text:
        return None

    try:
        datetime.strptime(text, "%H:%M")
    except ValueError as error:
        raise ValueError("Time must use HH:MM format.") from error
    return text


def _normalize_choice(value, valid_values, default=None, field_name="Value"):
    text = _clean_review_text(value)
    if not text:
        return default

    text = text.lower()
    if text not in valid_values:
        raise ValueError(f"{field_name} must be one of: {', '.join(valid_values)}.")
    return text


def _normalize_morning_checkin(checkin):
    return {
        "checkin_date": _clean_review_date(checkin.get("checkin_date")),
        "available_study_minutes": _clean_optional_int(
            checkin.get("available_study_minutes"),
            minimum=0,
        ),
        "available_time_blocks": _clean_review_text(
            checkin.get("available_time_blocks")
        ),
        "fixed_commitments": _clean_review_text(checkin.get("fixed_commitments")),
        "extra_commitments": _clean_review_text(checkin.get("extra_commitments")),
        "sleep_quality": _clean_review_text(checkin.get("sleep_quality")),
        "energy_level": _clean_review_text(checkin.get("energy_level")),
        "stress_level": _clean_review_text(checkin.get("stress_level")),
        "mood": _clean_review_text(checkin.get("mood")),
        "top_personal_priority": _clean_review_text(
            checkin.get("top_personal_priority")
        ),
        "avoiding_task": _clean_review_text(checkin.get("avoiding_task")),
        "hard_stop_time": _clean_time_text(checkin.get("hard_stop_time")),
        "notes": _clean_review_text(checkin.get("notes")),
    }


def create_or_update_morning_checkin(checkin):
    checkin = _normalize_morning_checkin(checkin)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO morning_checkins (
                checkin_date, available_study_minutes, available_time_blocks,
                fixed_commitments, extra_commitments, sleep_quality,
                energy_level, stress_level, mood, top_personal_priority,
                avoiding_task, hard_stop_time, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(checkin_date) DO UPDATE SET
                available_study_minutes = excluded.available_study_minutes,
                available_time_blocks = excluded.available_time_blocks,
                fixed_commitments = excluded.fixed_commitments,
                extra_commitments = excluded.extra_commitments,
                sleep_quality = excluded.sleep_quality,
                energy_level = excluded.energy_level,
                stress_level = excluded.stress_level,
                mood = excluded.mood,
                top_personal_priority = excluded.top_personal_priority,
                avoiding_task = excluded.avoiding_task,
                hard_stop_time = excluded.hard_stop_time,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            ''',
            (
                checkin["checkin_date"],
                checkin["available_study_minutes"],
                checkin["available_time_blocks"],
                checkin["fixed_commitments"],
                checkin["extra_commitments"],
                checkin["sleep_quality"],
                checkin["energy_level"],
                checkin["stress_level"],
                checkin["mood"],
                checkin["top_personal_priority"],
                checkin["avoiding_task"],
                checkin["hard_stop_time"],
                checkin["notes"],
                now,
                now,
            ),
        )
        conn.commit()

    return get_morning_checkin_by_date(checkin["checkin_date"])


def get_morning_checkin_by_date(checkin_date):
    checkin_date = _clean_review_date(checkin_date)
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, checkin_date, available_study_minutes,
                   available_time_blocks, fixed_commitments,
                   extra_commitments, sleep_quality, energy_level,
                   stress_level, mood, top_personal_priority, avoiding_task,
                   hard_stop_time, notes, created_at, updated_at
            FROM morning_checkins
            WHERE checkin_date = ?
            LIMIT 1
            ''',
            (checkin_date,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_morning_checkins(limit=7):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, checkin_date, available_study_minutes,
                   available_time_blocks, fixed_commitments,
                   extra_commitments, sleep_quality, energy_level,
                   stress_level, mood, top_personal_priority, avoiding_task,
                   hard_stop_time, notes, created_at, updated_at
            FROM morning_checkins
            ORDER BY checkin_date DESC, updated_at DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _normalize_personal_commitment(commitment):
    title = _clean_review_text(commitment.get("title"))
    if not title:
        raise ValueError("Commitment title is required.")

    commitment_type = _normalize_choice(
        commitment.get("commitment_type"),
        VALID_COMMITMENT_TYPES,
        default="other",
        field_name="Commitment type",
    )
    status = _normalize_choice(
        commitment.get("status"),
        VALID_COMMITMENT_STATUSES,
        default="planned",
        field_name="Commitment status",
    )

    return {
        "title": title,
        "commitment_type": commitment_type,
        "planned_date": _clean_review_date(commitment.get("planned_date")),
        "start_time": _clean_time_text(commitment.get("start_time")),
        "estimated_minutes": _clean_optional_int(
            commitment.get("estimated_minutes"),
            minimum=1,
        ),
        "priority": _clean_optional_int(commitment.get("priority"), 1, 5) or 3,
        "status": status,
        "notes": _clean_review_text(commitment.get("notes")),
    }


def create_personal_commitment(commitment):
    commitment = _normalize_personal_commitment(commitment)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO personal_commitments (
                title, commitment_type, planned_date, start_time,
                estimated_minutes, priority, status, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                commitment["title"],
                commitment["commitment_type"],
                commitment["planned_date"],
                commitment["start_time"],
                commitment["estimated_minutes"],
                commitment["priority"],
                commitment["status"],
                commitment["notes"],
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_personal_commitments_for_date(planned_date, include_ignored=False):
    planned_date = _clean_review_date(planned_date)
    status_clause = "" if include_ignored else "AND status != 'ignored'"
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, title, commitment_type, planned_date, start_time,
                   estimated_minutes, priority, status, notes,
                   created_at, updated_at
            FROM personal_commitments
            WHERE planned_date = ?
              {status_clause}
            ORDER BY
                CASE WHEN start_time IS NULL THEN 1 ELSE 0 END,
                start_time ASC,
                priority DESC,
                created_at DESC
            ''',
            (planned_date,),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_personal_commitment_status(commitment_id, status):
    status = _normalize_choice(
        status,
        VALID_COMMITMENT_STATUSES,
        field_name="Commitment status",
    )
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE personal_commitments
            SET status = ?, updated_at = ?
            WHERE id = ?
            ''',
            (status, now, commitment_id),
        )
        conn.commit()
        return cursor.rowcount


def save_daily_command(
    command_date,
    input_summary_json,
    output_json,
    raw_response=None,
):
    command_date = _clean_review_date(command_date)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO daily_commands (
                command_date, input_summary_json, output_json,
                raw_response, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ''',
            (
                command_date,
                input_summary_json,
                output_json,
                raw_response,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_latest_daily_command(command_date=None):
    params = ()
    where_clause = ""
    if command_date:
        where_clause = "WHERE command_date = ?"
        params = (_clean_review_date(command_date),)

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, command_date, input_summary_json, output_json,
                   raw_response, created_at
            FROM daily_commands
            {where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            ''',
            params,
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_daily_commands(limit=7):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, command_date, input_summary_json, output_json,
                   raw_response, created_at
            FROM daily_commands
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _normalize_daily_command_review(review):
    command_id = int(review.get("command_id"))
    if command_id <= 0:
        raise ValueError("Command id is required.")

    score = review.get("completion_score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(100.0, score))

    return {
        "command_id": command_id,
        "command_date": _clean_review_date(review.get("command_date")),
        "review_date": _clean_review_date(review.get("review_date")),
        "completion_score": score,
        "planning_accuracy": _clean_review_text(review.get("planning_accuracy")),
        "main_tasks_completed": _clean_optional_int(
            review.get("main_tasks_completed"),
            minimum=0,
        ) or 0,
        "main_tasks_total": _clean_optional_int(
            review.get("main_tasks_total"),
            minimum=0,
        ) or 0,
        "focus_minutes": _clean_optional_int(review.get("focus_minutes"), minimum=0) or 0,
        "focus_sessions_count": _clean_optional_int(
            review.get("focus_sessions_count"),
            minimum=0,
        ) or 0,
        "avoidance_flags": _clean_review_text(review.get("avoidance_flags")),
        "time_estimation_notes": _clean_review_text(
            review.get("time_estimation_notes")
        ),
        "overload_warning": _clean_review_text(review.get("overload_warning")),
        "feedback_summary": _clean_review_text(review.get("feedback_summary")),
    }


def create_or_update_daily_command_review(review):
    review = _normalize_daily_command_review(review)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO daily_command_reviews (
                command_id, command_date, review_date, completion_score,
                planning_accuracy, main_tasks_completed, main_tasks_total,
                focus_minutes, focus_sessions_count, avoidance_flags,
                time_estimation_notes, overload_warning, feedback_summary,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(command_id) DO UPDATE SET
                command_date = excluded.command_date,
                review_date = excluded.review_date,
                completion_score = excluded.completion_score,
                planning_accuracy = excluded.planning_accuracy,
                main_tasks_completed = excluded.main_tasks_completed,
                main_tasks_total = excluded.main_tasks_total,
                focus_minutes = excluded.focus_minutes,
                focus_sessions_count = excluded.focus_sessions_count,
                avoidance_flags = excluded.avoidance_flags,
                time_estimation_notes = excluded.time_estimation_notes,
                overload_warning = excluded.overload_warning,
                feedback_summary = excluded.feedback_summary,
                updated_at = excluded.updated_at
            ''',
            (
                review["command_id"],
                review["command_date"],
                review["review_date"],
                review["completion_score"],
                review["planning_accuracy"],
                review["main_tasks_completed"],
                review["main_tasks_total"],
                review["focus_minutes"],
                review["focus_sessions_count"],
                review["avoidance_flags"],
                review["time_estimation_notes"],
                review["overload_warning"],
                review["feedback_summary"],
                now,
                now,
            ),
        )
        conn.commit()

    return get_daily_command_review_by_command(review["command_id"])


def get_daily_command_review_by_command(command_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, command_id, command_date, review_date, completion_score,
                   planning_accuracy, main_tasks_completed, main_tasks_total,
                   focus_minutes, focus_sessions_count, avoidance_flags,
                   time_estimation_notes, overload_warning, feedback_summary,
                   created_at, updated_at
            FROM daily_command_reviews
            WHERE command_id = ?
            LIMIT 1
            ''',
            (int(command_id),),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_daily_command_reviews(limit=7):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, command_id, command_date, review_date, completion_score,
                   planning_accuracy, main_tasks_completed, main_tasks_total,
                   focus_minutes, focus_sessions_count, avoidance_flags,
                   time_estimation_notes, overload_warning, feedback_summary,
                   created_at, updated_at
            FROM daily_command_reviews
            ORDER BY review_date DESC, updated_at DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _memory_candidate_hash(memory_type, memory_key, memory_value):
    raw = "|".join([
        _clean_memory_text(memory_type) or "",
        _clean_memory_text(memory_key) or "",
        _clean_memory_text(memory_value) or "",
    ]).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_memory_candidate(candidate):
    memory_type = _clean_memory_type(candidate.get("memory_type"))
    memory_key = _clean_memory_text(candidate.get("memory_key"))
    if not memory_key:
        raise ValueError("Memory candidate key is required.")

    memory_value = _clean_memory_text(candidate.get("memory_value"))
    if not memory_value:
        raise ValueError("Memory candidate value is required.")

    decision_status = (
        _clean_memory_text(candidate.get("decision_status")) or "pending"
    )
    if decision_status not in VALID_MEMORY_CANDIDATE_DECISIONS:
        decision_status = "pending"

    candidate_hash = _clean_memory_text(candidate.get("candidate_hash"))
    if not candidate_hash:
        candidate_hash = _memory_candidate_hash(
            memory_type,
            memory_key,
            memory_value,
        )

    return {
        "candidate_hash": candidate_hash,
        "memory_type": memory_type,
        "memory_key": memory_key,
        "memory_value": memory_value,
        "confidence": _clean_memory_confidence(candidate.get("confidence")) or "medium",
        "source": _clean_memory_text(candidate.get("source")) or "feedback_loop",
        "evidence_json": _clean_memory_text(candidate.get("evidence_json")),
        "decision_status": decision_status,
    }


def create_agent_memory_candidate(candidate):
    candidate = _normalize_memory_candidate(candidate)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT OR IGNORE INTO agent_memory_candidates (
                candidate_hash, memory_type, memory_key, memory_value,
                confidence, source, evidence_json, decision_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                candidate["candidate_hash"],
                candidate["memory_type"],
                candidate["memory_key"],
                candidate["memory_value"],
                candidate["confidence"],
                candidate["source"],
                candidate["evidence_json"],
                candidate["decision_status"],
                now,
                now,
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return cursor.lastrowid


def _fetch_agent_memory_candidates(where_clause="", params=()):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, candidate_hash, memory_type, memory_key, memory_value,
                   confidence, source, evidence_json, decision_status,
                   created_at, updated_at
            FROM agent_memory_candidates
            {where_clause}
            ''',
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


def get_pending_agent_memory_candidates():
    return _fetch_agent_memory_candidates(
        '''
        WHERE decision_status = 'pending'
        ORDER BY updated_at DESC, id DESC
        '''
    )


def update_agent_memory_candidate_decision(candidate_id, decision_status):
    if decision_status not in VALID_MEMORY_CANDIDATE_DECISIONS:
        raise ValueError(
            "Memory candidate decision must be one of: "
            f"{', '.join(VALID_MEMORY_CANDIDATE_DECISIONS)}."
        )

    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE agent_memory_candidates
            SET decision_status = ?, updated_at = ?
            WHERE id = ?
            ''',
            (decision_status, now, int(candidate_id)),
        )
        conn.commit()
        return cursor.rowcount


def promote_memory_candidate_to_memory(candidate_id):
    candidates = _fetch_agent_memory_candidates(
        "WHERE id = ? LIMIT 1",
        (int(candidate_id),),
    )
    if not candidates:
        return None

    candidate = candidates[0]
    if memory_exists(candidate["memory_type"], candidate["memory_key"]):
        update_agent_memory_candidate_decision(candidate_id, "duplicate")
        return None

    memory_id = create_agent_memory({
        "memory_type": candidate["memory_type"],
        "memory_key": candidate["memory_key"],
        "memory_value": candidate["memory_value"],
        "confidence": candidate["confidence"],
        "source": candidate["source"],
        "is_active": 1,
    })
    update_agent_memory_candidate_decision(candidate_id, "accepted")
    return memory_id


def create_checkin_answer(answer):
    question = _clean_review_text(answer.get("question"))
    if not question:
        raise ValueError("Question is required.")

    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO checkin_answers (
                checkin_date, question, answer, reason, answer_type,
                source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                _clean_review_date(answer.get("checkin_date")),
                question,
                _clean_review_text(answer.get("answer")),
                _clean_review_text(answer.get("reason")),
                _clean_review_text(answer.get("answer_type")),
                _clean_review_text(answer.get("source")) or "ai_question_coach",
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_checkin_answers_by_date(checkin_date):
    checkin_date = _clean_review_date(checkin_date)
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, checkin_date, question, answer, reason, answer_type,
                   source, created_at, updated_at
            FROM checkin_answers
            WHERE checkin_date = ?
            ORDER BY created_at DESC, id DESC
            ''',
            (checkin_date,),
        )
        return [dict(row) for row in cursor.fetchall()]


def create_command_center_message(
    message_date,
    role,
    content,
    proposal_json=None,
    applied=0,
):
    role = _clean_review_text(role)
    if role not in ("user", "assistant", "system"):
        raise ValueError("Message role must be user, assistant, or system.")

    content = _clean_review_text(content)
    if not content:
        raise ValueError("Message content is required.")

    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO command_center_messages (
                message_date, role, content, proposal_json, applied,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                _clean_review_date(message_date),
                role,
                content,
                _clean_review_text(proposal_json),
                1 if applied else 0,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def mark_command_center_message_applied(message_id):
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE command_center_messages
            SET applied = 1,
                updated_at = ?
            WHERE id = ?
            ''',
            (now, int(message_id)),
        )
        conn.commit()
        return cursor.rowcount


def get_recent_command_center_messages(message_date=None, limit=20):
    limit = max(1, int(limit))
    params = []
    where_clause = ""
    if message_date:
        where_clause = "WHERE message_date = ?"
        params.append(_clean_review_date(message_date))

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT id, message_date, role, content, proposal_json, applied,
                   created_at, updated_at
            FROM command_center_messages
            {where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            ''',
            (*params, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


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


def _json_text(value):
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _clean_planning_cap(value):
    if value in (None, ""):
        return None
    try:
        cap = int(value)
    except (TypeError, ValueError):
        return None
    return cap if cap >= 0 else None


def create_or_update_behavior_plan(plan):
    plan_date = _clean_review_date(plan.get("plan_date"))
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO behavior_plans (
                plan_date, source, main_objective, full_plan_json,
                minimum_viable_day_json, if_then_plans_json, woop_json,
                avoidance_warning, planning_cap_minutes, output_json,
                raw_response, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_date) DO UPDATE SET
                source = excluded.source,
                main_objective = excluded.main_objective,
                full_plan_json = excluded.full_plan_json,
                minimum_viable_day_json = excluded.minimum_viable_day_json,
                if_then_plans_json = excluded.if_then_plans_json,
                woop_json = excluded.woop_json,
                avoidance_warning = excluded.avoidance_warning,
                planning_cap_minutes = excluded.planning_cap_minutes,
                output_json = excluded.output_json,
                raw_response = excluded.raw_response,
                updated_at = excluded.updated_at
            ''',
            (
                plan_date,
                _clean_review_text(plan.get("source")) or "behavior_design",
                _clean_review_text(plan.get("main_objective")),
                _json_text(plan.get("full_plan_json")),
                _json_text(plan.get("minimum_viable_day_json")),
                _json_text(plan.get("if_then_plans_json")),
                _json_text(plan.get("woop_json")),
                _clean_review_text(plan.get("avoidance_warning")),
                _clean_planning_cap(plan.get("planning_cap_minutes")),
                _json_text(plan.get("output_json")),
                _clean_review_text(plan.get("raw_response")),
                now,
                now,
            ),
        )
        conn.commit()

    return get_behavior_plan_by_date(plan_date)


def get_behavior_plan_by_date(plan_date):
    plan_date = _clean_review_date(plan_date)
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, plan_date, source, main_objective, full_plan_json,
                   minimum_viable_day_json, if_then_plans_json, woop_json,
                   avoidance_warning, planning_cap_minutes, output_json,
                   raw_response, created_at, updated_at
            FROM behavior_plans
            WHERE plan_date = ?
            LIMIT 1
            ''',
            (plan_date,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_behavior_plans(limit=7):
    limit = max(1, int(limit))
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, plan_date, source, main_objective, full_plan_json,
                   minimum_viable_day_json, if_then_plans_json, woop_json,
                   avoidance_warning, planning_cap_minutes, output_json,
                   raw_response, created_at, updated_at
            FROM behavior_plans
            ORDER BY plan_date DESC, updated_at DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_task_behavior_fields(task_id, updates):
    allowed_fields = {
        "first_action",
        "next_action",
        "energy_level",
        "cognitive_load",
        "emotional_friction",
        "avoidance_risk",
        "behavior_prompt",
        "last_behavior_designed_at",
    }
    safe_updates = {
        key: value for key, value in (updates or {}).items()
        if key in allowed_fields
    }
    if not safe_updates:
        return 0

    cleaned_updates = {}
    text_fields = {"first_action", "next_action", "behavior_prompt"}
    for field in text_fields:
        if field in safe_updates:
            cleaned_updates[field] = _clean_review_text(safe_updates[field])

    choice_fields = {
        "energy_level": (VALID_BEHAVIOR_ENERGY_LEVELS, "Energy level"),
        "cognitive_load": (VALID_COGNITIVE_LOADS, "Cognitive load"),
        "emotional_friction": (VALID_BEHAVIOR_FRICTIONS, "Emotional friction"),
        "avoidance_risk": (VALID_AVOIDANCE_RISKS, "Avoidance risk"),
    }
    for field, (valid_values, field_name) in choice_fields.items():
        if field in safe_updates:
            cleaned_updates[field] = _normalize_choice(
                safe_updates[field],
                valid_values,
                default=None,
                field_name=field_name,
            )

    now = datetime.now().isoformat(timespec="seconds")
    cleaned_updates["last_behavior_designed_at"] = (
        _clean_review_text(safe_updates.get("last_behavior_designed_at")) or now
    )
    cleaned_updates["updated_at"] = now

    assignments = ", ".join(f"{field} = ?" for field in cleaned_updates)
    values = [cleaned_updates[field] for field in cleaned_updates]
    values.append(int(task_id))

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            UPDATE tasks
            SET {assignments}
            WHERE id = ?
            ''',
            tuple(values),
        )
        conn.commit()
        return cursor.rowcount


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


def _clean_course_name(value):
    text = _clean_candidate_text(value)
    return text or "No course"


def _course_key(value):
    return _clean_course_name(value).casefold()


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


def get_task_candidates(
    decision_status="pending",
    course=None,
    source=None,
    due_filter=None,
):
    clauses = []
    params = []
    if decision_status:
        clauses.append("decision_status = ?")
        params.append(decision_status)
    if course and course != "All courses":
        clauses.append("COALESCE(course, 'No course') = ?")
        params.append(course)
    if source and source != "All sources":
        clauses.append("COALESCE(source, '') = ?")
        params.append(source)

    today = date.today().isoformat()
    if due_filter == "No due date":
        clauses.append("due_at IS NULL")
    elif due_filter == "Due today or earlier":
        clauses.append("due_at IS NOT NULL AND due_at <= ?")
        params.append(today)
    elif due_filter == "Future due date":
        clauses.append("due_at IS NOT NULL AND due_at > ?")
        params.append(today)

    where_clause = ""
    if clauses:
        where_clause = "WHERE " + " AND ".join(clauses)

    return _fetch_task_candidates(
        f'''
        {where_clause}
        ORDER BY urgency_score DESC, due_at ASC, created_at DESC
        ''',
        tuple(params),
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


def promote_candidate_to_task(candidate_id, status="suggested", allow_untrusted_confirm=False):
    candidate = get_task_candidate(candidate_id)
    if not candidate:
        return None

    if is_course_archived(candidate.get("course")):
        update_task_candidate_decision(candidate_id, "ignored")
        return None

    if (
        status == "confirmed"
        and candidate.get("recommended_status") != "confirmed"
        and not allow_untrusted_confirm
    ):
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


def get_archived_courses():
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, course_key, course_name, is_active, reason,
                   archived_at, created_at, updated_at
            FROM course_archives
            WHERE is_active = 1
            ORDER BY course_name ASC
            '''
        )
        return [dict(row) for row in cursor.fetchall()]


def is_course_archived(course):
    course_key = _course_key(course)
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT 1
            FROM course_archives
            WHERE course_key = ? AND is_active = 1
            LIMIT 1
            ''',
            (course_key,),
        )
        return cursor.fetchone() is not None


def archive_course(course, reason=None):
    course_name = _clean_course_name(course)
    course_key = _course_key(course_name)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO course_archives (
                course_key, course_name, is_active, reason,
                archived_at, created_at, updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(course_key) DO UPDATE SET
                course_name = excluded.course_name,
                is_active = 1,
                reason = excluded.reason,
                archived_at = excluded.archived_at,
                updated_at = excluded.updated_at
            ''',
            (course_key, course_name, reason, now, now, now),
        )
        cursor.execute(
            '''
            UPDATE tasks
            SET status = 'ignored',
                needs_review = 0,
                urgency_score = 0,
                urgency_label = 'low',
                last_scored_at = ?,
                updated_at = ?
            WHERE COALESCE(course, 'No course') = ?
              AND status NOT IN ('done', 'ignored')
            ''',
            (now, now, course_name),
        )
        tasks_ignored = cursor.rowcount
        cursor.execute(
            '''
            UPDATE task_candidates
            SET decision_status = 'ignored',
                updated_at = ?
            WHERE COALESCE(course, 'No course') = ?
              AND decision_status = 'pending'
            ''',
            (now, course_name),
        )
        candidates_ignored = cursor.rowcount
        conn.commit()

    return {
        "course_name": course_name,
        "tasks_ignored": tasks_ignored,
        "candidates_ignored": candidates_ignored,
    }


def unarchive_course(course):
    course_name = _clean_course_name(course)
    course_key = _course_key(course_name)
    now = datetime.now().isoformat(timespec="seconds")

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE course_archives
            SET is_active = 0,
                updated_at = ?
            WHERE course_key = ?
            ''',
            (now, course_key),
        )
        conn.commit()
        return cursor.rowcount


def get_course_summaries():
    tasks = get_all_tasks()
    candidates = _fetch_task_candidates()
    archived = {
        row["course_key"]: row for row in get_archived_courses()
    }
    summaries = {}

    def summary_for(course):
        course_name = _clean_course_name(course)
        key = _course_key(course_name)
        if key not in summaries:
            summaries[key] = {
                "course_key": key,
                "course_name": course_name,
                "active_tasks": 0,
                "ignored_tasks": 0,
                "done_tasks": 0,
                "pending_candidates": 0,
                "total_tasks": 0,
                "archived": key in archived,
            }
        return summaries[key]

    for task in tasks:
        row = summary_for(task.get("course"))
        row["total_tasks"] += 1
        if task.get("status") in ("done",):
            row["done_tasks"] += 1
        elif task.get("status") == "ignored":
            row["ignored_tasks"] += 1
        else:
            row["active_tasks"] += 1

    for candidate in candidates:
        if candidate.get("decision_status") == "pending":
            summary_for(candidate.get("course"))["pending_candidates"] += 1

    return sorted(
        summaries.values(),
        key=lambda row: (
            not row["archived"],
            -row["active_tasks"],
            -row["pending_candidates"],
            row["course_name"],
        ),
    )


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


def ignore_past_quercus_intake_items(today=None):
    today = _clean_candidate_date(today or date.today())
    now = datetime.now().isoformat(timespec="seconds")
    quercus_task_sources = (
        "quercus_assignment",
        "quercus_calendar",
        "quercus_upcoming",
        "quercus_todo",
    )
    quercus_external_sources = (
        "canvas_assignment",
        "quercus_assignment",
        "quercus_calendar",
        "quercus_upcoming",
        "quercus_todo",
    )

    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f'''
            UPDATE tasks
            SET status = 'ignored',
                needs_review = 0,
                urgency_score = 0,
                urgency_label = 'low',
                last_scored_at = ?,
                updated_at = ?
            WHERE status NOT IN ('done', 'ignored')
              AND due_at IS NOT NULL
              AND due_at < ?
              AND (
                  source IN ({','.join('?' for _ in quercus_task_sources)})
                  OR external_source IN ({','.join('?' for _ in quercus_external_sources)})
              )
            ''',
            (
                now,
                now,
                today,
                *quercus_task_sources,
                *quercus_external_sources,
            ),
        )
        tasks_ignored = cursor.rowcount

        cursor.execute(
            '''
            UPDATE task_candidates
            SET decision_status = 'ignored',
                updated_at = ?
            WHERE decision_status = 'pending'
              AND due_at IS NOT NULL
              AND due_at < ?
            ''',
            (now, today),
        )
        candidates_ignored = cursor.rowcount
        conn.commit()

    return {
        "tasks_ignored": tasks_ignored,
        "candidates_ignored": candidates_ignored,
    }


def delete_task(task_id):
    with closing(_connect()) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
