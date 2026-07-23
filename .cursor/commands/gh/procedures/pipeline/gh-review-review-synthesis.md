---
name: gh-review-review-synthesis
description: >-
  Mandatory parallel subagent review and five-axis synthesis for gh-review.
  Replaces review.md + code-review-and-quality.md for issue-scoped review.
---

# gh-review review synthesis

Load **`.cursor/commands/gh/procedures/lib/consider-reviewing.md`** end-to-end.

## gh-review rules (stricter than default review)

- Run **all applicable** Task reviewers every invocation — no doc-only skip unless user asked to skip reviews
- When the diff touches `**/*test*`, `**/spec/**`, `__tests__`, or test harness config, include **`test-review-agent`**
- One parent turn, parallel Task calls, `readonly: true`
- Merge per consider-reviewing (**Applicability**, **Aggregate verdict**, **Issues**, **Notes**)
- **Test findings are never optional** — carry every test-related issue into triage; do not drop them as non-blocking

## Five-axis synthesis

After subagents return, add a short **five-axis synthesis** (Critical / Important / Suggestion mapped from merged issues plus any gaps subagents missed):

1. **Correctness** — Spec match? Edge cases? Tests adequate?
2. **Readability** — Clear names? Straightforward logic? Well-organized?
3. **Architecture** — Existing patterns? Clean boundaries? Right abstraction level?
4. **Security** — Input validated? Secrets safe? Auth checked? (See [security-and-hardening.md](../lib/security-and-hardening.md) when needed.)
5. **Performance** — No N+1 queries? No unbounded ops? (See [performance-optimization.md](../lib/performance-optimization.md) when needed.)

Map raw reviewer severities to the four-level scale: CRITICAL → Blocker or Critical (judgment on scope); HIGH → Critical or Major; MEDIUM → Major; LOW → Minor. See [gh-review-triage-rules.md §Severity](gh-review-triage-rules.md#severity) for the full mapping and merge-gate rules.

Normalize findings per [gh-review-rr-ids.md](gh-review-rr-ids.md) before Phase 3 triage.
