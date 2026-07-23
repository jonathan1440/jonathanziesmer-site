# Write AGENTS.md Contract — Procedure

Operational contract for `/write-agents-contract`. Load with [write-agents-contract.md](write-agents-contract.md).

## What this produces

An **agent contract** (`AGENTS.md`), not a project summary. A contract describes decisions and boundaries the code must respect — including code that does not exist yet.

Co-locate with the code it governs:

- `<target-dir>/AGENTS.md` — the contract
- `<target-dir>/CLAUDE.md` — `@AGENTS.md` pointer so Claude Code loads the sibling contract

Root for project-wide; subdirectories for local architectural contracts. Every `AGENTS.md` written or split out gets an adjacent `CLAUDE.md`.

## The replacement test (mandatory filter)

For every proposed line in **Principles** and **Architectural contract**, ask:

> If I replaced every file in this directory with a different implementation that still respected this principle, would the principle still read true?

- **Yes** → principle (keep)
- **No** → summary (reject or rewrite as a decision, not a shape description)

Flag rejected lines explicitly in the proposal. Do not write summaries into the contract.

## Six contract criteria (quality filter)

Before presenting a draft, score each criterion as **present**, **partial**, or **missing**:

1. **Predicts evolution** — roadmap-aware guidance, not a snapshot
2. **Validation explicit** — how to validate; what cannot be validated
3. **Stable** — should change ~10% of the time per feature, not every PR
4. **Risk boundaries** — easy vs hard/risky changes named
5. **Forward-testable** — user can throwaway-implement next roadmap items with minimal steering
6. **Invisible context cached** — product/audience "why" the agent cannot infer from code

Missing criteria drive the question batch in Step 4.

---

## Step 1: Resolve scope

Collect if not provided:

| Input | Default |
|-------|---------|
| **Target directory** | Current workspace root, or user-supplied path |
| **Mode** | `scan` (full directory) or `diff` (git diff on directory) |
| **Diff ref** | `HEAD` unstaged+staged, or user-supplied (`main...HEAD`, commit range, PR) |
| **Existing contract** | Read `<target-dir>/AGENTS.md` and `<target-dir>/CLAUDE.md` if present |

Confirm the target directory exists and is inside a git repo when using diff mode.

### Diff mode commands

```bash
# Uncommitted changes under target dir
git diff -- "<target-dir>"
git diff --cached -- "<target-dir>"

# Branch comparison
git diff main...HEAD -- "<target-dir>"

# Named commit range
git diff abc123..def456 -- "<target-dir>"
```

Classify diff hunks: new files, deleted files, moved files, boundary-crossing edits.

### Pitfall mode (agent-friendly)

Use when an agent (or human) discovered a **durable surprise** mid-build/review — something the next agent trajectory would miss if absent from `AGENTS.md`.

**Inputs:**

| Input | Required |
| --- | --- |
| Candidate bullet(s) | Yes — one sentence each; what to do / not do |
| Evidence | Optional — file path, issue URL, or short "how we learned this" |
| Target directory | Default: workspace root (or nearest existing `AGENTS.md`) |

**Procedure (skip full Steps 2–4 interview):**

1. Read existing `AGENTS.md` at the target (and parent contracts if nested).
2. Deduplicate — if an equivalent line already exists, report **no change** and stop.
3. Run the **replacement test** on each candidate. Reject session-only tips, file inventories, and one-off debug notes.
4. Map survivors to the best section:
   - **Context the code does not carry** — default for gotchas / invisible pitfalls
   - **Principles** / **Architectural contract** — only if the line is a true invariant
   - **Change categories** — only if it changes what needs a design conversation
5. Present a **proposed diff** (before/after or exact bullets to add). Tag confidence (`inferred` from this incident).
6. **Stop.** Do not write until the user approves. If the user is offline (auto-workflow), file/update a Task issue titled `AGENTS.md pitfall proposal` with the proposed bullets and a pointer to `/write-agents-contract --pitfall` — never open a PR that edits `AGENTS.md`.

**Agent trigger examples:** OIDC/deploy footgun, CDK param injection rule, harness script that must not be bypassed, review finding that is really a contract gap.

**Anti-triggers (do not propose):** one-task implementation detail, temporary workaround, anything that fails the replacement test, anything that would push the file over 200 lines without a cut/split plan.

---

## Step 2: Gather evidence

Run analysis appropriate to mode. Prefer commands over hand-maintained lists.

### Structure (always)

```bash
# High-level layout — adapt flags to project
ls "<target-dir>"
find "<target-dir>" -maxdepth 3 -type d | head -50
```

Read (when present): package manifest, Makefile, CI config, test config, README, existing AGENTS.md, parent AGENTS.md.

### Code signals to extract

| Signal | Look for |
|--------|----------|
| **Boundaries** | Public exports, API routes, middleware, interfaces, package boundaries |
| **Invariants** | Auth checks, validation layers, error handling contracts, idempotency |
| **Validation** | Test commands, lint, typecheck, CI jobs, coverage thresholds |
| **Naming/layout** | Folder semantics, file suffix conventions, co-location patterns |
| **Risk zones** | Migrations, auth, payments, PII, distributed state, external integrations |

### Diff mode extras

- Which architectural boundaries did the diff cross?
- Is this a routine change category or a boundary-crossing change?
- Does existing AGENTS.md need updating, or is the diff implementation-only?

Do **not** enumerate individual source files in the contract. Extract patterns and boundaries only.

### Sufficiency gate (required before drafting)

Decide whether there is enough signal to propose contract content. Check:

| Signal | Thin (stop) | Enough (continue) |
|--------|-------------|---------------------|
| Source files | Scaffold, boilerplate, or &lt; ~3 meaningful modules | Recurring patterns, boundaries, or conventions visible |
| Git history | No commits or only init/scaffold under target dir | Commits show stable conventions, boundaries, or repeated workflows |
| Diff (diff mode) | Trivial rename/format-only | Boundary-crossing or convention-establishing change |

**If thin:** report clearly — e.g. "Not enough code or history here to infer a contract. Writing AGENTS.md now would be guesswork." Do **not** invent principles, boundaries, or change categories to fill the template.

Then:

1. Ask whether the user has decisions, boundaries, roadmap, or context they want captured
2. If they say no → **do not create or update** `AGENTS.md`; suggest revisiting after more code lands
3. If they offer content → treat as user-supplied proposals (see **User-supplied content** below)

Partial contracts are OK when evidence supports only one or two sections — but never pad empty sections.

---

## Step 3: Draft proposals with confidence tags

Produce a **proposal document** (chat output, not the file yet). Tag every item:

| Tag | Meaning |
|-----|---------|
| **inferred** | Strong evidence from code/CI/tests |
| **hypothesis** | Plausible from patterns; needs user confirmation |
| **must-ask** | Cannot infer; requires human context |

Organize proposals under the four contract sections:

### 1. Principles

Decisions about what this area is and is not, trade-offs accepted, optimization targets. Apply replacement test to each line.

### 2. Where things live

High-level layout and naming conventions. **Command pointers only** — never a hand-maintained file list:

```markdown
## Where things live

Run `tree -L 2 <target-dir>` for current layout.

- `src/handlers/` — HTTP entry points (suffix: `*Handler.ts`)
- `src/domain/` — business logic; no I/O imports
- Shared test helpers: `src/test/fixtures/`
```

### 3. Architectural contract

Invariants and boundaries, named by **actual symbols, interfaces, or middleware**:

```markdown
## Architectural contract

- Changes crossing `domain/` → `infra/` boundary are architectural — discuss first
- `UserRepository` interface is the persistence contract; implementations are swappable
- All HTTP handlers must pass through `authMiddleware` before business logic
```

Not: "Respect separation of concerns."

### 4. Change categories

| Shippable after normal review | Needs conversation first |
|-------------------------------|--------------------------|
| New handler following existing pattern | New external dependency or service |
| Bug fix within one module | Schema migration affecting prod data |
| Test coverage for existing behavior | Auth model or permission model change |

Tailor rows to what the evidence and diff actually show.

Also draft:

- **Validation** — commands to run; known gaps ("no e2e for checkout flow")
- **Invisible context** — placeholders for product/roadmap items marked `must-ask`

Run replacement test on all Principles and Architectural contract lines. List failures under **Rejected (summary, not principle)**.

If the sufficiency gate stopped drafting, skip to Step 4 with only user-supplied items (if any).

---

## Step 4: Interactive review (required)

**Do not write `AGENTS.md` until the user confirms.** Present the proposal, then ask targeted questions.

Use AskQuestion when available; otherwise ask conversationally. Batch questions by gap type:

### Roadmap and evolution (criterion 1, 5)

- What are the next 1–3 features or refactors planned for this area?
- Anything explicitly **not** changing soon that the contract should freeze guidance around?

### Invisible context (criterion 6)

- Who is the user/audience for this code?
- Why is it shaped this way (historical decisions, org constraints)?
- What would a new engineer get wrong without being told?

### Risk boundaries (criterion 4)

- Which changes have burned you before?
- What requires design review vs normal PR review?

### Validation limits (criterion 2)

- What do you trust the test suite to catch?
- What requires manual/staging verification?

### Diff-specific (when in diff mode)

- Does this diff reflect a new boundary or a routine extension?
- Should the contract change, or only implementation?

After answers: merge into proposal, re-run replacement test, re-score the six criteria.

### User-supplied content

When the user adds or insists on lines:

1. Run **replacement test** and six-criteria filter on each item
2. If it fails or is weak, **challenge directly** — name why (summary not principle, implementation detail, will go stale, duplicates parent contract, etc.)
3. Propose a rewrite when possible
4. If user **insists** after pushback → include as requested (note in chat that you disagreed; no need to annotate the file)

Do not agree performatively. Do not silently drop user content without explaining why.

---

## Step 5: Write or update AGENTS.md

Only after explicit user approval ("write it", "looks good", "approve").

### Line budget (hard cap: 200 lines)

Count lines in the final draft (including blank lines and headings). **Maximum 200 lines.**

If over 200, apply in order — stop when under cap:

1. **Split** — move scoped sections to `<subdir>/AGENTS.md` where subdirectories have distinct boundaries. Parent file references children; child files hold local principles/contract only. **Create `<subdir>/CLAUDE.md`** (`@AGENTS.md`) for each new child contract. Re-count each file.
2. **Condense** — shorten prose while keeping human readability. Apply [caveman.md](../core/caveman.md) **lite** or **full** rules to bullet text: drop filler, use fragments, parallel bullets — not unreadable compression. Re-read aloud: if a human would struggle, condensing failed.
3. **Cut** — remove lowest-value lines (weakest principles, redundant validation, duplicated parent context). Prefer cutting over mangling readability.

Never exceed 200 lines in a single `AGENTS.md`. If split + cut still cannot fit, the scope is too broad — split further or ask the user which sections to drop.

### Output template

```markdown
# Agent Contract — [Area Name]

<!-- Contract for: <relative-path-from-repo-root> -->
<!-- Last reviewed: YYYY-MM-DD -->

## Principles

- [Decision that survives reimplementation]
- [...]

## Where things live

Run `tree -L 2 <target-dir>` (or project-specific command) for ground truth.

- [Kind of thing] → [location pattern / naming convention]
- [...]

## Architectural contract

- [Named boundary or invariant]
- [...]

## Change categories

### Shippable after normal PR review

- [...]

### Needs a design conversation first

- [...]

## Validation

**Run after changes:**

\`\`\`bash
[commands inferred from project]
\`\`\`

**Cannot be fully validated automatically:**

- [...]

## Context the code does not carry

- [Product, audience, historical why — only what user confirmed]
```

### Update rules (existing AGENTS.md)

- Preserve stable sections; edit only what the review changed
- Remove lines that fail replacement test (summaries disguised as principles)
- Do not add file inventories or implementation snapshots
- If diff mode and change is implementation-only: **leave AGENTS.md unchanged** and say so
- After edits, re-check line count; apply split/condense/cut if over 200 lines

### CLAUDE.md (required companion)

For **every** `AGENTS.md` created or updated in Step 5, write or refresh the sibling **`CLAUDE.md`** in the same directory.

**Content — exactly one line, no extra prose:**

```markdown
@AGENTS.md
```

Rules:

- Same directory as the `AGENTS.md` it points at (`src/api/CLAUDE.md` → `src/api/AGENTS.md`)
- Overwrite existing `CLAUDE.md` only if content is wrong or missing the pointer; do not add other instructions to this file
- When split creates multiple contracts, each subdirectory gets its own pair (`AGENTS.md` + `CLAUDE.md`)
- When Step 5 does not write `AGENTS.md` (thin directory, user declined, diff-only no change), **do not** create or update `CLAUDE.md`
- When updating an existing `AGENTS.md`, ensure sibling `CLAUDE.md` exists with `@AGENTS.md`; create if missing

---

## Step 6: Forward-test prompt (optional close)

After writing, offer:

> Pick the next roadmap item. I can attempt a throwaway implementation using only this contract — no other steering — to see where the contract breaks.

This is the contract's own test harness.

---

## Anti-patterns (reject on sight)

| Anti-pattern | Why |
|--------------|-----|
| File inventory ("`foo.ts` does X") | Stale on first commit |
| Framework tutorial | Agent already knows React/Django/etc. |
| Restating obvious code shape | Summary, not contract |
| Editing every PR | Tracking implementation, not decisions |
| Vague boundaries ("keep layers separate") | Not actionable |
| Invented content on thin dirs | Guesswork, not contract |
| AGENTS.md &gt; 200 lines | Too much to load; split or cut |

## Related commands

- [caveman.md](../core/caveman.md) — terse prose when condensing contracts (`lite` or `full`)
