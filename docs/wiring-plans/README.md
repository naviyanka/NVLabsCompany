# Frontend-Backend Wiring Plans

This folder contains detailed analysis for wiring up each frontend page to the backend API.

## Structure

- **Per-page files** (`activity.md`, `agents.md`, etc.) — Each file documents:
  - What the frontend currently shows (mock data shape)
  - What backend endpoints already exist and can be wired directly
  - What's missing in the backend and needs to be added
  - Implementation steps (ordered by dependency)

- **`_dependencies.md`** — Cross-page dependency map showing which pages depend on other pages being wired first.

- **`_pending-tasks.md`** — Running task list of features that are blocked because another page hasn't been wired yet. Once a blocking page is completed, come back and resolve these.

## Approach

1. Pick a page
2. Read its wiring plan file
3. Implement "direct wire-up" items first (no backend changes needed)
4. Implement "backend additions" next
5. Mark any cross-page blocked items in `_pending-tasks.md`
6. Move to the next page

## Page Priority Order

1. `/activity` (current)
2. _(to be determined based on dependencies)_
