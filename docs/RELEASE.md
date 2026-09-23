# Release Flow (Version → Tag → Build and Release)

This document explains the project's release flow and how to run it locally or from the GitHub UI.

## Overview

- `.github/workflows/release.yml` is the single release pipeline. Run it manually with a version `X.Y.Z`; it updates `main`, creates the annotated tag `vX.Y.Z`, builds platform artifacts, and creates or updates the GitHub Release.

## Secrets and permissions

- `PAT_TOKEN` (repo secret): a personal access token used by the release workflow when pushing `main` and tags. The token must be either:
  - Classic PAT: include `repo` and `workflow` scopes; or
  - Fine-grained PAT: granted to this repository with **Actions/Workflows** (Read & write) and **Repository contents** (Read & write) as needed.
- `GITHUB_TOKEN` (provided by Actions): `release.yml` requires `contents: write` permission (set at top-level `permissions`) so the `create_release` job can create releases and attach files.

Ensure any organization SSO or repo policy authorizes the PAT account.

## Running a release

1. From the GitHub UI: Actions → Build and Release → Run workflow → enter `version` (e.g., `0.1.1`).
2. Or use `gh` CLI (ensure `gh` is authenticated and pointing at the repo):

```bash
gh workflow run release.yml --ref main -f version=0.1.1
```

3. The `release` job validates the version, updates `clipmorph/__version__.py`, pushes `main`, and creates the annotated tag `vX.Y.Z`.
4. The build matrix checks out that exact tag, builds Windows/macOS/Linux artifacts, and then attaches them to the GitHub Release for `vX.Y.Z`.

## Rerunning a failed build/release for an existing tag

If a `Build and Release` run failed and the Git tag already exists, you can re-run the build without deleting the tag:

1. Run the `Build and Release` workflow again with the same `version` and set `allow_existing_tag` to `true`.
2. Example (gh CLI):

```bash
gh workflow run release.yml --ref main -f version=0.1.1 -f allow_existing_tag=true
```

3. Behavior:
  - The `release` job detects the tag already exists.
  - If `allow_existing_tag` is `false` (default), the workflow will abort to avoid accidental re-releases.
  - If `allow_existing_tag` is `true`, the workflow will skip creating a new tag, build the existing tag, and attach or overwrite its release assets.

Note: the PAT used to dispatch must have Actions/Workflows dispatch permission (see "Secrets and permissions").

## Troubleshooting

- 403 when pushing `main` or tags: the PAT lacks repository contents write permission, is not authorized for organization SSO, or cannot bypass the repository's branch rules. Regenerate or authorize the PAT as required.
- `softprops/action-gh-release` failing with 403: ensure `release.yml` has `permissions: contents: write` (already configured in this repo) or change the release job to use `secrets.PAT_TOKEN` if org policy requires a PAT.
- Missing artifacts in Release: confirm `create_release` job ran after all matrix jobs and successfully downloaded uploaded artifacts by checking the workflow logs for `actions/download-artifact` steps.

## Implementation notes

- The pipeline produces three artifacts: `clipmorph-windows.exe`, `clipmorph-macos`, and `clipmorph-linux` (self-extracting). The `create_release` job downloads each artifact and then calls `softprops/action-gh-release` once to attach them to the Release — this avoids race conditions from multiple matrix jobs each trying to create/update the Release.
- The `pyproject.toml` uses dynamic version from `clipmorph.__version__`, so updating that file keeps package version metadata consistent with the tag.

## If your org forbids PATs

If a PAT cannot be used, alternatives include:
- Using a GitHub App with permissions to dispatch workflows.
- Implementing an external artifact store (S3) and an `attach-release` workflow that runs with a privileged account to collect and attach artifacts.

If you want, I can add a short `CONTRIBUTING.md` section that points to this doc and lists who may run releases and how to create/authorize the PAT. 

---
File location:
- Release workflow: .github/workflows/release.yml
