"""Guard the documented command-line surface.

Two checks keep ``docs/CLI_WEB_PARITY.md`` and the parser in step: every
command's rendered ``--help`` is compared against an explicit manifest of its
options, arguments, and subcommands, and the CLI contract table in the parity
document is checked for flags and commands the parser must provide.
"""

import contextlib
import io
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import typer

from clipmorph.cli import app
from clipmorph.cli import run_cli

PARITY_DOCUMENT = Path(__file__).resolve().parents[1] / "docs" / "CLI_WEB_PARITY.md"

# rich reads COLUMNS when stdout is not a terminal, so a wide value keeps the
# help panels unwrapped and the panel cells parseable.
WIDE_TERMINAL = {"COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"}

# Global options are declared once in clipmorph.cli, on the root callback and
# on every leaf command, so they are accepted before a group and after a leaf
# command but not between a group and its subcommand. Every leaf manifest entry
# therefore ends with them; group entries carry their own options only.
GLOBAL_OPTIONS = ("--data-dir", "--app-config")

# One entry per command: command path -> (options, subcommands, arguments).
# Options and subcommands are matched exactly; arguments are
# ``(name, required)`` pairs. ``--help`` is provided by the parser and omitted.
COMMANDS: dict[tuple[str, ...], tuple[tuple[str, ...], tuple[str, ...],
                                     tuple[tuple[str, bool], ...]]] = {
    (): (GLOBAL_OPTIONS, ("init", "web", "auth", "job", "layout"), ()),
    ("init",): (("--config-path",) + GLOBAL_OPTIONS, (), ()),
    ("web",): (("--host", "--port") + GLOBAL_OPTIONS, (), ()),
    ("auth",): ((), ("status", "set", "twitter"), ()),
    ("auth", "status"): (("--json",) + GLOBAL_OPTIONS, (), ()),
    ("auth", "set"): (GLOBAL_OPTIONS, (), (("platform", True),)),
    ("auth", "twitter"): (GLOBAL_OPTIONS, (), ()),
    ("job",): ((), ("create", "list", "get", "update", "delete",
                    "resume", "cancel", "review", "render", "upload",
                    "artifacts"), ()),
    ("job", "create"): (("--job-configs", "--config-dir", "--dry-run", "--yes",
                         "--json") + GLOBAL_OPTIONS, (),
                        (("source", True),)),
    ("job", "list"): (("--status", "--json") + GLOBAL_OPTIONS, (), ()),
    ("job", "get"): (("--json",) + GLOBAL_OPTIONS, (), (("job_id", True),)),
    ("job", "update"): (("--patch", "--reopen", "--json") + GLOBAL_OPTIONS, (),
                        (("job_id", True),)),
    ("job", "delete"): (("--yes",) + GLOBAL_OPTIONS, (), (("job_id", True),)),
    ("job", "resume"): (GLOBAL_OPTIONS, (), (("job_id", True),)),
    ("job", "cancel"): (("--yes", "--json") + GLOBAL_OPTIONS, (),
                        (("job_id", True),)),
    ("job", "review"): (("--edits", "--accept", "--reopen", "--json")
                        + GLOBAL_OPTIONS, (),
                        (("job_id", True), ("checkpoint", True))),
    ("job", "render"): (GLOBAL_OPTIONS, (), (("job_id", True),)),
    ("job", "upload"): (("--platform", "--attempt-id", "--artifact-id",
                         "--confirm-historical-artifact", "--json")
                        + GLOBAL_OPTIONS, (), (("upload_args", False),)),
    ("job", "artifacts",): ((), ("list", "preview", "download",
                                 "rename", "delete", "prune"), ()),
    ("job", "artifacts", "list"): (("--json",) + GLOBAL_OPTIONS, (),
                                    (("job_id", True),)),
    ("job", "artifacts", "preview"): (GLOBAL_OPTIONS, (),
                                       (("job_id", True), ("artifact_id", True))),
    ("job", "artifacts", "download"): (("--destination",) + GLOBAL_OPTIONS, (),
                                        (("job_id", True), ("artifact_id", True))),
    ("job", "artifacts", "rename"): (("--name",) + GLOBAL_OPTIONS, (),
                                      (("job_id", True), ("artifact_id", True))),
    ("job", "artifacts", "delete"): (("--yes",) + GLOBAL_OPTIONS, (),
                                      (("job_id", True), ("artifact_id", True))),
    ("job", "artifacts", "prune"): (("--json",) + GLOBAL_OPTIONS, (),
                                    (("job_id", True),)),
    ("layout",): ((), ("list", "create", "get", "delete"), ()),
    ("layout", "list"): (("--json",) + GLOBAL_OPTIONS, (), ()),
    ("layout", "create"): (("--json",) + GLOBAL_OPTIONS, (),
                           (("configuration", True),)),
    ("layout", "get"): (("--json",) + GLOBAL_OPTIONS, (), (("layout_id", True),)),
    ("layout", "delete"): (("--yes",) + GLOBAL_OPTIONS, (), (("layout_id", True),)),
}

# typer 0.27 renders the upload argument's metavar in the Arguments panel where
# older typer renders the parameter name; accept either display.
ARGUMENT_DISPLAY_ALIASES: dict[tuple[str, ...],
                              set[tuple[tuple[str, bool], ...]]] = {
    ("job", "upload"): {(("ID | RETRY ID PLATFORM", False),)},
}

# rich downgrades rounded corners to square on legacy Windows consoles, so
# accept both families; the side border is the same glyph either way.
PANEL_BORDER_TOPS = ("\u250c", "\u256d")
PANEL_BORDER_BOTTOMS = ("\u2514", "\u2570")
PANEL_BORDER_SIDE = "\u2502"
CELL_SEPARATOR = re.compile(r"\s{2,}")
OPTION_PATTERN = re.compile(r"^--[a-z][a-z0-9-]*$")
ARGUMENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DOCUMENTED_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def help_text(path: tuple[str, ...]) -> str:
    """Return one command's rendered ``--help`` output."""
    output = io.StringIO()
    with patch.dict(os.environ, WIDE_TERMINAL), contextlib.redirect_stdout(output):
        code = run_cli([*path, "--help"])
    if code != 0:
        raise AssertionError(f"clipmorph {' '.join(path)} --help exited {code}")
    return output.getvalue()



def help_text_shortcut(path: tuple[str, ...]) -> str:
    """Return one command's rendered ``-h`` output."""
    output = io.StringIO()
    with patch.dict(os.environ, WIDE_TERMINAL), contextlib.redirect_stdout(output):
        code = run_cli([*path, "-h"])
    if code != 0:
        raise AssertionError(f"clipmorph {' '.join(path)} -h exited {code}")
    return output.getvalue()


def panel_rows(help_output: str, panel: str) -> list[list[str]]:
    """Return the cell groups of one help panel, top to bottom."""
    rows: list[list[str]] = []
    inside = False
    for line in help_output.splitlines():
        stripped = line.strip()
        if not inside:
            inside = (stripped.startswith(PANEL_BORDER_TOPS)
                      and f" {panel} " in stripped)
            continue
        if stripped.startswith(PANEL_BORDER_BOTTOMS):
            break
        if not stripped.startswith(PANEL_BORDER_SIDE):
            break
        body = stripped.strip(PANEL_BORDER_SIDE).strip()
        rows.append([cell for cell in CELL_SEPARATOR.split(body) if cell])
    return rows


def options_of(help_output: str) -> tuple[str, ...]:
    return tuple(sorted(cell for row in panel_rows(help_output, "Options")
                        for cell in row if OPTION_PATTERN.match(cell)
                        and cell != "--help"))


def subcommands_of(help_output: str) -> tuple[str, ...]:
    return tuple(sorted(cell for row in panel_rows(help_output, "Commands")
                        for cell in row if " " not in cell))


def arguments_of(help_output: str) -> tuple[tuple[str, bool], ...]:
    arguments = []
    for row in panel_rows(help_output, "Arguments"):
        if row[0] == "*":
            required, name = True, row[1]
        elif ARGUMENT_PATTERN.match(row[0]):
            required, name = False, row[0]
        elif len(row) >= 2 and row[1].startswith("<"):
            # typer 0.27 renders the declared metavar (e.g. the variadic
            # upload argument) in place of the parameter name.
            required, name = False, row[0]
        else:
            continue
        arguments.append((name, required))
    return tuple(arguments)


def walk_click(command, prefix: tuple[str, ...] = ()):
    """Yield every command path of the command tree typer exposes.

    typer 0.27 vendored its click clone, so the tree is walked through the
    click-like ``.commands`` mapping every group exposes instead of importing
    a click module directly.
    """
    yield prefix
    children = getattr(command, "commands", None)
    if children:
        for name, child in children.items():
            yield from walk_click(child, (*prefix, name))


class CommandSurfaceTests(unittest.TestCase):
    def test_parser_exposes_exactly_the_manifest_commands(self):
        command_paths = set(walk_click(typer.main.get_command(app)))

        self.assertEqual(command_paths, set(COMMANDS))

    def test_every_command_help_matches_the_manifest(self):
        for path, (options, subcommands, arguments) in COMMANDS.items():
            with self.subTest(command=" ".join(["clipmorph", *path])):
                rendered = help_text(path)
                self.assertEqual(options_of(rendered), tuple(sorted(options)))
                self.assertEqual(subcommands_of(rendered),
                                 tuple(sorted(subcommands)))
                accepted = {arguments} | ARGUMENT_DISPLAY_ALIASES.get(path, set())
                self.assertIn(arguments_of(rendered), accepted)


class ParityDocumentTests(unittest.TestCase):
    def setUp(self):
        document = PARITY_DOCUMENT.read_text(encoding="utf-8")
        self.contract = document.split("## CLI Contract", 1)[1].split("\n## ", 1)[0]

    def assert_documented(self, text: str, label: str) -> None:
        self.assertTrue(text in self.contract, f"{label} is undocumented")

    def test_documented_flags_exist_on_a_command(self):
        known = {option for options, _, _ in COMMANDS.values() for option in options}
        known.add("--help")

        for flag in sorted(set(DOCUMENTED_FLAG.findall(self.contract))):
            with self.subTest(flag=flag):
                self.assertIn(flag, known)

    def test_every_manifest_command_is_documented(self):
        for path in COMMANDS:
            if not path:
                continue
            with self.subTest(command=" ".join(path)):
                self.assert_documented(" ".join(path[-2:]), " ".join(path))

    def test_every_command_group_is_documented(self):
        groups = {path for path in COMMANDS
                  if path and path in {child[:len(path)]
                                       for child in COMMANDS if len(child) > len(path)}}

        for group in sorted(groups):
            with self.subTest(group=" ".join(group)):
                self.assert_documented(" ".join(group), " ".join(group))

    def test_json_escape_hatch_is_documented(self):
        for path, (options, _, _) in COMMANDS.items():
            if "--json" not in options:
                continue
            with self.subTest(command=" ".join(path)):
                self.assert_documented("--json", " ".join(path))


class HelpShortcutTests(unittest.TestCase):
    """argparse answered ``-h`` too, so both spellings must keep working."""

    def test_short_help_flag_is_accepted_on_every_command(self):
        for path in COMMANDS:
            with self.subTest(command=" ".join(["clipmorph", *path])):
                rendered = help_text_shortcut(path)
                self.assertIn("Usage", rendered)
                self.assertIn("-h", rendered)


if __name__ == "__main__":
    unittest.main()
