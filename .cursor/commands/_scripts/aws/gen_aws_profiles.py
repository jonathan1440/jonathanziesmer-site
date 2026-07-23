#!/usr/bin/env python3
"""
Scans a workspace directory for CDK projects and generates AWS SSO profiles
in ~/.aws/config. Profile names are formatted as {project_name}_{environment},
e.g. dialpad_events_staging.

Usage:
    python3 gen_aws_profiles.py /path/to/workspace
    python3 gen_aws_profiles.py /path/to/workspace --dry-run
    python3 gen_aws_profiles.py /path/to/workspace --ensure-direnv

── Workflow ──────────────────────────────────────────────────────────────────

1. Generate profiles (run once, or re-run when projects are added):

    python3 gen_aws_profiles.py ~/workspace

2. Authenticate with SSO (run once per day, covers all profiles):

    aws sso login --sso-session plnu

   This opens a browser to complete the SSO flow. Credentials are cached in
   ~/.aws/sso/cache/ and shared across all profiles, so you only need to do
   this once regardless of how many accounts you're working with.

3. Use a profile with any AWS tool:

   AWS CLI:
       aws s3 ls --profile dialpad_events_staging

   CDK:
       cdk deploy --profile dialpad_events_staging

   Environment variable (applies to all commands in the current shell):
       export AWS_PROFILE=dialpad_events_staging

   Per-command env var (useful in scripts):
       AWS_PROFILE=dialpad_events_staging cdk synth

4. Verify which account you're currently targeting:

    aws sts get-caller-identity --profile dialpad_events_staging

── Notes ─────────────────────────────────────────────────────────────────────

- SSO sessions expire after 8-12 hours. Re-run step 2 if you get an
  authentication error mid-session.
- This script is idempotent. Re-running it will update changed profiles and
  add new ones without touching anything else in ~/.aws/config.
- A .envrc file is written to each project root setting AWS_PROFILE to the
  default environment (staging > dev > prod). If a .envrc already exists,
  only the export AWS_PROFILE line is updated; all other content is preserved.
  Requires direnv (https://direnv.net) to take effect in your shell. When
  direnv is on PATH, the script runs `direnv allow` in each project directory
  after writing or updating `.envrc` so the environment activates without a
  manual step. With `--ensure-direnv`, the script will also try to install
  direnv (via brew) and add hook lines to common zsh/bash rc files.
- If a project's `.gitignore` exists, the script ensures it contains `.envrc`
  so the file isn't accidentally committed.
- Profile names are derived from the directory containing cdk.json. If a repo
  has a nested cdk.json in a subdirectory, the profile name will reflect the
  subdirectory name rather than the repo root.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

SSO_SESSION_NAME = "plnu"
SSO_ROLE_NAME    = "AdministratorAccess"
SSO_START_URL    = "https://d-92670c3242.awsapps.com/start"
SSO_REGION       = "us-west-2"
DEFAULT_REGION   = "us-west-2"

# Context keys that are environments (have an "account" field inside them).
# Everything else in context is either a CDK feature flag or a scalar config value.
CDK_FLAG_PREFIX = "@aws-cdk/"

# ── Helpers ──────────────────────────────────────────────────────────────────

def slug(name: str) -> str:
    """Normalize a string to lowercase snake_case for use in a profile name."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def find_cdk_projects(workspace: Path) -> list[tuple[str, dict]]:
    """
    Walk workspace looking for cdk.json files. Returns a list of
    (project_name, cdk_context) tuples. project_name is derived from
    the directory containing cdk.json.
    """
    projects = []

    for cdk_file in sorted(workspace.rglob("cdk.json")):
        # Skip anything inside node_modules, .venv, cdk.out, etc.
        parts = cdk_file.parts
        if any(p.startswith(".") or p in {"node_modules", "cdk.out", "__pycache__"} for p in parts):
            continue

        try:
            data = json.loads(cdk_file.read_text())
        except json.JSONDecodeError as e:
            print(f"  [WARN] Could not parse {cdk_file}: {e}", file=sys.stderr)
            continue

        context = data.get("context", {})
        project_name = slug(cdk_file.parent.name)
        projects.append((project_name, context, cdk_file))

    return projects


def extract_environments(context: dict) -> list[tuple[str, str]]:
    """
    Find keys in context that represent environments (dicts containing an
    "account" field). Returns a list of (env_key, account_id) tuples.
    Skips CDK feature flags and non-dict values.
    """
    envs = []
    for key, value in context.items():
        if key.startswith(CDK_FLAG_PREFIX):
            continue
        if not isinstance(value, dict):
            continue
        account = value.get("account")
        if account:
            envs.append((key, str(account)))
    return envs


def build_profile(profile_name: str, account_id: str) -> dict:
    return {
        "sso_session":    SSO_SESSION_NAME,
        "sso_account_id": account_id,
        "sso_role_name":  SSO_ROLE_NAME,
        "region":         DEFAULT_REGION,
    }


def sso_session_block() -> dict:
    return {
        "sso_start_url":           SSO_START_URL,
        "sso_region":              SSO_REGION,
        "sso_registration_scopes": "sso:account:access",
    }

# ── .envrc ───────────────────────────────────────────────────────────────────

ENV_PRIORITY = ["staging", "dev", "prod"]


def select_default_env(envs: list[tuple[str, str]]) -> str:
    """Pick the default environment key using ENV_PRIORITY order."""
    env_keys = {key for key, _ in envs}
    for candidate in ENV_PRIORITY:
        if candidate in env_keys:
            return candidate
    # If none of the priority names match, just take the first one found.
    return envs[0][0]


def write_envrc(project_dir: Path, profile_name: str, dry_run: bool) -> str:
    """
    Write or update AWS_PROFILE in a project's .envrc file.
    If the file exists, replaces the existing export AWS_PROFILE line (if any)
    and appends one if none is found. Returns a status string for logging.
    """
    envrc_path = project_dir / ".envrc"
    new_line = f"export AWS_PROFILE={profile_name}\n"

    if envrc_path.exists():
        original = envrc_path.read_text()
        lines = original.splitlines(keepends=True)
        matched = False
        new_lines = []
        for line in lines:
            if re.match(r"^\s*export\s+AWS_PROFILE\s*=", line):
                if line == new_line:
                    return "unchanged"
                new_lines.append(new_line)
                matched = True
            else:
                new_lines.append(line)
        if not matched:
            new_lines.append(new_line)
        if not dry_run:
            envrc_path.write_text("".join(new_lines))
        return "updated"
    else:
        if not dry_run:
            envrc_path.write_text(new_line)
        return "created"


def ensure_envrc_ignored(project_dir: Path, dry_run: bool) -> bool:
    """
    If a project's .gitignore exists, ensure it contains a literal ".envrc"
    ignore entry. Returns True if the .gitignore was changed (or would be
    changed in dry_run), False otherwise.
    """
    gitignore_path = project_dir / ".gitignore"
    if not gitignore_path.exists():
        return False

    try:
        original = gitignore_path.read_text()
    except Exception:
        return False

    for line in original.splitlines():
        stripped = line.strip()
        if stripped in {".envrc", "/.envrc"}:
            return False

    addition = ".envrc\n"
    if dry_run:
        return True

    if not original:
        gitignore_path.write_text(addition)
        return True

    if original.endswith("\n"):
        gitignore_path.write_text(original + addition)
    else:
        gitignore_path.write_text(original + "\n" + addition)
    return True


def run_direnv_allow(project_dir: Path) -> bool:
    """Run `direnv allow` in project_dir. Returns True if direnv ran successfully."""
    direnv_exe = get_direnv_executable()
    if not direnv_exe:
        return False
    try:
        subprocess.run(
            [direnv_exe, "allow"],
            cwd=project_dir,
            capture_output=True,
            timeout=10,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_direnv_executable() -> str | None:
    exe = shutil.which("direnv")
    if exe:
        return exe

    # Common Homebrew + local install locations.
    for candidate in [
        "/opt/homebrew/bin/direnv",
        "/usr/local/bin/direnv",
        str(Path.home() / ".local" / "bin" / "direnv"),
    ]:
        if Path(candidate).exists():
            return candidate

    # If brew is present, attempt to resolve the installed executable by prefix.
    brew_exe = shutil.which("brew")
    if brew_exe:
        try:
            prefix = subprocess.check_output(
                [brew_exe, "--prefix", "direnv"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            candidate = str(Path(prefix) / "bin" / "direnv")
            if Path(candidate).exists():
                return candidate
        except Exception:
            pass

    return None


def brew_install_direnv() -> bool:
    brew_exe = shutil.which("brew")
    if not brew_exe:
        return False

    try:
        subprocess.run(
            [brew_exe, "install", "direnv"],
            check=True,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def detect_preferred_shell() -> str:
    shell_path = os.environ.get("SHELL", "")
    shell_name = os.path.basename(shell_path).lower()
    if shell_name in {"zsh", "bash", "fish"}:
        return shell_name
    return "zsh"


def update_rc_file_with_direnv_hook(
    rc_path: Path,
    shell: str,
    hook_line: str,
) -> bool:
    """
    Idempotently add a direnv hook block to rc_path.
    Returns True if the file changed, False otherwise.
    """
    marker_begin = f"# >>> direnv hook ({shell}) [gen_aws_profiles] >>>"
    marker_end = f"# <<< direnv hook ({shell}) [gen_aws_profiles] <<<"
    block = f"{marker_begin}\n{hook_line}\n{marker_end}\n"

    try:
        original = rc_path.read_text() if rc_path.exists() else ""
    except Exception:
        return False

    if marker_begin in original and marker_end in original:
        # Replace existing block.
        start = original.find(marker_begin)
        end = original.find(marker_end, start)
        end = end + len(marker_end)
        end = end if end <= len(original) else len(original)
        new_text = original[:start] + block + original[end:]
        if new_text == original:
            return False
        rc_path.write_text(new_text)
        return True

    if hook_line.strip() in original:
        # Hook already present, but without our marker. Leave as-is.
        return False

    # Append block.
    prefix = "" if not original or original.endswith("\n") else "\n"
    rc_path.write_text(original + prefix + block)
    return True


def ensure_direnv_installed_and_hooked() -> bool:
    """
    Best-effort: install direnv and ensure hooks are present in common rc files.
    Returns True if direnv executable becomes available.
    """
    if get_direnv_executable():
        # If installed, still try to add hooks so new terminals pick it up.
        pass
    else:
        print("direnv not found on PATH, attempting to install via brew...")
        if not brew_install_direnv():
            print("direnv install failed or brew not available. Please install direnv manually.", file=sys.stderr)
            return False

    if not get_direnv_executable():
        print("direnv still not available after install. Please install direnv manually.", file=sys.stderr)
        return False

    preferred_shell = detect_preferred_shell()

    home = Path.home()

    interactive_rc_by_shell = {
        "zsh": home / ".zshrc",
        "bash": home / ".bashrc",
        "fish": home / ".config" / "fish" / "config.fish",
    }

    candidate_files: list[tuple[str, Path, str]] = [
        ("zsh", home / ".zshrc", 'eval "$(direnv hook zsh)"'),
        ("zsh", home / ".zprofile", 'eval "$(direnv hook zsh)"'),
        ("bash", home / ".bashrc", 'eval "$(direnv hook bash)"'),
        ("bash", home / ".profile", 'eval "$(direnv hook bash)"'),
        ("fish", home / ".config" / "fish" / "config.fish", "direnv hook fish | source"),
    ]

    # “Update any that we find”, but also ensure the interactive rc for the
    # detected shell exists, so interactive terminals pick up direnv.
    targets: list[tuple[str, Path, str]] = []
    for shell_name, rc_path, hook_line in candidate_files:
        is_preferred_interactive = (
            shell_name == preferred_shell and rc_path == interactive_rc_by_shell[shell_name]
        )
        if rc_path.exists() or is_preferred_interactive:
            targets.append((shell_name, rc_path, hook_line))

    updated_any = False
    for shell_name, rc_path, hook_line in targets:
        changed = update_rc_file_with_direnv_hook(rc_path, shell_name, hook_line)
        updated_any = updated_any or changed
        if changed:
            print(f"Updated direnv hook in {rc_path}")

    if not updated_any:
        print("direnv hook appears to already be present in your shell rc files.")

    return True


# ── Config read/write ─────────────────────────────────────────────────────────

def load_aws_config(config_path: Path) -> configparser.RawConfigParser:
    config = configparser.RawConfigParser()
    if config_path.exists():
        config.read(config_path)
    return config


def write_aws_config(config: configparser.RawConfigParser, config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w") as f:
        config.write(f)


def apply_profiles(
    config: configparser.RawConfigParser,
    new_profiles: dict[str, dict],
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    """
    Merge new_profiles into config. Returns (added, updated) lists of profile names.
    new_profiles is a dict of {section_name: {key: value}}.
    """
    added, updated = [], []

    for section, values in new_profiles.items():
        if config.has_section(section):
            existing = dict(config.items(section))
            if existing != values:
                for k, v in values.items():
                    config.set(section, k, v)
                updated.append(section)
        else:
            if not dry_run:
                config.add_section(section)
            for k, v in values.items():
                if not dry_run:
                    config.set(section, k, v)
            added.append(section)

    return added, updated

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate AWS SSO profiles from CDK projects.")
    parser.add_argument("workspace", type=Path, help="Path to workspace root directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to ~/.aws/config.")
    parser.add_argument("--config", type=Path, default=Path.home() / ".aws" / "config", help="Path to AWS config file (default: ~/.aws/config).")
    parser.add_argument(
        "--ensure-direnv",
        action="store_true",
        help="If direnv is missing, attempt to install via brew and add hooks to common zsh/bash/fish rc files.",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"Error: {workspace} is not a directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {workspace} for CDK projects...\n")
    projects = find_cdk_projects(workspace)

    if not projects:
        print("No cdk.json files found.")
        sys.exit(0)

    # Build all profile sections to write
    new_sections: dict[str, dict] = {}

    # Always ensure the sso-session block is present
    sso_section = f"sso-session {SSO_SESSION_NAME}"
    new_sections[sso_section] = sso_session_block()

    # (project_dir, default_profile_name) for .envrc writing
    envrc_targets: list[tuple[Path, str]] = []

    for project_name, context, cdk_file in projects:
        envs = extract_environments(context)
        if not envs:
            print(f"  [SKIP] {cdk_file.parent} — no environment blocks with 'account' found")
            continue

        print(f"  {cdk_file.parent.relative_to(workspace)}")
        for env_key, account_id in envs:
            profile_name = f"{project_name}_{slug(env_key)}"
            section = f"profile {profile_name}"
            new_sections[section] = build_profile(profile_name, account_id)
            print(f"    {profile_name}  ({account_id})")

        default_env = select_default_env(envs)
        default_profile = f"{project_name}_{slug(default_env)}"
        envrc_targets.append((cdk_file.parent, default_profile))
        print(f"    .envrc → {default_profile}")

    print()

    if args.dry_run:
        print("── Dry run: no changes written ──")
        print(f"Would write {len(new_sections)} sections to {args.config}\n")
        for section, values in new_sections.items():
            print(f"[{section}]")
            for k, v in values.items():
                print(f"  {k} = {v}")
            print()
        print(".envrc changes:")
        for project_dir, profile_name in envrc_targets:
            envrc_path = project_dir / ".envrc"
            exists = "update" if envrc_path.exists() else "create"
            print(f"  {exists} {envrc_path}")
            print(f"    export AWS_PROFILE={profile_name}")
        return

    config = load_aws_config(args.config)
    added, updated = apply_profiles(config, new_sections, dry_run=False)
    write_aws_config(config, args.config)

    print(f"Written to {args.config}")
    if added:
        print(f"  Added   ({len(added)}): {', '.join(added)}")
    if updated:
        print(f"  Updated ({len(updated)}): {', '.join(updated)}")
    if not added and not updated:
        print("  No changes (all profiles already up to date).")

    print()
    envrc_created, envrc_updated, envrc_unchanged = [], [], []
    envrc_dirs_to_allow: list[Path] = []
    gitignore_updated: list[str] = []
    for project_dir, profile_name in envrc_targets:
        status = write_envrc(project_dir, profile_name, dry_run=False)
        label = str(project_dir / ".envrc")
        if ensure_envrc_ignored(project_dir, dry_run=False):
            gitignore_updated.append(str(project_dir / ".gitignore"))
        if status == "created":
            envrc_created.append(label)
            envrc_dirs_to_allow.append(project_dir)
        elif status == "updated":
            envrc_updated.append(label)
            envrc_dirs_to_allow.append(project_dir)
        else:
            envrc_unchanged.append(label)

    if envrc_created:
        print(f".envrc created  ({len(envrc_created)}):")
        for p in envrc_created:
            print(f"  {p}")
    if envrc_updated:
        print(f".envrc updated  ({len(envrc_updated)}):")
        for p in envrc_updated:
            print(f"  {p}")
    if envrc_unchanged and not envrc_created and not envrc_updated:
        print(".envrc — no changes.")

    if gitignore_updated:
        # Avoid duplicate paths if a directory appears multiple times.
        unique_paths = sorted(set(gitignore_updated))
        print(f"\n.gitignore updated ({len(unique_paths)}):")
        for p in unique_paths:
            print(f"  {p}")

    if envrc_dirs_to_allow and get_direnv_executable():
        print()
        for project_dir in envrc_dirs_to_allow:
            if run_direnv_allow(project_dir):
                print(f"  direnv allow: {project_dir}")
            else:
                print(f"  [WARN] direnv allow failed in {project_dir}", file=sys.stderr)
    elif envrc_dirs_to_allow:
        if args.ensure_direnv and ensure_direnv_installed_and_hooked():
            print()
            for project_dir in envrc_dirs_to_allow:
                if run_direnv_allow(project_dir):
                    print(f"  direnv allow: {project_dir}")
                else:
                    print(f"  [WARN] direnv allow failed in {project_dir}", file=sys.stderr)
        else:
            print("\n  Run `direnv allow` in each project directory to activate .envrc")

    print(f"\nTo authenticate: aws sso login --sso-session {SSO_SESSION_NAME}")


if __name__ == "__main__":
    main()
