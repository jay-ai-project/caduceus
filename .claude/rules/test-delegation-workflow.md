# Test Delegation Workflow (subagent-based)

> **Portable template.** This file and the two agents in `.claude/agents/`
> (`e2e-test-writer.md`, `e2e-test-runner.md`) are written to be project-agnostic.
> To reuse in another project: copy the `.claude/agents/*` files and this file,
> then add one line to that project's `CLAUDE.md`:
> `@.claude/rules/test-delegation-workflow.md`

## Purpose

Keep the **main agent's context** focused on building the product, while
delegating test *authoring* and test *execution* to subagents. Two roles, chosen
deliberately for their **context** properties:

| Role | Who | Context | Why |
|---|---|---|---|
| **Write tests** | `e2e-test-writer` (conventions) via a **`fork`** subagent | **Inherits** the main session | It must know what was just built to write meaningful tests |
| **Run tests** | `e2e-test-runner` subagent | **Clean / empty** | Objective QA; and large browser reports never bloat the main context |

## When this triggers

After an implementation slice is **functionally complete** (the feature/change
works) and it is time to add or update tests. Do **not** trigger for trivial
one-line edits, pure refactors already covered by tests, or read-only work.

In an AI-DLC project this corresponds to the Construction → Build & Test stage,
right after code generation. It composes with, and does not replace, that flow.

## The workflow

### 1. Write tests → delegate to a `fork` (context-preserving)

When it's time to write/extend tests:

- Spawn a subagent with **`subagent_type: "fork"`**. A fork clones the current
  conversation, so the writer sees the full implementation you just did — no need
  to re-explain the design.
- In the fork's prompt, tell it to **read and follow the conventions in
  `.claude/agents/e2e-test-writer.md`**, and give it the scope (which
  feature/files to cover, unit vs. e2e).
- If the change needs **browser / end-to-end** coverage specifically, that same
  writer agent's conventions cover Playwright/e2e; keep it in one fork unless the
  e2e surface is large enough to warrant its own focused fork.
- The fork writes the test files, runs them once to confirm they pass, and
  returns a short summary (files added, count, pass/fail). You resume with your
  original context intact and only that summary added.

> Alternative (cold): if you need tests for code you did **not** just write in
> this session, invoke `e2e-test-writer` as a normal (non-fork) subagent — it will
> explore the code itself. Prefer `fork` right after implementing.

### 2. Run tests → delegate to a clean-context QA subagent

To execute the test suite (especially browser/e2e), spawn the
**`e2e-test-runner`** subagent (a fresh, empty context — do **not** fork):

- It runs the already-written tests, knows nothing about the implementation, and
  reports an **objective, compact** result.
- It distills large Playwright/browser output (HTML reports, traces, screenshots)
  down to: pass/fail counts, failing test names + one-line causes, environment
  issues, and artifact *paths* — never pasting the full report back.
- You receive only that summary, keeping the main context small even across many
  runs.

## Handoff protocol (what each subagent returns)

- **Writer (fork):** files created/modified, test count, and "N passed" (or the
  failure if it couldn't get them green). Keep prose minimal.
- **Runner (clean):** the compact result block defined in `e2e-test-runner.md`.
  If tests fail, it reports faithfully — it does **not** edit code to make them
  pass (that's the main agent's / writer's job on the next turn).

## Guardrails

- The **runner never modifies source or test code** — it only runs and reports.
- The **writer does not run the full production app or long browser suites** as
  its deliverable — it authors tests and confirms they pass; large-suite
  execution is the runner's job.
- Report outcomes honestly: a failing suite is surfaced, not hidden or "fixed"
  by weakening assertions.
