# Acceptance criteria format (Given / When / Then)

Normative rules for `/gh-spec`. Subagent output shape: [_templates/spec/ac-subagent-output.md](../../_templates/spec/ac-subagent-output.md).

## Rules

- **Given** sets state only — no actions.
- **When** is a single user or system trigger.
- **Then** is observable and testable — no vague "works correctly."
- Include error, empty, and permission paths where the story implies them.
- Use stable IDs (`AC-01`, `AC-02`, …) across the feature for traceability into plans, tasks, and PRs.
- Number scenarios in a **flat list** under each story (no P1/P2 priority labels).

## User-facing layout (SPEC / docs/acceptance-criteria.md)

```markdown
### US-01: [Short title]
As a [role], I want [goal], so that [benefit].

**Acceptance scenarios:**

1. **AC-01** — Happy path
   - **Given** [initial context / preconditions]
   - **When** [action or trigger]
   - **Then** [observable outcome]

2. **AC-02** — [Scenario name, e.g. validation failure]
   - **Given** …
   - **When** …
   - **Then** …
```

Parent assigns **global sequential** `AC-*` IDs after subagents return (see merge script in `spec-story-ac-procedure.md`).
