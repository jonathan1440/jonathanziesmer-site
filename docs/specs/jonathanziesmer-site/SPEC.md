# jonathanziesmer.com — Site Spec

## Purpose

A personal portfolio and resume site for a software engineer. The goal is to
communicate professional credibility, show real work, and give hiring managers a
clear path to reach out. The running and coaching background lives here as
texture and personality, not as a separate service offering.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Framework | [Astro](https://astro.build) | Static by default, zero JS overhead, excellent for content sites |
| Styling | [Tailwind CSS](https://tailwindcss.com) | Removes layout decision fatigue, easy to override for custom design |
| Language | TypeScript | Type safety in component props and data files |
| Content | Markdown + Astro content collections | Projects and experience as structured `.md` files in Git |
| Contact form | [Resend](https://resend.com) via Astro API route | Simple email delivery, generous free tier |
| Hosting | [Cloudflare Pages](https://pages.cloudflare.com) | Free, fast globally, deploys from GitHub on push |
| Domain | Cloudflare Registrar | DNS already managed there, keeps it simple |
| Analytics | [Umami](https://umami.is) (self-hosted on Cloudflare) or Cloudflare Web Analytics | Privacy-respecting, no cookie banner needed |

### Why not Next.js?

No dynamic data fetching, no auth, no API-heavy features. Next.js earns its
complexity on app-like projects. For a portfolio site, the overhead is noise.

---

## Design System

### Aesthetic Direction

The reference point is Garmin watch UI: precision, performance data, clean
functional layouts with just enough personality to feel human. Not sterile --
purposeful. Think technical running gear branding (On Running, Tracksmith,
Satisfy) crossed with well-designed engineering documentation. The site should
feel like it was built by someone who takes both craft and performance seriously.

One axis of restraint, one axis of personality. The layout and color are quiet.
The typography is where the character lives.

---

### What to Avoid (AI-Generated Tell Signs)

These patterns appear on almost every AI-generated or template portfolio site.
Avoiding them puts you ahead of most:

- Warm cream backgrounds (~#F4F1EA) with terracotta or clay accents -- this is
  the Claude/Notion palette and it's everywhere
- Dark backgrounds with a single acid-green or purple gradient accent
- Fake numbered sections (01 / 02 / 03) used as decoration rather than real
  sequence markers
- Hero sections with a giant headline, subtitle, and two stacked CTA buttons on
  a gradient -- every template does this
- Too many card components with shadows and rounded corners -- when everything
  is a card, nothing has hierarchy

---

### Color Palette

A white base with one real accent used sparingly. The Garmin reference suggests
a cool, slightly utilitarian tone -- not warm, not playful.

| Role | Value | Usage |
|---|---|---|
| Background | `#FFFFFF` | Page base |
| Surface | `#F7F8FA` | Subtle section backgrounds, code blocks |
| Border | `#E2E5EA` | Dividers, input outlines, thin rules |
| Text primary | `#0F1117` | Headings, body copy |
| Text secondary | `#5A6272` | Metadata, dates, captions, stack tags |
| Accent | `#0057FF` | Links, active states, one CTA button, thin highlight rules |
| Accent dark | `#003FBB` | Hover state on accent |

The blue (`#0057FF`) is specific -- not a default Bootstrap or Tailwind blue.
It reads as technical and precise without veering into corporate. Use it
sparingly: links, one button per page, maybe a thin left-border on a featured
item. The discipline of using it rarely is what makes it feel intentional.

---

### Typography

This is where personality lives. Two weights of two families, used with
restraint.

| Role | Family | Weight / Style | Notes |
|---|---|---|---|
| Display / H1 | [Fraunces](https://fonts.google.com/specimen/Fraunces) | 300–400, optical size `opsz` 144 | Variable font, humanist, slightly editorial. Use only for the largest heading on a page. |
| Headings H2–H4 | [DM Sans](https://fonts.google.com/specimen/DM+Sans) | 500–600 | Clean, geometric, pairs well with Fraunces |
| Body | DM Sans | 400 | Same family as headings, keeps it unified |
| Monospace / tags | [JetBrains Mono](https://fonts.google.com/specimen/JetBrains+Mono) | 400 | Stack tags, code snippets, small metadata labels |

Fraunces has a distinctly human quality -- slightly soft, a little literary --
which provides contrast against the otherwise utilitarian layout. Use it only
for the H1 on each page. Everything else is DM Sans.

**Type scale (Tailwind custom config):**

```js
fontSize: {
  'xs':  ['0.75rem',  { lineHeight: '1rem' }],
  'sm':  ['0.875rem', { lineHeight: '1.375rem' }],
  'base':['1rem',     { lineHeight: '1.625rem' }],
  'lg':  ['1.125rem', { lineHeight: '1.75rem' }],
  'xl':  ['1.25rem',  { lineHeight: '1.875rem' }],
  '2xl': ['1.5rem',   { lineHeight: '2rem' }],
  '3xl': ['2rem',     { lineHeight: '2.5rem' }],
  '4xl': ['2.75rem',  { lineHeight: '3.25rem' }],   // H1 / Fraunces
}
```

---

### Layout Principles

**Centered single column.** Max content width of `760px`, centered, with
generous horizontal padding on mobile. Don't fight the column. The interesting
thing won't be the grid -- it'll be the type and the color.

**Whitespace as structure.** Let sections breathe. Generous `padding-y` between
sections does more for legibility than any divider or card component.

**Thin horizontal rules** (`1px`, `#E2E5EA`) between major sections instead of
background color changes. This is the Garmin UI move -- precise, minimal
delineation.

**Data-style metadata.** Dates, company names, stack tags, and role labels
rendered in JetBrains Mono at `text-xs` in `text-secondary`. Looks like a
watch data field. Gives the site a technical texture without trying hard.

**No hero gradient.** The home page opens with your name in Fraunces and a
single clean sentence. That's the hero.

---

### Component Conventions

**Accent rule.** A `3px` left border in `#0057FF` on featured project cards or
highlighted experience items. Use on one or two items maximum per page -- it
loses meaning if everything has it.

**Stack tags.** Monospace, small, no background fill -- just the text in
`text-secondary` with a thin border. Not colorful pill badges. They should read
like data, not marketing.

**Buttons.** One style: solid accent background, white text, no border radius
(or `2px` max -- square feels more Garmin than rounded). Secondary action: text
link with an underline on hover, no button chrome at all.

**No drop shadows.** Use borders (`1px solid #E2E5EA`) instead. Shadows make
things feel floaty and generic. Borders feel precise.

**Icons.** Use [Lucide](https://lucide.dev) -- clean, consistent stroke weight,
works well at small sizes. Astro has a Lucide integration. Avoid icon libraries
that mix styles.

---

### Motion

Almost none. This is not a place for scroll animations or fade-ins.

The one exception: a subtle `opacity` + `translateY` entrance on the home page
H1, 200ms, ease-out. Single orchestrated moment, nothing else moves. Respect
`prefers-reduced-motion`.

---

### Reference Sites

Study these -- not to copy, but to understand what restrained, intentional
personal sites look like in practice:

- [paco.me](https://paco.me) -- typographic restraint, personality through copy
- [leerob.io](https://leerob.io) -- clean engineering portfolio, good hierarchy
- [rauno.me](https://rauno.me) -- interaction design, motion done right

For the Garmin aesthetic specifically, look at Garmin Connect web UI and the
Forerunner/Fenix product pages. Note how they use thin rules, monospace data
labels, and a single accent color against white.

---

## Pages

### `/` — Home

The first impression. Loads fast, reads immediately.

**Content:**
- Name, one-line title (e.g. "Software Engineer")
- 2–3 sentence bio that names both the engineering work and the running background
  without over-explaining either
- Two CTAs: "View my work" (→ `/projects`) and "Get in touch" (→ `/contact`)
- Optional: a subtle footer stat or two (years of experience, languages, something
  that earns credibility without a wall of text)

---

### `/about` — About

Where both sides of the identity live together.

**Content:**
- Longer bio: engineering background, current role at PLNU, what you build and
  why it matters
- Running section: competitive history, coaching certification, race directing,
  the USATF certifier work — framed as "what I do outside of work" rather than
  a services pitch
- Values or working philosophy (optional, keep it short — one or two sentences
  per point, not a manifesto)
- Link to resume PDF + LinkedIn

---

### `/experience` — Experience

The professional timeline. Can double as an interactive resume.

**Content:**
- Work history (PLNU, CampLife, earlier roles) with role, dates, and 2–4 bullet
  points per position focused on impact and technologies used
- Education (Southern Adventist University, any certifications worth naming)
- Skills section: languages, frameworks, cloud platforms, tools — grouped
  loosely, not exhaustively
- Resume PDF download button (prominent)
- LinkedIn link

**Implementation note:** Store each role as a structured Markdown file with
YAML frontmatter (`title`, `company`, `dates`, `stack[]`, `bullets[]`). Astro
content collections render these automatically, and you can update your
experience without touching layout code.

---

### `/projects` — Projects

Show the work. Quality over quantity — 4 to 8 projects is plenty.

**Content per project card:**
- Project name and one-line description
- Tech stack tags
- What problem it solved (1–2 sentences)
- Links: GitHub repo and/or live demo where applicable

**Good candidates to include:**
- PLNU integrations work (Workday, Salesforce, Canvas pipelines)
- The knowledge graph system (PostgreSQL + pgvector, podcast corpus)
- The Strava/intervals.icu → Google Sheets sync script
- The AWS CDK / Lambda work
- The Cursor training curriculum and agent workflow system (shows engineering
  leadership beyond just writing code)

**Implementation note:** Same pattern as `/experience` — one `.md` file per
project with frontmatter, rendered into cards by a single layout component.

---

### `/contact` — Contact

Simple and frictionless.

**Content:**
- Brief line inviting contact ("Open to interesting engineering roles and
  freelance projects.")
- Form: name, email, subject (optional), message
- Form submits to an Astro API route → Resend → your inbox
- Fallback: direct email address displayed below the form for people who hate
  forms
- LinkedIn link

---

## Site-Wide

- **Nav:** Logo/name (left), links to About / Experience / Projects / Contact
  (right). Keep it flat — no dropdowns.
- **Footer:** Copyright, LinkedIn, GitHub, email icon. Minimal.
- **Resume PDF:** Hosted in `/public/resume.pdf`, updated manually as needed.
  Link appears in nav (as a button) and on `/about` and `/experience`.
- **Mobile:** Astro + Tailwind handles responsive layout naturally. Nav collapses
  to a hamburger on small screens.
- **SEO:** Astro has first-class support for `<meta>` tags. Add a base
  `SEO.astro` component used across all pages with sensible defaults.

---

## Repo Structure (Suggested)

```
jonathanziesmer.com/
├── src/
│   ├── components/       # Nav, Footer, ProjectCard, ExperienceItem, SEO
│   ├── content/
│   │   ├── projects/     # one .md per project
│   │   └── experience/   # one .md per role
│   ├── layouts/          # BaseLayout.astro
│   └── pages/            # index.astro, about.astro, experience.astro,
│                         # projects.astro, contact.astro, api/contact.ts
├── public/
│   └── resume.pdf
├── astro.config.mjs
├── tailwind.config.mjs
└── tsconfig.json
```

---

## What to Build First

1. Scaffold the Astro project (`npm create astro@latest`)
2. Add Tailwind (`npx astro add tailwind`)
3. Build `BaseLayout.astro` with nav and footer
4. Wire up content collections for projects and experience
5. Build `/projects` and `/experience` pages — these have the most content
   dependency and will force you to write the copy early
6. Build `/about` and `/`
7. Add the contact form last (requires Resend account and API route)
8. Deploy to Cloudflare Pages, connect domain

---

*Last updated: July 2026 — includes design system*
