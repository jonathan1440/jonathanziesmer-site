---
name: triage-surface-area-groups
description: >-
  Surface-area grouping (SA1–SA6) and reviewer selection for parallel triage
  subagents. Shared by gh-review and research-issues.
---

# Triage surface-area groups (SA1–SA6)

Use when triaging **≥3 findings** via parallel Task subagents. Group by **surface area**, not severity alone.

## Assign groups

After inventory and scope load, **before** researching findings:

1. Tag each finding with **primary surface** from its `path:line` and summary (contract doc, API layer, domain store, orchestration, infra/CDK, tests/CI, cross-cutting).
2. Cluster into **1–6 groups** by shared surface (same directory prefix, same OpenAPI tag, same plan PR slice, same external system).
3. Label groups **SA1** … **SA6** (use only as many as needed; never more than six parallel subagents).
4. Record a draft **Subagent ownership** table for the output doc:

| SA | Surface / plan slice | Typical paths or components | `subagent_type` |
|----|----------------------|-----------------------------|-----------------|
| SA1 | … | … | … |

## Grouping heuristics (merge/split)

| Signal | Group together |
|--------|----------------|
| Same `src/<package>/` tree or same OpenAPI file | One SA |
| Same PR slice in scope plan (P4 routes, P5 CDK, …) | One SA |
| Same runtime boundary (auth, submit, worker, deploy) | One SA |
| Test-only vs production bug | Prefer **SA for tests** unless finding is purely “prod broken, test would catch” |

| Signal | Split or separate SA |
|--------|----------------------|
| Security/auth vs business logic | Different SA |
| OpenAPI contract vs implementation file | Same SA if same finding; split only when volume forces it |
| >10 findings in one cluster | Split by subdirectory or severity tier |

**Example (finish-photos Phase 2 — adapt per repo):**

| SA | Surface | Typical fix surface |
|----|---------|-------------------|
| SA1 | Contract & auth | OpenAPI, JWT/CORS, error envelope |
| SA2 | Domain & RR client | `race_id`, stores, `race_roster_*` |
| SA3 | Submit orchestration | `pipeline_submit*`, `runners_store` |
| SA4 | HTTP routes & deploy | `src/api/*`, CDK, Docker/CI image |
| SA5 | Tests & docs/CI | `tests/`, workflows, RUNBOOK |
| SA6 | Cross-cutting | Worker/phase alignment, staging gates |

## Parallel subagents

**Required when ≥3 findings.** Optional for 1–2 findings (parent may research inline).

Launch **one Task per SA group** in a **single parent turn** (`readonly: true`, `run_in_background: false` unless user is in multitask mode). Cap: **6** concurrent tasks.

**Reviewer pick (`subagent_type`):**

| Dominant surface | Prefer |
|------------------|--------|
| Auth, HTTP clients, API errors | `python-reviewer` or `code-reviewer` |
| Security, secrets, SSRF, authz | `security-reviewer` |
| Tests, assertions, CI gaps | `test-review-agent` |
| SQL, migrations, DynamoDB query design | `database-reviewer` |
| TypeScript/React UI | `typescript-reviewer` |
| Mixed / unclear | `code-reviewer` |

**Parent responsibilities after subagents return:**

1. Spot-check any high-confidence or disputed dispositions against code.
2. Resolve conflicts when two SAs touched the same root cause — one ID, one disposition.
3. Ensure every input finding appears exactly once in the merged set.

For **every** finding (whether subagent or parent researched):

1. **Read the code** at cited paths (and tests). Do not rely on review memory alone.
2. **Verify disputed facts** with commands when cheap — cite command output in the write-up.
3. **Quote plan/spec** only when the finding claims a contract mismatch.
4. **Assign Owner** = SA label from the group that researched it.

## Anti-patterns

- Researching ≥3 findings serially in the parent instead of SA-grouped parallel Tasks
- Launching more than six subagents or one subagent per finding (defeats merge/routing)
- Grouping by severity only (CRITICAL batch, HIGH batch) instead of **surface area**
- Omitting **Owner** / **Subagent ownership** so fix commands cannot parallelize by SA
