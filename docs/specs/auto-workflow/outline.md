# Auto-workflow — GitHub board → local Cursor agents

**Parent workflow:** [generic-workflow/workflow-outline.md](../generic-workflow/workflow-outline.md)  
**Context:** Boris Cherny's "Steps of AI Adoption" (Jul 2026) mapped to Cursor. This spec is the single source for automating the `gh-*` pipeline; it supersedes the earlier two-doc split (event outline + step-4 adoption plan).

The generic workflow outline assumes each `gh-*` command is invoked manually. This spec makes the **GitHub Project board the state machine**: moving an issue between Status columns triggers local agents, and agents move issues onward when they finish. Humans steer by moving cards and reviewing PRs; agents do the work in between.

---

## Constraints (non-negotiable)

1. **Local compute only.** All agent processes run on this machine (or an always-on host you own). No Cursor Cloud Agents, no Cursor Automations that spawn cloud VMs.
2. **Free, local + GitHub only.** No paid third-party services and no external infrastructure. Event delivery uses the GitHub API from this machine; no webhook tunnels (ngrok/Cloudflare/smee) required.
3. **Remote control encouraged.** Sessions should be steerable from the Cursor iOS app / cursor.com/agents via Remote Control — the phone is a control plane, never a compute plane.

```text
GitHub Project board (Status column moves)
        │  polled via gh api graphql
        ▼
local dispatcher (launchd poller + state diff + queue)
        │  spawns detached
        ▼
cursor agent / cursor-sdk  (local process, worktrees)
        │
        ▼
your disk · gh auth · AWS SSO · sibling repos
        ▲
        │  Remote Control / My Machines worker
Cursor iOS app (monitor, steer, approve)
```

| Allowed | Out of scope |
| --- | --- |
| Headless `cursor agent -p -f` on this machine | Cursor Automations (cloud-triggered cloud agents) |
| Local `cursor-sdk` / `@cursor/sdk` with local runtime | Cloud Agents API runs with `env.type: "cloud"` (Cursor-hosted VMs) |
| Cloud Agents API / SDK targeting **this machine's worker** (`env.type: "machine"`/`"pool"`) | Bugbot Autofix (spawns a cloud agent) |
| `agent worker start` / Remote Control (compute stays here) | |
| `launchd`/cron polling with `gh` | Webhook tunnels (ngrok, Cloudflare, smee) |
| Self-hosted GitHub Actions runner (optional, PR/CI events only) | Slack bridges requiring a public endpoint |
| Git worktrees + `/multitask` / best-of-n on disk | Any path where the harness procedure runs off-box |

Mechanical GitHub Actions (`ci.yml`, `promote.yml`, `deploy.yml`) stay as they are — they are not agent runtimes.

---

## Where the harness sits today

Strong **step 2** on the adoption ladder, with pieces of step 3 built.

| Strength (in-session) | Gap (end-to-end) |
| --- | --- |
| Parallel review subagents | Every `/gh-*` stage is human-kicked |
| Worktree isolation in `/gh-build` and `/gh-resolve-issues` | No `.cursor/hooks.json` |
| 7-tier self-verification harness | No dispatcher watching the board |
| Mandatory contract-reviewer exit gate | No SDK / CLI orchestration |
| | No cost / usage logging for agent runs |

### Claude Code concepts → local Cursor equivalents

| Article concept | Local Cursor equivalent |
| --- | --- |
| Auto mode + permission pre-approval | Run Modes (Auto-review), `permissions.json`, `sandbox.json`; headless `-f` / `--approve-mcps` / `--trust` |
| Subagents with worktree isolation | Task subagents, `/worktree`, CLI `--worktree`, `/multitask`, best-of-n on disk |
| Claude Code Review / Security Review | Local `/gh-review` + `.cursor/agents/` reviewers; optional `/review-bugbot` in-session (no Autofix) |
| Routines, `/loop`, `/batch`, `/goal` | `launchd` timers + the dispatcher; SDK fan-out |
| Claude Tag (monitor a channel, kick off tasks) | The board itself: move a card from your phone (GitHub mobile) or steer via Cursor iOS Remote Control |
| Claude kicks off Claude | Dispatcher chaining + dispatcher-initiated Status moves (Phase 3); local hooks (`stop`) |
| CLAUDE.md + Skills | `AGENTS.md` + `.cursor/` commands/skills (already strong) |
| OTel / Analytics | Local run log keyed by SDK `requestId`; optional Admin API if plan tier allows |
| Agent sandboxing | Local `sandbox.json` + hooks with `deny` + `failClosed: true` |

---

## Trigger contract — Status is the state machine

Branch naming, PR body conventions (`Closes owner/repo#N`), and issue types (Spec, User Story, Task, Bug) are the routing keys. Status field values must match [workflow-outline.md §5.3](../generic-workflow/workflow-outline.md) exactly.

### Transition → command map

| Issue type | Status transition | Moved by | Dispatcher action |
| --- | --- | --- | --- |
| Task | To-do → **In progress** | Human (or dispatcher, Phase 3) | `/gh-build` on that task |
| Task | → **Review / QA** | Agent (end of `/gh-build`) | `/gh-review` (task-level, 1 cycle) → `/gh-resolve-issues` immediately after |
| User Story | To-do → **In progress**, **no Task sub-issues yet** | Human | `/gh-plan` on that story |
| User Story | → **Review / QA** (all task sub-issues closed; `promote.yml` opened the story PR) | Automation | Two-cycle: `/gh-review` → `/gh-resolve-issues` → `/gh-review` (new findings only) → `/gh-resolve-issues` |
| Spec | → **Review / QA** (story sub-issues closed; spec PR open) | Automation | Same two-cycle review |
| Any | → **Ready to ship** | Agent (end of resolve) | Nothing — human PR review + merge is the gate |
| Spec | Spec PR merged to `main` | Human merge | Post-merge job: watch deploy, run tier 7, comment results on the spec issue; human signs off staging (medium release tier) before the spec closes |

**Review always chains resolve.** At every level (task, story, spec), `/gh-review` completing immediately triggers `/gh-resolve-issues` in the same job — a single prompt, not a second dispatch. When review files no Bug sub-issues, the resolve step is a no-op and the issue moves straight to Ready to ship.

**Not Status-triggered (stay human-kicked):** `/gh-spec` (interactive by design), `/gh-update-plan` (judgment call), `/gh-estimate-work` (client-facing, needs human context).

### Who sets Status — amendment to §5.3

The parent workflow says the *agent* sets **In progress** at the start of `/gh-build`. Under this spec, the direction inverts for kickoff: a **board move causes the build**. Rules to avoid double-firing:

1. Human (or Phase-3 dispatcher) moves a Task to **In progress** → dispatcher starts `/gh-build`.
2. The agent no longer needs to set In progress at build start (it's already there); `gh-build-publish.py set-status` calls become idempotent no-ops when Status already matches.
3. All *forward* moves remain agent-owned: → Review / QA when the PR opens, → Ready to ship after resolve.
4. Derived story/spec In-progress states (set when children build) are **ignored** by the dispatcher — only the "story In progress with zero task sub-issues = plan it" case triggers anything.

§5.3 of the parent workflow-outline needs a short amendment noting this inversion (open item below).

### Idempotency and safety rules

- **Active-run registry.** The dispatcher keeps a local registry (JSON/SQLite, gitignored) of `issue → {run id, pid, started}`. A transition on an issue with an active run is a no-op. This also absorbs the agent's own Status writes echoing back through the poller.
- **One build per story branch.** Queue lock keyed on `repo + base_branch`; parallel task builds on the same story branch race on merges.
- **Concurrency cap.** Start with 2–3 simultaneous local agents (worktrees); tune to the machine.
- **Retry budget.** A failed run may be retried once automatically; after that, escalate (comment @-mentioning the owner on the issue per §5.4) and mark the issue so the dispatcher won't re-fire until a human moves it again.
- **Never auto-merge.** Agents comment, update issues, and request reviewers only.

---

## Event delivery — poller first

GitHub Project Status changes emit the `projects_v2_item` **webhook** event, but that event is *not* a GitHub Actions trigger, and receiving webhooks locally requires a public endpoint (tunnel = third-party software). Under the free/local/GitHub-only constraint, the primary delivery is **polling**:

| Path | Hears Status moves? | Cost | Extra software | Latency | Role |
| --- | --- | --- | --- | --- | --- |
| **`launchd` poller + `gh api graphql`** | Yes | $0 | None | poll interval (~60 s) | **Primary** |
| Self-hosted GitHub Actions runner | No (PR/CI/issue events only) | $0 | Runner agent | seconds | Optional secondary for PR-merged / CI-completed signals |
| Webhook + tunnel | Yes | Free tiers exist | Tunnel client | seconds | Explicitly out — violates constraint 2; revisit only if poll latency ever hurts |

A ~60-second poll is fine for this workflow: every triggered job runs minutes to hours.

### Dispatcher design (`launchd` poller)

One Python script under `.cursor/commands/_scripts/auto/` (tests in `tests/`), run by a `launchd` interval job:

1. **Fetch** — `gh api graphql`: project items with content (issue number, type, repo), Status field value, sub-issue counts; plus open PRs on `task/US-*` / `story/US-*` / `spec/*` branches for the post-merge and promote signals.
2. **Diff** — compare against the last-seen snapshot in the state store; emit transitions.
3. **Filter** — apply the transition → command map, the active-run registry, locks, and the retry budget.
4. **Spawn** — two modes (see Remote control section for the iOS-visibility mechanics):

   **Primary — worker-routed (visible in the iOS inbox).** Create the run via the Cloud Agents API / SDK targeting this machine's registered worker, so the run is steerable from the phone while tools execute locally:

   ```python
   agent = cursor.agents.create(
       env={"type": "machine", "name": "<worker-name>"},   # registered via `agent worker start`
       prompt="Run /gh-review on the task issue linked from PR <url>. "
              "Follow .cursor/commands/gh/gh-review.md exactly, then run "
              "/gh-resolve-issues on the Bug sub-issues it files. Do not merge the PR.",
   )
   ```

   **Fallback — plain headless (no inbox visibility)** for utility jobs that never need phone steering:

   ```bash
   cursor agent -p -f --approve-mcps \
     --workspace <repo-or-worktree> \
     --output-format json \
     "<same prompt>"
   ```

   Prefer worktrees (CLI `--worktree`) so the main checkout stays free for inspection. For follow-ups on the same issue, send a new run to the existing agent (`POST /v1/agents/{id}/runs`, or `create-chat` + `--resume <id>` in headless mode) instead of cold-starting.
5. **Log** — schema v1 lifecycle events (`run_started` / `run_finished`) plus legacy spawn/reap lines: timestamp, transition, issue/PR URL, prompt class, `requestId`, model, exit code, duration. Nightly rollup via `usage_summary.py` (Phase 4).

**Job record schema** (state store):

```json
{
  "issue": "owner/repo#123",
  "kind": "build | review | resolve | plan | post-merge",
  "chat_id": "…",
  "request_id": "…",
  "workspace": "/path/to/worktree",
  "lock_key": "repo+story/US-7",
  "status": "running | done | failed | escalated",
  "attempts": 1,
  "started": "…", "ended": "…"
}
```

Exit-code policy: `0` → done, advance per procedure; nonzero → one retry, then escalate. The agent's own escalation path (issue comment + blocker sub-issue, §5.4) is authoritative; the dispatcher only guarantees it happened.

---

## Remote control (iOS) — making runs show up in the inbox

The iOS app, cursor.com/agents, and the desktop Agents Window share one backend. **A run appears in the iOS inbox if and only if it is managed by that backend.** Plain headless `cursor agent -p` processes are local-only and never appear. Three documented ways to get inbox visibility while tool execution stays on this machine:

| Mechanism | How | Fits the dispatcher? |
| --- | --- | --- |
| **Self-hosted worker routing** | Register this machine with `agent worker start` ("My Machines" / a named pool). Create runs via the Cloud Agents API v1 (`POST /v1/agents` with `env.type: "machine"` or `"pool"` + `env.name`) or the SDK (`env: machine`/`pool`). The backend manages the agent, so it shows in the inbox; every tool call executes on this machine. | **Yes — primary spawn mode** |
| **Remote Control** | In an interactive session, run `/remote-control`. Cursor auto-manages a worker on this computer; the loop moves to the backend, tools stay local. Requires Remote Control enabled under Settings → Agents (Cursor ≥ 3.9.8). | For sessions a human started at the desk |
| **iOS-initiated** | In the app, pick a worker per run: "My Machines" or a Self-Hosted Pool. | Ad-hoc kickoff from the phone |

Setup checklist:

1. Enable **Remote Control** (Agents Window → Settings → Agents; on Teams/Enterprise an admin must enable it in the Dashboard).
2. Keep the host awake (built-in "keep this computer awake" setting).
3. Run `agent worker start` as a `launchd` service so the worker survives reboots (worker auth token via `--auth-token-file`; user-scoped worker tokens exist at `/v1/sub-tokens` for team service accounts, personal API key otherwise).

**Nuance vs. the local-only constraint:** with worker routing, the *agent loop* (model calls, orchestration) runs on Cursor's backend while *all tool execution* — files, terminal, git, tests, AWS SSO — stays on this machine. That satisfies the intent of constraint 1 (no cloud VMs touch the code; secrets never leave the box) and is the price of inbox visibility. Jobs that don't need phone visibility can still use plain headless `-p` spawns.

Board moves are also phone-friendly via the GitHub mobile app — moving a card from your phone *is* the kickoff UI.

---

## Roadmap

Items are numbered `{phase}.{n}` for reference (e.g. "doing 1.3").

### Phase 0 — Unattended-run policy (config only, land first)

| # | Item |
| --- | --- |
| **0.1** | **`.cursor/permissions.json`** — allowlist `gh`, `git`, `python3`, `pytest`, `ruff`, `cdk synth`, `bash scripts/test-tier*.sh`; `autoRun` guidance for the Auto-review classifier. |
| **0.2** | **`.cursor/sandbox.json`** — allow PyPI, npm, GitHub, and the AWS endpoints SSO/CDK need; deny-by-default network. |
| **0.3** | **`.cursor/hooks.json`** — guardrails: deny `cdk deploy` to production from any agent, deny pushes to `main`, deny edits to `.github/workflows/` deploy gates. **Caveat:** hook `ask`/`allow` verdicts are currently ignored (only `deny` blocks); use `deny` + `failClosed: true`. |

### Phase 1 — Poller + the two core transitions

| # | Item |
| --- | --- |
| **1.1** | Build the dispatcher (poller, state store, registry, spawn, log). |
| **1.2** | Register the machine as a worker (`agent worker start` under `launchd`); enable Remote Control. |
| **1.3** | Wire **Task → In progress ⇒ `/gh-build`** and **Task → Review / QA ⇒ `/gh-review` → `/gh-resolve-issues`** (chained in one prompt). |
| **1.4** | Amend workflow-outline §5.3 (kickoff inversion). |
| **1.5** | Confirm worker-routed runs appear in the iOS inbox end to end. |

### Phase 2 — Story/spec levels

| # | Item |
| --- | --- |
| **2.1** | Story/spec **Review / QA** ⇒ two-cycle review + resolve. |
| **2.2** | Story **In progress** (no tasks) ⇒ `/gh-plan`. |

### Phase 3 — Agents kick off agents

| # | Item |
| --- | --- |
| **3.1** | Task PR merged ⇒ dispatcher picks the next unblocked To-do task on the story and **moves it to In progress itself**, which triggers `/gh-build` through the same contract. Guards: blocker edges from `/gh-plan`, one build per story branch, 3-failure escalation. Highest time-saver, highest risk — validate Phases 1–2 under real PRs first. |
| **3.2** | Spec PR merged ⇒ post-merge job (deploy watch, tier 7, comment on spec issue; human staging sign-off). |

### Phase 4 — Background maintenance + visibility

| # | Item |
| --- | --- |
| **4.1** | `launchd` timers for: dependency/CDK-pin bumps (PR + tiers 1–4), ruff-rule adoption, docs/`AGENTS.md` drift detection, stale-issue triage, nightly tier-7 against staging (local AWS SSO) filing Bug issues on anomalies. **Done** — hybrid probes in `maintenance_checks.py` + daily `maintenance.py run-all` plist; see [phase-4-runbook.md](phase-4-runbook.md). Host still needs SSO + optional `test-tier7-local.sh`. |
| **4.2** | Local memory store so cron runs skip known-good states and avoid duplicate PRs. **Done** — `memory.py` claims/receipts + GitHub marker/open-PR checks. |
| **4.3** | Nightly usage summary from the dispatcher log (runs, durations, failures, per-class counts); optional Admin API enrichment if plan tier allows — never a dependency. **Done** — schema v1 `run_started`/`run_finished` + `usage_summary.py` → `log_dir/summaries/`. |

### Phase 5 — Step 4: steer by intent

| # | Item |
| --- | --- |
| **5.0** | **Shared admission** — `admission.py` + durable `intent_queue` + registry file lock; all spawns (board, maintenance, packs, orchestrator) share concurrency/locks. Per-class models via `spawn.models` (`composer-2.5` for build/resolve; `auto` otherwise). |
| **5.1** | **Local SDK orchestrator** (`orchestrator.py` + `goal_store.py`): `submit --goal` publishes a Spec issue in **To-do** (skip interactive `/gh-spec` review). Human edits, then moves Spec **To-do → In progress** (= approval). Dispatcher runs `goal_approve`, creates User Stories, then fans plan/build/review through the same admission queue/locks. Optional `cursor-sdk` decompose with local fallback (`requirements-auto.txt`). |
| **5.2** | **Domain packs** under `packs/*.json`: CDK migration, IAM sweep, feedback remediation, cost regression (pricing MCP required or setup alert). CLI: `orchestrator.py pack <name>`. |
| **5.3** | **Risk-classified review** (`risk_review.py`): maps PRs to `AGENTS.md` categories; `design_conversation` latches and stops chaining. Machine-checked `contract_signoff` bound to PR `head_sha` before requesting human review. **Resolve PR policy:** each review finding gets its own PR; agents may merge finding Bug/Task PRs only (`merge_policy.py`). Spec / User Story / normal Task PRs stay human-merge only. |
| **5.4** | **Guardrail ladder:** production keeps GitHub environment reviewers; staging QA stays human (medium release tier). Concurrency cap + structural review cycle limits (task 1 / story-spec 2) — **no daily run quotas**. Model map in config. Completion requires observed PR merge (`completion.py`). See [phase-5-runbook.md](phase-5-runbook.md). |

---

## What not to automate

| Step | Reason |
| --- | --- |
| `/gh-spec` interactive review / AC authoring | Orchestrator may **publish** a Spec draft to **To-do**; human must edit and move Spec To-do → In progress before stories fan out |
| `/gh-update-plan` | Judgment-based; parent workflow warns against replanning after every task |
| `/gh-estimate-work` | Optional client workflow; estimates need human context |
| Merge of Spec / User Story / normal Task PRs | Human quality gate by design (§4.d). Exception: agents may merge **review-finding** Bug/Task PRs only |
| Escalations (verify-loop exhaustion, scope explosion, unresolvable conflicts) | Human story/spec owner decision |
| Spec issue close on merge | Medium release tier requires staging validation first (§6) |

---

## Practical constraints

| Constraint | Mitigation |
| --- | --- |
| Host must be online | Always-on machine (Mac mini); `launchd` restarts the poller; "keep awake" for Remote Control |
| Laptop sleep kills the loop | Same — plan for an always-on host before Phase 3–4 |
| Race conditions on branches | Lock keyed on `repo + base_branch`; active-run registry |
| Poller misses event actor | Registry absorbs agent-echoed Status writes; humans only move To-do → In progress |
| Long-running `/gh-build` | Detached subprocess; log to file; poller never blocks on jobs |
| Multi-repo stories | Sibling-repo layout on disk; dispatcher reads manifest paths from the story issue |
| Machine thrash | Concurrency cap 2–3 worktrees to start |
| Bugbot (if left enabled as GitHub App) | Comment-only external signal; fixes still flow through local `/gh-resolve-issues`; never enable Autofix |

---

## Open items

Cross-cutting checklist; roadmap IDs in parentheses where they overlap.

| # | Item |
| --- | --- |
| **O.1** | Dispatcher script + state store under `.cursor/commands/_scripts/auto/` (**1.1**) — **done** (Phase 1) |
| **O.2** | `launchd` plist(s) for poller and Phase-4 timers; document install in README (**1.1**, **4.1**) — **done** (poller/worker + maintenance/summary plists; [phase-4-runbook.md](phase-4-runbook.md)) |
| **O.3** | Amend [workflow-outline.md §5.3](../generic-workflow/workflow-outline.md): board move To-do → In progress is the kickoff signal; agent Status writes become idempotent (**1.4**) — **done** |
| **O.4** | Set up worker-routed spawning: `agent worker start` as a `launchd` service + Cloud Agents API/SDK spawn targeting `env.type: "machine"`; confirm runs appear in the iOS inbox (**1.2**, **1.5**) — code + runbook done; host E2E confirm still manual |
| **O.5** | Poll interval + GraphQL query cost check (stay well inside `gh` rate limits) |
| **O.6** | **Decided** — poller suffices for Phase 3 (merge-triggered chain + post-merge); self-hosted runner deferred. See [phase-3-runbook.md](phase-3-runbook.md). |
| **O.7** | Multi-repo checkout layout convention for story issues spanning repos |

---

## Related files

| Path | Role |
| --- | --- |
| [../generic-workflow/workflow-outline.md](../generic-workflow/workflow-outline.md) | Parent manual workflow; §5.3 Status lifecycle (amendment pending) |
| [../generic-workflow/workflow-alignment-plan.md](../generic-workflow/workflow-alignment-plan.md) | Pipeline alignment with parent outline |
| [phase-1-runbook.md](phase-1-runbook.md) | Phase 1 install + E2E checklist (poller, worker, iOS) |
| [phase-2-runbook.md](phase-2-runbook.md) | Phase 2 story/spec plan + two-cycle review E2E checklist |
| [phase-3-runbook.md](phase-3-runbook.md) | Phase 3 merge-triggered chain + post-merge watch |
| [phase-4-runbook.md](phase-4-runbook.md) | Phase 4 maintenance timers, memory, usage summary |
| [phase-5-runbook.md](phase-5-runbook.md) | Phase 5 orchestrator, packs, risk gate, merge policy |
| `.cursor/auto-workflow.json` | Dispatcher config (local overrides in gitignored `.local.json`) |
| `.cursor/commands/_scripts/auto/` | Poller / dispatcher / maintenance package |
| `.cursor/commands/gh/*.md` | Command procedures embedded verbatim in agent prompts |
| `.cursor/commands/_scripts/gh/*-publish.py` | Mechanical GitHub/git operations agents run (incl. `set-status`) |
| `docs/templates/issues/*.md` | Issue templates (branch names, traceability fields) |
| `AGENTS.md` | Change categories for risk-classified review (Phase 5) |
| `scripts/test-tier*.sh` | Self-verification loop agents run before surfacing work |
