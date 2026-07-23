---
name: gh-resolve-issues
description: Fix Bug sub-issues from gh-review on the task branch using Composer. Use when user says /gh-resolve-issues.
user-invocable: true
disable-model-invocation: true
allowed-tools: Read, Bash, Grep, Glob
---

## Cursor → Claude Code

This skill wraps `.cursor/` harness content. Read the entrance file below, then every procedure it links.

- **Subagents:** When a procedure says `Task` with `subagent_type="explore"` (or similar), spawn a Claude Code subagent (`Explore`, `general-purpose`, or a custom agent from `.claude/agents/`).
- **Scripts:** Run helpers under `.cursor/commands/_scripts/` with `python3` from repo root.
- **Paths:** All procedure links resolve relative to the entrance file's directory under `.cursor/commands/`.


## Entrance

Read and follow **`.cursor/commands/gh/gh-resolve-issues.md`**.
