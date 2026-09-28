"""Platform registry tests and the mechanical platform drift guard.

`PlatformCoverageDriftTests` is the enforcement half of
`docs/PLATFORM_EXTENSION_GUIDE.md`: one case per touchpoint a platform has to
reach, so a new platform cannot land half-wired. The registry cases own the
coupling property, which is why the guard lives here rather than in
`tests/test_web.py`.
"""

import importlib
import inspect
import re
import unittest
from pathlib import Path

from clipmorph.auth import AUTH_ENVIRONMENT_KEYS
from clipmorph.cli import summarize_runtime_configuration
from clipmorph.platforms import (
    PLATFORM_DEFAULT_CONFIG,
    PLATFORM_TITLE,
    SUPPORTED_PLATFORMS,
    build_platform_default_config,
    enabled_platforms,
    is_supported_platform,
)
from clipmorph.policy import CAPABILITY_MATRIX
from clipmorph.preflight import PLATFORM_CREDENTIALS

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES_DOC = REPO_ROOT / "docs" / "PLATFORM_CAPABILITIES.md"
EXTENSION_GUIDE_DOC = REPO_ROOT / "docs" / "PLATFORM_EXTENSION_GUIDE.md"
PARITY_DOC = REPO_ROOT / "docs" / "CLI_WEB_PARITY.md"
FRONTEND_APP = REPO_ROOT / "frontend" / "src" / "App.svelte"
WEB_MODULE = REPO_ROOT / "clipmorph" / "web.py"
ADAPTER_DIRECTORY = REPO_ROOT / "clipmorph" / "upload_pipeline" / "platforms"
ADAPTER_PACKAGE = "clipmorph.upload_pipeline.platforms"
METADATA_HEADING = "## Upload metadata rules"
METADATA_SECTION = (METADATA_HEADING, "## Dynamic account rules")
# The parity contract is pinned to its CLI section: an API row may stay generic.
CLI_CONTRACT_SECTION = ("## CLI Contract", "## API Contract")
# Guide status markers: "- [x] youtube" ticks, "- [ ] facebook (...)" does not.
GUIDE_MARKER = re.compile(r"^-\s*\[([x ])\]\s+([a-z0-9_]+)\b", re.MULTILINE)


def repo_relative(path: Path) -> str:
    """Return a file's repository-relative path for failure messages."""
    return path.relative_to(REPO_ROOT).as_posix()


def token_pattern(token: str) -> re.Pattern[str]:
    """Match a platform token as a standalone word, not inside a path or URL.

    The capability doc already links `developers.facebook.com` for Instagram, so
    a plain substring search would call Facebook documented the moment someone
    adds it. A token only counts as documented when it stands on its own.
    """
    return re.compile(rf"(?<![\w.@-]){re.escape(token)}(?![\w])", re.IGNORECASE)


def documented_content_modes(path: Path, heading: str) -> dict[str, str]:
    """Return the content_mode each platform row documents, keyed by platform."""
    section = path.read_text(encoding="utf-8").split(heading, 1)[1]
    modes = {}
    for line in section.split("## ", 1)[0].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] != "Platform" \
                and not set(cells[0]) <= {"-"}:
            modes[cells[0]] = cells[1]
    return modes


class PlatformRegistryTests(unittest.TestCase):
    def test_supported_platforms_are_the_documented_four(self):
        self.assertEqual(
            set(SUPPORTED_PLATFORMS),
            {"youtube", "instagram", "tiktok", "twitter"})

    def test_every_supported_platform_has_a_policy_rule(self):
        for platform in SUPPORTED_PLATFORMS:
            self.assertIn(platform, CAPABILITY_MATRIX)

    def test_guide_lists_exactly_supported_platforms(self):
        markers = GUIDE_MARKER.findall(
            EXTENSION_GUIDE_DOC.read_text(encoding="utf-8"))
        self.assertTrue(
            markers, f"{EXTENSION_GUIDE_DOC.name} must mark its platforms with "
                     "- [x] / - [ ] status markers")
        ticked = {platform for state, platform in markers if state == "x"}
        self.assertEqual(
            ticked, set(SUPPORTED_PLATFORMS),
            f"{EXTENSION_GUIDE_DOC.name} must tick exactly the platforms in "
            "clipmorph/platforms.py::SUPPORTED_PLATFORMS")

    def test_membership_helper_is_case_insensitive(self):
        self.assertTrue(is_supported_platform("YouTube"))
        self.assertFalse(is_supported_platform("facebook"))

    def test_defaults_cover_every_supported_platform(self):
        defaults = build_platform_default_config()
        self.assertEqual(list(defaults), list(SUPPORTED_PLATFORMS))
        self.assertEqual(defaults["youtube"]["category"], "22")
        self.assertEqual(defaults["youtube"]["privacy_status"], "public")
        self.assertEqual(defaults["instagram"]["share_to_feed"], True)
        self.assertEqual(defaults["tiktok"]["privacy_level"],
                         "PUBLIC_TO_EVERYONE")
        self.assertEqual(PLATFORM_DEFAULT_CONFIG["twitter"], {})

    def test_empty_include_means_all_and_exclude_prunes(self):
        self.assertEqual(enabled_platforms({}), list(SUPPORTED_PLATFORMS))
        self.assertEqual(
            enabled_platforms({"include": []}), list(SUPPORTED_PLATFORMS))
        self.assertEqual(
            enabled_platforms({"include": ["YouTube"], "exclude": ["youtube"]}),
            [])

    def test_include_selection_is_ordered_and_deduplicated(self):
        resolved = enabled_platforms({"include": ["twitter", "youtube", "youtube"]})
        self.assertEqual(resolved, ["twitter", "youtube"])

    def test_runtime_summary_maps_overrides_onto_defaults(self):
        summary = summarize_runtime_configuration({
            "youtube_privacy_status": "private",
            "youtube_category": "20",
            "tiktok_privacy_level": "SELF_ONLY",
        })
        self.assertEqual(summary["youtube"]["privacy_status"], "private")
        self.assertEqual(summary["youtube"]["category"], "20")
        self.assertEqual(summary["tiktok"]["privacy_level"], "SELF_ONLY")


class PlatformCoverageDriftTests(unittest.TestCase):
    """Every supported platform must reach every touchpoint, or CI fails.

    One case per touchpoint named in `docs/PLATFORM_EXTENSION_GUIDE.md`. The
    messages name the platform and the file, so the failure is the instruction
    for the next step of the guide.
    """

    def assert_platform_in(self, path, *, platforms=None, section=None):
        """Fail unless every platform is referenced in the file at `path`.

        A platform matches on its registry id or on its display title, which is
        how the `"twitter"` / "Twitter/X" alias is accepted, and it must appear
        as a standalone token rather than inside a longer name or URL. `section`
        pins the search to the text between two headings. `platforms` defaults
        to the registry and exists so the guard's own failure mode can be
        exercised against a copy of it without touching repository files.
        """
        text = path.read_text(encoding="utf-8")
        if section:
            heading, following = section
            self.assertIn(heading, text,
                          f"{repo_relative(path)} must document {heading!r}")
            text = text.split(heading, 1)[1].split(following, 1)[0]
        for platform in SUPPORTED_PLATFORMS if platforms is None else platforms:
            tokens = (platform, PLATFORM_TITLE.get(platform, platform))
            with self.subTest(platform=platform):
                if not any(token_pattern(token).search(text) for token in tokens):
                    self.fail_missing(platform, repo_relative(path))

    def assert_registered(self, mapping, location):
        """Fail with the same actionable message for an in-memory touchpoint."""
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                if platform not in mapping:
                    self.fail_missing(platform, location)

    def fail_missing(self, platform, location):
        self.fail(
            f"platform '{platform}' missing from '{location}'; add the "
            "platform there and follow docs/PLATFORM_EXTENSION_GUIDE.md")

    def test_registry_declares_title_and_defaults_for_every_platform(self):
        self.assert_registered(PLATFORM_TITLE,
                               "clipmorph/platforms.py::PLATFORM_TITLE")
        self.assert_registered(
            PLATFORM_DEFAULT_CONFIG,
            "clipmorph/platforms.py::PLATFORM_DEFAULT_CONFIG")
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertTrue(
                    PLATFORM_TITLE[platform].strip(),
                    f"platform '{platform}' has an empty display title in "
                    "'clipmorph/platforms.py::PLATFORM_TITLE'")

    def test_policy_matrix_documents_every_platform(self):
        self.assert_registered(CAPABILITY_MATRIX,
                               "clipmorph/policy.py::CAPABILITY_MATRIX")
        self.assert_platform_in(CAPABILITIES_DOC, section=METADATA_SECTION)
        modes = documented_content_modes(CAPABILITIES_DOC, METADATA_HEADING)
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                if platform not in modes:
                    self.fail_missing(platform,
                                      f"{repo_relative(CAPABILITIES_DOC)} "
                                      f"{METADATA_HEADING} table")
                self.assertEqual(modes[platform],
                                 CAPABILITY_MATRIX[platform].content_mode)

    def test_capability_doc_documents_every_platform(self):
        self.assert_platform_in(CAPABILITIES_DOC)

    def test_extension_guide_marks_every_platform(self):
        self.assert_platform_in(EXTENSION_GUIDE_DOC)

    def test_parity_cli_rows_reference_every_platform(self):
        self.assert_platform_in(PARITY_DOC, section=CLI_CONTRACT_SECTION)

    def test_frontend_platforms_const_lists_every_platform(self):
        self.assert_platform_in(FRONTEND_APP)

    def test_web_credential_surface_covers_every_platform(self):
        # One generic route serves every platform, so web.py needs no
        # per-platform edit; the platform set it reports is the auth schema.
        self.assertIn(
            "/api/v1/credentials/{platform}",
            WEB_MODULE.read_text(encoding="utf-8"),
            "clipmorph/web.py must keep one generic credential route")
        self.assert_registered(AUTH_ENVIRONMENT_KEYS,
                               "clipmorph/auth.py::AUTH_ENVIRONMENT_KEYS")

    def test_preflight_credentials_cover_every_platform(self):
        # Preflight indexes this map by platform id, so a missing entry is a
        # KeyError at upload time rather than a warning.
        self.assert_registered(PLATFORM_CREDENTIALS,
                               "clipmorph/preflight.py::PLATFORM_CREDENTIALS")

    def test_cli_defaults_mapping_covers_every_platform(self):
        self.assert_registered(
            summarize_runtime_configuration({}),
            "clipmorph/cli.py::summarize_runtime_configuration")

    def test_adapter_module_and_pipeline_keyword_exist_for_every_platform(self):
        # Imported here so the registry cases above stay import-light.
        from clipmorph.upload_pipeline import UploadPipeline
        from clipmorph.upload_pipeline.platforms import BaseUploadPipeline

        parameters = inspect.signature(UploadPipeline.__init__).parameters
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                module_path = ADAPTER_DIRECTORY / f"{platform}.py"
                if not module_path.is_file():
                    self.fail_missing(platform, repo_relative(module_path))
                module = importlib.import_module(f"{ADAPTER_PACKAGE}.{platform}")
                adapters = [
                    value for value in vars(module).values()
                    if isinstance(value, type)
                    and issubclass(value, BaseUploadPipeline)
                    and value is not BaseUploadPipeline]
                self.assertTrue(
                    adapters, f"{module_path.name} must define a "
                              "BaseUploadPipeline subclass")
                self.assertIn(
                    platform, parameters,
                    f"UploadPipeline must accept a '{platform}' keyword so a "
                    f"submission can enable '{platform}'")

    def test_guard_reports_a_platform_missing_from_a_touchpoint(self):
        # Driven with a copy of the registry, so the failure path is proved
        # without mutating a repository file.
        guard = PlatformCoverageDriftTests()
        with self.assertRaises(AssertionError) as caught:
            guard.assert_platform_in(
                CAPABILITIES_DOC, platforms=(*SUPPORTED_PLATFORMS, "facebook"))

        self.assertIn("platform 'facebook' missing from "
                      "'docs/PLATFORM_CAPABILITIES.md'",
                      str(caught.exception))


if __name__ == "__main__":
    unittest.main()
