import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "check_structure",
    Path(__file__).resolve().parents[1] / "scripts" / "check_structure.py",
)
check_structure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_structure)


class StructurePolicyTests(unittest.TestCase):
    def test_root_layout_allows_optional_local_files_to_be_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for file_name in [
                ".gitattributes",
                ".gitignore",
                "AGENTS.md",
                "CHANGELOG.md",
                "LICENSE",
                "README.md",
                "pyproject.toml",
                "requirements.txt",
                "template.env",
            ]:
                (root / file_name).write_text("placeholder\n", encoding="utf-8")

            with patch.object(check_structure, "REPO_ROOT", root):
                self.assertEqual(check_structure.check_root_layout(), [])
