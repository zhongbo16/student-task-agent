# Course Task Inbox Demo Test

Use this script to manually test the v0 product flow.

## 1. Sample Syllabus Text

Paste this into **Add Material** with material type `syllabus`.

```text
STA457 Applied Statistics

Assignments:
- Workshop 1 is due May 20 at 11:59 PM and is worth 5%.
- Workshop 2 is due May 27 at 11:59 PM and is worth 5%.
- Final project proposal is due June 10 at 5:00 PM and is worth 10%.

Quizzes:
- Quiz 1 will be held on May 24 and covers Lectures 1-3.

Exam:
- Midterm exam is scheduled for June 18 from 2:00 PM to 4:00 PM.
```

## Expected Behavior

- Click **Extract Task Suggestions**.
- The app should create suggested tasks only.
- The suggested tasks should appear in **Review Suggestions**.
- None of the AI-created tasks should be automatically confirmed.
- Each suggestion should include a source snippet when the AI provides one.

## What To Check

- Confirm one suggestion.
- Edit one suggestion before confirming.
- Ignore one suggestion.
- Confirmed tasks should appear in **Tasks**.
- Ignored suggestions should not appear in **Tasks**.

## 2. Sample Announcement With Deadline Extension

After confirming `Workshop 2`, paste this into **Check Updates**.

```text
Announcement: Workshop 2 deadline update

The deadline for STA457 Workshop 2 has been extended.
The new deadline is May 29 at 11:59 PM.
Everything else about the assignment remains the same.
```

## Expected Behavior

- Click **Check for New Tasks or Deadline Changes**.
- The app should detect a possible deadline update for the existing Workshop 2 task.
- The app should show:
  - matched existing task
  - current due date
  - proposed new due date
  - source snippet
  - confidence
  - reason
- The existing task deadline should not change until **Accept Deadline Update** is clicked.

## What To Check

- Ignore the update once and verify the task deadline does not change.
- Run the check again if needed.
- Accept the update and verify the confirmed task now has the new due date.

## 3. Sample Announcement With New Quiz

Paste this into **Check Updates**.

```text
New quiz announcement

STA457 Quiz 2 will be held on June 3 during tutorial.
It will cover Lectures 4 and 5.
```

## Expected Behavior

- The app should create a new suggested task.
- The task should appear in **Review Suggestions**.
- The task should not appear in **Tasks** until confirmed.

## 4. Sample Duplicate Text

Paste this into **Add Material** or **Check Updates** after the original Workshop 1 task exists.

```text
Reminder: STA457 Workshop 1 is due May 20 at 11:59 PM.
```

## Expected Behavior

- The app should avoid silently creating a confirmed duplicate.
- If uncertain, it should keep the item in review instead of changing an existing task automatically.

## 5. Vague Date Test

Paste this into **Add Material**.

```text
The reading response will be due sometime after Reading Week.
More details will be announced later.
```

## Expected Behavior

- The AI should not invent a due date.
- If it creates a suggestion, confidence should be medium or low.
- The user should review it before confirming.

## Local-Only Checks

These should work without an OpenAI API key:

- Open **Review Suggestions**.
- Confirm a suggested task.
- Edit a suggested task.
- Ignore a suggested task.
- Open **Tasks** and view confirmed tasks.
- Mark a confirmed task done.

OpenAI is only needed for:

- **Add Material** extraction.
- **Check Updates** extraction.
