"""Freshness and coverage checks for the generated configuration-form spec.

The dashboard renders its configuration form from ``frontend/public/form-spec.json``
(issue #257). These tests fail loudly when the shipped spec drifts from
``clipmorph.configuration`` or when a settable field is missing from it.
"""

import json
import unittest
from pathlib import Path

from clipmorph.configuration import DEFAULT_APP_CONFIGURATION
from clipmorph.configuration import SCHEDULE_MODES
from clipmorph.configuration import SUBTITLE_RENDERERS
from clipmorph.form_spec import form_spec, render_spec, spec_path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_SPEC = REPO_ROOT / "clipmorph" / "web_assets" / "form-spec.json"


def _collect_paths(node: dict, paths: set[str]) -> None:
    """Recursively collect every field path declared by a spec (sub)tree."""
    for field in node.get("fields", []):
        paths.add(field["path"])
    for section in node.get("sections", []):
        _collect_paths(section, paths)


def spec_paths(spec: dict) -> set[str]:
    paths: set[str] = set()
    for section in spec.get("sections", []):
        _collect_paths(section, paths)
    platforms = spec.get("platforms", {})
    for section in platforms.get("sections", []):
        _collect_paths(section, paths)
    for fields in platforms.get("flat_fields", {}).values():
        paths.update(field["path"] for field in fields)
    return paths


def default_leaves(node, prefix: str = "") -> set[str]:
    """Every non-object leaf in a defaults tree, as a dotted path."""
    leaves: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            leaves.update(default_leaves(value, path))
        else:
            leaves.add(path)
    return leaves


class FormSpecFreshnessTests(unittest.TestCase):
    def test_shipped_spec_matches_generated_output(self):
        self.assertTrue(spec_path().is_file(), "frontend/public/form-spec.json is missing; "
                                               "run python -m clipmorph.form_spec")
        self.assertEqual(spec_path().read_text(encoding="utf-8"), render_spec())

    def test_built_spec_matches_when_present(self):
        if not SHIPPED_SPEC.is_file():
            self.skipTest("web_assets spec is only present after a frontend build")
        self.assertEqual(SHIPPED_SPEC.read_text(encoding="utf-8"), render_spec())

    def test_spec_covers_every_settable_default_leaf(self):
        spec = form_spec()
        covered = spec_paths(spec)
        expected = default_leaves(DEFAULT_APP_CONFIGURATION["job_defaults"])
        expected.discard("general.source")  # identity, not user-settable
        missing = sorted(expected - covered)
        self.assertEqual(missing, [], f"spec omits settable leaves: {missing}")

    def test_spec_declares_schedule_and_inline_layout(self):
        covered = spec_paths(form_spec())
        self.assertIn("upload.schedule.publish_at", covered)
        self.assertIn("upload.schedule.mode", covered)
        self.assertIn("conversion.layout", covered)

    def test_spec_enums_carry_options(self):
        spec = form_spec()
        fields = {}

        def walk(node):
            for field in node.get("fields", []):
                fields[field["path"]] = field
            for section in node.get("sections", []):
                walk(section)

        for section in spec["sections"]:
            walk(section)
        self.assertEqual(fields["conversion.subtitles.renderer"]["options"],
                         ["overlay", "stacked"])
        self.assertEqual(fields["upload.schedule.mode"]["options"],
                         ["local", "platform"])

    def test_spec_enum_options_match_schema_constants(self):
        # The spec derives its enum options from the schema-owned constants, so
        # a schema-side change must flow through (issue #257, review F9).
        spec = form_spec()
        fields = {}

        def walk(node):
            for field in node.get("fields", []):
                fields[field["path"]] = field
            for section in node.get("sections", []):
                walk(section)

        for section in spec["sections"]:
            walk(section)
        self.assertEqual(
            set(fields["conversion.subtitles.renderer"]["options"]),
            set(SUBTITLE_RENDERERS))
        self.assertEqual(
            set(fields["upload.schedule.mode"]["options"]),
            {mode for mode in SCHEDULE_MODES if mode is not None})

    def test_spec_marks_transcription_keys_protected_per_platform(self):
        spec = form_spec()
        protected = set()

        def walk(node):
            for field in node.get("fields", []):
                if field.get("protected"):
                    protected.add(field["path"])
            for section in node.get("sections", []):
                walk(section)

        for section in spec["platforms"]["sections"]:
            walk(section)
        self.assertIn("conversion.subtitles.transcription_language", protected)

    def test_spec_is_json_serializable_and_stable(self):
        first = json.dumps(form_spec(), sort_keys=True)
        second = json.dumps(form_spec(), sort_keys=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
