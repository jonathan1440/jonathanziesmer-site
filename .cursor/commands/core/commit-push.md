---
name: commit-push
description: Run the existing commit skill to create a conventional commit, then push the current branch to its tracked remote. Use when the user explicitly wants to commit and push, or invokes "/commit-push".
---

# Commit and Push

## When to use this skill

Use this skill when:

- The user asks to both **commit and push** changes.
- The user invokes `/commit-push`.
- The user requests "commit and push", "commit + push", or similar phrasing.

Do **not** use this skill when:

- The user only wants a commit without pushing (use the `commit` skill alone).
- The user is working on a branch that must not be pushed yet (e.g. WIP, experiment).

## Workflow

Follow this workflow exactly, using the `commit` skill first, then pushing.

### 1. Prepare the working tree

1. Use git status to understand the current state:

   ```bash
   git status
   ```

2. If there are obvious build artifacts or generated files that should not be committed, confirm they are ignored or unstaged before continuing.

### 2. Create the commit using the `commit` skill

1. Invoke the existing `commit` skill.
2. Follow its instructions to:
   - Inspect the diff and git status.
   - Intelligently stage files (grouping related changes together where appropriate).
   - Generate a **Conventional Commit** message based on the diff.
   - Run `git commit` with that message.

Honor all safety rules from the `commit` skill (no secrets, no destructive git commands, do not skip hooks, etc).

If the commit fails due to hooks or validation, fix the issues and create a new commit, not an amended one, unless the user has explicitly requested an amend and it is safe to do so.

### 3. Verify the commit

1. Confirm that there is now a clean working tree:

   ```bash
   git status
   ```

2. Optionally run tests or linters if:
   - The user requested it, or
   - The change is risky or affects critical paths.

If tests or linters fail, resolve the failures and either:
- Amend the commit if it is safe and explicitly requested, or
- Create a follow-up commit describing the fixes.

### 4. Push the current branch

1. Determine the current branch and its upstream:

   ```bash
   git status -sb
   ```

2. Show the commits that will be pushed and capture their details:

   - **If the branch already has an upstream**:

     ```bash
     git log --oneline @{u}..HEAD
     ```

   - **If there is no upstream yet** (first push), show recent commits on the branch:

     ```bash
     git log --oneline -n 10
     ```

3. For each commit that will be pushed, gather the following details using `git log` and/or `git show`:

   - Commit hash
   - Author
   - Commit date
   - Commit message/subject
   - Files touched (for example, via `git show --name-status <hash>` or similar)

   Include a concise summary of these commit details in your chat response **before** you run the push command, so the user can see exactly what is about to be pushed.

4. **If the branch already tracks a remote** (typical case), push:

   ```bash
   git push
   ```

5. **If the branch does not have an upstream yet**, set it once:

   ```bash
   git push -u origin <current-branch-name>
   ```

#### Safety rules for pushing

- Only push when the user has **explicitly** asked to push (e.g. via `/commit-push` or direct instruction).
- **Never** use `--force` or `--force-with-lease` unless the user has explicitly requested a force push and understands the consequences.
- **Never** force-push to protected branches like `main` or `master` unless the user explicitly asks and acknowledges the risk.
- Do not push partially committed work; ensure the commit reflects a coherent logical change.

### 5. Report back to the user

After a successful commit and push, summarize back to the user:

- The commit hash and message.
- The branch name and remote you pushed to.
- Any tests or linters that were run (and their outcome).

If the push fails (for example, due to non-fast-forward updates or permission issues), clearly report:

- The exact error message.
- The likely cause.
- Safe next steps or options (e.g. pull/rebase, open a PR from the current state, or ask the user whether a force push is acceptable).

