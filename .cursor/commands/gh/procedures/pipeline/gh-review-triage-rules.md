---
name: gh-review-triage-rules
description: >-
  CONFIRM / TRACK / DISMISS triage semantics, test-finding rules, and
  dismiss_reason / track_reason enums for gh-review.
---

# gh-review triage rules

Evidence-first triage for every RR-ID. See [gh-review-triage-doc.md](gh-review-triage-doc.md) for markdown output shape.

## Dispositions

| Outcome | Meaning | GitHub sub-issue |
|---------|---------|------------------|
| **CONFIRM** | Defect, AC violation, or regression-hiding test gap | **Bug** under **reviewed issue** |
| **TRACK** | Spec drift, hygiene, duplication, contract gaps, **test hygiene** — real follow-up, not a bug | **Task** under the **reviewed issue** (the input issue — not its parent) |
| **DISMISS** | Not real or explicitly excluded | None; triage doc only |

Classify with GitHub **issue types** (org-configured). Do **not** use a `bug` label.

| Artifact | Issue type | Sub-issue parent |
|----------|------------|------------------|
| CONFIRM finding | **Bug** | Reviewed issue (`review_issue`) |
| TRACK finding | **Task** | Reviewed issue (`review_issue`) — same as input; never the input issue's parent |

Every `sync-bugs` payload **must** include:

```json
"issue_type": "Bug",
"followup_issue_type": "Task"
```

Copy optional `story_issue` from `context` output when you want user-story traceability in finding bodies — it is **not** the Task sub-issue parent. Org must define issue types **Bug** and **Task** — `preflight` documents the requirement.

## Mapping from research-issues dispositions

When adapting findings from `/research-issues`:

| research-issues | gh-review |
|-----------------|-----------|
| LEGITIMATE_NOW | **CONFIRM** |
| LEGITIMATE_DEFER | **TRACK** (name the phase in rationale or `track_reason`) |
| HYPOTHETICAL | **DISMISS** (`dismiss_reason: hypothetical`) |
| INVALID | **DISMISS** (`dismiss_reason: wrong-fact` or `intentional`) |

## Test findings (mandatory triage)

Test-related review findings are **valid** and must be triaged. **Never DISMISS** a test finding because it is "style", "nice-to-have", "not a merge blocker", or "does not hide production behavior".

When `test-review-agent` or reviewers flag test issues, include them in the triage doc and payload like any other finding.

| Finding | Disposition | Notes |
|---------|-------------|-------|
| Regression-hiding gap, wrong/missing test for in-scope AC or SPEC | **CONFIRM** | Bug under reviewed issue |
| Weak assertions, missing negative cases, incomplete field checks, brittle structure, duplicated fixtures | **TRACK** | `track_reason: test-hygiene` |
| Missing coverage for a named later phase only | **TRACK** | Name the phase in rationale — not DISMISS |
| Reviewer misread existing coverage | **DISMISS** | `dismiss_reason: wrong-fact` only |
| Plan/SPEC explicitly defers the test for this slice | **DISMISS** | `dismiss_reason: intentional` only |

Test-related findings from reviewers (`test-review-agent`, correctness axis, etc.) **must** appear in triage. Valid outcomes are **CONFIRM**, **TRACK**, or **DISMISS** only when:

| DISMISS allowed | When |
|-----------------|------|
| `wrong-fact` | Coverage or assertion already exists; cite `path:line` |
| `intentional` | Plan, SPEC, or task issue **explicitly** defers the test for this slice |

**Invalid DISMISS rationales for test findings** (use **TRACK** instead):

- "style gap", "nice-to-have", "not a merge blocker"
- "does not hide production behavior" (unless `wrong-fact` with evidence)
- `hygiene` or `test-hygiene` as a dismiss reason — these are **TRACK** only
- `out-of-scope` when the finding targets code or tests changed in this slice

| Test finding | Disposition | `track_reason` when TRACK |
|--------------|-------------|---------------------------|
| Missing/wrong regression test for in-scope behavior | **CONFIRM** | — |
| Weak/partial assertions, no mutation check on `frozen` DTOs, missing negative protocol cases | **TRACK** | `test-hygiene` |
| Duplicated fixtures/helpers across test files | **TRACK** | `test-hygiene` or `duplication` |
| Untested CLI/API error paths agents rely on | **TRACK** | `contract` |
| Coverage deferred to a **named** later task/phase | **TRACK** | free text naming the phase |

`hygiene` and `test-hygiene` are **TRACK** reasons — never `dismiss_reason` values.

## Reason enums

**DISMISS reasons** (record in triage, not separate filing labels):

- `wrong-fact` — reviewer misread code or tests
- `hypothetical` — needs unbuilt scenario / no untrusted caller today
- `intentional` — stub or deferral per spec/AC for this slice only
- `out-of-scope` — real but not this issue's slice **and** no SPEC obligation (**not** for test gaps on files in the current diff)

**TRACK reasons** (optional metadata):

- `spec-drift` — SPEC promises behavior ACs don't cover
- `hygiene` — naming, structure, maintainability (production code)
- `test-hygiene` — weak assertions, missing negative cases, incomplete field checks, brittle test structure
- `duplication` — copied fixtures/helpers that should be shared
- `contract` — untested CLI/API error paths agents rely on

## Severity

**Severity is required on every `CONFIRM`** and optional-but-encouraged on `TRACK`. Use the four-level scale:

| Level | Meaning | Merge-gate behavior |
|-------|---------|---------------------|
| **Blocker** | System unusable, data loss, security breach | Blocks merge at every PR level |
| **Critical** | Core workflow broken, no workaround | Blocks merge at every PR level |
| **Major** | Significant degradation, workaround exists | Blocks story/spec PRs; task PRs may merge if impact is minor (reviewer judgment) |
| **Minor** | Style, naming, UX polish | Never blocks merge — follow-up issue only |

**Merge gate rule (outline §4.a.v, §7.b–d):** Only `Blocker` and `Critical` findings block a PR from merging. `Major` findings become follow-up bug issues and may block story/spec-level PRs at the reviewer's discretion. `Minor` findings are always follow-up only and never block.

**Severity mapping from raw reviewer output** (synthesis input → triage scale):

| Reviewer raw | Target scale |
|-------------|--------------|
| CRITICAL | Blocker or Critical (judgment on scope of impact) |
| HIGH | Critical or Major |
| MEDIUM | Major |
| LOW | Minor |
