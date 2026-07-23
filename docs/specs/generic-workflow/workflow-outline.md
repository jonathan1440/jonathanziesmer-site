# Generic workflow

An agent-driven SDLC pipeline: spec → plan → build → review → merge → deploy, tracked in
GitHub and scored by an automated testing harness. The only human checkpoints are running
the commands and the PR review gate; everything in between is agent-owned.

---

## 1. Components (the nouns)

Listed outer to inner.

1. **GitHub Organization** — holds repositories and projects.
2. **GitHub repository(s)** — tracks and stores the code.
3. **GitHub Project** — tracks and organizes the issues involved with the workflow (usually a
   planning project, as opposed to a work project).
4. **GitHub issues** — track, organize, and relate units of work (spec → user story → task →
   bug). Always reference, and often summarize, the relevant docs.
5. **Git branches** — keep development processes separate to avoid conflicts and race
   conditions. Nested off `main`: spec → user-story → task.
6. **Docs** — the ultimate sources of truth for specs and user stories (`docs/specs/`,
   `docs/user-stories/`). Issues point at them; they outlive any single issue.
7. **Commands** — instructions to the AI agent, named `gh-*`, that drive each phase.
8. **Testing harness** — a set of agent-invokable test tiers (`scripts/test-tier*.sh`) that
   score correctness end-to-end. The agent runs them; humans build and maintain them. See
   §3.

---

## 2. Roles

- **Human** — runs the `gh-*` commands, makes spec/story decisions during `/gh-spec`, and is
  the PR review gate before each merge. The human never triggers a test tier mid-loop and
  never triages findings by hand.
- **Agent** — owns everything between commands: writing tests and code, running the harness
  loop, triaging findings into issues, resolving them, opening PRs, and moving board status.
  When the agent cannot make progress it escalates by @-mentioning the owner on the issue
  (see §5.3), rather than silently guessing.

---

## 3. Testing harness (the reward function)

The harness is the reward function the agent hill-climbs against. Every tier is something the
agent invokes itself, runs only after the previous tier passes, and reads the output of with
no human in the room. Two questions drive the design: (1) what does "correct" mean
holistically (unit → integration → product-surface → contract alignment)? (2) when something
is not correct, does the agent get enough signal — stack traces, judge-subagent notes, logs,
screenshots — to climb toward a fix? A tier that passes but hands a failing agent nothing to
act on is a bad tier.

### The seven tiers (run in order, stop at the first failure)

1. **Lint and type** — cheapest signal, run first. `ruff check` + type checks. Fail fast
   before spending tokens downstream.
2. **Unit tests** — logic-level correctness on isolated functions. `pytest` (for this CDK
   repo, the synth assertions in `tests/unit/`).
3. **Security and compliance** — secrets, dependency CVEs, IAM/policy checks. For the CDK
   stack: `cdk-nag`, dependency audit, secret scanning.
4. **Single-service integration** — the service under test runs for real, everything external
   mocked/shimmed. `cdk synth` plus LocalStack or a per-branch ephemeral stack.
5. **Multi-service integration** — real services talking to real services on shared staging.
6. **Product-surface** — drive the actual UI/endpoints against a deployed preview (e.g.
   Playwright). Catches "the code works but the feature doesn't." Skip or adapt for pure-infra
   stacks with no surface (the current `SampleStack` skeleton).
7. **Rollout monitoring** — post-merge, post-deploy. Verify staging/production logs and
   metrics against an expected set. The only tier that runs after the human review gate (see
   §4.6).

### Which tiers run at which level

Tiers cost more and need more real infrastructure as the numbers climb, so they are gated by
scope, not run wholesale everywhere:

| Level | Tiers | Where |
| --- | --- | --- |
| **Task** (`/gh-build`, task-level `/gh-review`) | 1–4 | Isolated task branch; a task's acceptance criteria may pull in specific tier 5–6 cases, but 5–6 are not run wholesale per task. |
| **Story / spec** (story- and spec-level `/gh-review`) | 1–6 | Integrated branch with a real deployed preview, where multi-service and product-surface checks are meaningful. |
| **Post-merge** (deploy) | 7 | Real staging/production traffic (see §4.6). |

Tiers 1–6 are fully agent-driven and pre-merge. Tier 7 runs post-merge because it needs real
deploy traffic.

**Wiring:** each tier is a CLI command or MCP tool the agent can call —
`scripts/test-tier1-lint.sh` … `scripts/test-tier6-product.sh`. The agent runs them in order
and stops at the first failure, reading stderr/stack traces to decide its next move.

### Three rules

- **Don't human-gate any tier.** The only human checkpoint is PR review (§4.4.d), never
  mid-loop. A human-triggered test deploy collapses the autonomous cycle.
- **Don't make tests too rigid.** The agent may determine the tier-6 test plan and revise it
  during the loop; hardcoded scripts it cannot modify defeat the purpose.
- **`scripts/` is a verification dumping ground.** The agent dumps throwaway verification
  scripts there, retires them when they stop being useful, and writes new ones — curated by
  the agent, not by hand. (`scripts/github-setup/` stays the home for one-off repo-config
  scripts.)

### Two techniques

- **Testing agent as customer.** A judge subagent evaluates the product surface against the
  project's audience ("would this delight the target user?"), catching a class of problems
  unit tests never will. Wire it in as a `/gh-review` subagent (§4.4).
- **Shared test environment with respawn** (deferred — enterprise technique). Under
  concurrent-ticket load, give agents a shared staging plus the ability to respawn a specific
  service from a prior Git SHA and reroute their own test traffic to it, rebuilding only the
  broken dependency. Premature solo; reach for it only when many tickets run the loop at once.
  This repo is a template, so it stays deferred.

### Exit criterion

With zero humans in the loop, an agent can tell you whether a given PR breaks service
functionality. When tiers 1–6 pass and a contract-review subagent signs off (spec/story
acceptance criteria + the `AGENTS.md` architectural contract), you should have high confidence
the workflow produced a high-quality, compliant change. That confidence is the deliverable.

---

## 4. The workflow

### 4.1 Create a spec

a. User runs `/gh-spec`, specifying a GitHub repo and a GitHub project.
   1. Creates an empty GH Spec issue from a GH issue template.
   2. Creates a new git branch off `main` and links it to the GH issue.
   3. Creates a new directory under `docs/specs/` using a user-provided slug based on the spec
      name/purpose.
   4. Copies `spec.md.template` into the new `<spec-slug>/` directory.
   5. Works with the user to flesh out the spec, filling out the template as they go.
   6. Works with the user to define user stories (this can involve adopting or updating user
      stories already created for previous specs in the same project).
   7. Creates all user-story branches upfront (off the spec branch) to enable parallel
      planning.
   8. Copies `user-story.md.template` into `docs/user-stories/` and fills it out for each
      story.
   9. Creates user-story issues from the user-story issue template for each story.
   10. Links each user-story issue to its unique branch (from step 7) and as a sub-issue of the
       parent spec issue.
   11. Works with the user to define **acceptance criteria** for each user story, recorded in
       the user-story docs. Acceptance criteria are core to `/gh-spec`, not optional or
       deferred.
       - **Spec acceptance criteria** are the union of the acceptance criteria of all
         associated user stories — they are not authored separately.
b. **Optionally** run `/gh-estimate-work`, which sets developer-hour estimates on each user
   story and the spec issue. Needed when quoting work for a client.

### 4.2 Create a plan

a. User runs `/gh-plan`, specifying a user-story issue.
   1. Breaks the user story down into specific tasks.
   2. Stores each task in a GitHub task issue, created from the task issue template.
      - **Task acceptance criteria** are pointers to the acceptance criteria on the task's
        parent user story — a task does not define its own; it references the slice of the
        story's criteria it satisfies.
   3. Associates each task issue with a unique git branch, off the parent user-story branch.
   4. Links each task issue as a sub-issue of the parent user-story issue.
   5. **Parallelization:** multiple `/gh-plan` invocations can run in parallel on independent
      user stories (branches already exist from `/gh-spec`). This significantly reduces
      planning time for specs with many stories.
   6. **Task dependencies:** design tasks to be independent by default. If task B must wait for
      task A, link task B as "is blocked by" task A in GitHub (direct-only — if A blocks B and
      B blocks C, attach B→C only, not A→C). Limit external blockers to 3 per task and record
      the reason. Tasks without an explicit "is blocked by" link are assumed unblocked and can
      proceed in parallel.
b. **Optionally** the user runs `/gh-update-plan`, only when planning is significantly out of
   sync with reality:
        - A task estimated at 2 hours reveals >4 hours of work during implementation.
        - Completed tasks reveal shared dependencies that weren't obvious during planning.
        - Acceptance criteria for the story have changed since planning.
        - Do NOT replan after each task. The original plan is usually good enough; replanning after
     every task is analysis paralysis.
        - Document the drift reason when running `/gh-update-plan` so future plans benefit from the
     learning.

### 4.3 Implement

a. User runs `/gh-build`, specifying a task issue.
   1. Checks that the branch is up to date and merges in the parent user-story branch if
      necessary (see §5.1 for conflict handling).
   2. First writes/extends tests for the task's edge cases — primarily tier 2 (unit), plus any
      tier 3–4 coverage the acceptance criteria demand (see §3).
   3. Then implements the task.
   4. Then simplifies the code written.
   5. Then runs the harness — **tiers 1–4** in order, stopping at the first failure and reading
      its output — and iterates until every tier passes. The agent owns this loop end-to-end;
      no human triggers a tier. (Tiers 5–6 are exercised at story/spec review, §4.4.)
   6. **Error handling:** if a tier keeps failing after 3 verify iterations on the same failure
      class, escalate (see §5.3).
   7. Finally, opens a PR to merge into the parent user-story branch and links the PR to the
      task issue.
   8. **Merge strategy:** squash-merge for task PRs (see §5.2).

### 4.4 Review

a. User runs `/gh-review`, specifying an issue.
   1. Selects relevant subagents from a list of options to review the PR attached to the issue.
   2. Uses subagents to research and triage the issues it found.
   3. If a finding is legit, files it into a new GitHub bug or task issue from the appropriate
      template.
   4. Links the bug/task issues as sub-issues of the reviewed issue.
   5. **Severity gating:** only bugs marked "Critical" or "Blocker" prevent merge. "Major" and
      below become follow-up issues.
   6. **Harness re-run + judge:** `/gh-review` re-runs the tiers scoped to the review level
      (task: 1–4; story/spec: 1–6) and, for story/spec-level reviews, drives the tier-6 product
      surface with a "testing agent as customer" judge subagent ("would this delight the target
      user?"). Failures become bug/task sub-issues like any other finding.
   7. **Contract sign-off (exit criterion):** a contract-review subagent verifies the change
      against the spec/story acceptance criteria and the `AGENTS.md` architectural contract.
      Tiers passing + contract sign-off is the bar for high-confidence merge.
b. User runs `/gh-resolve-issues`, specifying an issue.
   1. Uses subagents to resolve the bug and task issues linked as sub-issues under the input
      issue.
   2. The subagents follow the same procedure as `/gh-build`.
c. **Review iteration cycle:**
   1. **Task-level reviews** (lower risk, single developer): run 1 cycle of `/gh-review` +
      `/gh-resolve-issues`.
   2. **Story-level and spec-level reviews** (higher integration risk): run 2 cycles:
      - Cycle 1: `/gh-review` + `/gh-resolve-issues` on all bugs/tasks found.
      - Cycle 2: `/gh-review` again (to catch regressions from fixes) + `/gh-resolve-issues` on
        new bugs found.
   3. After the final cycle, only Critical/Blocker issues block merge. Others become follow-up
      issues.
   4. If new issues are found after the review cycles, do NOT restart — use `/gh-update-plan` or
      escalate to the parent level.
d. **Manual review and merge:**
   1. After `/gh-resolve-issues` is complete, the PR is ready for human review.
   2. If reviewer feedback is minor (typos, small refactors, comments), the developer makes
      manual changes and re-requests review.
   3. If feedback requires substantial changes (new logic, architectural rework), create a new
      task/bug issue and loop back through `/gh-build` + `/gh-review`.
   4. Allow up to 2 re-request cycles before escalating to the story/spec owner.
   5. After human approval, merge using the level-appropriate strategy (§5.2).

### 4.5 Promote (open the next-level PR)

The next-level PR opens automatically once its children are all merged/closed — this is the
same trigger that moves the parent to **Review / QA** status (§5.4):

a. **Story PR** (story branch → spec branch) opens once **all task sub-issues of the story are
   closed**.
b. **Spec PR** (spec branch → `main`) opens once **all user-story sub-issues of the spec are
   closed**.

Each promoted PR is reviewed with the story/spec-level review cycle (§4.4.c.2) before its
manual merge.

### 4.6 Post-merge and deployment

> **Note:** the deploy story is not fully designed yet. What follows is the intended shape;
> treat the specifics as provisional (TODO: flesh out once deploy is designed).

This is **tier 7 (rollout monitoring)** — the only tier that runs after the human review gate.
Each risk level verifies staging/production logs and metrics against an expected set; the agent
reads that signal, a human only signs off.

a. After a spec PR merges to `main`, by project risk level (aligns with the release tier in
   `AGENTS.md`):
   1. **Low-risk (internal tools):** `main` is always releasable; work is "done" when CI
      passes.
   2. **Medium-risk:** require manual validation in staging (e.g. QA sign-off) before marking
      shipped.
   3. **High-risk (production services):** require staged rollout (canary, A/B, or gradual)
      before full release.
b. If tier 7 fails post-deploy, roll back rather than fix-forward — the per-level merge
   strategy (§5.2) is chosen partly to make reverts clean — and file the regression as a bug
   sub-issue on the spec.
c. Run `/write-agents-contract` (diff mode: `main~1...main`) to update `AGENTS.md` with any new
   architectural decisions, boundaries, or principles that emerged. Skip if the diff is
   implementation-only and crosses no new architectural boundaries.
d. Close the spec issue only after deployment is confirmed.
e. Link the deployment/release to the spec issue so there's a paper trail from code to
   shipping.

---

## 5. Cross-cutting rules

### 5.1 Branching and merge conflicts

- Branches nest: task off story, story off spec, spec off `main`. Parallel task branches off a
  shared story branch **will** diverge, so each `/gh-build` re-merges the parent branch before
  it starts (§4.3.a.1) and again before opening its PR.
- The agent resolves merge conflicts as part of the build loop; a resolved conflict must
  re-pass the scoped tiers. If the agent cannot resolve a conflict cleanly after 3 attempts, it
  escalates (§5.3) rather than forcing a resolution.
- **Delete every branch on merge** — task branch on task-PR merge, story branch on story-PR
  merge, spec branch on spec-PR merge. No branch outlives the PR that consumed it.

### 5.2 Merge strategy (by level)

| PR | Direction | Strategy | Why |
| --- | --- | --- | --- |
| Task | task → story | **Squash merge** | Keeps story history clean; task-level noise hidden; easy single-task revert. |
| Story | story → spec | **Regular merge** (preserve commits) | Preserves task grouping in spec history; shows which tasks went into each story. |
| Spec | spec → `main` | **Squash merge** | Keeps `main` minimal; easy whole-spec revert; easier release management and rollback. |

### 5.3 Board status lifecycle

Status is set via the GitHub Projects API (GraphQL `updateProjectV2ItemFieldValue`); the field
must be named "Status" and option values must match exactly. `gh-build-publish.py set-status`
allows manual override (`in-progress | review-qa | todo | ready-to-ship`). When the item already
has the requested Status, `set-status` is an **idempotent no-op** (`noop: true`).

**Kickoff inversion (auto-workflow):** Under
[auto-workflow/outline.md](../auto-workflow/outline.md), a **board move causes the build**. A
human (or Phase-3 dispatcher) moves a Task **To-do → In progress**; the local poller starts
`/gh-build`. The agent no longer needs to set In progress at build start (it is already there).
All *forward* moves remain agent-owned: → **Review / QA** when the PR opens, → **Ready to ship**
after resolve. Derived story/spec **In progress** states (set when children build) are ignored by
the dispatcher — only “story In progress with zero task sub-issues” triggers `/gh-plan` (Phase 2).

**Task issues:**

| Status | Set when |
| --- | --- |
| **To-do** | Issue created (by `/gh-spec`, `/gh-plan`, or `/gh-review`). |
| **In progress** | **Kickoff:** human (or Phase-3 dispatcher) moves the card — this starts `/gh-build`. Agent `set-status in-progress` at prepare is idempotent if already set. Also used at the start of `/gh-resolve-issues` when the agent begins work. |
| **Review / QA** | End of `/gh-build`, when the PR is opened; the state `/gh-review` runs against. |
| **Ready to ship** | End of `/gh-resolve-issues`, when all bug sub-issues are closed and the PR is updated. |

**User-story and spec issues** (same lifecycle, driven by their children):

| Status | Set when |
| --- | --- |
| **To-do** | Issue created by `/gh-spec`. |
| **In progress** | `/gh-build` runs on **any** sub-issue. |
| **Review / QA** | **All** sub-issues are closed (this is the same trigger that opens the next-level PR, §4.5). |
| **Ready to ship** | After the last `/gh-resolve-issues` run at this level. |

### 5.4 Error handling and escalation

Escalation means @-mentioning the story/spec owner on the issue and filing a new task/bug
issue that captures the blocker before handing off.

a. **Test failures during `/gh-build`:** if tiers keep failing after 3 verify iterations on the
   same failure class, escalate and stop.
b. **Critical bugs during `/gh-review`** (security, data loss, crashes): escalate; file a new
   task issue; do NOT merge until fixed.
c. **Major bugs during `/gh-review`** (performance, UX): file a follow-up bug issue. Task PRs
   may merge if impact is minor; story/spec PRs should resolve before merge.
d. **Minor issues during `/gh-review`** (style, naming, comments): add to follow-up issues.
   Don't block merge.
e. **Task scope explosion** (single task balloons past 2× the original estimate or blocks
   multiple other tasks): escalate to the story owner for a re-planning decision.

---

## 6. Worked example

```
User:
1.  /gh-spec on a new spec → creates 3 user stories + 3 story branches (all upfront)
2.  (Parallel) /gh-plan on user stories 1, 2, 3 — or sequentially if preferred
3.  /gh-build on task 1 (from story 1)
4.  /gh-review on task 1 (1 review cycle for task-level)
5.  /gh-resolve-issues on bugs found in task 1 → task issue moves to Ready to ship
6.  Manual review of PR, approve, squash-merge into story 1 branch (branch deleted)
7.  <repeat 3–6 for remaining tasks on story 1>
8.  All story-1 task sub-issues closed → story-1 PR opens automatically (story → Review/QA)
9.  /gh-review on story 1 PR (cycle 1)
10. /gh-resolve-issues on bugs found in story 1
11. /gh-review on story 1 PR again (cycle 2 — catches regressions from fixes)
12. /gh-resolve-issues on any new bugs found in cycle 2 → story moves to Ready to ship
13. Manual review of PR, approve, regular-merge into spec branch (branch deleted)
14. <repeat 3–13 for story 2, story 3, …>
15. All story sub-issues closed → spec PR opens automatically (spec → Review/QA)
16. /gh-review on spec PR (cycle 1)
17. /gh-resolve-issues on bugs found in spec
18. /gh-review on spec PR again (cycle 2)
19. /gh-resolve-issues on any new bugs found in cycle 2 → spec moves to Ready to ship
20. Manual review of PR, approve, squash-merge into main (branch deleted)
21. /write-agents-contract --diff main~1...main (update AGENTS.md; skip if no contract changes)
22. Verify deployment (per project risk level) and close the spec issue
```
