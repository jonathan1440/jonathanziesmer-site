---
name: plan
description: Restate requirements, identify risks, produce a phased implementation plan, and WAIT for user confirmation before writing any code. Use when starting a new feature, doing significant architectural changes, or when requirements feel unclear.
---

# Plan

Invoke the **planner** persona (or run the equivalent prompt) to produce a comprehensive implementation plan **before** writing any code. The planner does not touch the working tree until the plan is approved.

## What the Planner Does

1. **Restate requirements** — clarify what is being built in concrete terms.
2. **Identify risks** — surface blockers, unknowns, and integration concerns.
3. **Phase the work** — break the implementation into ordered phases with explicit outputs.
4. **Map dependencies** — what must be built before what.
5. **Estimate complexity** — High / Medium / Low, with rough hours.
6. **Constrain scope to the smallest viable change** — each phase must extend existing patterns in the touched area; do not plan drive-by refactors, renames, or “while we’re here” modernization unless the user explicitly asked for them.
7. **Wait for confirmation** — present the plan and stop. Do not write code until the user replies with `yes`, `proceed`, or a modification request.

## When to Use

- Starting a new feature
- Architectural changes
- Complex refactoring touching multiple files or components
- Ambiguous or evolving requirements

For GitHub-native specs and tasks, use [/gh-spec](../../gh-spec.md) then [/gh-plan](../../gh-plan.md). This `plan.md` is the **local** planner path (no GitHub issue sync).

## Minimal Change & Pattern Preservation

The plan must describe the **smallest change** that satisfies the requirement — not a cleaner rewrite.

Before phasing work, inspect how similar behavior is already implemented nearby (same module, layer, or feature family). The plan should **name the pattern to follow** (e.g. existing handler style, error shape, state hook, repository call site) and treat that as the default implementation approach.

**Include in the plan only when required for the task:**
- New files, types, or abstractions
- Cross-cutting refactors or pattern migrations
- Renames, import churn, or formatting sweeps
- “Consistency” fixes in files the task does not need to touch

**Defer to a separate phase (or separate task) unless the user explicitly requested refactor/modernization:**
- Replacing an established pattern with a different one (callbacks → async/await, class → hooks, raw SQL → ORM wrapper, inline → new helper layer)
- Extracting shared utilities because two call sites look similar
- Updating unrelated code to match a new style

If a different pattern would be objectively better but was **not** requested, note it under **Out of scope / follow-ups** — do not schedule it in the implementation phases.

## Output Shape

```markdown
# Implementation Plan: <feature>

## Requirements Restatement
<concrete, testable statements>

## Phases
### Phase 1: <name>
- <step>
- <step>

### Phase 2: <name>
...

## Dependencies
<external services, libraries, prereqs>

## Risks
- <Severity>: <risk>
- ...

## Existing Patterns to Follow
- <file or module>: <pattern to mirror for this change>

## Out of Scope (unless user asked)
- <drive-by refactor, pattern migration, or cleanup deferred>

## Estimated Complexity
<High | Medium | Low> — <rough hours>

WAITING FOR CONFIRMATION
```

## Modifying the Plan

Reply with one of:

- `yes` / `proceed` — execute the plan (use `/tdd` or `/prp-implement`)
- `modify: <changes>` — adjust the plan
- `different approach: <alternative>` — re-plan from a different angle
- `skip phase N` / `do phase N first` — reorder

## Critical Rules

- The planner MUST NOT write production code until the user explicitly confirms.
- The plan goes to a file (e.g. `tasks/plan.md`, `.claude/plan/<feature>.md`) so it survives compaction.
- Reference the plan file in any subsequent implementation session.
- **Smallest necessary diff:** every planned step must justify why it is required for the stated requirement; if a step is optional polish or pattern alignment, move it to **Out of Scope** or a follow-up task.
- **Match before invent:** implementation phases must extend the codebase’s current patterns in the touched area. Do not plan a pattern change unless the user asked for a refactor or the task cannot be done without one.
