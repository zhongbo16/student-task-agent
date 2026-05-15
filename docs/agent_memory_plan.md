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

## Future AI Boss

Future AI Boss features should use:

- current tasks
- Today Plan
- recent study_sessions
- recent daily_reviews
- active agent_memory

The AI Boss should treat raw execution data as evidence and active memories as user-controlled guidance.

## User Control

User control is the core rule for persistent memory:

- The user can manually create memory.
- The user can deactivate memory.
- AI-generated memory should not silently overwrite user-confirmed memory.
- Raw data should not be overwritten by AI summaries.
- Memory should be editable or deactivatable by the user.

Future AI-generated memory should be shown to the user for review before becoming durable guidance.
