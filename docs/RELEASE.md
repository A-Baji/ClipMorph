# Release Flow (Tag → Build and Release)

This document explains the project's release flow and how to run it locally or from the GitHub UI.

## Overview

- Two workflows coordinate releases:
  - `.github/workflows/tag.yml` — "Tag" workflow: run manually to create an annotated tag `vX.Y.Z` and update `clipmorph/__version__.py`.
  - `.github/workflows/build_and_release.yml` — "Build and Release" workflow: triggered by a pushed tag `v*` (or `workflow_dispatch`), builds platform artifacts (Windows/macOS/Linux) and creates/updates the GitHub Release with attached artifacts.

## Secrets and permissions

- `PAT_TOKEN` (repo secret): a personal access token used by `tag.yml` when pushing tags and (optionally) dispatching builds for existing tags. The token must be either:
  - Classic PAT: include `repo` and `workflow` scopes; or
  - Fine-grained PAT: granted to this repository with **Actions/Workflows** (Read & write) and **Repository contents** (Read & write) as needed.
- `GITHUB_TOKEN` (provided by Actions): `build_and_release.yml` requires `contents: write` permission (set at top-level `permissions`) so the `create_release` job can create releases and attach files.

Ensure any organization SSO or repo policy authorizes the PAT account.

## Running a normal release (create new tag)

1. From the GitHub UI: Actions → Tag → Run workflow → enter `version` (e.g., `0.1.1`).
2. Or use `gh` CLI (ensure `gh` is authenticated and pointing at the repo):

```bash
gh workflow run tag.yml --ref main -f version=0.1.1
```

3. `tag.yml` will validate the version string, update `clipmorph/__version__.py`, commit if changed, create annotated tag `vX.Y.Z`, push the tag and main branch (if updated).
4. Pushing the tag triggers the `Build and Release` workflow which will build artifacts in a matrix and then run a single `create_release` job that downloads artifacts and attaches them to the GitHub Release for `vX.Y.Z`.

## Rerunning a failed build/release for an existing tag

If a `Build and Release` run failed and the Git tag already exists, you can re-run the build without deleting the tag:

1. Run the `Tag` workflow again with the same `version` and set `allow_existing_tag` to `true`.
2. Example (gh CLI):

```bash
gh workflow run tag.yml --ref main -f version=0.1.1 -f allow_existing_tag=true
```

3. Behavior:
  - `tag.yml` detects the tag already exists.
  - If `allow_existing_tag` is `false` (default), the workflow will abort to avoid accidental re-releases.
  - If `allow_existing_tag` is `true`, the workflow will skip creating a new tag and will dispatch the `build_and_release.yml` workflow for the existing tag (this uses `PAT_TOKEN`). The `Build and Release` workflow will then run as if the tag were just pushed, rebuild artifacts, and the downstream `create_release` job will attach/overwrite assets on the Release.

Note: the PAT used to dispatch must have Actions/Workflows dispatch permission (see "Secrets and permissions").

## Troubleshooting

- 403 when dispatching build workflow: PAT lacks `workflow`/Actions/Workflows write permission, PAT not authorized for org SSO, or PAT user lacks repo access. Regenerate the PAT with the correct scopes and authorize SSO if required.
- `softprops/action-gh-release` failing with 403: ensure `build_and_release.yml` has `permissions: contents: write` (already configured in this repo) or change the release job to use `secrets.PAT_TOKEN` if org policy requires a PAT.
- Missing artifacts in Release: confirm `create_release` job ran after all matrix jobs and successfully downloaded uploaded artifacts by checking the workflow logs for `actions/download-artifact` steps.

## Implementation notes

- The build produces three artifacts: `clipmorph-windows.exe`, `clipmorph-macos`, and `clipmorph-linux` (self-extracting). The `create_release` job downloads each artifact and then calls `softprops/action-gh-release` once to attach them to the Release — this avoids race conditions from multiple matrix jobs each trying to create/update the Release.
- The `pyproject.toml` uses dynamic version from `clipmorph.__version__`, so updating that file keeps package version metadata consistent with the tag.

## If your org forbids PATs

If a PAT cannot be used, alternatives include:
- Using a GitHub App with permissions to dispatch workflows.
- Implementing an external artifact store (S3) and an `attach-release` workflow that runs with a privileged account to collect and attach artifacts.

If you want, I can add a short `CONTRIBUTING.md` section that points to this doc and lists who may run releases and how to create/authorize the PAT. 

---
File locations:
- Tag workflow: .github/workflows/tag.yml
- Build & Release workflow: .github/workflows/build_and_release.yml
