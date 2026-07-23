# Spec — User story & AC subagent prompts

Copy-ready Task prompts for story review, story drafting, and AC generation. Load **only when dispatching subagents** — see [spec-story-ac-procedure.md](spec-story-ac-procedure.md) for orchestration and merge rules.

**Output templates** (load and paste into each Task prompt body):

- Stories: [_templates/spec/story-subagent-output.md](../../../_templates/spec/story-subagent-output.md)
- AC: [_templates/spec/ac-subagent-output.md](../../../_templates/spec/ac-subagent-output.md)

---

## Story review (single story)

```
Readonly spec story review. Do not write files or spawn subagents.

Feature: [name]
Assumptions:
[bullets]

Locked decisions:
[bullets]

User story to review:
[paste]

Check: actor clarity, goal coherence, benefit linkage, scope (one testable slice), flow vs adjacent context: [other story titles if any]

Output format: [paste contents of _templates/spec/story-subagent-output.md]
Recommendation must be accept | revise | split | reject.
If revise or split, include side-by-side original and proposed text with rationale.
```

## Story draft (from discussion)

```
Readonly spec story draft. Do not write files or spawn subagents.

Feature: [name]
Assumptions:
[bullets]

Requirements summary from discussion:
[bullets]

Draft a flat list of user stories (US-01, US-02, …). No priority labels.
Each story: one testable slice, not an epic.

Output format: [paste contents of _templates/spec/story-subagent-output.md]
Use Recommendation: accept for each proposed story unless you recommend splitting before user sees them (then use split with proposed stories).
```

## AC generation (single approved story)

```
Readonly acceptance criteria author. Do not write files or spawn subagents.

Approved story:
US-NN: [title]
As a … I want … so that …

Context — other stories in feature (titles only): [list]
Assumptions: [bullets]
Locked decisions: [bullets]

Write Given → When → Then acceptance scenarios for this story only.
Include happy path plus error, empty, and permission paths where the story implies them.
Use flat numbered list under this story. Use temporary AC IDs AC-[story-local]-01, AC-[story-local]-02; parent will renumber globally.

Output format: [paste contents of _templates/spec/ac-subagent-output.md]
AC rules: [paste _docs/planning/ac-format-rules.md Rules section, or summarize]
```
