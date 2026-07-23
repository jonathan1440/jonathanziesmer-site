# Phase 5 runbook — steer by intent

**Parent:** [outline.md](./outline.md) · **Previous:** [phase-4-runbook.md](./phase-4-runbook.md)

Phase 5 adds goal orchestration, domain packs, risk-classified review with
SHA-bound contract SIGN-OFF, and an explicit merge policy for finding PRs.

## Architecture

```text
orchestrator submit --goal
        │
        ▼
   Spec issue (To-do)  ←── human edits
        │
        │  human moves Spec → In progress
        ▼
   goal_approve (mechanical stories)
        │
        ▼
   admission.py  ←── board / packs / maintenance
        │
        ▼
   runner (spawn.models) → local agent
        │
        ▼
   risk_review + contract_signoff@head_sha
        │
        ├─ design_conversation → latch (no further chain)
        └─ normal → request human review
              │
              └─ finding PRs: agent may merge
                 parent Spec/Story/Task PRs: human only
```

## Models (5.4)

Configured in [`.cursor/auto-workflow.json`](../../../.cursor/auto-workflow.json):

```json
"spawn": {
  "mode": "headless",
  "models": {
    "build": "composer-2.5",
    "resolve": "composer-2.5",
    "default": "auto"
  }
}
```

Legacy `spawn.model` still works as a fallback default.

**No daily run quotas.** Loop bounds: Task review/resolve ≤1 cycle; Story/Spec ≤2.
Concurrency remains `concurrency` (default 2).

## Orchestrator (5.1)

```bash
# Optional: pip install -r requirements-auto.txt  # cursor-sdk
python3 .cursor/commands/_scripts/auto/orchestrator.py submit --goal "migrate CDK pin"
python3 .cursor/commands/_scripts/auto/orchestrator.py status
# After editing the Spec on GitHub, move Status To-do → In progress
# (or manually:)
python3 .cursor/commands/_scripts/auto/orchestrator.py approve --spec-issue owner/repo#N
```

Approval creates User Stories from the stored draft. Plan/build still follow
existing board transitions and Phase 3 chain rules. Only **unblocked** tasks
are scheduled (blocker edges from `/gh-plan`).

## Domain packs (5.2)

```bash
python3 .cursor/commands/_scripts/auto/orchestrator.py pack list
python3 .cursor/commands/_scripts/auto/orchestrator.py pack cdk_migration
python3 .cursor/commands/_scripts/auto/orchestrator.py pack cost_regression
```

Cost pack requires `spawn.mcp.aws_pricing: true` (or equivalent) in config;
otherwise it emits a setup alert rather than a false-success noop.

Pack defs: `.cursor/commands/_scripts/auto/packs/*.json`

## Risk + SIGN-OFF (5.3)

- Classifier: `risk_review.classify_change` / agent `risk_classify` prompt
- Payload fields (see `gh-review.payload.schema.json`):
  - `risk_class`: `normal` | `design_conversation`
  - `contract_signoff`: `{verdict, head_sha, reviewed_at}`
- Gate: `risk_review.risk_gate` — design latches via `Registry.mark_risk_latched`;
  normal requires `SIGN-OFF` with matching live PR head SHA

## Merge policy (5.3 / 5.4)

| PR kind | Who merges |
| --- | --- |
| Spec / User Story / normal Task | **Human only** |
| Review-generated Bug / finding Task | **Agent may merge** after gates |

Module: `.cursor/commands/_scripts/auto/merge_policy.py`

Every code-bearing issue should have a PR for visibility. Parent Ready to ship
only after finding PRs are merged and the parent PR is still open
(`completion.should_mark_ready_to_ship`).

## Admission (5.0)

All spawns go through `admission.admit_and_spawn`. Overflow intents land in
`state_dir/queue/` and drain on later `dispatch.py once|poll` cycles.
Registry writes use `fcntl` locking.

## E2E checklist

1. [ ] `pytest tests/auto/` passes
2. [ ] Config loads with `spawn.models`
3. [ ] `orchestrator.py submit` creates Spec + goal (`awaiting_approval`) against a test repo
4. [ ] Moving Spec To-do → In progress triggers `goal_approve` (stories created)
5. [ ] Domain pack `cost_regression` without MCP → setup_alert
6. [ ] Review payload with mismatched `head_sha` fails `signoff_valid`
7. [ ] `can_agent_merge_pr(issue_type="Spec")` is denied; Bug finding allowed
8. [ ] Never auto-merge parent Spec/Story/Task PRs

## Related files

| Path | Role |
| --- | --- |
| `.cursor/commands/_scripts/auto/admission.py` | Shared spawn gate |
| `.cursor/commands/_scripts/auto/intent_queue.py` | Durable pending intents |
| `.cursor/commands/_scripts/auto/model_policy.py` | Model resolution |
| `.cursor/commands/_scripts/auto/orchestrator.py` | Goal CLI + pack CLI |
| `.cursor/commands/_scripts/auto/goal_store.py` | Goal persistence |
| `.cursor/commands/_scripts/auto/domain_packs.py` | Pack runner |
| `.cursor/commands/_scripts/auto/risk_review.py` | Classifier + SIGN-OFF gate |
| `.cursor/commands/_scripts/auto/merge_policy.py` | Agent merge allowlist |
| `.cursor/commands/_scripts/auto/completion.py` | Completion-on-merge rules |
| `requirements-auto.txt` | Optional `cursor-sdk` |
| `tests/auto/test_admission.py` etc. | Coverage |
