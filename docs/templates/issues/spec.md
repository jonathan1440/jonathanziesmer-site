---
name: Spec
about: Parent spec tracking issue created by /gh-spec
title: "<feature title>"
labels: []
---
## Spec artifact

`docs/specs/<feature-slug>/SPEC.md` on branch `spec/<feature-slug>`

Manifest: `docs/specs/<feature-slug>/gh-spec.manifest.json`

## Affected repositories

| Repository | Role |
|------------|------|
| `owner/repo` | — |

## Development branches

Create each branch in every repository listed (same branch name). Link to this issue via `gh issue develop` in `owner/repo` only.

| Repository | Branch | Issue link |
|------------|--------|------------|
| `owner/repo` | `spec/<feature-slug>` | Yes |

## Objective

<!-- One-paragraph summary from SPEC.md Objective section -->

## Status

- [x] Stories approved
- [x] Acceptance criteria approved
- [x] Technical spec approved
- [ ] Tasks published (`/gh-plan` per story)

## Story index

| Story | Issue | Repositories | AC IDs |
|-------|-------|--------------|--------|
| US-01 | #TBD | `owner/repo` | AC-01 |

## Traceability

- **Canonical AC:** story sub-issues below (not duplicated in `SPEC.md`).
- **Work units:** `/gh-plan` per story creates task sub-issues (scope, tests, blockers).

_Parent issue #N_
