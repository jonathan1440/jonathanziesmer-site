# Procedures index

Split into **pipeline** (GitHub SDLC orchestration) and **lib** (reusable discipline loaded by entrances and pipeline steps).

## Pipeline (`pipeline/`)

| File | Loaded by | ~lines |
| --- | --- | --- |
| gh-spec-driven-development.md | /gh-spec | 200 |
| gh-spec-github-procedure.md | /gh-spec (publish) | 301 |
| spec-story-ac-procedure.md | /gh-spec | 150 |
| spec-story-ac-prompts.md | spec-story-ac-procedure | 80 |
| gh-plan-procedure.md | /gh-plan | 234 |
| gh-plan-research-procedure.md | /gh-plan, gh-plan-update | 122 |
| gh-plan-update-procedure.md | /gh-update-plan | 110 |
| gh-update-plan-github-procedure.md | /gh-update-plan | 108 |
| planning-shared.md | /gh-plan, /gh-update-plan | 60 |
| branch-sync-procedure.md | gh-plan, gh-update-plan | 80 |
| gh-estimate-work-procedure.md | /gh-estimate-work | 100 |
| gh-build-github-procedure.md | /gh-build | 284 |
| gh-review-procedure.md | /gh-review | 170 |
| gh-review-github-procedure.md | /gh-review | 211 |
| gh-review-review-synthesis.md | /gh-review | 50 |
| gh-review-triage-rules.md | /gh-review | 80 |
| gh-review-rr-ids.md | /gh-review | 60 |
| gh-review-triage-doc.md | /gh-review | 70 |
| triage-surface-area-groups.md | gh-review, research-issues | 90 |
| research-issues-procedure.md | /research-issues | 137 |
| gh-resolve-issues-github-procedure.md | /gh-resolve-issues | 330 |
| gh-resolve-parallel-subagents.md | /gh-resolve-issues | 69 |

## Library (`lib/`)

| File | Typical loader |
| --- | --- |
| plan.md | /plan, gh-spec |
| build.md | /build, gh-build |
| build-discipline.md | gh-build, build |
| bug-fix-discipline.md | gh-resolve-issues, gh-build (prove_it) |
| plan-minimal-change.md | gh-plan, gh-update-plan |
| edge-cases.md | gh-spec |
| review.md | /review |
| code-review-and-quality.md | review |
| consider-reviewing.md | review, gh-review |
| test-driven-development.md | build, gh-build |
| debugging-and-error-recovery.md | build, gh-build, gh-resolve |
| code-simplification.md | gh-build |
| browser-testing-with-devtools.md | gh-build |
| security-and-hardening.md | review |
| performance-optimization.md | review |
| incremental-implementation.md | build |
| shipping-and-launch.md | reference |
| dispatching-parallel-agents.md | gh-resolve-issues |
