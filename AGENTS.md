# jonathanziesmer-site — Agent contract

Personal portfolio / resume site for hiring managers. Running and coaching are
personality texture only — not a service offering.

Authoritative product + design spec: `docs/specs/jonathanziesmer-site/SPEC.md`.
Content inventory: `docs/content-sources.md`.

## Principles

- Static-first Astro site. Prefer zero client JS; add interactivity only when a
  page requires it (e.g. contact form, mobile nav).
- Credibility and clarity over marketing chrome. One composition per viewport;
  whitespace and type carry hierarchy.
- Site copy is curated from the resume inventory — never a dump of
  `~/Projects/career`.
- Design system in the SPEC is binding: white base, accent `#0057FF` used
  sparingly, Fraunces for page H1 only, DM Sans for body/headings, JetBrains Mono
  for metadata/tags.
- Avoid AI-portfolio tells called out in the SPEC (cream/terracotta, purple glow,
  hero CTA stacks, card soup, decorative numbered sections).

## Where things live

Run `tree -L 2 .` for current layout. App layout:

- `src/content/projects/` — one Markdown file per project card
- `src/content/experience/` — one Markdown file per role
- `src/pages/` — routes; contact API under `src/pages/api/`
- `src/components/`, `src/layouts/` — UI and `BaseLayout`
- `public/resume.pdf` — served resume (until scaffold: `assets/resume.pdf`)
- `docs/specs/jonathanziesmer-site/SPEC.md` — product/design contract
- `docs/content-sources.md` — which career files feed which pages
- `.cursor/commands/` — SDLC harness; start at `.cursor/commands/ENTRANCE.md`

## Architectural contract

- Stack (locked): Astro + Tailwind CSS + TypeScript; Markdown content
  collections; Resend via Astro API route for contact; Cloudflare Pages hosting.
  Accounts/secrets for Resend and Cloudflare are deferred until deploy.
- Experience and projects are data: YAML frontmatter + body in content
  collections. Layout components render collections; do not hard-code role or
  project copy into page components.
- Content selection must match `docs/content-sources.md` (resume-selected roles
  and the seven listed projects). Adding a project means updating that inventory
  and the resume story — not inventing portfolio filler.
- Resume PDF path: stage in `assets/resume.pdf`; after scaffold, host at
  `public/resume.pdf` and link from nav / about / experience.
- Contact form submits server-side to Resend; always show a plain email fallback.
- Design tokens and type scale live in Tailwind config per SPEC — do not
  introduce a second palette or display font.
- Motion: home H1 entrance only (`opacity` + `translateY`, ~200ms, respect
  `prefers-reduced-motion`). No scroll-triggered animation libraries.

## Change categories

| Shippable after normal review | Needs conversation first |
| --- | --- |
| Copy/frontmatter updates within inventory | New page or nav item |
| Component polish within SPEC design rules | New CSS framework or UI kit |
| Content collection schema fields already used elsewhere | Replacing Astro/Tailwind/Resend/Cloudflare |
| SEO meta defaults, minor layout spacing | Analytics vendor choice or cookie/consent surface |
| Bug fixes in contact API within Resend pattern | Auth, CMS, or dynamic backend |

## Validation

- `npm run build` — must succeed before claiming done (`astro check` and `astro build`)
- `npm run check` — typecheck
- Visual pass against SPEC palette/type/layout on home + one content page

Cannot validate yet: Resend delivery, Cloudflare deploy, production DNS.

## Context the code does not carry

- Audience: recruiters and hiring managers evaluating a software engineer.
- Career repo (`~/Projects/career`) is the long-form source of truth; this repo
  holds the public site and a frozen resume snapshot (`resume-senior.md`).
- Domain intent: jonathanziesmer.com (DNS/registrar on Cloudflare per SPEC).
- Do not pitch coaching or racing as paid services on this site.
