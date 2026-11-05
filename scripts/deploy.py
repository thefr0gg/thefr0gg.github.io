"""Build the Hugo site and publish it to a branch (for GitHub Pages "Deploy from a branch").

Usage:
    poetry run python scripts/deploy.py                 # build and push to the "gh-pages" branch
    poetry run python scripts/deploy.py --branch pages  # use another branch name
    poetry run python scripts/deploy.py --no-push       # build and commit locally, don't push

The site is built into a temporary directory (``public/`` is not touched), then
committed on top of the target branch using a temporary git worktree, so your
working tree and the branch you have checked out are never modified. If the branch
doesn't exist yet it is created as an orphan branch with no shared history.

Then, in the GitHub repository: Settings -> Pages -> Build and deployment ->
Source: "Deploy from a branch" -> pick the branch and the "/ (root)" folder.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(
    cmd: list[str], cwd: Path = ROOT, check: bool = True, quiet: bool = False
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if result.stdout.strip() and not quiet:
        print(result.stdout.rstrip())
    if check and result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        sys.exit(f"error: command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def git(
    *args: str, cwd: Path = ROOT, check: bool = True, quiet: bool = False
) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd, check=check, quiet=quiet)


def rmtree(path: Path) -> None:
    """Remove a directory tree, including read-only files (git objects on Windows)."""

    def onerror(func, p, _exc):  # noqa: ANN001
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=onerror)


def find_hugo() -> list[str]:
    hugo = shutil.which("hugo")
    if hugo:
        return [hugo]
    if shutil.which("poetry"):
        return ["poetry", "run", "hugo"]
    sys.exit("error: hugo not found; install it or run this script with `poetry run`")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--branch", default="gh-pages", help="branch to publish to (default: gh-pages)")
    parser.add_argument("--remote", default="origin", help="git remote to push to (default: origin)")
    parser.add_argument("--base-url", default=None, help="override baseURL (default: the one in hugo.toml)")
    parser.add_argument("-m", "--message", default=None, help="commit message")
    parser.add_argument("--no-push", action="store_true", help="commit to the local branch but don't push")
    args = parser.parse_args()

    if args.branch in ("main", "master"):
        sys.exit(f"error: refusing to publish build output to '{args.branch}'")

    dirty = git("status", "--porcelain", check=False, quiet=True).stdout.strip()
    if dirty:
        print("warning: you have uncommitted changes; they will be part of the build\n")
    source = git("rev-parse", "--short", "HEAD").stdout.strip()

    tmp = Path(tempfile.mkdtemp(prefix="hugo-deploy-"))
    site, worktree = tmp / "site", tmp / "worktree"
    try:
        # 1. Build into a temporary directory.
        build = [*find_hugo(), "--gc", "--minify", "--destination", str(site)]
        if args.base_url:
            build += ["--baseURL", args.base_url]
        run(build)
        if not (site / "index.html").exists():
            sys.exit("error: the build produced no index.html")

        # 2. Check out the target branch in a temporary worktree.
        has_remote = bool(git("fetch", args.remote, args.branch, check=False).returncode == 0)
        if has_remote:
            git("worktree", "add", "-B", args.branch, str(worktree), f"{args.remote}/{args.branch}")
        else:
            print(f"\nBranch '{args.branch}' not found on '{args.remote}'; creating it.\n")
            git("worktree", "add", "--detach", str(worktree))
            git("checkout", "--orphan", args.branch, cwd=worktree)
            git("rm", "-rf", "--quiet", ".", cwd=worktree, check=False)

        # 3. Replace the branch contents with the fresh build.
        for entry in worktree.iterdir():
            if entry.name == ".git":
                continue
            rmtree(entry) if entry.is_dir() else entry.unlink()
        shutil.copytree(site, worktree, dirs_exist_ok=True)
        (worktree / ".nojekyll").touch()  # serve files as-is, skip GitHub's Jekyll step

        # 4. Commit and push.
        git("add", "-A", cwd=worktree)
        if not git("status", "--porcelain", cwd=worktree, quiet=True).stdout.strip():
            print("\nNothing changed since the last deploy; the branch is already up to date.")
            return
        message = args.message or f"Deploy site from {source}"
        git("commit", "--quiet", "-m", message, cwd=worktree)
        if args.no_push:
            print(f"\nCommitted to local branch '{args.branch}' (not pushed).")
        else:
            git("push", args.remote, f"{args.branch}:{args.branch}", cwd=worktree)
            print(f"\nDeployed to '{args.remote}/{args.branch}'.")
    finally:
        if worktree.exists():
            git("worktree", "remove", "--force", str(worktree), check=False)
        git("worktree", "prune", check=False)
        rmtree(tmp) if tmp.exists() else None


if __name__ == "__main__":
    main()
