# Course Task Inbox

Course Task Inbox is a local-first Streamlit + SQLite app that helps students turn course materials, syllabi, and announcements into reviewable tasks.

The core idea is simple: AI can suggest tasks, but those suggestions are not official until the student confirms them.

This is not a cloud deployment, an autonomous agent, or a general AI productivity platform. It is a persistent course task inbox.

## Main v0 Workflow

1. **Add Material**
   Upload a PDF or paste syllabus, assignment, or announcement text.

2. **Review Suggestions**
   Review AI-extracted task suggestions. Confirm, edit, or ignore each one.

3. **Tasks**
   View confirmed tasks in Today, This Week, All Tasks, and Done.

4. **Check Updates**
   Paste later announcements or changed course material to detect new tasks or possible deadline changes. Existing task deadlines are never changed automatically.

5. **Settings**
   Check local configuration and access developer-only experimental pages when needed.

## What v0 Includes

- PDF upload and text extraction.
- Pasted course material input.
- AI task extraction from course material.
- Suggested tasks that require user review.
- Confirm / Edit / Ignore actions for suggestions.
- A persistent confirmed task dashboard.
- A simple manual fallback for adding one confirmed task without AI.
- Check Updates flow for later announcements and possible deadline changes.
- Source snippets so students can verify why a task or update was suggested.
- Local SQLite persistence.

## Review-First Rules

- AI-created tasks are saved as `suggested`.
- Suggested tasks do not appear as official confirmed tasks until the user confirms them.
- Deadline updates are stored as pending update suggestions.
- Existing confirmed task deadlines change only after the user accepts an update.
- Reviewing, confirming, editing, ignoring, and viewing tasks work locally without an OpenAI API key.

## Experimental / Preserved for Development

The repository still contains older experimental work that is hidden from the main v0 workflow, including:

- AI Boss / command center experiments.
- Agent memory.
- Focus sessions.
- Daily reviews.
- Behavior design.
- Quercus / Canvas sync experiments.
- Urgency scoring and task intake experiments.

These are preserved for development only. They are not part of the main Course Task Inbox v0 experience.

## Project Files

- `app.py` - Streamlit UI and page routing.
- `db.py` - SQLite schema, migrations, and persistence helpers.
- `models.py` - task schema and normalization.
- `file_parser.py` - PDF metadata and text extraction.
- `ai_parser.py` - AI task extraction from course material.
- `planner.py` - existing task sorting helpers.
- `docs/V0_SCOPE.md` - v0 product scope.
- `docs/DEMO_TEST.md` - manual demo and validation script.

Experimental modules such as `ai_boss.py`, `behavior_design.py`, `canvas_client.py`, `task_intake.py`, and `urgency.py` remain in the repo for development continuity.

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

5. Add an OpenAI key if you want AI extraction:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

Optional experimental Canvas / Quercus variables may also exist in `.env.example`, but they are not required for the v0 flow.

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

## Manual Demo

Use `docs/DEMO_TEST.md` to test the main product loop:

1. Paste sample syllabus text.
2. Extract suggestions.
3. Confirm, edit, and ignore suggestions.
4. Verify confirmed tasks appear in Tasks.
5. Paste an announcement with a deadline extension.
6. Accept or ignore the pending deadline update.
