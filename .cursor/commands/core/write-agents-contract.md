---
name: write-agents-contract
description: >-
  Draft or update AGENTS.md agent contracts (scan/diff) or propose a single
  discovered pitfall for approval (pitfall mode). Interactive questions before
  writing; never invent on thin dirs; challenge weak additions; hard cap 200
  lines. Use when creating/updating AGENTS.md or CLAUDE.md, when an agent
  discovers a durable surprise/gotcha/pitfall the next agent would miss, after
  merge when architecture drifted, or when the user mentions agent contracts.
---

# Write AGENTS.md Contract

Create or update an **agent contract** for a directory — not a codebase summary.

Load and follow **[write-agents-contract-procedure.md](write-agents-contract-procedure.md)**.

## Usage

```bash
/write-agents-contract                         # scan workspace root
/write-agents-contract src/api                 # scan specific directory
/write-agents-contract --diff src/api          # diff mode on directory
/write-agents-contract --diff main...HEAD      # branch diff on workspace root
/write-agents-contract --pitfall "…"           # propose one durable surprise (agents use this)
```

## Modes

| Mode | When | Write gate |
| --- | --- | --- |
| **scan** / **diff** | Authoring or revising a contract | Full interactive Steps 1–4; Step 5 only on approval |
| **pitfall** | Agent (or human) found a durable surprise mid-work | Lightweight propose → still **no write without approval** |

Pitfall mode is the auto-friendly path. Agents **must not** edit `AGENTS.md` themselves — they propose via this command and wait for the user.

## Default behavior: interactive (scan / diff)

1. **Analyze** — scan directory or git diff; read existing `AGENTS.md`
2. **Sufficiency gate** — if code/history too thin, say so; do not invent content
3. **Propose** — draft sections with confidence tags (`inferred` / `hypothesis` / `must-ask`)
4. **Filter** — run replacement test; reject summaries; challenge weak user additions (add if user insists)
5. **Ask** — targeted questions for gaps (roadmap, risk, invisible context, validation limits)
6. **Write** — only after explicit user approval; **hard cap 200 lines** per `AGENTS.md` (split, condense, or cut); create or refresh adjacent `CLAUDE.md` for each contract written

Never write or overwrite `AGENTS.md` without confirmation. Never pad a thin directory with invented principles. Do not create `CLAUDE.md` when no `AGENTS.md` is written.

## Start

Collect if not provided:

1. **Target directory** — path relative to repo root (default: workspace root)
2. **Mode** — `scan`, `diff`, or `pitfall`
3. **Diff ref** — when diff mode: unstaged, staged, `main...HEAD`, or user-supplied range
4. **Pitfall text** — when pitfall mode: one or more candidate bullets (+ optional evidence path)

Then execute procedure Steps 1–4 (or **Pitfall mode**). Stop at the proposal + questions. Step 5 only on approval.

## Contract vs summary (one-line test)

> If every file were reimplemented but still obeyed this line, would the line still be true?

Yes → principle. No → summary — do not put it in the contract.

## Output location

For each directory that gets a contract:

- `<target-dir>/AGENTS.md` — co-located with the code it governs
- `<target-dir>/CLAUDE.md` — single line `@AGENTS.md` (sibling pointer; same directory)

Reference child contracts from parent `AGENTS.md` when nesting via split.

## When diff mode says "no contract change"

If the diff is implementation-only and crosses no new boundaries, report that and **do not edit** `AGENTS.md`. Implementation churn is not contract churn.

## When there is not enough to write

If the directory has too little code or commit history to infer real principles and boundaries, **say so** and stop. Do not create or expand `AGENTS.md` with filler.

You may ask whether the user has decisions, boundaries, or context worth capturing. Anything they offer goes through the same replacement test and quality filter — **challenge** additions that look like summaries, implementation detail, or low-signal prose. If the user insists after pushback, add it anyway.

## Line budget: 200 lines max

`AGENTS.md` must stay **under 200 lines**. If a draft exceeds that: split into subdirectory contracts where possible, condense (see procedure — `/caveman lite` for terseness), or cut. Condense only while the file stays easily human-readable; otherwise cut instead of compressing into mush.
