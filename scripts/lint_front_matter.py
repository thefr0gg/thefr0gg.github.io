"""Validate the TOML front matter of every page under content/.

Usage: python scripts/lint_front_matter.py [content-dir]
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path

REQUIRED = {
    "blog": ("title", "date", "tags"),
    "projects": ("title", "date", "summary"),
}
URL_FIELDS = ("github", "website", "link")
FRONT_MATTER = re.compile(r"\A\+\+\+\r?\n(.*?)\r?\n\+\+\+\r?\n", re.DOTALL)


def lint(path: Path, root: Path) -> list[str]:
    match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        return ["missing +++ TOML front matter"]
    try:
        meta = tomllib.loads(match.group(1))
    except tomllib.TOMLDecodeError as exc:
        return [f"invalid TOML front matter: {exc}"]

    errors = []
    section = path.relative_to(root).parts[0]
    for field in REQUIRED.get(section, ("title",)):
        if not meta.get(field):
            errors.append(f"missing required field '{field}'")
    if "date" in meta and not isinstance(meta["date"], datetime):
        errors.append("'date' must be a TOML datetime")
    if "tags" in meta and not (
        isinstance(meta["tags"], list)
        and all(isinstance(t, str) and t == t.lower() for t in meta["tags"])
    ):
        errors.append("'tags' must be a list of lowercase strings")
    if meta.get("draft") is True:
        errors.append("page is still marked draft = true")
    for field in URL_FIELDS:
        value = meta.get(field)
        if value and not str(value).startswith(("https://", "http://")):
            errors.append(f"'{field}' must be an http(s) URL")
    return errors


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "content")
    failed = False
    for path in sorted(root.rglob("*.md")):
        for error in lint(path, root):
            failed = True
            print(f"{path}: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
