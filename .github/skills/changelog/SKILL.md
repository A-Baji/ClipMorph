---
name: changelog
description: "Use when: adding, revising, reviewing, or releasing changelog items in ClipMorph, including GitHub Release notes. Follows Keep a Changelog 1.1.0."
---

# Changelog Management

`CHANGELOG.md` is the canonical, human-readable history for ClipMorph. Keep it
in [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) format and
use it as the source for GitHub Release notes.

## When to Add an Item

Add an item under `## [Unreleased]` whenever a change is notable to a user,
operator, package consumer, or integrator. Include new capabilities, behavior
changes, deprecations, removals, bug fixes, security changes, configuration or
CLI contract changes, and compatibility changes.

Do not add entries for internal refactors, routine dependency updates, test-only
work, CI-only work, or implementation steps unless they change the delivered
product, supported installation path, or user-visible behavior.

## How to Write an Item

- Write for people rather than as a commit-log summary.
- State the outcome and affected surface in one concise bullet.
- Group entries under only the applicable standard headings: `Added`, `Changed`,
  `Deprecated`, `Removed`, `Fixed`, and `Security`.
- Do not create empty headings or use nonstandard categories such as
  `Validation` or `Scope note`.
- Call out a breaking change, removal, or security impact plainly.
- Keep versions in reverse chronological order.

## Releasing

1. Move relevant `Unreleased` items into `## [X.Y.Z] - YYYY-MM-DD` using the
   UTC release date, then leave a new empty `## [Unreleased]` section above it.
2. Add or update the version comparison links at the bottom of `CHANGELOG.md`.
3. Confirm `python -m clipmorph.release_notes vX.Y.Z CHANGELOG.md <output>`
   extracts exactly that section.
4. The release workflow uses this extracted section for the GitHub Release body;
   it uploads the complete `CHANGELOG.md` only as an asset.

## Review

Before merging, verify every user-notable change has one accurate item, every
released version has an ISO 8601 date, and no release body includes notes from
another version.