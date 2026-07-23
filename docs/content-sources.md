# Content sources

Build-time map from site pages to source material. Selection is **resume-only**
([resume-senior.md](../resume-senior.md)); detail comes from `~/Projects/career`
when writing Astro content collections.

Canonical resume generator output: `~/Projects/career/generated/`
(markdown snapshot in-repo: `resume-senior.md`; PDF staged at `assets/resume.pdf`
→ move to `public/resume.pdf` after Astro scaffold).

Do **not** dump the entire career repo into the site.

---

## Experience (`/experience`)

| Role | Dates | Career sources |
| --- | --- | --- |
| Software Engineer, Point Loma Nazarene University | Jan 2026 – Present | `~/Projects/career/profile/work-history.md` + PLNU project files in Projects below |
| Full-Stack Software Engineer, CampLife | Aug 2021 – Jun 2025 | `~/Projects/career/profile/work-history.md` + CampLife project files below |
| Education: B.S. Computer Science, Southern Adventist University | Jul 2018 – Aug 2021 | `~/Projects/career/profile/education.md` |

### Experience bullets (not `/projects` cards)

| Resume item | Career sources |
| --- | --- |
| CampLife cross-functional backlog / stack ownership | `~/Projects/career/projects/cross-functional-backlog-team.md` |
| CampLife occupancy analysis + CampEx | `~/Projects/career/projects/rv-park-data-analysis.md`, `~/Projects/career/projects/occupancy-rules-reengineering.md` |

### Skills section

From resume groups (Languages, AWS, Platforms & Practices). Optional enrichment:
`~/Projects/career/meta/skills-taxonomy.md`, `~/Projects/career/meta/technologies.md`.

---

## Projects (`/projects`) — 7 cards

| Site project | Resume basis | Career file |
| --- | --- | --- |
| Finish Line Photo Extractor | Named PROJECTS entry | `~/Projects/career/projects/finish-line-photo-extractor.md` |
| Workday Student Data Integrations | PLNU bullet 1 | `~/Projects/career/projects/workday-student-data-integrations.md` |
| GitHub Platform Migration & Engineering Standards | PLNU bullet 2 | `~/Projects/career/projects/github-platform-migration.md` |
| Automated Test Coverage (Python/Java) | PLNU bullet 3 | `~/Projects/career/projects/plnu-automated-test-coverage.md` |
| Agentic Cursor Dev Workflow | PLNU bullet 4 | `~/Projects/career/projects/agentic-cursor-dev-workflow.md` |
| ETL Pipeline for Customer Onboarding | CampLife bullet 1 | `~/Projects/career/projects/etl-pipeline-customer-onboarding.md` |
| Inventory Lifecycle Tracking | CampLife bullet 3 | `~/Projects/career/projects/inventory-lifecycle-tracking.md` |

---

## Home / About

| Page need | Sources |
| --- | --- |
| Bio / summary | `resume-senior.md` SUMMARY + `~/Projects/career/profile/core.md` |
| Running / personality texture | `~/Projects/career/profile/core.md` Personal Info; racing roles in `work-history.md` (e.g. White Oak Mountain Racing) — personality only, not a services pitch |

---

## Spec

Design system, pages, and stack: [specs/jonathanziesmer-site/SPEC.md](specs/jonathanziesmer-site/SPEC.md).
