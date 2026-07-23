---
name: gh-spec
description: Spec-driven development with GitHub parent issue and story sub-issues — repo SPEC.md plus GitHub Project traceability
---

Load and follow:

1. **`.cursor/commands/gh/procedures/pipeline/gh-spec-driven-development.md`** — specify + publish (Phases 0–1.5); **stop after publish**
2. **`.cursor/commands/gh/procedures/pipeline/spec-story-ac-procedure.md`** — story/AC subagents (during Specify)
3. **`.cursor/commands/gh/procedures/pipeline/gh-spec-github-procedure.md`** — load **only at Phase 1.5 (publish)**

Do **not** load or invoke [/gh-plan](gh-plan.md), [/gh-build](gh-build.md), or [/gh-update-plan](gh-update-plan.md) as part of `/gh-spec`.

## Start (collect if missing)

| Input | How |
|-------|-----|
| Home repo | `gh repo view --json nameWithOwner` or user `OWNER/REPO` |
| GitHub Project | Title, number, or URL |
| Feature slug | kebab-case → `docs/specs/<slug>/` |

## Ordered checklist

1. Collect inputs → `init-spec-artifacts --bootstrap` (or [procedure: Home repo](procedures/pipeline/gh-spec-github-procedure.md)) → [driven-dev: Phase 0](procedures/pipeline/gh-spec-driven-development.md)
2. Clarifying questions + Steps 1–2 → [driven-dev: Phase 1](procedures/pipeline/gh-spec-driven-development.md) (stories + AC gates)
3. Story/AC subagents → [spec-story-ac-procedure.md](procedures/pipeline/spec-story-ac-procedure.md)
4. Technical spec + repo mapping → [driven-dev: Step 3–4](procedures/pipeline/gh-spec-driven-development.md) + [procedure: Per-story repositories](procedures/pipeline/gh-spec-github-procedure.md)
5. User approves spec + repo table → multi-repo branch bootstrap → [procedure: All affected repos](procedures/pipeline/gh-spec-github-procedure.md)
6. `verify-spec --input publish-payload.json` → commit home repo → `finish-spec` (see [procedure: Commands](procedures/pipeline/gh-spec-github-procedure.md))
7. Present parent + story issue URLs and **stop**

Do not publish until all gates pass. Do not duplicate bash/JSON from linked files here.
