import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from clipmorph.transcript import (
    create_edit_session,
    load_edit_session,
    native_scalars,
    save_edit_session,
)


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

    def test_numpy_scalars_are_coerced_to_native_persistence_types(self):
        """WhisperX emits numpy timestamps; the session must store natives.

        ``np.float64`` subclasses ``float``, so the JSON session write accepts
        it while the manifest's YAML dump raises "cannot represent an object"
        and fails the job after a clean transcription.
        """
        session = create_edit_session("source-hash", [{
            "start": np.float64(0.1),
            "end": np.float64(0.9),
            "text": "Hello there",
            "words": [{"word": "hello", "start": np.float64(0.1),
                       "end": np.float64(0.5), "score": np.float32(0.9)}],
        }], 3.0)

        self.assertNotIsInstance(session["segments"][0]["start"], np.generic)
        self.assertNotIsInstance(
            session["segments"][0]["words"][0]["score"], np.generic)
        self.assertEqual(session["segments"][0]["start"], 0.1)
        json.dumps(session)
        yaml.safe_dump(session)
        self.assertIsInstance(native_scalars(np.float64(1.5)), float)
        self.assertIsInstance(native_scalars(np.int64(2)), int)

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
