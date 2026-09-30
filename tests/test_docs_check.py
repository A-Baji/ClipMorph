import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib.util

spec = importlib.util.spec_from_file_location(
    "check_docs",
    Path(__file__).resolve().parents[1] / "scripts" / "check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


class DocsCheckTests(unittest.TestCase):
    def test_offered_cli_flags_include_stable_long_options(self):
        flags = check_docs.offered_cli_flags()
        if flags is None:  # CLI not importable here; cf. check_docs contract
            self.skipTest("clipmorph CLI not importable")
        self.assertIn("--dry-run", flags)
        self.assertIn("--data-dir", flags)

    def test_unknown_readme_flags_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text(
                "Reduce with --transcription-model and --phone-home.\n",
                encoding="utf-8")
            with patch.object(check_docs, "REPO_ROOT", root):
                problems = []
                check_docs.check_readme_flags(problems)

        self.assertTrue(any("--phone-home" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
