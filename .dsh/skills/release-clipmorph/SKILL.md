---
name: release-clipmorph
description: Cut a ClipMorph release by version — dispatch tag.yml, which rewrites the version module, pushes a v tag, and drives 3-OS PyInstaller builds
whenToUse: When the user asks to release a new ClipMorph version or publish build artifacts to a GitHub Release
---

# Release ClipMorph

## Purpose

Cut a release end to end: bump the version, tag it, and publish Windows, macOS, and Linux executables as a GitHub Release.

## When

Use when asked to release, tag, or publish a new version of ClipMorph. Do not use for ordinary code changes.

## Prerequisites

- `gh` CLI authenticated with permission to dispatch workflows on this repository
- The state you want to ship is already merged to `main`
- Target version in `X.Y.Z` form (workflow input pattern `^[0-9]+\.[0-9]+\.[0-9]+$`)

## Procedure

1. Dispatch the release workflow:

   ```
   gh workflow run tag.yml --ref main -f version=X.Y.Z
   ```

   To publish a version whose tag already exists, also pass: `-f allow_existing_tag=true`.

2. `tag.yml` then rewrites `clipmorph/__version__.py` from the `version` input, commits and pushes to `main`, and pushes the tag `v{version}`.

3. The `v*` tag push triggers `build_and_release.yml`, which checks out with Git LFS (bundled FFmpeg binaries), builds a single-file PyInstaller executable on the 3-OS matrix (windows, mac, ubuntu), and publishes a GitHub Release with assets `clipmorph-windows.exe`, `clipmorph-macos`, `clipmorph-linux`.

## Verification

- `gh run list --workflow tag.yml --limit 1` shows a completed success, then `gh run list --workflow build_and_release.yml --limit 3` shows all matrix legs green
- `gh release view v{version}` lists the three expected assets (a red × on one leg means that platform's asset is missing)
- `clipmorph/__version__.py` on `main` now reads the intended `X.Y.Z`

## Failure modes

- Version not matching `X.Y.Z` → rejected at dispatch, nothing is cut
- Tag already exists without `allow_existing_tag=true` → dispatch fails, no release is cut
- A single-OS build leg failing does not fail the others — the missing asset is the symptom; check that leg's logs
- FFmpeg LFS objects are large; slow/failing LFS checkout on a leg looks like a build failure at the install/PyInstaller step

## Constraints

- There is no local release or PyInstaller command — releases only come from GitHub Actions
- Never echo workflow secrets (e.g. the PAT token used for publishing)
- Do not hand-edit `clipmorph/__version__.py` outside the workflow; it is the version single source of truth
