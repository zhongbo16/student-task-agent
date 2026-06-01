# Course Task Inbox V0 Scope

## Product Positioning

Course Task Inbox turns course materials, syllabi, and announcements into a persistent student task dashboard with human-reviewed AI suggestions.

It is not a general AI Boss, behavior coach, life manager, or multi-agent system.

## Core V0 Workflow

1. User uploads a PDF or pastes course material.
2. AI extracts structured task suggestions.
3. Suggestions appear in Review Suggestions.
4. User confirms, edits, or ignores each suggestion.
5. Confirmed tasks appear in Tasks.
6. User later pastes announcements or changed course material.
7. The app flags new task suggestions, possible duplicates, and possible deadline updates.
8. Existing deadlines change only after the user accepts an update.

## Included Features

- Add Material with PDF upload and pasted text.
- Material labels: syllabus, announcement, assignment instruction, other.
- AI task extraction into suggested tasks only.
- Review Suggestions inbox with Confirm, Edit, and Ignore.
- Confirmed task dashboard with Today, This Week, All Tasks, and Done.
- Check Updates flow for new tasks, duplicates, and possible deadline changes.
- Source snippets for AI-created suggestions and update suggestions.
- Simple duplicate detection based on title similarity, course, task type, and due date.
- Local SQLite persistence.

## Excluded Features

The focused v0 does not include these as main product features:

- AI Boss personality.
- Behavior coaching or behavior design.
- Daily command or command center workflow.
- Focus session timer.
- Daily review.
- Agent memory.
- Complex urgency scoring as a core workflow.
- Canvas or Quercus sync as required setup.
- Calendar sync.
- Autonomous task editing.
- Multi-agent architecture.
- Multi-user accounts.
- Cloud deployment.

Some older experimental code may remain available under Settings for development, but it is not part of the v0 product.

## Future Backlog

- Canvas / Quercus sync.
- Calendar export or sync.
- Reminders.
- Agent memory.
- Daily planning.
- Daily review.
- Study session timer.
- Behavior design.
- Mobile app.
- Multi-user accounts.
- Cloud deployment.
- Advanced task prioritization.

## Product Principles

- The app should be understandable in 10 seconds.
- AI output is a suggestion, not an automatic commitment.
- Confirmed task deadlines are never changed without user approval.
- Every AI-created task or deadline update should show a source snippet.
- Prefer hiding complexity over adding more product surface.
- Keep the main navigation boring and clear: Add Material, Review Suggestions, Tasks, Check Updates, Settings.

## Manual Testing Checklist

1. Upload or paste a syllabus containing several assignments and extract suggestions.
2. Confirm, edit, and ignore suggestions from Review Suggestions.
3. Confirmed tasks appear in Today, This Week, or All Tasks as appropriate.
4. Paste an announcement extending an existing assignment deadline.
5. Confirm that a pending update appears and the deadline changes only after accepting it.
6. Paste an announcement adding a new quiz and confirm it becomes a suggested task.
7. Paste duplicate material and confirm likely duplicates are not silently confirmed.
8. Paste vague dates and confirm the app keeps uncertainty in the review flow.
