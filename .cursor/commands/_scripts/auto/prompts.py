"""Prompt templates handed to spawned Cursor agents, keyed by dispatch kind."""

from __future__ import annotations

from typing import Any

BUILD_PROMPT = """Run /gh-build on task issue {url} ({issue}).
Follow .cursor/commands/gh/gh-build.md exactly, including the worktree/verify-loop
guardrails. Stop after 3 verify-loop iterations on the same failure class and
escalate instead of retrying further. Do not merge the resulting PR."""

REVIEW_RESOLVE_PROMPT = """Run /gh-review on task issue {url} ({issue}).
Follow .cursor/commands/gh/gh-review.md exactly. Include structured
contract_signoff {{verdict, head_sha, reviewed_at}} and risk_class on the
publish payload. If risk_class is design_conversation, stop and escalate —
do not chain resolve. If the review finds CONFIRM issues, run
/gh-resolve-issues afterward with per-finding PRs (agent may merge finding
PRs only). Do not merge the parent Task PR. Request human review only when
SIGN-OFF head_sha matches the live PR head."""

REVIEW_RESOLVE_2CYCLE_PROMPT = """Run a two-cycle review on {url} ({issue}).
Follow .cursor/commands/gh/gh-review.md, then .cursor/commands/gh/gh-resolve-issues.md
on any findings (per-finding PRs; agent may merge finding PRs only), then
/gh-review again on the new findings only. Persist contract_signoff bound to
the final PR head SHA and risk_class. If design_conversation, hard-stop.
Finish by requesting a human reviewer only after SIGN-OFF@head_sha is valid.
Do not merge the parent Spec/Story PR."""

PLAN_PROMPT = """Run /gh-plan on User Story {url} ({issue}).
Follow .cursor/commands/gh/gh-plan.md exactly to decompose the story into Task
sub-issues with blocker edges. Do not start any Task builds yourself."""

POST_MERGE_PROMPT = """The Spec PR for {url} ({issue}) merged to main via PR #{pr}.
1. Watch the deploy workflow on main: `gh run list --workflow deploy.yml --branch main --limit 1`
   then `gh run watch <run-id>` until it completes.
2. Comment on the Spec issue with the Actions run URL for that deploy.
3. Run `bash scripts/test-tier7-monitor.sh` against staging. Exit code 2 means
   SKIP (no monitoring configured) and is fine. On failure, file a Bug issue
   with the failure details and recommend a rollback in your comment.
4. Never close the Spec issue and never merge anything. This is a medium
   release tier: staging validation still needs a human QA or manual sign-off
   before the Spec issue can be closed."""

GOAL_APPROVE_PROMPT = """Phase 5 goal approval for Spec {url} ({issue}).

The Spec moved To-do → In progress (human approval). Run the mechanical story
fan-out if not already done:

  python3 .cursor/commands/_scripts/auto/orchestrator.py approve --spec-issue {issue}

Then ensure each created User Story is on the Project board in To-do. Do not
start builds yourself unless a story already has Task sub-issues and a human
(or chain) moved a Task to In progress. Do not merge any PRs."""

RESOLVE_PROMPT = """Run /gh-resolve-issues on {url} ({issue}).
Follow .cursor/commands/gh/gh-resolve-issues.md. For each review-generated Bug
or Task finding, open its own PR and merge that finding PR after gates pass.
Never merge the parent Spec, User Story, or normal Task PR."""

RISK_CLASSIFY_PROMPT = """Classify the open PR linked to {url} ({issue}) against
AGENTS.md change categories. Return structured JSON only:
{{"category":"normal"|"design_conversation","evidence":[...],"agents_md_refs":[...]}}.
When uncertain, choose design_conversation. Do not merge."""

DOMAIN_PACK_PROMPT = """Phase 5 domain pack: {pack_name}

Repo: {repo}
Marker (must appear in PR/issue body): {marker}
Instructions:
{instructions}

Rules:
1. Follow the instructions above.
2. Never merge Spec, User Story, or normal Task PRs.
3. Review-generated Bug/Task finding PRs may be merged after gates.
4. If nothing to do, exit without opening a duplicate PR.
5. Include the marker string in any PR or issue body you create."""

MAINTENANCE_DEPS_PROMPT = """Phase 4 maintenance job: dependency / CDK-pin bump.

Repo: {repo}
Bumps (from → to): {bumps_json}
Marker (must appear in PR body): {marker}

Rules:
1. Raise existing minimum-version floors in requirements-*.txt for the listed
   packages. Do NOT introduce a lockfile. Do NOT change GitHub Action SHAs.
2. If aws-cdk is listed, update the CDK CLI pin atomically in
   .github/workflows/ci.yml, .github/workflows/deploy.yml, docs/DEPLOYMENT.md,
   and AGENTS.md (same version string everywhere).
3. Open ONE PR on branch chore/auto-deps-<YYYYMMDD>. Include the marker in the
   PR body. Never merge the PR.
4. Run `bash scripts/test-tiers.sh 4` and fix failures before opening the PR.
5. If nothing needs changing after inspection, exit without a PR."""

MAINTENANCE_RUFF_PROMPT = """Phase 4 maintenance job: ruff rule adoption.

Repo: {repo}
Candidate opportunities: {opportunities_json}
Marker (must appear in PR body): {marker}

Rules:
1. Pick at most ONE rule family/rule to adopt this run.
2. Prefer zero-noise clean rules, or rules safely fixed with `ruff check --fix`.
3. Update pyproject.toml select list; open ONE PR on branch
   chore/auto-ruff-<rule>-<YYYYMMDD>. Include the marker in the PR body.
4. Run `bash scripts/test-tiers.sh 4` before opening the PR. Never merge.
5. If no rule is safe to adopt, exit without a PR."""

MAINTENANCE_DOCS_PROMPT = """Phase 4 maintenance job: AGENTS.md / docs drift detection.

Repo: {repo}
Current hash: {agents_hash}
Previous checkpoint: {checkpoint_hash}
Marker (must appear in Task body or comment): {marker}

Rules:
1. Detection ONLY. Do NOT rewrite AGENTS.md or CLAUDE.md yourself.
2. Diff the contract against recent main changes and summarize drift.
3. File or update ONE native Task issue (not a Bug) titled
   "AGENTS.md drift detected" whose body contains the marker. Comment with
   suggested edits for a human to apply via /write-agents-contract.
4. Never open a PR that edits AGENTS.md. Never merge anything."""

MAINTENANCE_STALE_PROMPT = """Phase 4 maintenance job: stale-issue triage.

Repo / project: {repo}
Stale threshold (days): {stale_days}
Candidates JSON: {candidates_json}
Marker for comments: {marker}

Rules:
1. For each candidate, add ONE triage comment containing the marker if no such
   comment already exists on that issue. Suggest next action (close, unblock,
   re-prioritize). Mention the escalate owner if configured: {escalate_owner}.
2. NEVER close issues. NEVER move Project Status cards based on age alone.
3. Skip issues that are Ready to ship, closed, blocked, or have an active
   dispatcher job.
4. Do not create review Bug findings; comments only."""

MAINTENANCE_TIER7_SETUP_PROMPT = """Phase 4 maintenance job: staging tier-7 setup alert.

Repo: {repo}
Reason: {reason}
Details: {details_json}
Marker (must appear in issue body): {marker}

Rules:
1. File or update ONE native Task issue titled
   "Auto-workflow tier-7 staging setup gap" whose body contains the marker.
2. Explain that either AWS SSO is expired/missing or
   scripts/test-tier7-local.sh is absent (exit 2 SKIP).
3. Do NOT file an infrastructure Bug. Do NOT invent AWS account IDs or
   credentials. Never merge anything."""

MAINTENANCE_TIER7_ANOMALY_PROMPT = """Phase 4 maintenance job: staging tier-7 anomaly.

Repo: {repo}
AWS profile: {profile}
Exit code: {exit_code}
Stdout/stderr excerpt in details: {details_json}
Marker (must appear in Bug body): {marker}

Rules:
1. File or update ONE native Bug issue (issue type Bug, never a `bug` label)
   whose body contains the marker and the anomaly fingerprint context.
2. Include profile, timestamp, exit code, and failure excerpt.
3. Do NOT auto-rollback. Do NOT close Spec issues. Never merge anything.
4. If a Bug with this marker already exists, comment with the new occurrence
   instead of opening a duplicate."""


def build_prompt(kind: str, transition: dict[str, Any]) -> str:
    """Render the prompt template for `kind` using fields from `transition`."""
    fields = {
        "issue": transition.get("issue", ""),
        "url": transition.get("url", ""),
        "number": transition.get("number", ""),
        "repo": transition.get("repo", ""),
        "title": transition.get("title", ""),
        "parent_number": transition.get("parent_number", ""),
        "pr": transition.get("pr", ""),
        "bumps_json": transition.get("bumps_json", "{}"),
        "opportunities_json": transition.get("opportunities_json", "[]"),
        "candidates_json": transition.get("candidates_json", "[]"),
        "details_json": transition.get("details_json", "{}"),
        "marker": transition.get("marker", ""),
        "agents_hash": transition.get("agents_hash", ""),
        "checkpoint_hash": transition.get("checkpoint_hash", ""),
        "stale_days": transition.get("stale_days", ""),
        "escalate_owner": transition.get("escalate_owner", ""),
        "reason": transition.get("reason", ""),
        "profile": transition.get("profile", ""),
        "exit_code": transition.get("exit_code", ""),
    }
    templates = {
        "build": BUILD_PROMPT,
        "review_resolve": REVIEW_RESOLVE_PROMPT,
        "plan": PLAN_PROMPT,
        "review_resolve_2cycle": REVIEW_RESOLVE_2CYCLE_PROMPT,
        "post_merge": POST_MERGE_PROMPT,
        "goal_approve": GOAL_APPROVE_PROMPT,
        "resolve": RESOLVE_PROMPT,
        "risk_classify": RISK_CLASSIFY_PROMPT,
        "maintenance_deps_bump": MAINTENANCE_DEPS_PROMPT,
        "maintenance_ruff_rules": MAINTENANCE_RUFF_PROMPT,
        "maintenance_docs_drift": MAINTENANCE_DOCS_PROMPT,
        "maintenance_stale_triage": MAINTENANCE_STALE_PROMPT,
        "maintenance_tier7_setup": MAINTENANCE_TIER7_SETUP_PROMPT,
        "maintenance_tier7_anomaly": MAINTENANCE_TIER7_ANOMALY_PROMPT,
        "domain_cdk_migration": DOMAIN_PACK_PROMPT,
        "domain_iam_security_sweep": DOMAIN_PACK_PROMPT,
        "domain_feedback_remediation": DOMAIN_PACK_PROMPT,
        "domain_cost_regression": DOMAIN_PACK_PROMPT,
    }
    # Allow prompt_class aliases used as job.kind for maintenance.
    if kind in templates:
        fields = {
            **fields,
            "pack_name": transition.get("pack_name") or transition.get("pack") or kind,
            "instructions": transition.get("instructions", ""),
        }
        return templates[kind].format(**fields)
    raise ValueError(f"unknown dispatch kind: {kind!r}")
