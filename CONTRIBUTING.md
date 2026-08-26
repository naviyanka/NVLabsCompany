# Contributing to NEXUS

Thank you for contributing to **NEXUS — The Autonomous AI Company Operating System**! This guide outlines development standards, testing procedures, code intelligence protocols, and contribution workflows.

---

## Code of Conduct & Core Principles

1. **Async Throughout**: All Python backend operations must be asynchronous using native `async` / `await`.
2. **Type Safety**:
   - Backend: Python 3.12+ type hints with Pydantic and SQLModel.
   - Frontend: Strict TypeScript without implicit `any` types.
3. **No Superficial Symptom Patches**: Fix root causes rather than swallowing exceptions or returning dummy fallbacks.
4. **Preserve Documentation Integrity**: Preserve docstrings, comments, and architectural specifications.

---

## Code Intelligence Protocols

NEXUS uses **GitNexus** and **CodeGraph** for codebase navigation and automated blast radius impact analysis.

### 1. Mandatory GitNexus Impact Analysis (Before Editing)

Before modifying any existing function, class, or method, you **MUST** run impact analysis to evaluate affected upstream processes:

```bash
# Run GitNexus impact analysis on a target symbol
npx gitnexus impact <SymbolName>
```

> [!WARNING]
> If impact analysis returns a **HIGH** or **CRITICAL** risk score, you must report the blast radius (affected callers, execution flows, and modules) before proceeding with code modifications.

### 2. Mandatory `detect_changes()` Verification (Before Committing)

Before finalizing any commit, verify that your modifications only affect expected symbols and execution flows:

```bash
# Check modified symbol scope
npx gitnexus detect-changes
```

### 3. CodeGraph Exploration

For fast architectural lookups across symbols and call paths:
- **MCP Tool**: `codegraph_explore`
- **CLI Command**: `codegraph explore "<concept or symbol>"`

---

## Running Verification & Tests

### Backend Unit & Integration Tests (Python)

All backend tests must pass with 100% clean execution under standard and CI environment configurations.

```bash
# Activate virtual environment
source .venv/bin/activate  # or .\.venv\Scripts\Activate.ps1 on Windows

# Run complete test suite
pytest tests/ --tb=short

# Run tests under GitHub Actions environment settings
$env:DATABASE_URL="sqlite+aiosqlite:///./test.db"
$env:AUTH_ENABLED="false"
pytest tests/ -x --tb=short -q
```

Current test suite baseline: **3,109 passed tests**.

### Frontend Typecheck & Build (TypeScript / React)

```bash
cd dashboard

# 1. Typecheck TypeScript codebase
npx tsc --noEmit

# 2. Verify Vite production build
npx vite build
```

### End-to-End Tests (Playwright)

```bash
# Run Playwright end-to-end browser tests
npx playwright test
```

---

## Submitting Pull Requests

1. **Branch Naming**: Use descriptive branch names (`feat/hermes-agent-integration`, `fix/sse-stream-timeout`, `docs/architecture-update`).
2. **Clean Commit Messages**: Follow Conventional Commits (`feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`).
3. **Verification Output**: Include test execution results and `npx gitnexus detect-changes` summary in your PR description.
