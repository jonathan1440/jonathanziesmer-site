"""Shared git checkout discovery and commands for gh-spec / gh-build scripts."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def split_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError(f"repo must be OWNER/NAME, got: {repo!r}")
    owner, name = repo.split("/", 1)
    return owner, name


def git_toplevel(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    path = Path(result.stdout.strip())
    return path if path.is_dir() else None


def origin_remote_url(repo_path: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def remote_matches_repo(remote: str, owner: str, name: str) -> bool:
    normalized = remote.removesuffix(".git")
    if f"{owner}/{name}" in normalized:
        return True
    return normalized.endswith(f"/{name}")


def find_local_repo_path(task_repo: str, roots: list[Path]) -> str | None:
    owner, name = split_repo(task_repo)
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        toplevel = git_toplevel(root)
        if toplevel and toplevel.name == name and toplevel not in seen:
            candidates.append(toplevel)
            seen.add(toplevel)
        direct = root / name
        if direct.is_dir() and direct not in seen:
            candidates.append(direct)
            seen.add(direct)
        try:
            for child in root.iterdir():
                if child.is_dir() and child.name == name and child not in seen:
                    candidates.append(child)
                    seen.add(child)
        except OSError:
            continue

    exact: list[Path] = []
    by_name: list[Path] = []
    for path in candidates:
        if not (path / ".git").exists():
            continue
        remote = origin_remote_url(path)
        if not remote:
            continue
        if remote_matches_repo(remote, owner, name):
            exact.append(path)
        elif name in remote:
            by_name.append(path)

    if len(exact) == 1:
        return str(exact[0])
    if len(exact) > 1:
        raise SystemExit(
            f"ambiguous local checkout for {task_repo}: "
            + ", ".join(str(p) for p in exact)
        )
    if len(by_name) == 1:
        return str(by_name[0])
    if len(by_name) > 1:
        raise SystemExit(
            f"ambiguous local checkout for {task_repo} (fork/name match): "
            + ", ".join(str(p) for p in by_name)
        )
    return None


def git_run(
    args: list[str],
    repo_path: str,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        check=check,
    )


def workspace_roots_from_args(args: argparse.Namespace) -> list[Path]:
    roots = [Path(p).resolve() for p in (getattr(args, "workspace_root", None) or [])]
    repo_path = getattr(args, "repo_path", None)
    if repo_path:
        roots.insert(0, Path(repo_path).resolve())
    if not roots:
        cwd = Path.cwd().resolve()
        roots = [cwd, cwd.parent]
    git_root = git_toplevel(roots[0])
    if git_root and git_root not in roots:
        roots.insert(0, git_root)
    return roots


def resolve_repo_checkout(
    github_repo: str,
    roots: list[Path],
    explicit: dict[str, str] | None = None,
) -> str:
    if explicit and github_repo in explicit:
        path = explicit[github_repo]
        if not Path(path).is_dir():
            raise SystemExit(f"checkout path does not exist for {github_repo}: {path}")
        return str(Path(path).resolve())
    found = find_local_repo_path(github_repo, roots)
    if not found:
        raise SystemExit(
            f"no local checkout for {github_repo}; pass --repo-path or --workspace-root"
        )
    return found


def cmd_resolve_checkouts(args: argparse.Namespace) -> int:
    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    if not repos:
        raise SystemExit("--repos required (comma-separated owner/name list)")
    roots = workspace_roots_from_args(args)
    resolved: dict[str, str | None] = {}
    errors: list[str] = []
    for repo in repos:
        try:
            resolved[repo] = find_local_repo_path(repo, roots)
        except SystemExit as exc:
            errors.append(str(exc))
            resolved[repo] = None
    output = {"checkouts": resolved}
    if errors:
        output["errors"] = errors
    print(json.dumps(output, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser(
        "resolve-checkouts",
        help="Map owner/repo list to local git checkout paths",
    )
    resolve.add_argument(
        "--repos",
        required=True,
        help="Comma-separated GitHub repos (owner/name)",
    )
    resolve.add_argument(
        "--workspace-root",
        action="append",
        help="Directory to scan for checkouts (repeatable; default cwd + parent)",
    )
    resolve.add_argument(
        "--repo-path",
        help="Explicit home-repo checkout (prepended to search roots)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "resolve-checkouts":
        return cmd_resolve_checkouts(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
