"""Guards the wheel package layout so subpackages remain importable after `pip install`.

Regression test for a packaging bug where `[tool.setuptools] packages = ["clipmorph"]`
silently dropped clipmorph.ffmpeg, clipmorph.conversion_pipeline, and
clipmorph.upload_pipeline (and their submodules) from the built wheel, breaking
`clipmorph web` / `clipmorph-ui` at runtime even though `--help` still worked.
"""

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_MODULES = [
    "clipmorph/__init__.py",
    "clipmorph/__main__.py",
    "clipmorph/ffmpeg/__init__.py",
    "clipmorph/conversion_pipeline/__init__.py",
    "clipmorph/conversion_pipeline/convert.py",
    "clipmorph/conversion_pipeline/edit.py",
    "clipmorph/conversion_pipeline/transcribe.py",
    "clipmorph/upload_pipeline/__init__.py",
    "clipmorph/upload_pipeline/platforms/__init__.py",
    "clipmorph/upload_pipeline/platforms/youtube.py",
]


class WheelPackageLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(REPO_ROOT),
             "--no-deps", "--no-build-isolation", "--wheel-dir", cls._temp_dir.name],
            check=True, capture_output=True, text=True)
        wheels = list(Path(cls._temp_dir.name).glob("clipmorph-*.whl"))
        assert wheels, "expected a built clipmorph wheel"
        cls.wheel_path = wheels[0]

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()

    def test_wheel_contains_all_subpackage_modules(self):
        with zipfile.ZipFile(self.wheel_path) as archive:
            names = set(archive.namelist())
        missing = [module for module in REQUIRED_MODULES if module not in names]
        self.assertEqual(missing, [], f"wheel is missing modules: {missing}")


if __name__ == "__main__":
    unittest.main()
