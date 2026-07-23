# Spec — User story & AC subagent procedure

Parent orchestrator for `/gh-spec`. **Subagents research and draft; the parent owns human gates, merge, and file writes.**

Subagents are **readonly** (`readonly: true`). They must **not** spawn further subagents, write files, or ask the user questions.

Script: `.cursor/commands/_scripts/gh/spec-story-ac-merge.py`

---

## Hub-and-spoke rules

| Parent (orchestrator) | Subagents |
| --- | --- |
| Clarifying questions, assumptions, story-source gate | Story review, story drafting, AC generation |
| Present merged story proposals; **wait for user approval** | — |
| Launch AC subagents only **after** stories accepted | Given/When/Then drafts per story |
| Present merged AC; **wait for user review** | — |
| Write `SPEC.md` / `docs/acceptance-criteria.md`, technical sections | — |

**Never** skip user approval gates because a subagent returned output.

---

## When subagents are required

| Step | Subagents required when |
| --- | --- |
| **Story review / draft** | User provided ≥1 story, **or** user chose **have me draft them**, **or** ≥2 stories in scope |
| **AC generation** | Always, once stories are **user-approved** (including infra-only technical scenarios) |

**Optional inline (parent only):** single infra-only change with one technical scenario and user confirmed **skip stories** — parent may draft one story + AC without Task.

---

## Subagent selection

| Step | `subagent_type` | Fallback |
| --- | --- | --- |
| Story coherence review | `ce-spec-flow-analyzer` | `generalPurpose` |
| Story drafting (from discussion) | `ce-spec-flow-analyzer` | `generalPurpose` |
| Acceptance criteria (Given/When/Then) | `ce-spec-flow-analyzer` | `qa-test-engineer` |

Use `ce-spec-flow-analyzer` for flow gaps and missing journeys; use `qa-test-engineer` when AC need heavy edge-case / test-path coverage and flow is already clear.

---

## Step 1 — Story review / draft (subagents)

Load [spec-story-ac-prompts.md](spec-story-ac-prompts.md) when dispatching Task subagents.

### Inputs to pass every story subagent

- Feature name and one-paragraph objective
- **Assumptions** block from parent
- User's raw stories (if any) **or** "draft from discussion" with bullet summary of clarified requirements
- Locked decisions from conversation (constraints, out-of-scope)
- Story format requirement: flat `US-NN`, `As a … I want … so that …`, no priority labels
- Mode: `review` | `draft` | `review-and-split` (when one epic needs splitting)

### Parallelism

- **One story provided:** one subagent (`review` mode).
- **2–6 stories:** one subagent per story in **one parent message** (parallel Task calls).
- **>6 stories:** batch **2–3 stories per subagent**, max **6 subagents**; merge batches in parent.

### Required subagent output

Load and include in each Task prompt: [_templates/spec/story-subagent-output.md](../../../_templates/spec/story-subagent-output.md).

### Parent merge (after subagents return)

1. Validate subagent output, then merge and renumber:

```bash
python3 .cursor/commands/_scripts/gh/spec-story-ac-merge.py validate-stories --input batch1.md batch2.md
python3 .cursor/commands/_scripts/gh/spec-story-ac-merge.py merge-stories --input batch1.md batch2.md --output merged-stories.md
```

2. Surface **revise** / **split** items as side-by-side ORIGINAL vs PROPOSED blocks (script prints warnings; parent presents to user).
3. Dedupe stories that subagents split differently — pick one framing or ask user.
4. Present full story list to user; **GATE — wait for explicit acceptance** before Step 2.

---

## Step 2 — AC generation (subagents)

Run **only after** the user accepts the story list. Load [spec-story-ac-prompts.md](spec-story-ac-prompts.md) when dispatching Task subagents.

### Inputs to pass every AC subagent

- **One approved story** (`US-NN` + full story text)
- Adjacent stories summary (titles only) for flow context — avoid duplicate AC
- Assumptions and locked decisions
- AC format and rules: [_docs/planning/ac-format-rules.md](../../../_docs/planning/ac-format-rules.md)
- Starting AC ID offset if batching (e.g. "begin at AC-07") — subagents use story-local temp IDs; parent renumbers globally

### Parallelism

- **One story:** one subagent.
- **2–6 stories:** one subagent per story, parallel.
- **>6 stories:** batch 2 stories per subagent, max 6 subagents.

### Required subagent output

Load and include in each Task prompt: [_templates/spec/ac-subagent-output.md](../../../_templates/spec/ac-subagent-output.md).

### Parent merge (after subagents return)

1. Validate, merge, and assign **global sequential** `AC-01`, `AC-02`, …:

```bash
python3 .cursor/commands/_scripts/gh/spec-story-ac-merge.py validate-ac --input ac-batch1.md ac-batch2.md
python3 .cursor/commands/_scripts/gh/spec-story-ac-merge.py merge-ac \
  --stories merged-stories.md --input ac-batch1.md ac-batch2.md --output merged-ac.md
```

2. Review duplicate/overlap warnings; dedupe or note for user.
3. Present full **User Stories & Acceptance Criteria** section to user.
4. **GATE — wait for user review** of AC before Step 3 (technical spec).

After AC approval for `/gh-spec`: merge stories and AC into the publish payload — do **not** run `write-artifact` for local AC files. Canonical AC lives in GitHub story sub-issues; `SPEC.md` gets the story index and technical sections only ([gh-spec-driven-development](gh-spec-driven-development.md) **Artifact layout**).

---

## Red flags (orchestrator)

- Running story review or AC generation serially in the parent when parallelism applies
- Launching AC subagents before user accepts stories
- Letting subagents write `SPEC.md` or ask the user questions
- Subagents spawning nested Tasks
- Presenting subagent output without renumbering `US-*` / `AC-*` or merging cross-story conflicts
- Skipping `validate-*` before presenting merged output to the user

---

## Verification (parent, before Step 3)

```bash
python3 .cursor/commands/_scripts/gh/spec-story-ac-merge.py validate-stories --input merged-stories.md
python3 .cursor/commands/_scripts/gh/spec-story-ac-merge.py validate-ac --input merged-ac.md
```

- [ ] Story subagents ran (or inline exception documented)
- [ ] User explicitly approved story list
- [ ] AC subagents ran after story approval
- [ ] Global `AC-*` IDs assigned; user reviewed and approved AC
- [ ] Ready to write technical spec sections
