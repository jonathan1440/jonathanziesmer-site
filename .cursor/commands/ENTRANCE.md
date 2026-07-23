# Entrance points

User-invoked slash commands. Everything else under `commands/` is library, procedure, or infrastructure (`_docs/`, `_scripts/`, `_templates/`).

## GitHub SDLC (`commands/gh/`)

Run in order for a tracked feature:

```
/gh-spec → /gh-plan → /gh-build → /gh-review → /gh-resolve-issues
                ↑             ↘ /gh-update-plan  (when spec or plan drifts)
    /gh-estimate-work (optional — after spec or before plan)
```

| Command | File | Phase |
| --- | --- | --- |
| [/gh-spec](gh/gh-spec.md) | Spec + GitHub parent/story issues | spec |
| [/gh-plan](gh/gh-plan.md) | Task breakdown per story | plan |
| [/gh-update-plan](gh/gh-update-plan.md) | Re-plan after upstream drift | plan |
| [/gh-estimate-work](gh/gh-estimate-work.md) | Bottom-up hour estimates on Planning board | plan |
| [/gh-build](gh/gh-build.md) | Implement one task issue | build |
| [/gh-review](gh/gh-review.md) | Issue-scoped review + triage | review |
| [/gh-resolve-issues](gh/gh-resolve-issues.md) | Fix Bug sub-issues on task branch | build |

Pipeline detail: [gh/README.md](gh/README.md). Procedures: `gh/procedures/pipeline/` + `gh/procedures/lib/`; scripts in `_scripts/gh/`.

## Core (`commands/core/`)

Daily drivers outside the GitHub pipeline.

| Command | File | Use |
| --- | --- | --- |
| [/aws-sso](core/aws-sso.md) | AWS SSO profiles for CDK | ship |
| [/find-skills](core/find-skills.md) | Discover skills (`/find-skill` works too) | n/a |
| [/caveman](core/caveman.md) | Terse output mode | n/a |
| [/commit](core/commit.md) | Conventional commit | ship |
| [/commit-push](core/commit-push.md) | Commit then push | ship |
| [/iterate-on-action](core/iterate-on-action.md) | Commit, push, fix CI | ship |
| [/handoff](core/handoff.md) | Session handoff document | n/a |
| [/review](core/review.md) | Five-axis code review (local/PR) | quality |
| [/research-issues](core/research-issues.md) | Triage review findings without GitHub sync | quality |
| [/write-agents-contract](core/write-agents-contract.md) | Draft or update AGENTS.md | spec |

## Library (not entrances)

Reusable discipline under [gh/procedures/lib/](gh/procedures/lib/) — e.g. `/plan` and `/build` when not using GitHub issues. Index: [gh/procedures/README.md](gh/procedures/README.md).
