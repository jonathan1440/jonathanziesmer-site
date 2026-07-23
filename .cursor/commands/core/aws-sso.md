---
name: aws-sso
description: Manages AWS SSO profiles and in-use profile for CDK projects using gen_aws_profiles.py. Syncs ~/.aws/config and project .envrc from cdk.json context, runs direnv allow, and ensures SSO login before AWS commands. Use when managing AWS profiles, syncing CDK projects to SSO, setting AWS_PROFILE, deploying CDK, or when the user mentions AWS SSO, aws profile, or which account to use.
---

# AWS SSO profile management

Uses the script in this skill directory (`gen_aws_profiles.py`) to keep `~/.aws/config` and per-project `.envrc` in sync with CDK projects, then ensures the shell and commands use the right profile.

## When this skill applies

- User wants to sync or update AWS profiles from CDK projects.
- User is about to run an AWS or CDK command and profile/account matters.
- User asks to "use production profile", "deploy to staging", "run against prod", or similar.
- User mentions AWS SSO, AWS profile, or which account they're targeting.

## Workspace and project name

- **Default workspace**: Current git repo root. Resolve with `git rev-parse --show-toplevel` (from any subdirectory of the repo). If not in a git repo, use the current working directory or the single project root the user is working in.
- **Project name**: The script derives the project name from the **directory that contains `cdk.json`**. When the workspace is the git repo root and `cdk.json` is at repo root, the project name is the repo directory name (e.g. `dialpad_events`). If `cdk.json` is in a subdirectory (e.g. `infra/cdk.json`), the project name will be that subdirectory (e.g. `infra`). Profile names are `{project_name}_{environment}`, e.g. `dialpad_events_staging`.

## Workflow 1: Sync profiles (generate/update config and .envrc)

1. Resolve workspace: `git rev-parse --show-toplevel` (or fallback above). If multiple repos are in play, use the repo root for the project the user is working in.
2. Run the script (write immediately; no dry-run):
   ```bash
   python3 .cursor/commands/_scripts/aws/gen_aws_profiles.py --ensure-direnv "$(git rev-parse --show-toplevel)"
   ```
   Use the resolved workspace path; if not in git, use the appropriate directory path.
3. The script will also ensure each project’s `.gitignore` (if present) contains `.envrc`, then it will attempt to run `direnv allow` in each directory where it created/updated `.envrc` (and, with `--ensure-direnv`, it will also try to install direnv and add shell hooks if direnv is missing). If it still can't, run `direnv allow` manually in the affected project directories.
4. If the script exits non-zero or reports errors, stop and report to the user; do not run `direnv allow` or SSO login.

## Workflow 2: Before running AWS or CDK commands

1. **Ensure SSO is logged in.** Run:
   ```bash
   aws sso login --sso-session plnu
   ```
   - If it succeeds (or reports already logged in), continue.
   - If it fails (e.g. network, browser, permission), **stop execution**, tell the user that SSO login failed, and ask them to run `aws sso login --sso-session plnu` manually in their terminal, then retry.
2. **Choose profile for the command:**
   - If the user explicitly asked for an environment (e.g. "deploy to production", "run against prod", "use staging"), use the matching profile for **that command only**: `AWS_PROFILE={project}_{env}`, e.g. `AWS_PROFILE=dialpad_events_production`. Derive `project` and `env` from the repo’s `cdk.json` context (same logic as the script: project = directory containing `cdk.json`, env = key in context that has an `account` field). Use lowercase, snake_case for the env part (e.g. `production` → `production`).
   - If the user did not specify an environment, use the profile already set in the environment (e.g. from `.envrc` via direnv). If `AWS_PROFILE` is unset and the command is run from a project directory that has `.envrc`, assume the default env from the script (staging > dev > prod), e.g. `dialpad_events_staging`.
3. Run the AWS/CDK command with the chosen profile, e.g.:
   ```bash
   AWS_PROFILE=dialpad_events_staging cdk deploy -c config=staging
   ```
   or, if the shell already has `AWS_PROFILE` set and no override was requested, run the command without prefixing.

## Explicit environment (one-off profile)

When the user says things like "deploy to production", "run against prod", "use production profile", or "synth for staging":

- Set the profile **only for that command**: `AWS_PROFILE={project}_{environment} <command>`.
- Do **not** change `.envrc` or the default profile for the directory unless the user explicitly asks to "switch default to prod" or similar.
- Resolve `{project}_{environment}` from the relevant `cdk.json` (project = parent dir of `cdk.json`, environment = context key; slug both to lowercase snake_case).

## Checklist: Sync profiles

- [ ] Resolve workspace (git root or agreed project root).
- [ ] Run `python3 .../gen_aws_profiles.py <workspace>`; abort on script failure.
- [ ] If the script indicates `direnv allow` couldn't run, run it manually in each directory where `.envrc` was created or updated.
- [ ] Remind user to run `aws sso login --sso-session plnu` if they have not yet this session.

## Checklist: Before AWS/CDK command

- [ ] Run `aws sso login --sso-session plnu`. On failure, stop and ask user to run it manually.
- [ ] If user requested a specific environment, use `AWS_PROFILE={project}_{env}` for that command only.
- [ ] Otherwise use existing `AWS_PROFILE` or default from .envrc (staging > dev > prod).

## Script location and options

- Script: `.cursor/commands/_scripts/aws/gen_aws_profiles.py` (in `_scripts/aws/` next to this command)
- Takes one positional argument: path to workspace root (directory that contains one or more CDK projects).
- Optional: `--dry-run` to print changes without writing (use only when user asks to preview).
- Optional: `--ensure-direnv` to (1) install direnv via brew if missing, (2) add direnv hook lines to common zsh/bash/fish rc files, and (3) retry `direnv allow`.
- Optional: `--config` to override `~/.aws/config` (use only when user specifies a different config path).
- Idempotent: safe to run repeatedly; updates only changed profiles and leaves the rest of `~/.aws/config` and other `.envrc` content intact.

## Notes

- SSO sessions expire after 8–12 hours. If an AWS command fails with an auth error, run `aws sso login --sso-session plnu` again.
- The script writes an `sso-session plnu` block and `profile <name>` sections; it uses a single SSO session so one login covers all profiles.
