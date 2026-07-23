# Minimal change & pattern preservation

Apply when scoping `/gh-plan` tasks (not when authoring `plan.md` files).

## Rules

- Describe the **smallest change** that satisfies the acceptance criteria — not a cleaner rewrite.
- Before proposing tasks, inspect how similar behavior is implemented nearby (same module, layer, or feature family).
- **Name the pattern to follow** in each task draft (handler style, error shape, state hook, repository call site).
- Treat existing patterns as the default implementation approach.
- **Collapse ambiguity in the plan** — the planner chooses; the build worker only executes. Never leave "either A or B", "consider …", or open design questions in task `description` / `files` / `decisions`. Record the chosen approach under `decisions[]` (and mirror it in `files[].change` when relevant). Rejected alternatives go under **Out of scope**, not into the worker's task body.

## Include only when required

- New files, types, or abstractions
- Cross-cutting refactors or pattern migrations
- Renames, import churn, or formatting sweeps
- “Consistency” fixes in files the task does not need to touch

## Defer unless the user explicitly requested refactor

- Replacing an established pattern with a different one
- Extracting shared utilities because two call sites look similar
- Updating unrelated code to match a new style

If a different pattern would be objectively better but was **not** requested, note it under **Out of scope** in the subagent output — do not schedule it in proposed tasks.

## Task draft fields

Every proposed task should list:

| Field | Requirement |
| --- | --- |
| **decisions** | Locked choices the worker must not reopen (approach, API shape, library, error handling). Empty only when AC already leaves zero degrees of freedom. |
| **patterns** | Files/modules to mirror |
| **files** | ~5 primary source files (+ explicit test files); each `change` states the *chosen* edit, not options |
| **tests** | Task-narrow `verify` — cheap, specific commands beat full-suite |

Vague Scope is the main cost dial for `/gh-build`: ambiguous tasks force Composer to re-decide design and burn tokens. Explicit `decisions` + `files[].change` keep worker spend low.
