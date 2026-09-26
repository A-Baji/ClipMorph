"""Markdown sanity check for repository docs.

Detects problems that caused silent doc corruption before:
1. Relative link targets that resolve to missing files.
2. Mojibake sequences left by encoding double-decodes.
3. Duplicated adjacent bullet/line fragments.

Exits 0 when all checked markdown is clean; prints each problem and exits 1
otherwise. Run with `python scripts/check_docs.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MOJIBAKE_RE = re.compile(
    "\ufffd|[\u200b\u2060\ufffe]|\\b\u0226\u0226\u0226\\b|[\u2202\u00c7\u00cc\u00cb\u00c5]{3,}")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MIN_DUPLICATE_LEN = 24


def checked_files() -> list[Path]:
    files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "CHANGELOG.md",
    ]
    files.extend(sorted((REPO_ROOT / "docs").glob("*.md")))
    files.extend(sorted((REPO_ROOT / "quality").glob("*.md")))
    return [path for path in files if path.is_file()]


def relative_target(path: Path, target: str) -> Path | None:
    """Return the repo path for in-repo relative links, else None."""
    if "://" in target or target.startswith(("#", "mailto:", "/")):
        return None
    return (path.parent / target.split("#")[0]).resolve()


def check_file(path: Path, problems: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    repo_relative = path.relative_to(REPO_ROOT).as_posix()

    match = MOJIBAKE_RE.search(text)
    if match:
        problems.append(
            f"{repo_relative}: suspicious characters near index "
            f"{match.start()} ({match.group()!r})")

    for match in LINK_RE.finditer(text):
        target = relative_target(path, match.group(1))
        if target is not None and not target.exists():
            problems.append(
                f"{repo_relative}: broken relative link -> {match.group(1)}")

    previous = ""
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if (stripped.startswith(("-", "*", "|", "#"))
                and len(stripped) >= MIN_DUPLICATE_LEN
                and stripped in previous):
            problems.append(
                f"{repo_relative}:{number}: duplicated bullet fragment "
                f"(repeats line {number - 1})")
        previous = stripped


def main() -> int:
    problems: list[str] = []
    for path in checked_files():
        check_file(path, problems)
    for problem in problems:
        print(f"docs check: {problem}")
    if not problems:
        print("docs check passed.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
