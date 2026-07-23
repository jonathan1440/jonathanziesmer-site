---
name: find-skills
description: Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "find-skill", "is there a skill that can...", or express interest in extending capabilities.
---

# Find Skills

This skill helps you discover skills you **already have** (cataloged in the two Cursor index files below) and skills from the **open agent skills ecosystem** (skills.sh / registry via the CLI).

## When to Use This Skill

Use this skill when the user:

- Asks "how do I do X" where X might be a common task with an existing skill
- Says "find a skill for X" or "is there a skill for X"
- Asks "can you do X" where X is a specialized capability
- Expresses interest in extending agent capabilities
- Wants to search for tools, templates, or workflows
- Mentions they wish they had help with a specific domain (design, testing, deployment, etc.)

## What is the Skills CLI?

The Skills CLI (`npx skills`) is the package manager for the open agent skills ecosystem. Skills are modular packages that extend agent capabilities with specialized knowledge, workflows, and tools.

**Key commands:**

- `npx skills find [query]` - Search for skills interactively or by keyword
- `npx skills add <package>` - Install a skill from GitHub or other sources
- `npx skills check` - Check for skill updates
- `npx skills update` - Update all installed skills

**Browse skills at:** https://skills.sh/

## How to Help Users Find Skills

### Step 1: Understand What They Need

When a user asks for help with something, identify:

1. The domain (e.g., React, testing, design, deployment)
2. The specific task (e.g., writing tests, creating animations, reviewing PRs)
3. Whether this is a common enough task that a skill likely exists

Build a short mental query (keywords + intent) you will use for both local matching and `npx skills find`.

### Step 2: Check Pre-Existing Skills in the Cursor Workspace (Before the skills.sh search)

**Whenever the user is searching for a skill or capability**, check **only** these two catalog files for what already exists under Cursor — **before** querying the public skills ecosystem.

**Required reads** (in order; use Read on these paths only — do not glob, grep, or manually walk other paths under `~/.cursor` for discovery):

1. `.cursor/agents/index.md` — agent/skill index for this repo’s Cursor setup.
2. `.cursor/commands/index.md` — commands and workflow index.

Treat each file as the source of truth for names, descriptions, and paths it lists. Match the user’s intent (keywords + domain from Step 1) against the entries in **those two files only**.

**Do not** manually search other `.cursor` files (no scanning `.cursor/commands/**`, `.cursor/agents/**`, etc.) for this step. If an entry in an index points at a concrete path and the user needs detail, you may read **that** referenced file after the index already identified it as the match.

**Session-only context:** If the harness already lists specific skill paths or names (team rules, attached skills), you may mention those as already available without treating that as a substitute for reading the two indexes when the user asked for discovery.

**Match tiers:**

| Tier | Meaning | What you do |
| ---- | ------- | ----------- |
| **Close match** | An index entry’s description (and purpose) clearly covers the same domain **and** the same task the user asked about. | Tell the user about **that** capability: **full path** from the index (e.g. to `SKILL.md` or a command `.md`), `name`, what it does, and when to use it. **Do not run `npx skills find`** for discovery—you already have a suitable match. You may still briefly note they can use `npx skills find` if they want *additional* third-party options. |
| **Partial match** | Related domain or overlapping keywords in the indexes, but not a full fit (or you are unsure). | List **all** partial matches with path, name, and one line on relevance/gaps. **Then** run Step 3 (`npx skills find`) and continue from Step 4. |
| **No match** | Neither index lists anything plausibly related. | Go straight to Step 3 (`npx skills find`). |

If you find both a close match and weaker candidates, prefer the **close match** path: recommend the close match and skip `npx skills find` unless the user asked explicitly for “more options” or “what else exists.”

### Step 3: Search the skills.sh ecosystem (Skills CLI)

Run only when Step 2 did **not** yield a close match (always run after listing partial matches). This is the supported way to search the public registry backed by [skills.sh](https://skills.sh/) (equivalent to querying the skills.sh catalog via the CLI).

```bash
npx skills find [query]
```

For example:

- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

The command will return results like:

```
Install with npx skills add <owner/repo@skill>

vercel-labs/agent-skills@vercel-react-best-practices
└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 4: Present Options to the User

When you find relevant skills (from Step 2 indexes and/or Step 3 registry), present them clearly:

**For local skills (from the two indexes):** absolute path as given in the index entry, `name`/title from the index, and a short explanation of what it covers (read the linked file only if the user needs more detail than the index provides).

**For registry skills:**

1. The skill name and what it does
2. The install command they can run
3. A link to learn more at skills.sh

Example (registry):

```
I found a skill that might help! The "vercel-react-best-practices" skill provides
React and Next.js performance optimization guidelines from Vercel Engineering.

To install it:
npx skills add vercel-labs/agent-skills@vercel-react-best-practices

Learn more: https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 5: Offer to Install (Registry Only)

If the user wants to proceed with a **registry** skill, you can install it for them:

```bash
npx skills add <owner/repo@skill> -g -y
```

The `-g` flag installs globally (user-level) and `-y` skips confirmation prompts.

## Common Skill Categories

When searching, consider these common categories:

| Category        | Example Queries                          |
| --------------- | ---------------------------------------- |
| Web Development | react, nextjs, typescript, css, tailwind |
| Testing         | testing, jest, playwright, e2e           |
| DevOps          | deploy, docker, kubernetes, ci-cd        |
| Documentation   | docs, readme, changelog, api-docs        |
| Code Quality    | review, lint, refactor, best-practices   |
| Design          | ui, ux, design-system, accessibility     |
| Productivity    | workflow, automation, git                |

## Tips for Effective Searches

1. **Indexes first**: Always read `.cursor/agents/index.md` and `.cursor/commands/index.md` before `npx skills find` so you do not recommend installing what the catalog already lists. Do not brute-force scan the rest of `.cursor` for discovery.
2. **Use specific keywords**: "react testing" is better than just "testing"
3. **Try alternative terms**: If "deploy" doesn't work, try "deployment" or "ci-cd"
4. **Check popular sources**: Many skills come from `vercel-labs/agent-skills` or `ComposioHQ/awesome-claude-skills`

## When No Skills Are Found

If **neither** the two Cursor index files (Step 2) **nor** `npx skills find` (Step 3) surface anything useful:

1. Acknowledge that no matching skill was found in the indexes or in the registry
2. Offer to help with the task directly using your general capabilities
3. Suggest the user could create their own skill with `npx skills init`

Example:

```
I checked your local skills and searched the registry for "xyz" but didn't find a strong match.
I can still help you with this task directly! Would you like me to proceed?

If this is something you do often, you could create your own skill:
npx skills init my-xyz-skill
```
