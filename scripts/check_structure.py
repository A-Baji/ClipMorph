#!/usr/bin/env python3
"""Validate the repository's canonical structure policy."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Machine-local OpenCode automation surface (see .gitignore entry).
ALLOWED_ROOT_DIRS = {
    # Machine-local OpenCode automation surface (see the .gitignore entry).
    ".opencode",
    ".agents",
    ".claude",
    ".github",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "build",
    "clipmorph",
    "clipmorph.egg-info",
    "docs",
    "frontend",
    "input",
    "output",
    "quality",
    "scripts",
    "tests",
    "uploads",
}

REQUIRED_ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    "template.env",
}

OPTIONAL_ROOT_FILES = {
    "subtitles.srt",
}

# Machine-local artifacts (local credentials, generated subtitle output) may
# sit at the repo root for local runs.  They are matched by pattern so a new
# key file with a new timestamp never requires editing this policy.  Their
# presence is allowed; tracking them in git never is -- see
# check_local_files_untracked.
OPTIONAL_ROOT_FILE_PATTERNS = {
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
}

REQUIRED_CLIPMORPH_ITEMS = {
    "__init__.py",
    "__main__.py",
    "auth.py",
    "cli.py",
    "desktop_app.py",
    "form_spec.py",
    "job.py",
    "layout.py",
    "preflight.py",
    "transcript.py",
    "workflow.py",
    "web.py",
    "service.py",
    "policy.py",
    "release_notes.py",
    "ui_launcher.py",
}

REQUIRED_CLIPMORPH_DIRS = {
    "conversion_pipeline",
    "ffmpeg",
    "resources",
    "upload_pipeline",
    "web_assets",
}

REQUIRED_DOCS = {
    "CLI_WEB_PARITY.md",
    "PACKAGE_MATRIX.md",
    "PLATFORM_CAPABILITIES.md",
    "RELEASE.md",
    "structure-policy.md",
}


def _optional_file_allowed(name: str) -> bool:
    lower = name.lower()
    if name in OPTIONAL_ROOT_FILES:
        return True
    return any(fnmatch.fnmatch(lower, pattern)
               for pattern in OPTIONAL_ROOT_FILE_PATTERNS)


def find_unexpected_root_entries() -> list[str]:
    entries = {path.name for path in REPO_ROOT.iterdir()}
    unexpected = sorted(
        name for name in entries - ALLOWED_ROOT_DIRS
        if not (name in REQUIRED_ROOT_FILES or _optional_file_allowed(name)))
    return unexpected


def check_local_files_untracked() -> list[str]:
    """Local artifact files that git tracks violate the policy.

    Enforced here so the violation fails the structure check before it can
    reach git.  Outside a git work tree (unit tests patch ``REPO_ROOT`` to a
    plain temporary directory) there is nothing tracked, so the probe passes.
    """
    if not (REPO_ROOT / ".git").exists():
        return []
    candidates = sorted(
        path.name for path in REPO_ROOT.iterdir()
        if path.is_file() and path.name not in REQUIRED_ROOT_FILES
        and _optional_file_allowed(path.name))
    if not candidates:
        return []
    completed = subprocess.run(
        ["git", "ls-files", "--", *candidates],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return []
    return sorted(set(completed.stdout.split()) & set(candidates))


def check_root_layout() -> list[str]:
    problems: list[str] = []
    unexpected = find_unexpected_root_entries()
    if unexpected:
        problems.append(
            "Unexpected top-level entries; prefer the existing repo boundaries: "
            + ", ".join(unexpected)
        )

    missing_files = sorted(name for name in REQUIRED_ROOT_FILES if not (REPO_ROOT / name).exists())
    if missing_files:
        problems.append("Missing required repository files: " + ", ".join(missing_files))

    tracked_local_files = check_local_files_untracked()
    if tracked_local_files:
        problems.append(
            "Local artifact files must not be git-tracked: "
            + ", ".join(tracked_local_files)
        )

    return problems


def check_package_layout() -> list[str]:
    problems: list[str] = []
    clipmorph_root = REPO_ROOT / "clipmorph"
    if not clipmorph_root.is_dir():
        return ["Missing clipmorph package directory."]

    missing_items = sorted(name for name in REQUIRED_CLIPMORPH_ITEMS if not (clipmorph_root / name).exists())
    if missing_items:
        problems.append("Missing expected package modules: " + ", ".join(missing_items))

    missing_dirs = sorted(name for name in REQUIRED_CLIPMORPH_DIRS if not (clipmorph_root / name).is_dir())
    if missing_dirs:
        problems.append("Missing expected package subdirectories: " + ", ".join(missing_dirs))

    return problems


def check_docs_layout() -> list[str]:
    problems: list[str] = []
    docs_root = REPO_ROOT / "docs"
    if not docs_root.is_dir():
        return ["Missing docs directory."]

    missing_docs = sorted(name for name in REQUIRED_DOCS if not (docs_root / name).exists())
    if missing_docs:
        problems.append("Missing expected project docs: " + ", ".join(missing_docs))

    return problems


def check_frontend_layout() -> list[str]:
    problems: list[str] = []
    frontend_root = REPO_ROOT / "frontend"
    if not frontend_root.is_dir():
        return ["Missing frontend directory."]

    if not (frontend_root / "package.json").exists():
        problems.append("frontend/package.json is missing; the frontend app should remain separate from the Python package.")
    if not (frontend_root / "src").is_dir():
        problems.append("frontend/src is missing; the dashboard app should remain in its own app directory.")

    return problems


def check_tests_layout() -> list[str]:
    problems: list[str] = []
    tests_root = REPO_ROOT / "tests"
    if not tests_root.is_dir():
        return ["Missing tests directory."]

    test_files = sorted(p.name for p in tests_root.iterdir() if p.is_file())
    if not test_files:
        problems.append("tests/ should contain the repository's unittest suite.")

    return problems


def main() -> int:
    problems: list[str] = []
    problems.extend(check_root_layout())
    problems.extend(check_package_layout())
    problems.extend(check_docs_layout())
    problems.extend(check_frontend_layout())
    problems.extend(check_tests_layout())

    if problems:
        print("Structure policy check failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("Structure policy check passed.")
    print(f"Repository structure matches the canonical policy under {REPO_ROOT}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
