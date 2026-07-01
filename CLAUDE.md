# Project Steering — AI-DLC Workflow

This workspace develops, maintains, and operates software using the **AI-DLC**
(AI-Driven Development Life Cycle) workflow defined in [aidlc-rules/](aidlc-rules/).
That workflow is authoritative and **overrides default development behavior**.

## When this applies (trigger)

When the user makes a **software development request** — building a new feature or
app, modifying or refactoring existing code, fixing a non-trivial bug, planning
architecture, or reverse-engineering an existing codebase — you MUST follow the
AI-DLC workflow.

**Before starting the work**, read [aidlc-rules/core-workflow.md](aidlc-rules/core-workflow.md)
and follow it. Load rule-detail files from `aidlc-rules/rule-details/` on demand, exactly
as the workflow directs (paths like `common/process-overview.md` are relative to
`aidlc-rules/rule-details/`).

**Do NOT trigger the full workflow** for quick questions, explanations, read-only
lookups, or trivial single-line edits — answer those directly. When a request is
borderline, start lightweight (Workspace Detection + adaptive Requirements Analysis)
rather than full ceremony, and let the plan show what will actually run.

## Non-negotiables (from core-workflow.md — never skip)

- **Approval gates** — never advance past a stage without the user's explicit
  approval. Present the stage's completion message and wait.
- **Questions go in files, not chat** — put clarifying / multiple-choice questions
  in a `.md` file under `aidlc-docs/...` using `[Answer]:` tags (A/B/C/D/E). Do not
  ask multiple-choice questions inline.
- **Audit everything** — append every user input and your actions to
  `aidlc-docs/audit.md`; never overwrite that file.
- **Adaptive** — run only stages that add value; show the plan and let the user
  override inclusions/exclusions.
- **Validate content** — check Mermaid / ASCII / diagram syntax before writing files.
- **No emergent behavior in Construction** — use the standardized 2-option completion
  messages defined in each construction stage's rule file.

## Where things live

- **Workflow rules** (read-only, do not edit during a task): `aidlc-rules/`
- **Generated docs, state, audit log**: `aidlc-docs/` (in the project root — never put
  application code here)
- **Application code**: project root, per `rule-details/construction/code-generation.md`
- **Resume** — on any dev request, first check for `aidlc-docs/aidlc-state.md`; if it
  exists, resume per `rule-details/common/session-continuity.md` (load prior artifacts,
  show the "Welcome back" status, continue from the next step).

## Extensions (opt-in)

During Requirements Analysis, offer the opt-in extensions found under
`aidlc-rules/rule-details/extensions/` (Resiliency Baseline, Security Baseline,
Property-Based Testing). Load an extension's full rules only after the user opts in.

## Test Delegation (subagent workflow)

When an implementation slice is functionally complete and it's time to add/update
tests, delegate instead of doing it inline:

- **Writing tests** → spawn a **`fork`** subagent (inherits this session's context
  so it knows what was built) and have it follow `.claude/agents/e2e-test-writer.md`.
- **Running e2e/browser (Playwright) tests** → spawn the clean-context
  **`e2e-test-runner`** subagent (no fork); it runs the suite objectively and
  returns a compact result so large reports never bloat this context.

Full protocol: @.claude/rules/test-delegation-workflow.md
This block + the two `.claude/agents/*` files are a portable template — copy them
into other projects to reuse the workflow.
