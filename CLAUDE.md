@AGENTS.md

## Start here

@.cursor/commands/ENTRANCE.md

## GitHub SDLC pipeline

Run in order for a tracked feature:

```
/gh-spec → /gh-plan → /gh-build → /gh-review → /gh-resolve-issues
                ↑             ↘ /gh-update-plan  (when spec or plan drifts)
    /gh-estimate-work (optional — after spec or before plan)
```

| Command              | Source                                     |
| -------------------- | ------------------------------------------ |
| `/gh-spec`           | `.cursor/commands/gh/gh-spec.md`           |
| `/gh-plan`           | `.cursor/commands/gh/gh-plan.md`           |
| `/gh-update-plan`    | `.cursor/commands/gh/gh-update-plan.md`    |
| `/gh-estimate-work`  | `.cursor/commands/gh/gh-estimate-work.md`  |
| `/gh-build`          | `.cursor/commands/gh/gh-build.md`          |
| `/gh-review`         | `.cursor/commands/gh/gh-review.md`         |
| `/gh-resolve-issues` | `.cursor/commands/gh/gh-resolve-issues.md` |

## Core commands

| Command                  | Source                                           |
| ------------------------ | ------------------------------------------------ |
| `/aws-sso`               | `.cursor/commands/core/aws-sso.md`               |
| `/commit`                | `.cursor/commands/core/commit.md`                |
| `/commit-push`           | `.cursor/commands/core/commit-push.md`           |
| `/iterate-on-action`     | `.cursor/commands/core/iterate-on-action.md`     |
| `/handoff`               | `.cursor/commands/core/handoff.md`               |
| `/review`                | `.cursor/commands/core/review.md`                |
| `/research-issues`       | `.cursor/commands/core/research-issues.md`       |
| `/write-agents-contract` | `.cursor/commands/core/write-agents-contract.md` |
| `/find-skills`           | `.cursor/commands/core/find-skills.md`           |
| `/caveman`               | `.cursor/commands/core/caveman.md`               |

## Local (no GitHub) workflow

| Command  | Source                                        |
| -------- | --------------------------------------------- |
| `/plan`  | `.cursor/commands/gh/procedures/lib/plan.md`  |
| `/build` | `.cursor/commands/gh/procedures/lib/build.md` |

## Infrastructure

- **Scripts:** `.cursor/commands/_scripts/` (`gh/`, `handoff/`, `aws/`)
- **Templates:** `.cursor/commands/_templates/`
- **Procedures index:** `.cursor/commands/gh/procedures/README.md`
- **Review subagents:** `.claude/agents/` (symlinked from `.cursor/agents/`)
- **Handoff output:** `.cursor/handoffs/` (gitignored)

## Cursor → Claude Code

When a procedure references Cursor's `Task` tool or `subagent_type`, spawn a
Claude Code subagent instead (`Explore`, `general-purpose`, or a named agent
from `.claude/agents/`).

Regenerate the `.claude/` bridge after harness changes or edits to `.cursor/`:

```bash
python3 .cursor/commands/_scripts/sync_claude_bridge.py
```

