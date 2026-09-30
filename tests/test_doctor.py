"""Doctor command: check records, JSON structure, exit codes, lazy surface.

Every case drives the public ``run_cli`` entry point or ``run_checks`` with
the heavy collaborators (FFmpeg, torch, credentials) faked, so the suite
stays deterministic and never touches the network or the real binaries.
"""

import builtins
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from clipmorph.cli import run_cli
from clipmorph.doctor import _check_device, run_checks

# rich reads COLUMNS when stdout is not a terminal, so a wide value keeps the
# rendered report lines unwrapped and comparable.
WIDE_TERMINAL = {"COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"}

ALL_PLATFORMS = ("youtube", "instagram", "tiktok", "twitter", "hugging_face")


class FakeFFmpegConfig:
    """Stand-in for FFmpegConfig exposing the path properties."""

    def __init__(self, ffmpeg_path="ffmpeg", ffprobe_path="ffprobe"):
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path

    @property
    def ffmpeg_path(self):
        return self._ffmpeg_path

    @property
    def ffprobe_path(self):
        return self._ffprobe_path


class FakeFFmpegRunner:
    """Mirror of tests/test_preflight.py::FakeFFmpegRunner."""

    def __init__(self, info=None):
        self._info = info or {
            "format": {"duration": "12.5"},
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
            }],
        }

    def get_video_info(self, _input_path):
        return self._info


class _FakeCuda:
    def __init__(self, available):
        self._available = available

    def is_available(self):
        return self._available

    def get_device_name(self, _index):
        return "Fake GPU"


class _FakeTorch:
    def __init__(self, cuda_available=True):
        self.cuda = _FakeCuda(cuda_available)


@contextlib.contextmanager
def doctor_patches(*, torch_absent=False, all_credentials_configured=False):
    """Patch every heavy collaborator the doctor checks rely on."""
    real_import = builtins.__import__

    def import_without_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("No module named 'torch'")
        return real_import(name, *args, **kwargs)

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("clipmorph.ffmpeg.FFmpegConfig", FakeFFmpegConfig))
        stack.enter_context(patch("subprocess.run", Mock(
            side_effect=lambda cmd, **kwargs: Mock(
                stdout=f"{Path(cmd[0]).name} version 7.0.2\n"))))
        stack.enter_context(patch("clipmorph.auth.credential_status", Mock(
            return_value={platform: all_credentials_configured
                          for platform in ALL_PLATFORMS})))
        if torch_absent:
            stack.enter_context(
                patch("builtins.__import__", side_effect=import_without_torch))
        else:
            stack.enter_context(patch.dict(sys.modules, {"torch": _FakeTorch()}))
        yield


def _invoke(argv):
    """Run one command, returning ``(exit code, stdout)``."""
    output = io.StringIO()
    with patch.dict(os.environ, WIDE_TERMINAL), contextlib.redirect_stdout(output):
        code = run_cli(list(argv))
    return code, output.getvalue()


def _invoke_json(argv):
    """Run one command and parse its ``--json`` payload."""
    code, output = _invoke([*argv, "--json"])
    return code, json.loads(output)


def _seed_data_dir(temp_dir):
    """Create a data directory with the default source/output directories."""
    data_dir = Path(temp_dir) / "data"
    (data_dir / "sources").mkdir(parents=True)
    (data_dir / "output").mkdir()
    return data_dir


def _by_id(payload):
    return {check["id"]: check for check in payload["checks"]}


class DoctorJsonTests(unittest.TestCase):
    def test_all_ok_json_structure_with_expected_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(all_credentials_configured=True):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

        self.assertEqual(code, 0)
        self.assertEqual([check["id"] for check in payload["checks"]], [
            "ffmpeg", "ffprobe", "app_config", "source_dir", "output_dir",
            "layouts", "fonts", "credentials", "device", "artifacts_storage",
        ])
        for check in payload["checks"]:
            self.assertEqual(check["status"], "ok")
            self.assertTrue(check["detail"])

    def test_app_config_value_error_fails_and_exits_1(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            (data_dir / "app.yml").write_text("config_version: 99\n",
                                              encoding="utf-8")
            with doctor_patches(all_credentials_configured=True):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

        self.assertEqual(code, 1)
        records = _by_id(payload)
        self.assertEqual(records["app_config"]["status"], "failed")
        self.assertIn("config_version", records["app_config"]["detail"])
        # The config-dependent checks cannot run and fail with the same cause.
        for check_id in ("source_dir", "output_dir", "layouts"):
            self.assertEqual(records[check_id]["status"], "failed")
            self.assertIn("app configuration could not be loaded",
                          records[check_id]["detail"])

    def test_exit_code_mapping_follows_failed_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(torch_absent=True):
                code, _ = _invoke_json(["--data-dir", str(data_dir), "doctor"])
            self.assertEqual(code, 0)

            (data_dir / "app.yml").write_text("config_version: 99\n",
                                              encoding="utf-8")
            with doctor_patches():
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])
            self.assertEqual(code, 1)
            self.assertTrue(any(check["status"] == "failed"
                                for check in payload["checks"]))


class DoctorSourceMediaTests(unittest.TestCase):
    def test_missing_source_file_fails_media_check_and_exits_1(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            missing = data_dir / "sources" / "clip.mp4"
            with doctor_patches(all_credentials_configured=True):
                code, payload = _invoke_json(
                    ["--data-dir", str(data_dir), "doctor", "--source", str(missing)])

        self.assertEqual(code, 1)
        records = _by_id(payload)
        self.assertEqual(records["source_media"]["status"], "failed")
        self.assertIn("Input file does not exist", records["source_media"]["detail"])
        self.assertEqual(len(payload["checks"]), 11)

    def test_source_media_ok_with_fake_runner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            with doctor_patches(), patch("clipmorph.ffmpeg.FFmpegRunner",
                                         FakeFFmpegRunner):
                checks = run_checks(data_dir, data_dir / "app.yml", source)

        records = {check["id"]: check for check in checks}
        self.assertEqual(records["source_media"]["status"], "ok")
        self.assertEqual(records["source_media"]["detail"], "1920x1080, 12.5s")
        self.assertEqual(len(checks), 11)

    def test_source_media_rejects_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            source = data_dir / "sources" / "clip.txt"
            source.write_bytes(b"video")
            with doctor_patches():
                checks = run_checks(data_dir, data_dir / "app.yml", source)

        records = {check["id"]: check for check in checks}
        self.assertEqual(records["source_media"]["status"], "failed")
        self.assertEqual(records["source_media"]["detail"],
                         "unsupported source extension: .txt")

    def test_source_media_fails_without_video_stream(self):
        runner = FakeFFmpegRunner(info={"format": {"duration": "12.5"},
                                        "streams": []})
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            with doctor_patches(), patch("clipmorph.ffmpeg.FFmpegRunner",
                                         lambda: runner):
                checks = run_checks(data_dir, data_dir / "app.yml", source)

        records = {check["id"]: check for check in checks}
        self.assertEqual(records["source_media"]["status"], "failed")
        self.assertEqual(records["source_media"]["detail"],
                         "Input does not contain a video stream.")


class DoctorDeviceTests(unittest.TestCase):
    def test_device_warning_when_torch_import_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(torch_absent=True):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

        self.assertEqual(code, 0)
        records = _by_id(payload)
        self.assertEqual(records["device"]["status"], "warning")
        self.assertEqual(records["device"]["detail"],
                         "torch not installed; transcription unavailable on "
                         "this installation")

    def test_device_reports_cpu_fallback_when_cuda_unavailable(self):
        fake_package = types.ModuleType("clipmorph.conversion_pipeline")
        fake_transcribe = types.ModuleType(
            "clipmorph.conversion_pipeline.transcribe")
        fake_transcribe.resolve_transcription_device = lambda _requested: "cpu"
        with patch.dict(sys.modules, {
                "torch": _FakeTorch(cuda_available=False),
                "clipmorph.conversion_pipeline": fake_package,
                "clipmorph.conversion_pipeline.transcribe": fake_transcribe,
        }):
            record = _check_device()

        self.assertEqual(record["id"], "device")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["detail"],
                         "cuda unavailable; transcription falls back to cpu")


class DoctorCredentialsTests(unittest.TestCase):
    def test_credentials_warning_when_unconfigured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches():
                checks = run_checks(data_dir, data_dir / "app.yml")

        records = {check["id"]: check for check in checks}
        self.assertEqual(records["credentials"]["status"], "warning")
        self.assertIn("youtube", records["credentials"]["detail"])
        self.assertIn("hugging_face", records["credentials"]["detail"])


class _PretendStorage:
    """Stand-in backend reporting whatever verdict a case needs."""

    def __init__(self, status="ok", detail="pretend backend at gs://bucket"):
        self._health = (status, detail)

    def health(self):
        return self._health


class DoctorStorageTests(unittest.TestCase):
    def _artifacts_storage(self, payload):
        return {check["id"]: check for check in payload}["artifacts_storage"]

    def test_configured_backend_probe_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(), patch(
                    "clipmorph.storage.make_storage",
                    return_value=_PretendStorage()) as make_storage:
                checks = run_checks(data_dir, data_dir / "app.yml")

        record = self._artifacts_storage(checks)
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["detail"], "pretend backend at gs://bucket")
        # The backend is built from the loaded app.yml and the active data dir.
        configuration, data_dir_arg = make_storage.call_args.args
        self.assertEqual(configuration["storage"], {"backend": "local"})
        self.assertEqual(data_dir_arg, data_dir)

    def test_backend_probe_failure_fails_the_check_and_the_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            pretend = _PretendStorage("failed", "bucket is not writable")
            with doctor_patches(all_credentials_configured=True), patch(
                    "clipmorph.storage.make_storage", return_value=pretend):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

        self.assertEqual(code, 1)
        record = _by_id(payload)["artifacts_storage"]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["detail"], "bucket is not writable")

    def test_unbuildable_backend_reports_unavailable_without_failing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(all_credentials_configured=True), patch(
                    "clipmorph.storage.make_storage",
                    side_effect=ValueError("unknown storage backend: gcs")):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

        record = _by_id(payload)["artifacts_storage"]
        self.assertEqual(record["status"], "unavailable")
        self.assertEqual(record["detail"], "unknown storage backend: gcs")
        # Unavailable is a missing capability, not a broken environment.
        self.assertEqual(code, 0)

    def test_local_probe_recycles_its_file_inside_the_output_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(all_credentials_configured=True):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

            record = _by_id(payload)["artifacts_storage"]
            self.assertEqual(code, 0)
            self.assertEqual(record["status"], "ok")
            self.assertIn(str(data_dir / "output"), record["detail"])
            self.assertEqual(list((data_dir / "output").iterdir()), [])


class DoctorSurfaceTests(unittest.TestCase):
    def test_doctor_does_not_import_torch_when_absent(self):
        attempts = []
        real_import = builtins.__import__

        def import_without_torch(name, *args, **kwargs):
            if name == "torch":
                attempts.append(name)
                raise ImportError("No module named 'torch'")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with patch("clipmorph.ffmpeg.FFmpegConfig", FakeFFmpegConfig), \
                    patch("subprocess.run", Mock(side_effect=lambda cmd, **kwargs: Mock(
                        stdout=f"{Path(cmd[0]).name} version 7.0.2\n"))), \
                    patch("clipmorph.auth.credential_status", Mock(return_value={
                        platform: False for platform in ALL_PLATFORMS})), \
                    patch("builtins.__import__", side_effect=import_without_torch):
                code, payload = _invoke_json(["--data-dir", str(data_dir), "doctor"])

        # The device check is the only torch consumer, and its attempt failed
        # cleanly instead of pulling torch into the process.
        self.assertEqual(attempts, ["torch"])
        records = _by_id(payload)
        self.assertEqual(records["device"]["status"], "warning")
        self.assertEqual(code, 0)

    def test_text_report_renders_one_line_per_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = _seed_data_dir(temp_dir)
            with doctor_patches(all_credentials_configured=True):
                checks = run_checks(data_dir, data_dir / "app.yml")
                code, output = _invoke(["--data-dir", str(data_dir), "doctor"])

        self.assertEqual(code, 0)
        lines = [line for line in output.splitlines() if line.strip()]
        self.assertEqual(len(lines), len(checks))
        for line, check in zip(lines, checks):
            self.assertEqual(line, f"{check['id']:<60} {check['status']} "
                                   f"{check['detail']}")


if __name__ == "__main__":
    unittest.main()
