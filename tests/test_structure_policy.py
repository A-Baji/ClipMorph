import importlib.util
import subprocess
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
    REQUIRED_FILES = [
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        "template.env",
    ]

    def _seed_required_files(self, root: Path) -> None:
        for file_name in self.REQUIRED_FILES:
            (root / file_name).write_text("placeholder\n", encoding="utf-8")

    def test_root_layout_allows_optional_local_files_to_be_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._seed_required_files(root)

            with patch.object(check_structure, "REPO_ROOT", root):
                self.assertEqual(check_structure.check_root_layout(), [])

    def test_local_secret_artifact_with_any_name_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._seed_required_files(root)
            (root / "clipmorph-version-manager.2026-01-01.private-key.pem"
             ).write_bytes(b"key material")

            with patch.object(check_structure, "REPO_ROOT", root):
                self.assertEqual(check_structure.check_root_layout(), [])

    def test_tracked_local_artifact_fails_the_structure_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._seed_required_files(root)
            (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True,
                           capture_output=True)
            subprocess.run(["git", "add", "-f", ".env"], cwd=root, check=True,
                           capture_output=True)

            with patch.object(check_structure, "REPO_ROOT", root):
                self.assertEqual(check_structure.check_local_files_untracked(),
                                 [".env"])
                problems = check_structure.check_root_layout()
                self.assertTrue(
                    any(".env" in problem for problem in problems))
