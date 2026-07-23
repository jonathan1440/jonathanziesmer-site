# Code review (library)

Load and follow **[code-review-and-quality.md](code-review-and-quality.md)**.

Review the current changes (staged or recent commits) across all five axes:

1. **Correctness** — Does it match the spec? Edge cases handled? Tests adequate?
2. **Readability** — Clear names? Straightforward logic? Well-organized?
3. **Architecture** — Follows existing patterns? Clean boundaries? Right abstraction level?
4. **Security** — Input validated? Secrets safe? Auth checked? (Use **[security-and-hardening.md](security-and-hardening.md)** where needed.)
5. **Performance** — No N+1 queries? No unbounded ops? (Use **[code-simplification.md](code-simplification.md)** where needed.)

Categorize findings as Critical, Important, or Suggestion.
Output a structured review with specific file:line references and fix recommendations.

---

## Parallel subagent review (Task) — required

**Always** load and follow **[consider-reviewing.md](consider-reviewing.md)** end-to-end for every `/review` invocation. Do not skip Task reviewers unless consider-reviewing explicitly allows it (env skip, user asked to skip reviews, or zero applicable paths after applicability).

That workflow defines:

- **Applicability** — Infer edited paths; pick only **Task-supported** `subagent_type` values from the catalog in that file (source of truth: `.cursor/agents/` in this project, else `~/.cursor/agents/` frontmatter `name:`). Default `code-reviewer`; add language/domain reviewers when files match; skip irrelevant reviewers; do not spawn the same type twice.
- **Parallelism** — One assistant turn, multiple **Task** calls with `readonly: true` unless the user asked you to fix findings in this turn.
- **Per-reviewer prompt** — Absolute or workspace-relative paths; structured output with `## Verdict` (`PASS` | `PASS_WITH_NOTES` | `FAIL`) and `## Issues` rows `[CRITICAL|HIGH|MEDIUM|LOW] path:line — summary — suggestion`.
- **Merge** — Concatenate, sort CRITICAL → HIGH → MEDIUM → LOW, dedupe only when same file, overlapping or missing line, and same/near-duplicate summary (keep distinct root causes).
- **Aggregate verdict** — One top-level `FAIL` | `PASS_WITH_NOTES` | `PASS` per the table in consider-reviewing (any CRITICAL or any reviewer `FAIL` → **FAIL**, etc.).
- **Parent reply shape** — After subagents return, use the **Parent agent final reply format** from consider-reviewing (`## Applicability`, `## Aggregate verdict`, `## Issues`, `## Notes`).

After subagents return, **lead with** the merged subagent block (consider-reviewing format), then add a short **five-axis synthesis** (Critical / Important / Suggestion mapped from merged issues plus any gaps subagents missed) so humans see one coherent report.

Hook-specific behavior, env skips (`CURSOR_SKIP_CONSIDER_REVIEWING`), path limits, and one-shot suppress flags are documented in consider-reviewing; follow that file when the trigger is hook-driven.
