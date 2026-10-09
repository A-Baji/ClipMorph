# Artifact and Package Matrix

ClipMorph ships exactly two native executable variants per supported OS, plus a
Windows installer for the UI variant, plus the Python package from the tagged
GitHub repository in two install shapes. There is no npm-based end-user
distribution channel; npm is used only inside `frontend/` for development and
building the Svelte dashboard assets that get baked into the UI artifacts.

| Artifact | Audience | Contents | Entry point | Key dependencies | Platform(s) | Verification command |
|---|---|---|---|---|---|---|
| `clipmorph-cli-windows.zip` | Headless/CLI users, automation, CI | `clipmorph` CLI, bundled FFmpeg/FFprobe (Windows), fonts. No web assets, no FastAPI/Uvicorn, no browser-launch code. | `clipmorph/__main__.py` | Base `requirements.txt` only | Windows | `clipmorph.exe --help` |
| `clipmorph-cli-macos.zip` | Headless/CLI users, automation, CI | Same as above (macOS FFmpeg/FFprobe) | `clipmorph/__main__.py` | Base `requirements.txt` only | macOS | `./clipmorph --help` |
| `clipmorph-cli-linux` (self-extracting) | Headless/CLI users, automation, CI | Same as above (Linux FFmpeg/FFprobe) | `clipmorph/__main__.py` | Base `requirements.txt` only | Linux | `./clipmorph-cli-linux --help` |
| `clipmorph-ui-windows.zip` | Desktop users who want the dashboard | CLI + FastAPI/Uvicorn service, built Svelte assets (`clipmorph/web_assets`), desktop launcher | `clipmorph/ui_launcher.py` (→ `clipmorph/desktop_app.py` on Windows) | Base + `web` extra (`fastapi`, `uvicorn[standard]`, `python-multipart`, `pywebview`, `pystray`) | Windows | `clipmorph-ui.exe --help` (launches a native window on Windows; `--no-browser` runs the headless service) |
| `clipmorph-ui-macos.zip` | Desktop users who want the dashboard | Same as above (macOS FFmpeg/FFprobe) | `clipmorph/ui_launcher.py` | Base + `web` extra | macOS | `./clipmorph-ui --help` (native desktop shell is Windows-only in v1; opens the default browser) |
| `clipmorph-ui-linux` (self-extracting) | Desktop users who want the dashboard | Same as above (Linux FFmpeg/FFprobe) | `clipmorph/ui_launcher.py` | Base + `web` extra | Linux | `./clipmorph-ui-linux --help` (native desktop shell is Windows-only in v1; opens the default browser) |
| `clipmorph-ui-windows-setup.exe` | Windows desktop users who want an installed app | The Windows onedir UI build (exe + bundled FFmpeg + built `web_assets`) installed per-user with a Start Menu entry, an optional run-at-logon task, and an uninstaller; stages the WebView2 Evergreen bootstrapper | `clipmorph-ui.exe` (installed) | Base + `web` extra; built with Inno Setup 6 | Windows | install → launch from Start Menu → uninstall |
| GitHub source `clipmorph` (base) | CLI use via `pip install "clipmorph @ git+https://github.com/A-Baji/ClipMorph.git@vX.Y.Z"` | Python package: CLI, conversion/upload pipelines. Does **not** install FastAPI/Uvicorn or the built dashboard by default. | `clipmorph` console script → `clipmorph.__main__:main` | `requirements.txt` | Any | `python -m pip install "clipmorph @ git+https://github.com/A-Baji/ClipMorph.git@vX.Y.Z" && clipmorph --help` |
| GitHub source `clipmorph[web]` (extra) | Local web/dashboard use via the tagged repository URL | Adds FastAPI/Uvicorn, `python-multipart`, and the desktop-shell dependencies `pywebview`/`pystray`, enabling the `clipmorph web` / `clipmorph-ui` console scripts. Built dashboard assets ship inside the package data. | `clipmorph` (`clipmorph web`, headless) or `clipmorph-ui` console script → `clipmorph.ui_launcher:main` (native desktop shell on Windows; browser launcher elsewhere) | `requirements.txt` + `web` extra | Any (native shell: Windows v1) | `python -m pip install "clipmorph[web] @ git+https://github.com/A-Baji/ClipMorph.git@vX.Y.Z" && clipmorph web --help && clipmorph-ui --help` |

## CI/release gates that enforce this matrix

- `.github/workflows/tests.yml`: builds the frontend, installs `.[web]`, runs the full
  unit test suite (including `tests/test_ui_launcher.py` and `tests/test_desktop_app.py`),
  runs CLI smoke tests
  (`--help`, `init`, job-create dry-run, job inspection, upload-review resume gate), runs the
  packaged browser E2E suite (`tests/test_e2e_dashboard.py`) at desktop and mobile
  viewport sizes, and greps workflow files to reject `npm publish` steps.
- `.github/workflows/release.yml`: builds six PyInstaller artifacts (`cli`/`ui` ×
  Windows/macOS/Linux) from `clipmorph/__main__.py` or `clipmorph/ui_launcher.py`
  respectively, and fails the build if a `cli` artifact contains
  `web_assets/index.html` or a `ui` artifact is missing it. The Windows UI leg also
  installs Inno Setup (`choco install innosetup`), stages the WebView2 Evergreen
  bootstrapper, and compiles `scripts/installer/clipmorph.iss` into
  `clipmorph-ui-windows-setup.exe`. Before creating the
  GitHub Release it verifies all seven expected asset names exist, that
  `[project].version` in `pyproject.toml` matches the release tag, and that no workflow
  contains an npm distribution step. Python users install the base package or
  its `web` extra directly from the tagged GitHub repository URL.

## Notes

- **Desktop shell route (#211).** The UI is a native window on Windows built with
  `pywebview` (window) and `pystray` (tray) — no Rust/Node second runtime, no npm
  channel, so `PACKAGE_MATRIX.md` and the `#160` Electron/Tauri non-goal are both
  respected. The native shell is **Windows-only at v1**; macOS (`pystray`/`pywebview`
  main-thread conflict) and Linux (`webkit2gtk`/tray) are follow-up issues, and on
  those platforms `clipmorph-ui` opens the browser instead. The desktop app and the
  web app are the same application minus the window/tray/logon additions; see
  `docs/CLI_WEB_PARITY.md`.
- The frontend (`frontend/`) uses npm only to build `clipmorph/web_assets/` during
  CI and local development. Those built assets are packaged into the wheel and
  the UI executables; npm itself is never part of the shipped artifact or
  release/publish steps.
- `clipmorph web` (headless service, no browser launch) keeps working in both the
  base install with `web` extra and the UI executable's underlying package, for
  server/headless use cases.
