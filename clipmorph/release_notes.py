"""Extract version-specific release notes from the project changelog."""

import argparse
import re
from pathlib import Path


def extract_release_notes(changelog: str, version: str) -> str:
    """Return the changelog section for ``version`` without adjacent releases."""
    normalized_version = version.removeprefix("v")
    heading = re.compile(
        rf"^##\s+(?:\[)?v?{re.escape(normalized_version)}(?:\])?(?:\s|$).*?$",
        re.MULTILINE,
    )
    match = heading.search(changelog)
    if match is None:
        raise ValueError(f"No changelog notes found for version {normalized_version}.")

    next_heading = re.compile(r"^##\s+", re.MULTILINE).search(changelog, match.end())
    end = next_heading.start() if next_heading else len(changelog)
    return changelog[match.start():end].strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("changelog", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    notes = extract_release_notes(
        args.changelog.read_text(encoding="utf-8"), args.version
    )
    args.output.write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()