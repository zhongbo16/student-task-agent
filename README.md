# Student Task Agent

Student Task Agent is a local-first Streamlit + SQLite task organizer for university students.

The app currently supports manual task tracking, syllabus PDF upload, AI-assisted syllabus task suggestions, read-only Quercus/Canvas assignment sync, focus session logging, and daily reviews. Data is stored locally in SQLite.

## Current MVP Features

- Manual task creation
- SQLite persistence
- Dashboard views:
  - Today
  - This Week
  - Confirmed Tasks
  - Suggested Tasks
  - In Progress
  - Completed
  - All Tasks
- Task status actions:
  - Confirm / Ignore suggested tasks
  - Start / Mark Done confirmed tasks
  - Move in-progress tasks back to confirmed
  - Reopen completed tasks
- Priority and date-based task sorting
- Rule-based Today Plan
- PDF upload and text extraction with PyMuPDF
- AI syllabus task extraction with OpenAI
  - Extracted tasks are saved as `suggested`
  - AI tasks are never auto-confirmed
- Read-only Quercus/Canvas assignment sync
  - Assignments are imported as `confirmed`
  - Duplicate synced assignments are skipped
- Focus Session / Study Session log
  - Start and end focus sessions
  - Track actual minutes, blockers, notes, and completion status
- Daily Review
  - One review per date
  - Update existing reviews instead of creating duplicates
  - Export daily reviews to CSV
- Persistent Agent Memory
  - Manually store long-term preferences, rules, goals, and patterns
  - Deactivate memories without deleting raw data
  - Seed default AI Boss foundation memories without duplicates
- AI Boss v0
  - Generates a daily execution briefing from compact local context
  - Reads tasks, Today Plan, focus sessions, daily reviews, and agent memory
  - Saves briefings locally without automatically changing task status
- Data retention foundation
  - SQLite backups before schema migrations when practical
  - Raw data preserved for future agent memory

## Not Implemented Yet

- Autonomous AI task editing
- Screen monitoring
- Multi-user accounts
- Cloud deployment
- Canvas write actions
- Assignment submission
- Grade sync
- Calendar sync

## Project Files

- `app.py` - Streamlit UI and page routing
- `db.py` - SQLite schema, migrations, and persistence helpers
- `models.py` - task schema and normalization
- `planner.py` - rule-based task sorting and Today Plan
- `file_parser.py` - PDF metadata and text extraction
- `ai_parser.py` - AI syllabus task extraction
- `ai_boss.py` - AI Boss context building and briefing generation
- `canvas_client.py` - read-only Canvas API client
- `prompts/ai_boss.md` - AI Boss guardrails and JSON output prompt
- `docs/agent_memory_plan.md` - future agent memory plan

## Setup

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a local `.env` file from `.env.example`:

```bash
cp .env.example .env
```

5. Add keys only for features you want to use:

```env
OPENAI_API_KEY=your_openai_api_key_here
CANVAS_BASE_URL=https://q.utoronto.ca
CANVAS_API_TOKEN=your_canvas_api_token_here
```

Never commit `.env`.

## Run

```bash
streamlit run app.py
```

## Local Data

The app stores local data under `data/` and uploaded PDFs under `uploads/`.

Ignored by Git:

- `.env`
- SQLite database files
- database backups
- CSV exports
- uploaded PDFs

Only `uploads/.gitkeep` is committed so the upload directory exists in the repo.

## Data Model Summary

Main persisted data:

- `tasks`
- `study_sessions`
- `daily_reviews`
- `agent_memory`
- `ai_boss_briefings`

Future AI memory should summarize patterns from raw data without overwriting raw data.
