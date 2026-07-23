Repo research for /gh-plan. Readonly — no file writes, no subagents, no user questions.

Repo: {owner}/{name}
Local path: {absolute_path}
Story: {story_id} — {story_title}

Acceptance criteria (canonical):
{ac_block}

Spec context for this repo:
{spec_excerpt}

Constraints:
- semble-first code discovery in this repo only; grep literals after area found
- ~5 primary source files per proposed task (+ explicit test files)
- One repo only — do not research other repos
- Smallest viable change; mirror existing patterns (plan-minimal-change.md)
- Every task must include tests + verify command
- Propose 1–3 tasks for this repo for this story scope

Return output matching [_templates/planning/repo-research-output.md](../../_templates/planning/repo-research-output.md).
Use `TASK-DRAFT-*` locally — parent renames to `US-NN-TASK-*` or `<issue#>-TASK-*`.
