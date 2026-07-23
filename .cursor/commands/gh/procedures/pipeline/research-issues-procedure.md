# Research issues (review triage)

Procedure for researching code-review findings, classifying each against plan/spec scope, and writing a durable markdown triage document.

## Overview

Turn a **flat list of review findings** into a **researched, scoped triage document** so humans and agents can decide what to fix now vs defer vs dismiss.

This command does **not** replace `/review`; it follows review when findings need evidence, scope judgment, and a persistent record.

## When to use

- After `/review` or parallel subagent review (`consider-reviewing`)
- User says “research these issues,” “triage review findings,” “which are real vs hypothetical,” “write adversarial review doc”
- Before implementing fixes on a large review — avoid fixing hypothetical or out-of-scope items

## Inputs (required)

| Input | Source |
|-------|--------|
| **Findings list** | User paste, prior assistant `## Issues`, PR comments, or review markdown |
| **Scope anchors** | Implementation plan, spec, OpenAPI, parent phase plan — paths user `@`-mentions or you locate from PR context |
| **Code under review** | Files referenced in findings; read implementations and tests |
| **Output path** | User-provided, or default: alongside scope plan as `adversarial-review-<short-topic>.md` |

Optional: branch name, commit range, verification commands already run.

## Disposition labels (default)

Use these unless the user defines phase-specific labels (e.g. `LEGITIMATE_P2`):

| Label | Meaning |
|-------|---------|
| **LEGITIMATE_NOW** | Real bug/gap in current code or current PR/plan contract — fix in this slice |
| **LEGITIMATE_DEFER** | Real issue; full fix belongs in a **named later phase/PR** (state which) |
| **HYPOTHETICAL** | Theoretical, mis-scoped, or blocked on a future scenario not in current tree |
| **INVALID** | Wrong fact, intentional stub per plan, or positive addition — no code change |

If the project uses phased plans (P2, P4, …), map **LEGITIMATE_NOW** / **LEGITIMATE_DEFER** to those phase names in the summary table.

## Workflow

### Step 1 — Inventory findings

1. Normalize each finding to: **ID** (RR-01 or reuse review id), **severity**, **path:line**, **one-line summary**.
2. Dedupe only when same file, same line/range, and same root cause.
3. If the list is empty, stop and ask the user for findings or run `/review` first.

### Step 2 — Load scope anchors

Read the scope documents **before** judging findings:

- What the **current PR/phase** explicitly delivers
- What is **explicitly out of scope** (later PR, staging-only, product confirmation)
- Normative contracts: OpenAPI, discovery docs, SPEC sections cited in the plan

Extract a short **“Scope reminder”** bullet list for the output doc header.

### Step 3 — Assign surface-area groups (SA1…SA6)

Load [triage-surface-area-groups.md](triage-surface-area-groups.md) end-to-end. Assign groups after Step 1 inventory and Step 2 scope load, **before** researching findings.

### Step 4 — Research via parallel subagents (evidence-first)

Follow [triage-surface-area-groups.md](triage-surface-area-groups.md) §Parallel subagents. Use **LEGITIMATE_*** dispositions from the table above (not gh-review CONFIRM/TRACK/DISMISS).

**Subagent prompt:** [triage-subagent-prompt.research-issues.txt.template](../../../_templates/gh-review/triage-subagent-prompt.research-issues.txt.template) — fill `{{SCOPE_ANCHORS}}`, `{{SA_LABEL}}`, `{{SA_SURFACE}}`, `{{FINDINGS_LIST}}`.

**Parent responsibilities after subagents return:**

1. Spot-check any **LEGITIMATE_NOW** or disputed disposition against code.
2. Resolve conflicts when two SAs touched the same root cause — one ID, one disposition.
3. Ensure every input finding appears exactly once in the merged set.

For **every** finding: classify disposition using the **Disposition labels** table above; **recommend action**: fix now | fix in named phase | document/runbook | close.

### Step 5 — Write the markdown file

Create or overwrite the user-requested path. Base structure on [gh-review-triage.md.template](../../../../../docs/paperwork/gh-review-triage.md.template) with these substitutions:

- Title: `# Adversarial review research — [title]`
- **Summary table** columns: ID | Finding | Disposition | Fix when | **Owner**
- Finding subsections: use [finding-section.md.template](../../../_templates/gh-review/finding-section.md.template) but replace **Why CONFIRM / TRACK / DISMISS** with **Why legitimate vs hypothetical**
- **Disposition legend:** LEGITIMATE_NOW / LEGITIMATE_DEFER / HYPOTHETICAL / INVALID table from Step 1 labels (not gh-review disposition-legend.md)

**Writing rules:**

- Every finding gets a **full** subsection — no “see above” only.
- Prefer **LEGITIMATE_NOW** only when the bug exists **today** without assuming unbuilt features.
- Mark **HYPOTHETICAL** when exploit requires P4 routes, production deploy, or unstated caller behavior.
- Mark **INVALID** when plan explicitly allows the behavior (stubs, deferred product mapping).
- Call out **test gaps** separately from **production bugs** (test finding can be LEGITIMATE_NOW without implying prod is broken).

### Step 6 — Reply to the user

Short summary:

- Output file path (markdown link)
- Counts by disposition and by **Owner** (SA1…SA6)
- **Recommended merge blockers** (LEGITIMATE_NOW only)
- Which subagent groups ran (SA → finding count)
- Offer to implement fixes via `/gh-resolve-issues` only if asked

Do **not** claim findings are fixed in this command.

## Quality bar

- [ ] Findings grouped into ≤6 surface-area SAs; parallel Task used when ≥3 findings
- [ ] **Subagent ownership** table + **Owner** column on every summary row
- [ ] Every input finding appears in summary table + full section (or explained merge/drop)
- [ ] Each disposition cites code or verified fact, not vibe
- [ ] Out-of-scope work labeled with **named** later phase, not “later”
- [ ] Summary table enables scanning; full sections enable implementation
- [ ] No fix commits unless user requested fixes in the same turn

## Anti-patterns

See [triage-surface-area-groups.md](triage-surface-area-groups.md) §Anti-patterns, plus:

- Treating all security findings as **LEGITIMATE_NOW** when no caller passes untrusted input yet
- Deferring real P2 plan violations to “P4” without citing plan line
- Skipping verification of reviewer claims (e.g. wrong library defaults)
- Writing triage only in chat with no markdown file
- Implementing fixes during triage without user request

## See also

- [`review.md`](../lib/review.md) — generate findings
- [`code-review-and-quality.md`](../lib/code-review-and-quality.md) — review axes
- [`consider-reviewing.md`](../lib/consider-reviewing.md) — parallel review subagents
- [`gh-review-triage-rules.md`](./gh-review-triage-rules.md) — disposition mapping when syncing to GitHub via `/gh-review`
