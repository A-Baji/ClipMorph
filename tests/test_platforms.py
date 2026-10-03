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
    SUPPORTED_NATIVE_SCHEDULING,
    SUPPORTED_PLATFORMS,
    build_platform_default_config,
    is_supported_platform,
    native_scheduling_support,
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
PROBE_SCRIPT = REPO_ROOT / "quality" / "research" / "scheduling_probe.py"
METADATA_HEADING = "## Upload metadata rules"
METADATA_SECTION = (METADATA_HEADING, "## Dynamic account rules")
NATIVE_SCHEDULING_HEADING = "## Native publish scheduling"
# A blessed platform records the probe date in its capability cell; a disabled
# one records none, so the two cannot be confused.
PROBE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
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


def documented_native_scheduling(path: Path, heading: str) -> dict[str, str]:
    """Return each platform row's native-scheduling cell from a doc table."""
    section = path.read_text(encoding="utf-8").split(heading, 1)[1]
    cells_by_platform = {}
    for line in section.split("\n## ", 1)[0].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] != "Platform" \
                and not set(cells[0]) <= {"-"}:
            cells_by_platform[cells[0]] = cells[1]
    return cells_by_platform


class PlatformRegistryTests(unittest.TestCase):
    def test_supported_platforms_are_the_documented_five(self):
        self.assertEqual(
            set(SUPPORTED_PLATFORMS),
            {"youtube", "instagram", "tiktok", "twitter", "facebook"})

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
        self.assertTrue(is_supported_platform("Facebook"))
        self.assertFalse(is_supported_platform("linkedin"))

    def test_defaults_cover_every_supported_platform(self):
        defaults = build_platform_default_config()
        self.assertEqual(list(defaults), list(SUPPORTED_PLATFORMS))
        self.assertEqual(defaults["youtube"]["category"], "22")
        self.assertEqual(defaults["youtube"]["privacy_status"], "public")
        self.assertEqual(defaults["instagram"]["share_to_feed"], True)
        self.assertEqual(defaults["tiktok"]["privacy_level"],
                         "PUBLIC_TO_EVERYONE")
        self.assertEqual(PLATFORM_DEFAULT_CONFIG["twitter"], {})
        self.assertEqual(PLATFORM_DEFAULT_CONFIG["facebook"]["content_kind"],
                         "reel")

    def test_resolve_upload_participants_absence_default(self):
        from clipmorph.platforms import resolve_upload_participants
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {},
            "upload": {"skip": False},
        }
        self.assertEqual(
            resolve_upload_participants(config), list(SUPPORTED_PLATFORMS))

    def test_resolve_upload_participants_per_platform_skip(self):
        from clipmorph.platforms import resolve_upload_participants
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {},
            "upload": {"skip": False},
            "platforms": {
                "youtube": {"upload": {"skip": True}},
                "tiktok": {"upload": {"skip": True}},
            },
        }
        self.assertEqual(
            resolve_upload_participants(config),
            ["instagram", "twitter", "facebook"])

    def test_resolve_upload_participants_global_skip_with_override(self):
        from clipmorph.platforms import resolve_upload_participants
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {},
            "upload": {"skip": True},
            "platforms": {
                "youtube": {"upload": {"skip": False}},
            },
        }
        self.assertEqual(
            resolve_upload_participants(config), ["youtube"])

    def test_resolve_upload_participants_all_skipped(self):
        from clipmorph.platforms import resolve_upload_participants
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {},
            "upload": {"skip": True},
        }
        self.assertEqual(resolve_upload_participants(config), [])

    def test_runtime_summary_maps_overrides_onto_defaults(self):
        summary = summarize_runtime_configuration({
            "youtube_privacy_status": "private",
            "youtube_category": "20",
            "tiktok_privacy_level": "SELF_ONLY",
        })
        self.assertEqual(summary["youtube"]["privacy_status"], "private")
        self.assertEqual(summary["youtube"]["category"], "20")
        self.assertEqual(summary["tiktok"]["privacy_level"], "SELF_ONLY")


class NativeSchedulingRegistryTests(unittest.TestCase):
    """`upload.schedule.mode: platform` may only name a probed platform.

    The registry is a single source of truth gated on a maintainer probe, so
    the failure this guards against is claiming a capability the platform has
    not demonstrated: a flipped entry with no probe, or a doc that keeps
    advertising a mode the registry will refuse.
    """

    def test_registry_covers_every_supported_platform(self):
        self.assertEqual(set(SUPPORTED_NATIVE_SCHEDULING),
                         set(SUPPORTED_PLATFORMS))

    def test_helper_mirrors_the_registry_and_rejects_unknown_platforms(self):
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                self.assertEqual(native_scheduling_support(platform),
                                 SUPPORTED_NATIVE_SCHEDULING[platform])
        self.assertFalse(native_scheduling_support("linkedin"))

    def test_every_platform_ships_disabled_until_the_probe_runs(self):
        for platform, enabled in SUPPORTED_NATIVE_SCHEDULING.items():
            with self.subTest(platform=platform):
                self.assertFalse(
                    enabled,
                    f"platform '{platform}' is marked as holding a native "
                    "publication; run quality/research/scheduling_probe.py "
                    "first, then flip the registry and the capability doc "
                    "together")

    def test_capability_doc_cell_matches_the_registry(self):
        cells = documented_native_scheduling(CAPABILITIES_DOC,
                                             NATIVE_SCHEDULING_HEADING)
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                if platform not in cells:
                    self.fail(
                        f"platform '{platform}' missing from "
                        f"'{repo_relative(CAPABILITIES_DOC)}' "
                        f"{NATIVE_SCHEDULING_HEADING} table")
                cell = cells[platform]
                enabled = SUPPORTED_NATIVE_SCHEDULING[platform]
                if enabled:
                    self.assertIn("Enabled", cell)
                    self.assertTrue(
                        PROBE_DATE.search(cell),
                        f"an enabled '{platform}' row must record the probe "
                        f"date; found {cell!r}")
                else:
                    self.assertNotIn("Enabled", cell)
                    self.assertIsNone(
                        PROBE_DATE.search(cell),
                        f"'{platform}' is disabled in the registry, so its row "
                        f"must not claim a probe date; found {cell!r}")

    def test_probe_script_and_registry_doc_contract_stay_linked(self):
        # The gate is only actionable if the probe the error message names
        # exists and still tells the maintainer which two places to change.
        self.assertTrue(PROBE_SCRIPT.is_file(),
                        f"{repo_relative(PROBE_SCRIPT)} must exist: the "
                        "submission error points maintainers at it")
        probe = PROBE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("SUPPORTED_NATIVE_SCHEDULING", probe)
        self.assertIn(NATIVE_SCHEDULING_HEADING.lstrip("# "), probe)


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

    def test_adapter_credentials_renew_at_attempt_time(self):
        """Credentials that expire are re-derived or refreshed at attempt time.

        A maintainer's rule: any platform whose credentials expire renews
        them at attempt time with the platform's interactive authorization
        fallback, so an attempt never fails with a stale token that a fresh
        one would pass (a persisted `''` expiry answered 401 at upload time
        even though a valid refresh token was stored). Facebook's stored
        credential is a long-lived (finite, roughly 60 days) user token
        from which the adapter derives the Page token per run, and it
        documents that; the adapter's source naming its strategy is the
        mechanical check.
        """
        for platform in SUPPORTED_PLATFORMS:
            with self.subTest(platform=platform):
                module_path = ADAPTER_DIRECTORY / f"{platform}.py"
                text = module_path.read_text(encoding="utf-8").lower()
                if not any(strategy in text
                           for strategy in ("refresh", "long-lived")):
                    self.fail_missing_renewal(platform, repo_relative(module_path))

    def fail_missing_renewal(self, platform, location):
        self.fail(
            f"platform '{platform}' in '{location}' has no credential "
            "renewal strategy; a platform whose credentials expire must "
            "re-authenticate at attempt time (refresh a stored token, then "
            "the platform's interactive authorization fallback), and a "
            "non-expiring credential must document that; follow "
            "docs/PLATFORM_EXTENSION_GUIDE.md")

    def test_guard_reports_a_platform_missing_from_a_touchpoint(self):
        # Driven with a copy of the registry, so the failure path is proved
        # without mutating a repository file.
        guard = PlatformCoverageDriftTests()
        with self.assertRaises(AssertionError) as caught:
            guard.assert_platform_in(
                CAPABILITIES_DOC, platforms=(*SUPPORTED_PLATFORMS, "linkedin"))

        self.assertIn("platform 'linkedin' missing from "
                      "'docs/PLATFORM_CAPABILITIES.md'",
                      str(caught.exception))


if __name__ == "__main__":
    unittest.main()
