#!/usr/bin/env python3
"""Validate the repository's canonical structure policy."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_ROOT_DIRS = {
    ".agents",
    ".claude",
    ".github",
    ".git",
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
    ".env",
    "subtitles.srt",
    "clipmorph-version-manager.2025-10-15.private-key.pem",
}

ALLOWED_ROOT_FILES = REQUIRED_ROOT_FILES | OPTIONAL_ROOT_FILES

REQUIRED_CLIPMORPH_ITEMS = {
    "__init__.py",
    "__main__.py",
    "auth.py",
    "cli.py",
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


def find_unexpected_root_entries() -> list[str]:
    entries = {path.name for path in REPO_ROOT.iterdir()}
    unexpected = sorted(entries - ALLOWED_ROOT_DIRS - ALLOWED_ROOT_FILES)
    return unexpected


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
