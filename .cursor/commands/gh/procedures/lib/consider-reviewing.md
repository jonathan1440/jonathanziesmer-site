---
name: consider-reviewing
description: >-
  After agent edits files, select applicable Task review subagents, run them in
  parallel, merge findings into one issue list. Triggered by stop hook
  follow-up or manual invocation.
---

# Consider reviewing (post-edit)

Use when: hook follow-up asked for this skill, user says "consider reviewing", or you just edited code and need adversarial review.

## Goal

1. Infer **which edited files** matter (from conversation + last assistant turn).
2. Pick **applicable** review `subagent_type` values (Task tool)—only names the **current** Task tool accepts (see catalog below).
3. Launch **all applicable reviewers in one message** (parallel).
4. Reply using **Parent agent final reply format** (below): merged issues **and** aggregate verdict.

**Dedupe:** merge two findings only when **same file**, **same or overlapping line/range** (or both lack a line), **and** one-line summaries are the same or near-duplicates (same root cause). If same file + same theme but **different** summaries or lines, keep both.

## Reviewer catalog (this install)

**Source of truth for names available here:** files under **`.cursor/agents/`** in this project (if present), else **`~/.cursor/agents/`**, whose `name:` in frontmatter matches Task `subagent_type`. Do **not** assume types exist because they appear in generic Cursor docs or other repos—if Task rejects a name, use `code-reviewer` for that language instead.

| subagent_type | When applicable |
| --- | --- |
| `code-reviewer` | Default for most source/config changes. **Optional / skip** for doc-only churn (e.g. only `README*`, `CHANGELOG`, internal plans), generated-only lockfiles with no manual logic, or binary/image-only edits—unless the user asked to review prose or you need a quick consistency pass. |
| `security-reviewer` | Auth, secrets, crypto, network boundary, user input, payments, sessions, headers, new endpoints, dependency bumps with security impact. |
| `typescript-reviewer` | `.ts`, `.tsx`, `.mts`, `.cts`, or JS stack tooling touching types/build. |
| `python-reviewer` | `.py`, `pyproject.toml`, `requirements*.txt`, pytest/ruff config. |
| `java-reviewer` | `.java`, Maven/Gradle, Spring configs. |
| `database-reviewer` | SQL, migrations, Prisma/Drizzle schema, ORM models, query-heavy code. |
| `flutter-reviewer` | Dart or Flutter: `pubspec.yaml` / `pubspec.lock`, `lib/`, `bin/`, `tool/`, `test/` (Dart tests), `.dart` elsewhere in package. |
| `healthcare-reviewer` | Clinical/PHI workflows, CDSS, regulated healthcare code. |
| `test-review-agent` | Non-trivial changes to `**/*test*`, `**/spec/**`, `__tests__`, or test harness config. |
| `contract-reviewer` | **Mandatory in `/gh-review`** (every level) — sign-off against story/spec AC + `AGENTS.md` contract; see [gh-review-procedure.md Phase 2c](../pipeline/gh-review-procedure.md#phase-2c--contract-sign-off-exit-criterion). |
| `product-judge` | Story/spec-level `/gh-review` with a product surface (deployed preview, endpoints, CLI) — drives tier 6 as the customer. Skip for pure-infra changes with no surface. |

**Other Cursor deployments** sometimes expose e.g. `go-reviewer`, `kotlin-reviewer`, `rust-reviewer`. Use them **only** when your Task schema lists them; otherwise route Go/Kotlin/Rust through `code-reviewer`.

**Skip** a reviewer when zero files in its domain were touched, unless the change clearly crosses into that domain (example: small TS change but adds raw SQL → add `database-reviewer`).

**Do not** spawn the same `subagent_type` twice in one pass.

## Parallelism

One assistant message, multiple Task calls (or your client’s equivalent), **same user-visible turn**.

**Default:** reviewers are **read-only**—they produce a report. **Do not** apply fixes while executing this skill unless the user explicitly asked to fix findings in this turn (or a separate fix pass / skill is in scope). If unclear, report only and ask.

**Models:** Project review agents pin **Composer** (`composer-2.5`) in frontmatter. Keep it that way — review is high return at low cost; do not escalate reviewers to frontier models.

## Prompt each reviewer

Each Task prompt must include:

- List of **absolute or workspace-relative paths** to review.
- "Independent reviewer; find problems; return **structured** list."
- Ask for output shape:

```text
## Verdict
PASS | PASS_WITH_NOTES | FAIL

## Issues (ordered by severity)
- [CRITICAL|HIGH|MEDIUM|LOW] path:line — summary — suggestion
```

Subagents use `path:line` when known. In **Parent agent final reply format**, merged rows may use `path` only if line is unknown.

## Merge step (you, after subagents return)

1. Concatenate all issues.
2. Sort: CRITICAL → HIGH → MEDIUM → LOW.
3. Dedupe per **Dedupe** rule in Goal (do not collapse distinct root causes).
4. If any CRITICAL: say so first; recommend whether ship is blocked.

## Aggregate verdict (required)

After merging issues, set **one** top-level verdict for the user:

| Verdict | When |
| --- | --- |
| **FAIL** | Any merged issue is **CRITICAL**, **or** any reviewer returned `FAIL`, **or** you judge ship unsafe. |
| **PASS_WITH_NOTES** | Not FAIL, and (any remaining HIGH/MEDIUM/LOW **or** any reviewer returned `PASS_WITH_NOTES`). |
| **PASS** | Not FAIL, all reviewers `PASS`, merged issue list empty (use `- None` under Issues). |

If a reviewer omitted verdict, infer from their issues: CRITICAL/HIGH present → treat as at least `PASS_WITH_NOTES`; empty issues + no FAIL language → `PASS`.

## Parent agent final reply format

Use this structure so hook + human output stay consistent:

```text
## Applicability
(table or bullets: which subagent_type ran / skipped and why)

## Aggregate verdict
FAIL | PASS_WITH_NOTES | PASS

## Issues (severity → path — summary — suggestion)
- [SEVERITY] path — … — …  (line optional: `path:line` when known)
(or single line: - None)

## Notes
optional: incomplete reviewers, skipped doc-only pass, etc.
```

## When hook triggered you

Treat as **mandatory** when the user message is the **post-edit review follow-up** from the stop hook: it lists edited paths and tells you to run this skill. Exact wording is built in `~/.cursor/hooks/consider_reviewing_on_stop.py` (`followup_message`); do not depend on a fixed string in chat beyond recognizing that flow.

Disable for the session if the user asked to skip reviews, or set env `CURSOR_SKIP_CONSIDER_REVIEWING` to `1`, `true`, `yes`, or `on` (case-insensitive) so the hook does not re-queue.

Hook wiring: `~/.cursor/hooks.json` and `~/.cursor/hooks/*.py`. Cursor loads **user** hooks from `~/.cursor/` and **project** hooks from each workspace’s `.cursor/hooks.json`; both can run for the same event, so you may get duplicate `afterFileEdit` / `stop` invocations and races on the shared state directory—avoid defining the same hook in both places unless intentional.

**One-shot suppress (review → fix → no second ping):** After the hook successfully emits a review follow-up, it writes a per-conversation flag under the same temp state directory (`suppress_next_<sha256(conversation_id)>`). The **next** completed `stop` that has **non-empty recorded edits** for that conversation removes the flag and **does not** emit another follow-up (so the “fix review findings” turn does not re-queue review). A completed `stop` **without** path edits still **removes** an outstanding flag so a later real edit is not wrongly suppressed. Set `CURSOR_SKIP_CONSIDER_REVIEWING` to `1` / `true` / `yes` / `on` (case-insensitive) to skip hook logic entirely.

`hooks.json` uses `loop_limit` on the `stop` entry (Cursor caps how many times a `stop` hook may chain `followup_message` auto-submits; default is product-defined—see [Cursor hooks](https://cursor.com/docs/agent/hooks)).

## Limits

- Hook lists up to **25** unique edited paths in the follow-up (same threshold as “huge” list sampling below). Override with env `CURSOR_REVIEW_HOOK_MAX_PATHS` (integer, clamped 1–500).
- If edited file list is huge (**>25** unique paths in the turn), sample highest-risk paths in your merged reply + summarize omission.
- If a reviewer times out, note `incomplete: <subagent_type>` and continue with others.
