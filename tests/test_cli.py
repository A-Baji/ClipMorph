import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.__main__ import main


class CliInitializationTests(unittest.TestCase):
    def test_init_creates_template_without_configuring_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clipmorph.yaml"
            with patch.object(sys, "argv", [
                    "clipmorph", "--init", "--config-path", str(config_path)
            ]), patch("clipmorph.__main__.configure_ffmpeg") as configure:
                main()

            self.assertTrue(config_path.exists())
            self.assertIn("general:", config_path.read_text(encoding="utf-8"))
            configure.assert_not_called()

    def test_init_backs_up_existing_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clipmorph.yaml"
            config_path.write_text("old: true\n", encoding="utf-8")

            with patch.object(sys, "argv", [
                    "clipmorph", "--init", "--config-path", str(config_path)
            ]):
                main()

            backup_path = Path(f"{config_path}.backup")
            self.assertEqual(backup_path.read_text(encoding="utf-8"),
                             "old: true\n")
            self.assertIn("general:", config_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
