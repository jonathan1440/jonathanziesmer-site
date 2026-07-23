| Outcome | Meaning | GitHub sub-issue |
|---------|---------|------------------|
| **CONFIRM** | Defect, AC violation, or regression-hiding test gap | **Bug** under **reviewed issue** |
| **TRACK** | Spec drift, hygiene, duplication, contract gaps, **test hygiene** — real follow-up, not a bug | **Task** under the **reviewed issue** (not its parent) |
| **DISMISS** | Not real or explicitly excluded | None; triage doc only |

**DISMISS reasons:** `wrong-fact` | `hypothetical` | `intentional` | `out-of-scope` — never `hygiene` or `test-hygiene`

**TRACK reasons:** `spec-drift` | `hygiene` | `test-hygiene` | `duplication` | `contract` | free text
