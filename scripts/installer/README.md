# Windows installer

`clipmorph.iss` is the [Inno Setup 6](https://jrsoftware.org/isinfo.php) script
that packages the PyInstaller onedir UI build (`dist/clipmorph/`, which already
contains `clipmorph-ui.exe`, the bundled FFmpeg, and the built `web_assets`)
into `clipmorph-ui-windows-setup.exe`. The release workflow compiles it on the
Windows UI matrix leg; see `.github/workflows/release.yml`.

## Building locally

1. Build the UI onedir artifact first (see `docs/RELEASE.md` and the release
   workflow), so `dist/clipmorph/clipmorph-ui.exe` exists.
2. Stage the WebView2 Evergreen bootstrapper next to this script:

   ```powershell
   curl.exe -L -o scripts\installer\MicrosoftEdgeWebview2Setup.exe https://go.microsoft.com/fwlink/p/?LinkId=2124703
   ```

3. Compile from the repo root:

   ```powershell
   & "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=0.5.0 scripts\installer\clipmorph.iss
   ```

The result is `dist/installer/clipmorph-ui-windows-setup.exe`. It is unsigned in
v1, so Windows SmartScreen shows a warning; see `docs/RELEASE.md` for the
"More info -> Run anyway" path, and note that updates are manual (re-run a newer
installer).

## Run-at-logon

The installer's optional "Start ClipMorph when I sign in" task writes the
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ClipMorph` value, and the
tray menu toggles the same value (`clipmorph/desktop_app.py`). The uninstaller
removes it whether it was enabled by the install-time task or by the tray
toggle. It is never enabled implicitly.

## Console window

The Windows UI executable is built as a console application (`console=True` in
the release workflow's PyInstaller spec), so launching it from the Start Menu,
the post-install run, or run-at-logon shows a console window alongside the tray
app. A windowed build is deferred for v1 because `docs/PACKAGE_MATRIX.md`'s
artifact verification relies on the executable's `--help` console output.
