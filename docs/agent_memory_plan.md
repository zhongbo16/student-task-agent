# Agent Memory Plan

## Raw Data

The app should preserve raw execution data before trying to summarize it.

Raw data includes:

- tasks
- study_sessions
- daily_reviews
- Quercus assignments
- AI-extracted suggested tasks

Raw data is the evidence layer. It should stay available for review, export, and future analysis.

## Derived Memory

The `agent_memory` table stores long-term memory that can guide future planning and coaching.

Examples of derived memory:

- recurring blockers
- task avoidance patterns
- time estimation errors
- preferred management style
- high-friction courses
- stable personal rules
- long-term goals

MVP-13 supports manual memory creation and default seed memories. It does not automatically summarize raw data yet.

## AI Boss v0

MVP-14 adds AI Boss v0. It reads a compact snapshot of:

- current tasks
- Today Plan
- recent study_sessions
- recent daily_reviews
- active agent_memory

AI Boss v0 generates a daily execution briefing and saves it to
`ai_boss_briefings`. It can recommend priorities and first actions, but it does
not automatically edit tasks, mark tasks complete, change deadlines, or write to
Quercus.

Future AI Boss features should continue to treat raw execution data as evidence
and active memories as user-controlled guidance.

## User Control

User control is the core rule for persistent memory:

- The user can manually create memory.
- The user can deactivate memory.
- AI-generated memory should not silently overwrite user-confirmed memory.
- Raw data should not be overwritten by AI summaries.
- Memory should be editable or deactivatable by the user.

Future AI-generated memory should be shown to the user for review before becoming durable guidance.
