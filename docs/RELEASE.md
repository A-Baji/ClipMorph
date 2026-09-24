# Release Flow (Version → Build → Tag and Release)

This document explains the project's release flow and how to run it locally or from the GitHub UI.

## Overview

- `.github/workflows/release.yml` is the single release pipeline. Run it manually with a version `X.Y.Z`; it updates `main`, builds and smoke-tests two executable variants (CLI and UI) for Windows, macOS, and Linux from one commit, creates the annotated tag `vX.Y.Z` and GitHub Release only after the builds succeed, and then publishes the Python package to PyPI.
- See [docs/PACKAGE_MATRIX.md](PACKAGE_MATRIX.md) for the full artifact/package matrix (audience, contents, entry point, dependencies, platform, verification command).

## Secrets and permissions

- `PAT_TOKEN` (repo secret): a personal access token used by the release workflow when pushing `main` and tags. The token must be either:
  - Classic PAT: include `repo` and `workflow` scopes; or
  - Fine-grained PAT: granted to this repository with **Actions/Workflows** (Read & write) and **Repository contents** (Read & write) as needed.
- `GITHUB_TOKEN` (provided by Actions): `release.yml` requires `contents: write` permission (set at top-level `permissions`) so the `create_release` job can create releases and attach files.
- A `pypi` GitHub Environment must exist, configured for [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) against this repository's `publish_pypi` job. No PyPI API token secret is required or used.

Ensure any organization SSO or repo policy authorizes the PAT account.

## Running a release

1. From the GitHub UI: Actions → Build and Release → Run workflow → enter `version` (e.g., `0.1.1`).
2. Or use `gh` CLI (ensure `gh` is authenticated and pointing at the repo):

```bash
gh workflow run release.yml --ref main -f version=0.1.1
```

3. The `release` job validates the version, updates `clipmorph/__version__.py`, pushes `main`, and passes the resulting commit SHA to the build jobs. It does not create the tag yet.
4. The build matrix checks out that exact commit, builds and smoke-tests Windows/macOS/Linux artifacts, and uploads them as workflow artifacts.
5. Only after all build jobs succeed, the release job creates or reuses the annotated tag and attaches the artifacts to the GitHub Release for `vX.Y.Z`.

## Rerunning a failed build/release for an existing tag

If a `Build and Release` run failed after the tag was created, you can re-run the build without deleting the tag:

1. Run the `Build and Release` workflow again with the same `version` and set `allow_existing_tag` to `true`.
2. Example (gh CLI):

```bash
gh workflow run release.yml --ref main -f version=0.1.1 -f allow_existing_tag=true
```

3. Behavior:
  - The `release` job detects the tag already exists.
  - If `allow_existing_tag` is `false` (default), the workflow will abort to avoid accidental re-releases.
  - If `allow_existing_tag` is `true`, the workflow will reuse the existing tag's commit, rebuild it, and attach or overwrite its release assets.
  - If a build fails before tag creation, rerun with the same version and `allow_existing_tag=false`; the workflow will reuse the version commit on `main` and create the tag only after a successful build.

Note: the PAT used to dispatch must have Actions/Workflows dispatch permission (see "Secrets and permissions").

## Troubleshooting

- 403 when pushing `main` or tags: the PAT lacks repository contents write permission, is not authorized for organization SSO, or cannot bypass the repository's branch rules. Regenerate or authorize the PAT as required.
- `softprops/action-gh-release` failing with 403: ensure `release.yml` has `permissions: contents: write` (already configured in this repo) or change the release job to use `secrets.PAT_TOKEN` if org policy requires a PAT.
- Missing artifacts in Release: confirm `create_release` job ran after all matrix jobs and successfully downloaded uploaded artifacts by checking the workflow logs for `actions/download-artifact` steps.

## Implementation notes

- The pipeline produces six executable artifacts: `clipmorph-cli-{windows.zip,macos.zip,linux}` (CLI variant, no web dependencies or assets) and `clipmorph-ui-{windows.zip,macos.zip,linux}` (UI variant: bundles FastAPI/Uvicorn, the built Svelte dashboard, and a desktop launcher that selects a loopback port, waits for `/api/v1/health`, opens the default browser, and shuts down cleanly). Windows and macOS archives contain onedir builds so the large ML runtime is not extracted on every launch; Linux artifacts are self-extracting archives. A CI gate rejects a `cli` artifact that contains web assets and a `ui` artifact that is missing them.
- After the release is created, the `publish_pypi` job builds the base `clipmorph` sdist/wheel and publishes it to PyPI via trusted publishing. Only the Python package is published; there are no npm publish steps anywhere in this pipeline. Installing with `pip install clipmorph` gives the CLI; `pip install "clipmorph[web]"` additionally installs FastAPI/Uvicorn and enables `clipmorph web` (headless) and the `clipmorph-ui` desktop launcher console script.
- The `pyproject.toml` uses dynamic version from `clipmorph.__version__`, so updating that file keeps package version metadata consistent with the tag. The release workflow also verifies that version matches the tag before creating the Release.

## If your org forbids PATs

If a PAT cannot be used, alternatives include:
- Using a GitHub App with permissions to dispatch workflows.
- Implementing an external artifact store (S3) and an `attach-release` workflow that runs with a privileged account to collect and attach artifacts.

If you want, I can add a short `CONTRIBUTING.md` section that points to this doc and lists who may run releases and how to create/authorize the PAT. 

---
File location:
- Release workflow: .github/workflows/release.yml
