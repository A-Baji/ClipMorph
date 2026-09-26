import unittest

from clipmorph.platforms import (
    PLATFORM_DEFAULT_CONFIG,
    SUPPORTED_PLATFORMS,
    build_platform_default_config,
    enabled_platforms,
    is_supported_platform,
)
from clipmorph.cli import summarize_runtime_configuration
from clipmorph.policy import CAPABILITY_MATRIX


class PlatformRegistryTests(unittest.TestCase):
    def test_supported_platforms_are_the_documented_four(self):
        self.assertEqual(
            set(SUPPORTED_PLATFORMS),
            {"youtube", "instagram", "tiktok", "twitter"})

    def test_every_supported_platform_has_a_policy_rule(self):
        for platform in SUPPORTED_PLATFORMS:
            self.assertIn(platform, CAPABILITY_MATRIX)

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


if __name__ == "__main__":
    unittest.main()
