"""Policy-owned upload metadata composition and its documented rule set."""

import unittest
from pathlib import Path

from clipmorph.policy import (
    CAPABILITY_MATRIX,
    EMPTY_DESCRIPTION,
    CapabilityRule,
    build_platform_metadata,
    validate_artifact,
)

DOC_PATH = (Path(__file__).resolve().parent.parent / "docs"
            / "PLATFORM_CAPABILITIES.md")
CONTENT_MODES = {"separate", "combined", "caption"}


class BuildPlatformMetadataTests(unittest.TestCase):
    def test_youtube_keeps_separate_fields_and_a_keyword_list(self):
        metadata = build_platform_metadata("youtube", {
            "title": "Boss fight",
            "description": "Final boss with no healing",
            "tags": ["gaming", "boss fight"],
        })

        self.assertEqual(metadata["title"], "Boss fight")
        self.assertEqual(metadata["description"], "Final boss with no healing")
        self.assertEqual(metadata["keywords"], ["gaming", "boss fight"])
        self.assertEqual(set(metadata), {"title", "description", "keywords"})

    def test_youtube_bounds_title_and_falls_back_to_a_placeholder(self):
        limit = CAPABILITY_MATRIX["youtube"].caption_limit
        metadata = build_platform_metadata("youtube", {
            "title": "t" * 250,
            "description": "",
            "tags": [],
        })

        self.assertEqual(metadata["title"], "t" * 100)
        self.assertEqual(metadata["description"], EMPTY_DESCRIPTION)
        self.assertEqual(build_platform_metadata(
            "youtube", {"title": "x", "description": "d" * (limit + 50),
                        "tags": []})["description"], "d" * limit)

    def test_youtube_keyword_string_stays_a_single_trimmed_string(self):
        keywords = "k" * 600
        metadata = build_platform_metadata("youtube", {
            "title": "x", "description": "", "tags": keywords})

        self.assertEqual(metadata["keywords"], keywords[:500])

    def test_instagram_composes_a_caption_with_hashtags(self):
        metadata = build_platform_metadata("instagram", {
            "title": "Boss fight",
            "description": "Final boss with no healing",
            "tags": ["gaming"],
        })

        self.assertEqual(set(metadata), {"caption"})
        self.assertEqual(
            metadata["caption"],
            "Boss fight\n\nFinal boss with no healing\n\n#gaming")

    def test_instagram_caption_respects_the_matrix_limit(self):
        limit = CAPABILITY_MATRIX["instagram"].caption_limit
        caption = build_platform_metadata("instagram", {
            "title": "Boss fight",
            "description": "d" * (limit * 2),
            "tags": ["gaming"],
        })["caption"]

        self.assertLessEqual(len(caption), limit)
        self.assertTrue(caption.startswith("Boss fight"))
        self.assertIn("#gaming", caption)

    def test_tiktok_title_respects_the_matrix_limit(self):
        limit = CAPABILITY_MATRIX["tiktok"].caption_limit
        title = build_platform_metadata("tiktok", {
            "title": "Boss fight",
            "description": "d" * (limit * 2),
            "tags": ["gaming"],
        })["title"]

        self.assertLessEqual(len(title), limit)
        self.assertTrue(title.startswith("Boss fight"))

    def test_twitter_truncates_the_combined_string_to_the_matrix_limit(self):
        limit = CAPABILITY_MATRIX["twitter"].caption_limit
        title = "t" * (limit + 100)
        metadata = build_platform_metadata("twitter", {
            "title": title, "description": "d" * 400, "tags": ["gaming"]})

        self.assertEqual(set(metadata), {"tweet_text"})
        self.assertEqual(len(metadata["tweet_text"]), limit)
        self.assertEqual(metadata["tweet_text"], title[:limit])

    def test_composed_text_is_what_the_policy_decision_publishes(self):
        content = {"title": "Boss fight", "description": "d" * 900,
                   "tags": ["gaming", "speedrun"]}
        for platform in ("instagram", "tiktok", "twitter"):
            with self.subTest(platform=platform):
                composed = next(iter(
                    build_platform_metadata(platform, content).values()))
                decision = validate_artifact(platform, {}, {"caption": composed})
                self.assertEqual(composed, decision.metadata["caption"])

    def test_platform_name_casing_cannot_drift(self):
        self.assertEqual(
            build_platform_metadata("Twitter", {"title": "x"}),
            build_platform_metadata("twitter", {"title": "x"}))

    def test_unknown_platform_has_no_metadata(self):
        self.assertEqual(build_platform_metadata("facebook", {"title": "x"}), {})

    def test_options_replace_content_for_one_composition(self):
        metadata = build_platform_metadata(
            "twitter",
            {"title": "Boss fight", "description": "", "tags": []},
            {"title": "Clutch", "description": "one try"})

        self.assertEqual(metadata["tweet_text"], "Clutch\n\none try")

    def test_hashtag_normalization_strips_hashes_spaces_and_blanks(self):
        caption = build_platform_metadata("twitter", {
            "title": "x", "description": "",
            "tags": ["#gaming", "boss fight", "  ", ""]})["tweet_text"]

        self.assertEqual(caption, "x\n\n#gaming #bossfight")

    def test_hashtag_case_is_preserved(self):
        caption = build_platform_metadata("instagram", {
            "title": "Boss fight", "tags": ["Gaming"]})["caption"]

        self.assertEqual(caption, "Boss fight\n\n#Gaming")

    def test_empty_content_composes_an_empty_value(self):
        self.assertEqual(build_platform_metadata("twitter", {}),
                         {"tweet_text": ""})
        self.assertEqual(build_platform_metadata("youtube", {}),
                         {"title": "", "description": "Uploaded via API",
                          "keywords": []})


class CapabilityRuleMetadataTests(unittest.TestCase):
    def _install_rule(self, platform: str, rule: CapabilityRule):
        CAPABILITY_MATRIX[platform] = rule
        self.addCleanup(CAPABILITY_MATRIX.pop, platform, None)

    def test_every_rule_produces_exactly_its_declared_output_keys(self):
        for platform, rule in CAPABILITY_MATRIX.items():
            with self.subTest(platform=platform):
                self.assertIn(rule.content_mode, CONTENT_MODES)
                metadata = build_platform_metadata(
                    platform, {"title": "t", "description": "d",
                               "tags": ["g"]})
                self.assertEqual(tuple(metadata), rule.output_keys)
                self.assertTrue(metadata)

    def test_misconfigured_output_keys_fail_loudly(self):
        self._install_rule("broken", CapabilityRule(
            content_mode="separate", output_keys=("title",)))

        with self.assertRaises(ValueError):
            build_platform_metadata("broken", {"title": "t"})

    def test_rule_without_a_caption_limit_composes_unbounded(self):
        self._install_rule("unbounded", CapabilityRule(
            content_mode="caption", output_keys=("caption",)))

        caption = build_platform_metadata("unbounded", {
            "title": "Boss fight", "description": "d" * 6000,
            "tags": ["gaming"]})["caption"]

        self.assertEqual(caption,
                         "Boss fight\n\n" + "d" * 6000 + "\n\n#gaming")


class DocumentedMetadataRuleTests(unittest.TestCase):
    HEADING = "## Upload metadata rules"

    def metadata_rows(self) -> dict[str, dict[str, str]]:
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn(self.HEADING, text,
                      f"{DOC_PATH.name} must document the metadata rules")
        section = text.split(self.HEADING, 1)[1].split("## ", 1)[0]
        rows = {}
        for line in section.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0] != "Platform" \
                    and not set(cells[0]) <= {"-"}:
                rows[cells[0]] = dict(zip(
                    ("content_mode", "output_keys", "caption_limit"), cells[1:]))
        return rows

    def test_documented_metadata_rules_match_the_capability_matrix(self):
        rows = self.metadata_rows()

        self.assertEqual(set(rows), set(CAPABILITY_MATRIX))
        for platform, cells in rows.items():
            with self.subTest(platform=platform):
                rule = CAPABILITY_MATRIX[platform]
                self.assertEqual(cells["content_mode"], rule.content_mode)
                self.assertEqual(cells["output_keys"],
                                 ", ".join(rule.output_keys))
                self.assertEqual(int(cells["caption_limit"]),
                                 rule.caption_limit)


if __name__ == "__main__":
    unittest.main()
