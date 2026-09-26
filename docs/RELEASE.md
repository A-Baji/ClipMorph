# Release Flow (Version → Changelog → Merge → Build → Tag and Release)

This document explains the project's release flow and how to run it locally or from the GitHub UI.

## Overview

- `.github/workflows/release.yml` is the single release pipeline. `[project].version` in `pyproject.toml` is the only version source. After the version and matching changelog section are merged to `main`, dispatch the workflow from `main`; it builds both executable variants (CLI and UI) for Windows, macOS, and Linux from that exact commit, then creates the annotated tag `vX.Y.Z` on that release commit and publishes the GitHub Release. Python users install from the tagged GitHub repository URL.
- See [docs/PACKAGE_MATRIX.md](PACKAGE_MATRIX.md) for the full artifact/package matrix (audience, contents, entry point, dependencies, platform, verification command).

## Secrets and permissions

- `PAT_TOKEN` (repo secret): a personal access token used by the release workflow when pushing tags and dispatching workflows. The token must be either:
  - Classic PAT: include `repo` and `workflow` scopes; or
  - Fine-grained PAT: granted to this repository with **Actions/Workflows** (Read & write) and **Repository contents** (Read & write) as needed.
- `GITHUB_TOKEN` (provided by Actions): `release.yml` requires `contents: write` permission (set at top-level `permissions`) so the `create_release` job can create releases and attach files.
Ensure any organization SSO or repo policy authorizes the PAT account.

## Running a release

1. On `dev`, update `[project].version` in `pyproject.toml` and add the matching dated `X.Y.Z` section to `CHANGELOG.md` in the same release-preparation change.
2. Merge that change to `main` through the approved PR process. This merge commit is the release commit and contains both the version and its changelog entry.
3. From the GitHub UI, choose Actions → Build and Release → Run workflow with `main` selected. There is no version input; the workflow reads it from `pyproject.toml` on the selected commit.
4. Or use `gh` CLI (ensure `gh` is authenticated and pointing at the repo):

```bash
gh workflow run release.yml --ref main
```

5. The workflow validates the version and changelog section, then passes the selected `main` commit SHA to the build matrix. It does not change or push `main`.
6. The build matrix checks out that exact commit, builds and smoke-tests Windows/macOS/Linux artifacts, and uploads them as workflow artifacts.
7. Only after all builds and release-note validation succeed, the workflow creates the annotated tag `vX.Y.Z` pointing to the exact release commit, then publishes the GitHub Release and attaches the artifacts.

## Rerunning a failed build/release for an existing tag

If a `Build and Release` run failed after the tag was created, you can re-run the build without deleting the tag:

1. Rerun the workflow from the existing tag ref and set `allow_existing_tag` to `true`. The workflow reads the version from that tag's `pyproject.toml`, even if `main` has advanced.
2. Example (gh CLI):

```bash
gh workflow run release.yml --ref vX.Y.Z -f allow_existing_tag=true
```

3. Behavior:
  - The `release` job detects the tag already exists.
  - If `allow_existing_tag` is `false` (default), the workflow will abort to avoid accidental re-releases.
  - If `allow_existing_tag` is `true`, the workflow requires the checked-out ref to be that tag, verifies the tag resolves to the checked-out commit, rebuilds it, and attaches or overwrites its release assets.
  - If a build fails before tag creation, rerun from `main` with the default `allow_existing_tag=false`; the workflow resolves the still-committed version and creates the tag only after a successful build.

Note: the PAT used to dispatch must have Actions/Workflows dispatch permission (see "Secrets and permissions").

## Troubleshooting

- 403 when pushing tags: the PAT lacks repository contents write permission or is not authorized for organization SSO. Regenerate or authorize the PAT as required.
- `softprops/action-gh-release` failing with 403: ensure `release.yml` has `permissions: contents: write` (already configured in this repo) or change the release job to use `secrets.PAT_TOKEN` if org policy requires a PAT.
- Missing artifacts in Release: confirm `create_release` job ran after all matrix jobs and successfully downloaded uploaded artifacts by checking the workflow logs for `actions/download-artifact` steps.

## Implementation notes

- The pipeline produces six executable artifacts: `clipmorph-cli-{windows.zip,macos.zip,linux}` (CLI variant, no web dependencies or assets) and `clipmorph-ui-{windows.zip,macos.zip,linux}` (UI variant: bundles FastAPI/Uvicorn, the built Svelte dashboard, and a desktop launcher that selects a loopback port, waits for `/api/v1/health`, opens the default browser, and shuts down cleanly). Windows and macOS archives contain onedir builds so the large ML runtime is not extracted on every launch; Linux artifacts are self-extracting archives. A CI gate rejects a `cli` artifact that contains web assets and a `ui` artifact that is missing them.
- Python installation is sourced from the tagged GitHub repository rather than a package index. The base CLI install is `python -m pip install "clipmorph @ git+https://github.com/A-Baji/ClipMorph.git@vX.Y.Z"`; adding `[web]` installs FastAPI/Uvicorn and enables `clipmorph web` (headless) and the `clipmorph-ui` desktop launcher console script. There are no npm or PyPI publishing steps in this pipeline.
- `pyproject.toml` is the only version source. The package exposes its installed distribution version through `clipmorph.__version__`; frozen builds include that package metadata. The release workflow verifies that the version matches the tag and tags the exact version/changelog commit built by the matrix.

## If your org forbids PATs

If a PAT cannot be used, alternatives include:
- Using a GitHub App with permissions to dispatch workflows.
- Implementing an external artifact store (S3) and an `attach-release` workflow that runs with a privileged account to collect and attach artifacts.

If you want, I can add a short `CONTRIBUTING.md` section that points to this doc and lists who may run releases and how to create/authorize the PAT. 

---
File location:
- Release workflow: .github/workflows/release.yml
