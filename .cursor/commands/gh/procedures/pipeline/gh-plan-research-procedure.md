# gh-plan — Research subagent procedure

Subagent orchestration for `/gh-plan` and [gh-plan-update-procedure.md](gh-plan-update-procedure.md). Load with [gh-plan.md](../../gh-plan.md) and [gh-plan-procedure.md](gh-plan-procedure.md).

**Subagents research codebases; the parent owns GitHub context, blocker discovery, payload merge, and `finish-plan`.**

Subagents are **readonly** (`readonly: true`). They must **not** spawn further subagents, write files, run `finish-plan`, or ask the user questions.

---

## Hub-and-spoke

| Parent (orchestrator) | Subagents |
| --- | --- |
| Context, repo list, checkout mapping ([planning-shared.md](planning-shared.md)) | Per-repo code research |
| **Branch sync** before subagents ([branch-sync-procedure.md](branch-sync-procedure.md)) — skip when [update mode](gh-plan-update-procedure.md) | File scope, patterns, tests, task drafts |
| `gh project item-list` blocker scan | — |
| Merge tasks, assign `US-*-TASK-*` IDs, blocker graph | — |
| Write payload JSON, run `finish-plan`, present URLs | — |

**Never** skip subagents for multi-file research when target repos are on disk. **Never** hand publish commands to the user.

---

## When subagents are required

| Step | Subagents required when |
| --- | --- |
| **Repo research** | Always, when ≥1 **listed** repo has a local checkout |
| **Inline parent research** | Only when a listed repo has no local checkout — document gap in `story_notes`; do not research unlisted repos |

Launch **one research subagent per repo listed on the story issue** (not one mega-agent across repos).

---

## Subagent selection

| Step | `subagent_type` | Notes |
| --- | --- | --- |
| Per-repo implementation research | `explore` | `readonly: true`; thoroughness `medium` |
| Blocker / project scan | — | **Parent only** (Shell + `gh project item-list`) |
| Payload + publish | — | **Parent only** |

Fallback if `explore` unavailable: `generalPurpose` with `readonly: true`.

---

## Parent preamble (before launching subagents)

Complete [planning-shared.md](planning-shared.md) and **Branch sync** — **unless** invoked from [gh-plan-update-procedure.md](gh-plan-update-procedure.md) (sync already done; seed subagents with existing task ids + Scope tables).

1. Fetch story issue body + labels (`gh issue view --json body,title,labels,repository`).
2. Resolve `story_issue.id` (`US-NN`) from title/body or manifest.
3. Load parent spec issue + `SPEC.md` + manifest when present.
4. Resolve target repos (listed only) — [planning-shared.md §Target repos](planning-shared.md#target-repos).
5. Map each listed repo → local checkout — [planning-shared.md §Local checkout mapping](planning-shared.md#local-checkout-mapping).
6. **Branch sync** — [branch-sync-procedure.md](branch-sync-procedure.md) (`--mode plan`). **Skip in update mode.**
7. If a **listed** repo has no local path, note it in `story_notes` — do not launch a subagent.

---

## Repo research subagent — inputs

Load prompt template [_templates/planning/repo-research-prompt.md](../../../_templates/planning/repo-research-prompt.md) and substitute:

| Placeholder | Value |
|-------------|-------|
| `{owner}/{name}` | GitHub repo |
| `{absolute_path}` | Local checkout (required — abort with NO_CHECKOUT if missing) |
| `{story_id}` / `{story_title}` | From story issue |
| `{ac_block}` | Given/When/Then from issue body |
| `{spec_excerpt}` | Objective + cross-repo notes + stack for this repo only |

Required output shape: [_templates/planning/repo-research-output.md](../../../_templates/planning/repo-research-output.md).

**Discovery rules:**

- semble-first; grep literals only after area identified
- ~5 primary source files per task (+ explicit test files)
- Smallest viable change ([plan-minimal-change.md](../lib/plan-minimal-change.md))
- Every task must include tests + task-narrow verify command
- Every task must lock design choices in `decisions[]` (chosen approach only; rejected options → Out of scope)
- Propose 1–3 tasks for this repo

Use `TASK-DRAFT-*` locally — parent renames to `US-NN-TASK-*` or `<issue#>-TASK-*`.

---

## Parallelism

| Listed repos | Launch |
| --- | --- |
| 1 repo | 1 subagent |
| 2–6 repos | **N subagents in one parent message** (parallel Task calls) |

Max **6** parallel research subagents per `/gh-plan` invocation.

---

## Parent merge (after subagents return)

1. **Task IDs** — fresh plan: rename to `US-01-TASK-01`, … globally unique; **update mode**: preserve existing ids per [gh-plan-update-procedure.md](gh-plan-update-procedure.md). Preserve repo from subagent.
2. **story_notes** — cross-repo sequencing, shared state, patterns spanning tasks.
3. **Intra-plan blockers** — map `blocked_by_drafts` → `blockers[]` with `kind: task`.
4. **External blockers** (parent Shell) — [procedure §Blocker discovery](gh-plan-procedure.md#blocker-rules).
5. **Build payload** — [gh-plan.example.publish.json](../../examples/gh-plan.example.publish.json); `types.work`: `"Task"`.
6. **Run `finish-plan`** — [procedure §Commands](gh-plan-procedure.md#commands).

---

## Subagent red flags

- Inferring or pairing repos not listed on the story issue
- Using `SPEC.md` cross-repo tables to add research repos
- One subagent asked to research multiple listed repos
- Subagent writes payload or runs `finish-plan`
- Tasks proposed without tests or verify command
- Tasks that leave design open (`either`/`or`/`consider`/`TBD`) or omit `decisions` when a tradeoff existed

---

## Verification (before finish-plan)

Full checklist: [gh-plan-procedure.md §Verification](gh-plan-procedure.md#verification).
