---
name: gh-review
description: >-
  GitHub-issue-scoped code review with mandatory parallel subagent review,
  CONFIRM/TRACK/DISMISS triage, Bug sub-issue sync under the reviewed issue,
  Task sub-issue sync under the reviewed issue, stale close on re-review,
  and idempotent parent-comment upsert. Use when given a GitHub issue URL or number
  for story/task quality review with traceable bug and follow-up tracking.
---

# gh-review

Review code in the context of a **GitHub issue**, triage findings, and sync **Bug** and **Task** sub-issues under the **reviewed issue** (the input you were given).

## Load (in order)

1. [gh-review-procedure.md](procedures/pipeline/gh-review-procedure.md) — orchestration (Phases 0–5)
2. [gh-review-github-procedure.md](procedures/pipeline/gh-review-github-procedure.md) — payload schema, publish contract, idempotency
3. [gh-review-review-synthesis.md](procedures/pipeline/gh-review-review-synthesis.md) — parallel subagents + five-axis synthesis
4. [gh-review-triage-rules.md](procedures/pipeline/gh-review-triage-rules.md) — CONFIRM / TRACK / DISMISS + test findings
5. [gh-review-rr-ids.md](procedures/pipeline/gh-review-rr-ids.md) — RR-ID assignment and re-run rules
6. [gh-review.example.payload.json](examples/gh-review.example.payload.json) — sync-bugs payload shape

**On demand:** [gh-review-triage-doc.md](procedures/pipeline/gh-review-triage-doc.md) (Phase 3 write), [triage-surface-area-groups.md](procedures/pipeline/triage-surface-area-groups.md) (when ≥3 findings).

**Templates:** `.cursor/commands/_templates/gh-review/` — triage doc, finding sections, subagent prompts, [payload schema](../_templates/gh-review/gh-review.payload.schema.json).

## Mandatory execution (parent)

**You MUST run the gh-review scripts yourself** via Shell. Do **not** hand commands to the user. Script sequence: [gh-review-procedure.md](procedures/pipeline/gh-review-procedure.md) Phases 0 and 4.

On `sync-bugs` failure: diagnose, fix payload, retry. Do not skip publish.

## When to use

- Story or task issue needs pre-merge / pre-PR quality review with tracked bugs and follow-ups
- User provides a GitHub issue URL or `owner/repo#N`
- Re-review after fixes — see [gh-review-rr-ids.md](procedures/pipeline/gh-review-rr-ids.md)

## Inputs

| Input | Required | Example |
|-------|----------|---------|
| Issue | Yes | `https://github.com/org/repo/issues/20` or `org/repo#20` |
| Triage output path | No | Default: [gh-review-triage-doc.md](procedures/pipeline/gh-review-triage-doc.md) |

## When **not** to use

| Situation | Use instead |
|-----------|-------------|
| Local uncommitted changes | `/review` |
| PR merge gate only | `/review` |
| Findings list, no GitHub issue | `/research-issues` |
| Implement or fix Bug sub-issues on a development branch | `/gh-resolve-issues` |

## Harness re-run and sign-off (outline §4.4.a.6–7)

Every review re-runs the testing harness scoped to its level — task: tiers 1–4; story/spec: tiers 1–6 with the `product-judge` subagent driving tier 6 — and requires `contract-reviewer` sign-off against story/spec AC and `AGENTS.md`. Tier failures and sign-off rejections become findings like any other. See [gh-review-procedure.md Phases 2b–2c](procedures/pipeline/gh-review-procedure.md#phase-2b--harness-re-run-scoped-tiers).

## Review iteration cycles (outline §4.c)

Run the appropriate number of `/gh-review` + `/gh-resolve-issues` cycles before treating the PR as ready for human review:

| PR level | Cycles | Rationale |
|----------|--------|-----------|
| **Task** (task → story) | **1** | Lower integration risk; single developer scope |
| **Story** (story → spec) | **2** | Cycle 2 catches regressions introduced by cycle-1 fixes |
| **Spec** (spec → main) | **2** | Same as story — higher integration risk |

After the final cycle, only **Blocker** or **Critical** findings block merge (see [gh-review-triage-rules.md §Severity](procedures/pipeline/gh-review-triage-rules.md#severity)). New findings discovered after cycles are complete route to `/gh-update-plan` or escalate — do **not** restart review.

After `/gh-resolve-issues` completes, the PR goes to human review. See [README §Manual review and merge](README.md#manual-review-and-merge) for the human protocol and merge strategy. For spec-level PRs, see [README §Post-merge and release](README.md#post-merge-and-release) before closing the spec issue.

## See also

- [research-issues-procedure.md](procedures/pipeline/research-issues-procedure.md) — flat-list triage without GitHub sync (different dispositions)

> **Vocabulary:** triage here uses `CONFIRM / TRACK / DISMISS` — not the `LEGITIMATE_NOW / LEGITIMATE_DEFER / HYPOTHETICAL / INVALID` labels from `/research-issues`. See [gh-review-triage-rules.md](procedures/pipeline/gh-review-triage-rules.md) for the mapping between the two.
