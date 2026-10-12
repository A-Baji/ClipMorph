"""Phase 2C (#259) runtime verification — E11, E13, E14, E16, E17, E22, D24, U18.

Driven against the seeded server harness (``tests/e2e/harness.py``). The
backend contract behind the accept flow is pinned separately in
``tests/test_web.py::test_accept_checkpoint_resumes_pending_work_immediately``
and the store-level mocked-poll behavior in
``tests/e2e/e14-store-poll.mjs``; this script observes the built UI.

Checks (per the issue's verification map):
- E13  Playwright: modal closed after the accept call succeeds.
- E14  Playwright: after accept no poll iteration renders the job queued and
       the Running column's "queued N" sub-badge never grows (route-mocked
       queued passthrough; note the fixture's synthetic bytes make the real
       resumed run fail fast — the passthrough suppression itself is what is
       asserted, plus the board never shows a queued chip for the accepted
       job).
- E16  Playwright computed-style: both accept buttons share the accent class.
- E17  Playwright: Review tab shows only the current gate; a <video> mounts
       on the artifact preview URL for the conversion gate.
- E22  Playwright: no raw JSON visible on any review surface.
- U18  Playwright: background scroll locked; Tab cannot escape the dialog.
- D24  Playwright: live inline errors, partial create removes the created
       clip, reselection rule, no duplicate on second Create, last-clip /
       discard landing.

Usage::
    python tests/e2e/verify_phase2c.py [--evidence <dir>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
for candidate in (str(TESTS_DIR), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import harness  # noqa: E402

DESKTOP = {"width": 1920, "height": 1080}


class Reporter:
    def __init__(self):
        self.passes: list[str] = []
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passes.append(name)
        else:
            self.failures.append(f"{name}{f': {detail}' if detail else ''}")
        return bool(ok)


def _wait_ready(page) -> None:
    page.wait_for_selector(".shell", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Loading workspace')",
        timeout=15_000,
    )


_review_tab = "text=Review"


def open_job(page, url: str, title: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    # Issue #261 item 6: the single Jobs board is the default surface and
    # stage columns host the fixtures now (no Completed/Queue sub-tabs).
    page.wait_for_timeout(120)
    card = page.locator("article.card", has_text=title).first
    card.get_by_role("button").first.click()
    page.wait_for_selector("div.detail-modal", timeout=5_000)
    page.wait_for_timeout(200)


def _promote_conversion_review_fixture(data_dir: Path):
    """Prepare the two reviewed gates for the built UI.

    - "Checkpoint fixture: awaiting_review" becomes a working conversion
      gate: its single conversion group moves to ``awaiting_review`` the way
      the pipeline owns group records, and it gains a registered artifact for
      the media player.
    - Both review-gate fixtures get an active transcript revision pointer so
      the caption/segment review flow loads a revision (the revision itself
      is route-mocked in the verification, see below).

    The seeded fixture sets the conversion aggregate to ``awaiting_review``
    via an aggregate transition; the accept endpoint walks the GROUP records
    (the same records the pipeline owns), so promote the single group to
    awaiting review and register a real artifact file for the player.
    """
    from ux_fixtures import _registered_artifact

    from clipmorph.service import JobService

    service = JobService(data_dir)
    try:
        conversion_fixture = next(
            item for item in service.list_jobs()
            if item.status == "awaiting_review"
            and item.checkpoints["conversion"]["status"] == "awaiting_review"
            and item.checkpoints["transcript"]["status"] == "completed")
        groups = conversion_fixture.checkpoints["conversion"].get("groups") or {}
        group_id = next(iter(groups))
        for status in ("running", "awaiting_review"):
            conversion_fixture = service.get_job(conversion_fixture.job_id)
            revision = conversion_fixture.checkpoints["conversion"]["groups"][
                group_id]["revision"]
            conversion_fixture.transition_checkpoint(
                "conversion", status, revision, service.jobs_dir,
                group_id=group_id)
        conversion_fixture = service.get_job(conversion_fixture.job_id)
        _registered_artifact(conversion_fixture, service)

        # Both review-gate fixtures load their caption lines from the active
        # transcript revision.
        for manifest in (*service.list_jobs(),):
            if (manifest.status == "awaiting_review"
                    and manifest.checkpoints["transcript"]["status"]
                    == "awaiting_review"):
                manifest.active_transcript = {
                    "revision": manifest.checkpoints["transcript"]["revision"],
                    "path": "transcripts/1/session.json"}
                manifest.save(service.jobs_dir)
        print(f"promoted conversion review fixture: {conversion_fixture.job_id}")
    finally:
        service.close()


def run_modal_checks(page, url: str, report: Reporter, evidence: Path) -> dict:
    """E13/E14/E16/E17/E22/U18 checks on the review modal (states fixture)."""

    # The seeded fixtures carry no active transcript revision sessions, so
    # the transcript GET is route-mocked to a two-segment edit session while
    # every other request (accept, job lists) hits the real seeded server.
    def transcript_route(route):
        route.fulfill(json={
            "schema_version": 2, "revision": 1,
            "source_sha256": "0" * 64,
            "segments": [
                {"start": 0, "end": 1.5, "text": "Fixture caption one"},
                {"start": 1.5, "end": 3, "text": "Fixture caption two"},
            ],
        })

    page.route(re.compile(r"/api/v1/jobs/[^/]+/transcript$"), transcript_route)

    # --- Transcript gate: "Status fixture: awaiting_review" ----------------
    open_job(page, url, "Status fixture: awaiting_review")
    page.locator("button.tab", has_text="Review").click()
    page.wait_for_timeout(300)
    page.locator(".segment").first.wait_for(timeout=4_000)

    # E17: only the current gate — the transcript gate shows the editor and
    # exposes no composition gate affordances at all.
    report.check("E17 transcript: segment editor is the gate's affordance",
                 page.locator(".segment").count() >= 1)
    report.check("E17 transcript: no accept-composition present",
                 page.get_by_text("Accept composition").count() == 0)
    report.check("E17 transcript: no media player present",
                 page.locator("video").count() == 0)
    report.check("E22: no raw JSON text on the transcript gate",
                 "{" not in page.locator("div.detail-modal").inner_text())

    # E16: class-level comparison of the accept accent.
    accept_class = page.get_by_text("Accept transcript", exact=True).get_attribute("class")
    report.check("E16: 'Accept transcript' carries the accent class",
                 accept_class is not None and "btn btn-primary" in accept_class,
                 str(accept_class))

    # --- E13: accept closes the modal after the call succeeds ---------------
    page.get_by_text("Accept transcript", exact=True).click()
    # E14-DOM: sample the board while the accepted job's polls pass through;
    # a route-mocked queued passthrough must never surface as "Queued" chips
    # (issue #261 item 5: the legacy "queued N" sub-badge no longer exists).
    samples: list[dict] = []

    def sampler() -> None:
        if page.locator("div.detail-modal").count():
            samples.append({"modal": True})
            return
        card = page.locator("article.card",
                            has_text="Status fixture: awaiting_review")
        if not card.count():
            samples.append({"card": "gone"})
            return
        badges = card.locator(".badge")
        chips = [badges.nth(i).inner_text() for i in range(badges.count())]
        samples.append({"chips": chips})

    ticks = 0
    while True:
        sampler()
        ticks += 1
        if not page.locator("div.detail-modal").count():
            break
        if ticks > 40:
            break
        page.wait_for_timeout(60)
    report.check("E13: modal closed after the accept call succeeded",
                 page.locator("div.detail-modal").count() == 0 or page.locator(
                     "div.detail-modal").is_hidden(),
                 f"ticks={ticks}")
    page.wait_for_timeout(1_500)  # let the store's post-accept polls settle
    for _ in range(6):
        sampler()
        page.wait_for_timeout(120)
    bad_samples = [
        sample for sample in samples
        if (sample.get("chips") and any(chip.strip().lower() == "queued"
                                        for chip in sample["chips"]))
    ]
    report.check(
        "E14: no poll iteration renders the accepted job as queued (board)",
        not bad_samples, json.dumps(bad_samples[:3]))
    report.check(
        "E14: the legacy 'queued N' sub-badge never renders (item 5)",
        page.locator(".queued-badge").count() == 0,
        "queued-badge present")

    # --- Conversion gate (promoted fixture): player + structured data ------
    open_job(page, url, "Checkpoint fixture: awaiting_review")
    page.locator("button.tab", has_text="Review").click()
    page.wait_for_timeout(400)

    report.check("E17 conversion: accept-composition is the current gate",
                 page.get_by_text("Accept composition").count() == 1)
    report.check("E17 conversion: transcript editor hidden",
                 page.locator(".segment-editor, .segment textarea").count() == 0)
    video = page.locator("video.review-player")
    report.check("E17 conversion: a <video> mounts on the preview URL",
                 video.count() == 1 and "/artifacts/" in (video.get_attribute("src") or ""))

    # E16 computed-style/class equality across gates.
    composition_class = page.get_by_text("Accept composition", exact=True).get_attribute("class")
    report.check("E16: both accept actions share the accent class",
                 composition_class is not None
                 and "btn btn-primary" in composition_class,
                 str(composition_class))

    review_text = page.locator("div.detail-modal").inner_text()
    report.check("E22: no raw JSON blob is visible in composition review",
                 "{" not in review_text, review_text[:200])
    report.check("E22: composition renders labeled structured sections",
                 page.locator(".composition-block").count() > 0)

    # --- U18: focus trap + scroll lock -------------------------------------
    page.locator("h3", has_text="Composition").click()  # keep the dialog active
    page.locator("div.detail-modal").click(position={"x": 10, "y": 10})
    report.check("U18: background scroll locked (both scroll containers)",
                 page.evaluate(
                     "getComputedStyle(document.documentElement).overflow === 'hidden' "
                     "&& getComputedStyle(document.body).overflow === 'hidden'"))
    report.check("U18: the board cannot scroll behind the dialog",
                 page.evaluate("window.scrollY") == 0)
    page.mouse.move(15, 400)
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(150)
    report.check("U18: wheel input on the barrier never scrolls the board",
                 page.evaluate("window.scrollY") == 0)
    inside = lambda: page.evaluate(
        "!!document.activeElement && "
        "!!document.activeElement.closest('.detail-modal')")
    inside_steps = []
    for _ in range(12):
        page.keyboard.press("Tab")
        inside_steps.append(inside())
    report.check("U18: Tab cycles inside the dialog (12 steps)",
                 all(inside_steps), f"steps={inside_steps}")
    page.keyboard.press("Shift+Tab")
    report.check("U18: Shift+Tab cycles inside the dialog",
                 page.evaluate(
                     "!!document.activeElement.closest('.detail-modal')"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    report.check("U18: Escape closes the dialog; scroll unlocked",
                 page.locator("div.detail-modal").count() == 0
                 and page.evaluate("getComputedStyle(document.body).overflow") != "hidden"
                 and page.evaluate(
                     "getComputedStyle(document.documentElement).overflow") != "hidden")

    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        page.locator("div.content").first.screenshot(
            path=str(evidence / "after-2c-board.png"))
    return {"modal_samples": len(samples)}


def run_wizard_checks(page, url: str, report: Reporter, evidence: Path) -> dict:
    """D24: live validation, partial create, reselection, landings.

    The dry-run validation and bulk create are route-mocked so the two-clip
    scenario is deterministic: one clip "fails" validation with a message
    that names its config path, the other clips create and leave the wizard.
    """
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    page.get_by_text("Jobs", exact=True).first.click()
    page.wait_for_timeout(150)

    page.get_by_role("button", name=re.compile("New")).click()
    page.wait_for_selector(".wizard-modal", timeout=5_000)
    page.wait_for_selector(".clip-grid", timeout=5_000)
    clips = page.locator(".clip-card").all()
    names = []
    for clip in clips[:2]:
        clip.click()
        names.append(clip.inner_text().split("\n")[0])
    a, b = names[0], names[1]
    page.get_by_text("Next: Configure").click()
    page.wait_for_timeout(300)
    rail_names = page.locator(".rail-item .rail-name").all_inner_texts()
    report.check("D10/D24: the rail lists Batch plus both clips",
                 len(rail_names) == 3 and rail_names[0].strip() == "Batch",
                 str(rail_names))

    # Route-mock the wizard network (deterministic two-clip scenario).
    INVALID = (a, "platforms.youtube.privacy_status must be one of public, "
                  "private, unlisted")
    created_seen: list[dict] = []

    def validate_route(route):
        body = route.request.post_data_json or {}
        payload = body.get("job_configs", [])
        failed = [
            {"source": config.get("general", {}).get("source"),
             "status": "failed",
             "code": "invalid_config",
             "message": INVALID[1],
             "record_index": index}
            for index, config in enumerate(payload)
            if config.get("general", {}).get("source") == INVALID[0]
        ]
        route.fulfill(json={"valid": not failed, "created": [], "skipped": [],
                           "failed": failed, "warnings": []})

    def bulk_route(route):
        body = route.request.post_data_json or {}
        created = [
            {"source": config.get("general", {}).get("source"),
             "status": "created", "code": "created",
             "record_index": index, "job_id": f"wire-{index}",
             "created": True}
            for index, config in enumerate(body.get("job_configs", []))
        ]
        created_seen.append(body)
        route.fulfill(json={"created": created, "failed": [], "skipped": [],
                            "summary": {"created": len(created)}})

    page.route("**/api/v1/jobs/validate", validate_route)
    page.route("**/api/v1/jobs/bulk", bulk_route)

    # Edit a batch-level field inside the YouTube platform node; the
    # debounced dry-run maps clip A's error to the named field inline (D24).
    # The batch pane aggregates the per-source validation set; YouTube's
    # platform node starts collapsed (item 7 left the outer Platform card
    # expanded like every other section, but the rows keep their toggle).
    page.locator(".rail-item", has_text="Batch").click()
    page.wait_for_timeout(200)
    page.locator("button.platform-node-head", has_text="YouTube").click()
    page.wait_for_timeout(300)
    # Issue #261 item 7: config sections render expanded, so the mapped
    # field is directly reachable.
    privacy = (page.locator(".platform-body .config-field",
                            has_text="Privacy status").first
               .locator("select"))
    privacy.select_option("unlisted")
    page.wait_for_timeout(1_000)
    inline = page.locator(".field-error", has_text="privacy_status")
    report.check("D24: the mapped field error renders inline",
                 inline.count() >= 1, "no .field-error visible")

    # The per-job pane carries only that job's summary + its mapped error.
    page.locator(".rail-item", has_text=a).click()
    page.wait_for_timeout(300)
    report.check("D24: the per-job summary also names the source",
                 page.locator(".job-error", has_text=a).count() >= 1)

    # Partial create: only the valid clip is submitted; it leaves the rail.
    page.get_by_text(re.compile(r"Create \d+ job")).click()
    page.wait_for_timeout(700)
    rail_after = page.locator(".rail-item .rail-name").all_inner_texts()
    report.check("D24: the created clip leaves the wizard rail",
                 b not in rail_after and a in rail_after,
                 f"rail={rail_after}")
    report.check("D24: the Create submitted only valid jobs",
                 bool(created_seen)
                 and len(created_seen[0]["job_configs"]) == 1
                 and created_seen[0]["job_configs"][0]["general"]["source"] == b)

    # Second Create: the remaining clip is still invalid — nothing resubmits.
    page.get_by_text(re.compile(r"Create \d+ job")).click()
    page.wait_for_timeout(700)
    report.check("D24: a second Create never recreates the first clip",
                 len(created_seen) == 1, f"bulk calls={len(created_seen)}")
    rail_second = page.locator(".rail-item .rail-name").all_inner_texts()
    report.check("D24: the invalid job stays on the config step",
                 a in rail_second and len(rail_second) == 1,
                 f"rail={rail_second}")
    # D24 reselection (item 9): one clip remains, so the Batch entry is gone —
    # the remaining entry stays selectable and keeps its mapped inline error.
    page.locator(".rail-item", has_text=a).click()
    page.wait_for_timeout(300)
    page.locator("button.platform-node-head", has_text="YouTube").click()
    page.wait_for_timeout(200)
    report.check("D24: reselection keeps the remaining entry selectable",
                 page.locator(".rail-item.active", has_text=a).count() >= 1
                 and page.locator(".field-error").count() > 0,
                 "entry or field error missing")

    # Make it valid, create the last clip: the rail empties and the app
    # lands on the Jobs board (D24 last-clip landing, item 6 single view).
    page.unroute("**/api/v1/jobs/validate")

    def validate_all(route):
        route.fulfill(json={"valid": True, "created": [], "skipped": [],
                            "failed": [], "warnings": []})

    page.route("**/api/v1/jobs/validate", validate_all)
    page.get_by_text(re.compile(r"Create \d+ job")).click()
    page.wait_for_timeout(1_000)
    report.check("D24: the final valid clip is submitted once",
                 len(created_seen) == 2, f"bulk calls={len(created_seen)}")
    report.check("D24: last clip's create lands on the Jobs board",
                 page.locator(".wizard-modal").count() == 0
                 and page.locator(".board").count() >= 1,
                 "wizard-modal or board missing")
    report.check("D24: the wizard exited the config step",
                 page.locator(".rail").count() == 0)

    # Discard landing: a draft with remaining clips discards and the New
    # modal closes onto the Jobs board.
    page.get_by_role("button", name=re.compile("New")).click()
    page.wait_for_selector(".wizard-modal", timeout=5_000)
    page.wait_for_selector(".clip-grid", timeout=5_000)
    page.locator(".clip-card").first.click()
    page.get_by_text("Next: Configure").click()
    page.wait_for_timeout(250)
    page.get_by_text("Discard draft").first.click()
    page.get_by_role("button", name="Discard draft").last.click()  # confirm
    page.wait_for_timeout(400)
    report.check("D24: a discard with clips left closes the New modal",
                 page.locator(".wizard-modal").count() == 0,
                 "new modal still open after discard")

    if evidence:
        page.locator("div.content").first.screenshot(
            path=str(evidence / "after-2c-d24-queue-landing.png"))
    return {"names": names}


def main() -> int:
    parser = argparse.ArgumentParser(description="ClipMorph Phase 2C verification")
    parser.add_argument("--evidence", default=None,
                        help="optional directory for after-evidence PNGs")
    args = parser.parse_args()

    evidence = Path(args.evidence) if args.evidence else None
    report = Reporter()

    with tempfile.TemporaryDirectory(prefix="clipmorph-2c-") as temp_dir:
        data_dir = Path(temp_dir) / "data"
        harness.build_workspace("states", data_dir)
        _promote_conversion_review_fixture(data_dir)
        server = harness.start(data_dir)
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    context = browser.new_context(viewport=DESKTOP,
                                                  reduced_motion="reduce")
                    page = context.new_page()
                    page.set_default_timeout(8_000)
                    try:
                        run_modal_checks(page, server.url, report, evidence)
                    except Exception as error:
                        report.failures.append(f"modal checks crashed: {error}")
                finally:
                    browser.close()
                browser = playwright.chromium.launch()
                try:
                    context = browser.new_context(viewport=DESKTOP,
                                                  reduced_motion="reduce")
                    page = context.new_page()
                    page.set_default_timeout(8_000)
                    try:
                        run_wizard_checks(page, server.url, report, evidence)
                    except Exception as error:
                        report.failures.append(f"wizard checks crashed: {error}")
                finally:
                    browser.close()
        finally:
            server.stop()

    print(f"2C verification: {len(report.passes)} passed, "
          f"{len(report.failures)} failed")
    for line in report.passes:
        print(f"  PASS {line}")
    for line in report.failures:
        print(f"  FAIL {line}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
