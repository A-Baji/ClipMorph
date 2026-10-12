"""Seed the states fixture for the QA gate (tests/qa/qa-ui.config.json).

Run with the workspace data dir as argv[1]:
    python tests/qa/seed_states.py <data_dir>

- Promotes the conversion-gate fixture to a working awaiting-review gate with
  a registered artifact (reusing the 2C verification's promotion), and
- writes a real transcript edit session for the transcript-gate fixture so
  the Review tab's segment editor renders from the actual revision (the QA
  gate has no route mocks).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_ROOT / "tests"), str(REPO_ROOT / "tests" / "e2e")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from clipmorph.service import JobService  # noqa: E402
from clipmorph.transcript import create_edit_session  # noqa: E402


def main(data_dir: str) -> None:
    from verify_phase2c import _promote_conversion_review_fixture

    root = Path(data_dir)
    _promote_conversion_review_fixture(root)

    service = JobService(root)
    try:
        # The transcript-gate fixture gets a REAL edit session; the seeded
        # manifests carry synthetic bytes, so nothing here runs media work.
        manifest = next(
            item for item in service.list_jobs()
            if item.checkpoints["transcript"]["status"] == "awaiting_review")
        session = create_edit_session(
            manifest.source_sha256,
            [
                {"id": "segment-1", "start": 0.223, "end": 1.5,
                 "text": "Fixture caption one"},
                {"id": "segment-2", "start": 1.5, "end": 3.0,
                 "text": "Fixture caption two"},
            ],
            media_duration=4.0)
        # The fixture seeds the active transcript at revision 1 (ux_fixtures),
        # so the closed-expectation for the save is that revision.
        service.save_transcript_session(
            manifest.job_id, session, expected_revision=1,
            expected_checkpoint_revision=manifest.checkpoints["transcript"]["revision"])
        print(f"seeded transcript session for {manifest.job_id}")
    finally:
        service.close()


if __name__ == "__main__":
    main(sys.argv[1])
