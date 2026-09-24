import unittest

from clipmorph.release_notes import extract_release_notes


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_only_the_requested_version_section(self):
        changelog = """# Changelog

## [1.2.3] - 2026-09-24

### Added

- The release-specific change.

## [1.2.2] - 2026-09-23

- An older change.
"""

        self.assertEqual(
            extract_release_notes(changelog, "1.2.3"),
            "## [1.2.3] - 2026-09-24\n\n### Added\n\n- The release-specific change.\n",
        )

    def test_rejects_a_version_without_changelog_notes(self):
        with self.assertRaisesRegex(ValueError, "1.2.4"):
            extract_release_notes("# Changelog\n", "1.2.4")