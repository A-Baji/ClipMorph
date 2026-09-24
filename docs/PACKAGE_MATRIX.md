# Artifact and Package Matrix

ClipMorph ships exactly two native executable variants per supported OS, plus the
Python package on PyPI in two install shapes. There is no npm-based end-user
distribution channel; npm is used only inside `frontend/` for development and
building the Svelte dashboard assets that get baked into the UI artifacts.

| Artifact | Audience | Contents | Entry point | Key dependencies | Platform(s) | Verification command |
|---|---|---|---|---|---|---|
| `clipmorph-cli-windows.zip` | Headless/CLI users, automation, CI | `clipmorph` CLI, bundled FFmpeg/FFprobe (Windows), fonts. No web assets, no FastAPI/Uvicorn, no browser-launch code. | `clipmorph/__main__.py` | Base `requirements.txt` only | Windows | `clipmorph.exe --help` |
| `clipmorph-cli-macos.zip` | Headless/CLI users, automation, CI | Same as above (macOS FFmpeg/FFprobe) | `clipmorph/__main__.py` | Base `requirements.txt` only | macOS | `./clipmorph --help` |
| `clipmorph-cli-linux` (self-extracting) | Headless/CLI users, automation, CI | Same as above (Linux FFmpeg/FFprobe) | `clipmorph/__main__.py` | Base `requirements.txt` only | Linux | `./clipmorph-cli-linux --help` |
| `clipmorph-ui-windows.zip` | Desktop users who want the dashboard | CLI + FastAPI/Uvicorn service, built Svelte assets (`clipmorph/web_assets`), desktop launcher | `clipmorph/ui_launcher.py` | Base + `web` extra (`fastapi`, `uvicorn[standard]`, `python-multipart`) | Windows | `clipmorph-ui.exe --help` (launches, selects a loopback port, waits for `/api/v1/health`, opens the default browser) |
| `clipmorph-ui-macos.zip` | Desktop users who want the dashboard | Same as above (macOS FFmpeg/FFprobe) | `clipmorph/ui_launcher.py` | Base + `web` extra | macOS | `./clipmorph-ui --help` |
| `clipmorph-ui-linux` (self-extracting) | Desktop users who want the dashboard | Same as above (Linux FFmpeg/FFprobe) | `clipmorph/ui_launcher.py` | Base + `web` extra | Linux | `./clipmorph-ui-linux --help` |
| PyPI `clipmorph` (base) | CLI use via `pip install clipmorph` | Python package: CLI, conversion/upload pipelines. Does **not** install FastAPI/Uvicorn or the built dashboard by default. | `clipmorph` console script → `clipmorph.__main__:main` | `requirements.txt` | Any (`python -m pip install clipmorph`) | `python -m pip install clipmorph && clipmorph --help` |
| PyPI `clipmorph[web]` (extra) | Local web/dashboard use via `pip install "clipmorph[web]"` | Adds FastAPI/Uvicorn, `python-multipart`, and enables `clipmorph web` / `clipmorph-ui` console scripts. Built dashboard assets ship inside the wheel's `web_assets/` package data. | `clipmorph` (`clipmorph web`, headless) or `clipmorph-ui` console script → `clipmorph.ui_launcher:main` (desktop launcher) | `requirements.txt` + `web` extra | Any (`python -m pip install "clipmorph[web]"`) | `python -m pip install "clipmorph[web]" && clipmorph web --help && clipmorph-ui --help` |

## CI/release gates that enforce this matrix

- `.github/workflows/tests.yml`: builds the frontend, installs `.[web]`, runs the full
  unit test suite (including `tests/test_ui_launcher.py`), runs CLI smoke tests
  (`--help`, `--init`, dry-run, resume, `--data-dir`, ordinary startup), runs the
  packaged browser E2E suite (`tests/test_e2e_dashboard.py`) at desktop and mobile
  viewport sizes, and greps workflow files to reject `npm publish` steps.
- `.github/workflows/release.yml`: builds six PyInstaller artifacts (`cli`/`ui` ×
  Windows/macOS/Linux) from `clipmorph/__main__.py` or `clipmorph/ui_launcher.py`
  respectively, and fails the build if a `cli` artifact contains
  `web_assets/index.html` or a `ui` artifact is missing it. Before creating the
  GitHub Release it verifies all six expected asset names exist, that
  `clipmorph/__version__.py` matches the release tag, and that no workflow
  contains an `npm publish` step. `publish_pypi` builds the sdist/wheel for the
  base package and publishes to PyPI via trusted publishing after the release is
  created.

## Notes

- The frontend (`frontend/`) uses npm only to build `clipmorph/web_assets/` during
  CI and local development. Those built assets are packaged into the wheel and
  the UI executables; npm itself is never part of the shipped artifact or
  release/publish steps.
- `clipmorph web` (headless service, no browser launch) keeps working in both the
  base install with `web` extra and the UI executable's underlying package, for
  server/headless use cases.
