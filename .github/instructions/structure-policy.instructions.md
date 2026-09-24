---
name: structure-policy
description: Follow the repository structure policy before creating, moving, or deleting files.
applyTo: "**"
---

Read and follow the repository-local structure policy in [docs/structure-policy.md](docs/structure-policy.md) before creating, moving, or deleting files.

Prefer the repository’s established boundaries (`clipmorph/`, `tests/`, `docs/`, `frontend/`) over new top-level directories, and keep generated runtime state such as `build/`, `clipmorph.egg-info/`, `input/`, `output/`, and `uploads/` out of source changes. Update this policy when the project architecture intentionally changes.
