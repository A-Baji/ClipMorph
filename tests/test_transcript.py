import tempfile
import unittest
from pathlib import Path

from clipmorph.transcript import create_edit_session, load_edit_session, save_edit_session


class TranscriptEditSessionTests(unittest.TestCase):
    def test_session_preserves_original_and_round_trips(self):
        segments = [{
            "start": 0.0,
            "end": 1.5,
            "text": "Hello",
            "words": [{"word": "Hello", "censored": False}],
        }]
        session = create_edit_session("source-hash", segments, 2.0)
        session["segments"][0]["text"] = "Hi"
        session["segments"][0]["words"][0].update(
            {"censored": True, "replacement": "***",
             "emphasis": {"enabled": True, "style": "bold"}})

        with tempfile.TemporaryDirectory() as temp_dir:
            path = save_edit_session(session, Path(temp_dir) / "edited.json")
            loaded = load_edit_session(path)

        self.assertEqual(loaded["original_segments"][0]["text"], "Hello")
        self.assertEqual(loaded["segments"][0]["text"], "Hi")
        self.assertTrue(loaded["segments"][0]["words"][0]["censored"])

    def test_rejects_invalid_and_overlapping_timings(self):
        with self.assertRaises(ValueError):
            create_edit_session("hash", [{"start": 2, "end": 1}], 3)
        with self.assertRaises(ValueError):
            create_edit_session("hash", [
                {"start": 0, "end": 2},
                {"start": 1, "end": 3},
            ], 3)
        with self.assertRaises(ValueError):
            create_edit_session("hash", [{"start": 0, "end": 4}], 3)

    def test_sessions_have_stable_ids_and_segment_typography_overrides(self):
        session = create_edit_session("hash", [{
            "start": 0, "end": 1, "text": "Hello",
            "typography": {"size": 42, "italic": True},
        }], 2)

        self.assertEqual(session["schema_version"], 2)
        self.assertEqual(session["segments"][0]["id"],
                         session["original_segments"][0]["id"])
        self.assertEqual(session["segments"][0]["typography"]["size"], 42)

    def test_saved_revisions_are_immutable(self):
        session = create_edit_session("hash", [{
            "start": 0, "end": 1, "text": "Hello",
        }], 2)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "revision-0001.json"
            save_edit_session(session, path)
            with self.assertRaises(FileExistsError):
                save_edit_session(session, path)
            self.assertEqual(load_edit_session(path)["revision"], 1)


if __name__ == "__main__":
    unittest.main()
