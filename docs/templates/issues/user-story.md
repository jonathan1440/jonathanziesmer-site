---
name: User Story
about: User story sub-issue with acceptance scenarios created by /gh-spec
title: "<story title>"
labels: []
---
## User story

As a <role>, I want <goal>, so that <benefit>.

## Repositories touched

| Repository | Role |
|------------|------|
| `owner/repo` | — |

_Story issue home repo: `owner/repo` (this issue). Implementation may span the repositories above._

## Acceptance scenarios

### AC-01 — <scenario name>
- **Given** <precondition>
- **When** <action>
- **Then** <expected outcome>

## Links

- Parent spec: #N
- Spec file: `docs/specs/<feature-slug>/SPEC.md`

## Development branches

Create each branch in every repository listed (same branch name). Link to this issue via `gh issue develop` in `owner/repo` only.

| Repository | Branch | Issue link |
|------------|--------|------------|
| `owner/repo` | `user-story/US-XX-<story-slug>` | Yes |
