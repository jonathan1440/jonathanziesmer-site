---
name: gh-review-triage-doc
description: >-
  Markdown triage artifact structure for gh-review with CONFIRM/TRACK/DISMISS
  substitutions.
---

# gh-review triage document

## Scaffold (script)

After `context`, scaffold the file:

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py init-triage-doc \
  --context /tmp/gh-review-context.json \
  --result-json /tmp/gh-review-triage-init.json
```

Uses templates under `.cursor/commands/_templates/gh-review/`:

| Template | Purpose |
|----------|---------|
| [gh-review-triage.md.template](../../../../../docs/paperwork/gh-review-triage.md.template) | Full doc skeleton |
| [finding-section.md.template](../../../_templates/gh-review/finding-section.md.template) | Per-finding subsection |
| [disposition-legend.md](../../../_templates/gh-review/disposition-legend.md) | Legend block |

Default path (when `--output` omitted): `docs/paperwork/<feature>/gh-review-<issue#>-<slug>.md` — same rule as `init-payload` `triage_path`.

Use `--force` to overwrite an existing scaffold. Fill in scope reminder, SA table, summary rows, and one full section per RR-ID.

Before publish:

```bash
python3 .cursor/commands/_scripts/gh/gh-review-publish.py check-consistency \
  --input /tmp/gh-review-payload.json
```

## Manual path

Write to user path or default above. Substitutions vs [research-issues-procedure.md](research-issues-procedure.md) Step 5:

- **Disposition legend** → [disposition-legend.md](../../../_templates/gh-review/disposition-legend.md) or [gh-review-triage-rules.md](gh-review-triage-rules.md)
- **Summary table** columns: ID | Finding | Disposition | Reason | Owner | Repo
- Full finding sections for **every** RR-ID (all outcomes) — use [finding-section.md.template](../../../_templates/gh-review/finding-section.md.template)

## Triage subagent prompt

When ≥3 findings, load [triage-subagent-prompt.txt.template](../../../_templates/gh-review/triage-subagent-prompt.txt.template). Set `{{DISPOSITION_ENUM}}` to `CONFIRM | TRACK | DISMISS`.

## Writing rules

- Every finding gets a **full** subsection — no “see above” only.
- Prefer **CONFIRM** only when the bug or regression-hiding gap exists **today** without assuming unbuilt features.
- Mark **DISMISS** (`hypothetical`) when exploit requires unbuilt routes, production deploy, or unstated caller behavior.
- Mark **DISMISS** (`intentional`) when plan explicitly allows the behavior (stubs, deferred product mapping).
- Call out **test gaps** separately from **production bugs** (test finding can be **TRACK** without implying prod is broken).

## Anti-patterns

- Triage only in chat with no markdown file
- Omitting **Owner** / **Subagent ownership** so `/gh-resolve-issues` cannot parallelize fixes
