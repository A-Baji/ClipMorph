"""Issue #261 board / scroll-model / empty-state verification.

Re-derivable assertions over the seeded fixtures (tests/e2e/harness.py
--scenario empty|states), updated for the merged Jobs view:

- B2  the empty fixture renders exactly the six pipeline columns (Pending,
      Transcribe, Convert, Upload, Complete, Failed — item 4) with a
      "No jobs" placeholder in each.
- B3  no page-level horizontal scrollbar at 1920 / 1366 / 1024; at >=1400px
      the board container itself does not scroll horizontally, below 1400px
      it scrolls internally.
- B12 the states fixture hallows no legacy columns: Running / Awaiting
      review / Scheduled do not exist as columns (item 5 — they are card
      badges now), and pre-run jobs render under Pending.
- B19 completed jobs render with no `.progress` elements in the Complete
      column (B19 held after the item 2/6 card-grid migration).
- A1  the remaining empty-state prompts render: the expanded empty column
      (the old Completed archive default), Metrics, Layouts, and the New
      modal's empty clip grid.
- D10 a single-clip selection yields a rail with exactly one entry and no
      Batch entry, and (item 9) deselecting back to one clip from two drops
      the Batch entry.
- F1  the modal artifact row's "more" menu keeps the raw download (F21's
      "Download stays in the row menu" while "Open folder" is the affordance).
- F2  a discarded draft does not resurrect: "New" (a modal pop-up, item 3)
      after a discard opens an empty, unchecked clip grid, and a fresh
      single-clip selection still has no Batch entry.

Run:

    python tests/e2e/verify_board.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
for candidate in (str(TESTS_DIR), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import harness  # noqa: E402

COLUMNS = [
    "Pending", "Transcribe", "Convert", "Upload", "Complete", "Failed"]
VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080},
    "laptop": {"width": 1366, "height": 768},
    "small": {"width": 1024, "height": 768},
}


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


def _wait_ready(page):
    page.wait_for_selector(".shell", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Loading workspace')",
        timeout=15_000,
    )


def _page_scrolls(page) -> bool:
    return page.evaluate(
        "() => document.documentElement.scrollWidth"
        " > document.documentElement.clientWidth"
        " || document.body.scrollWidth > window.innerWidth",
    )


def _board_scrolls(page):
    return page.evaluate(
        "() => { const b = document.querySelector('.board');"
        " return b ? b.scrollWidth > b.clientWidth : null; }",
    )


def _column(page, label: str):
    return page.locator(f"section.column[aria-label='{label}']")


def run_empty_board(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    titles = page.locator("section.column .column-title").all_inner_texts()
    report.check("B2 empty: exactly the six pipeline columns render",
                 titles == COLUMNS, f"titles={titles}")
    empties = page.locator("section.column .column-empty",
                           has_text="No jobs").count()
    report.check("B2 empty: each column shows its 'No jobs' placeholder",
                 empties == 6, f"empties={empties}")
    report.check("B2 empty: no legacy status columns render",
                 page.locator(
                     "section.column[aria-label='Running'], "
                     "section.column[aria-label='Awaiting review'], "
                     "section.column[aria-label='Scheduled']").count() == 0,
                 "legacy columns present")


def run_scroll_model(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    for vp_name, vp in VIEWPORTS.items():
        page.set_viewport_size(vp)
        page.wait_for_timeout(150)
        page_ok = not _page_scrolls(page)
        board = _board_scrolls(page)
        expect_scroll = vp["width"] < 1400
        report.check(
            f"B3 {vp_name}: no page-level horizontal scrollbar",
            page_ok, f"page_scroll={not page_ok}")
        report.check(
            f"B3 {vp_name}: board internal scroll "
            f"{'present' if expect_scroll else 'absent'}",
            board is not None and board == expect_scroll,
            f"board_scroll={board}, expect={expect_scroll}")


def run_board_state_checks(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    # Item 5: the states fixture renders a card badge per job status chip
    # inside each stage column; pre-run jobs live under Pending.
    pending = _column(page, "Pending")
    report.check("B12 states: pre-run jobs render in the Pending column",
                 pending.locator(".card-main").count() >= 1,
                 "no pre-run card in Pending")
    report.check("B12 states: no 'queued N' sub-badge remains on cards",
                 page.locator(".queued-badge").count() == 0,
                 "queued-badge present")
    # B19: completed jobs render in the Complete column with no progress
    # bars (they render as chips + actions, B19's letter).
    complete = _column(page, "Complete")
    report.check("B19: the Complete column renders completed jobs "
                 "with no progress bars",
                 complete.locator(".card-main").count() >= 1
                 and complete.locator(".progress").count() == 0,
                 "progress bar on a completed card")


def run_artifact_row_menu(page, url: str, report: Reporter) -> None:
    """F1/F21: the modal artifact row keeps raw download in its "more" menu."""
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    # The Complete column's first card opens the detail modal on Overview,
    # whose Artifacts card hosts the row.
    _column(page, "Complete").locator(".card-main").first.click()
    page.wait_for_selector("div.detail-modal", timeout=5_000)
    page.wait_for_timeout(200)
    page.locator("button.tab", has_text="Overview").click()
    page.wait_for_timeout(200)
    more = page.locator("div.detail-modal .more button")
    report.check("F21: the artifact row exposes its 'more' menu",
                 more.count() >= 1, "no .more control on the artifact row")
    if more.count():
        more.first.click()
        page.wait_for_timeout(150)
        item = page.locator("div.detail-modal .more .menu a", has_text="Download")
        report.check("F1: the row menu keeps the raw download",
                     item.count() >= 1
                     and "/download" in (item.first.get_attribute("href") or ""),
                     "no Download item in the row menu")


def run_column_expand_and_back(page, url: str, report: Reporter) -> None:
    """Item 6: header-click expands the column into the full card grid; the
    back affordance (header button, Esc) returns to the All view."""
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    _column(page, "Complete").locator(".column-head").click()
    page.wait_for_timeout(200)
    report.check("item 6: the expanded column shows the full card grid",
                 page.locator(".jcard").count() >= 1, "no cards in full view")
    report.check("item 6: the expanded view carries the back affordance",
                 page.get_by_role("button",
                                  name="Back to all stages").count() == 1,
                 "back button missing")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    report.check("item 6: Esc returns to the All view",
                 page.locator(".board").count() >= 1, "board not restored")


def run_empty_prompts(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    _column(page, "Complete").locator(".column-head").click()
    page.wait_for_timeout(200)
    report.check("A1 complete: the expanded empty column prompts the user",
                 page.get_by_text("Nothing in Complete").count() >= 1,
                 "expanded-column empty prompt missing")
    page.get_by_text("Metrics", exact=True).first.click()
    page.wait_for_timeout(150)
    report.check("A1 metrics: empty state prompts the user",
                 page.get_by_text("No published posts with metrics yet")
                 .count() >= 1, "metrics empty prompt missing")
    page.get_by_text("Layouts", exact=True).first.click()
    page.wait_for_timeout(150)
    report.check("A1 layouts: empty state prompts the user",
                 page.get_by_text("No presets yet").count() >= 1,
                 "layouts empty prompt missing")
    page.get_by_text("Jobs", exact=True).first.click()
    page.wait_for_timeout(150)
    page.get_by_role("button", name=re.compile("New")).first.click()
    page.wait_for_selector(".wizard-modal", timeout=5_000)
    page.wait_for_timeout(150)
    report.check("A1 clips: empty clip grid prompts the user",
                 page.get_by_text("No clips in your source folder yet")
                 .count() >= 1, "clip-grid empty prompt missing")
    report.check("F2 empty: the wizard shows no Batch rail at step 1",
                 page.locator(".rail").count() == 0, ".rail present at step 1")


def run_single_clip_and_discard(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    page.get_by_role("button", name=re.compile("New")).first.click()
    page.wait_for_selector(".wizard-modal", timeout=5_000)
    page.wait_for_timeout(150)
    # D10 + item 9: the rail tracks the live selection. Start with two clips
    # (a Batch entry exists), then drop to one from the clips step.
    page.get_by_role("button", name="Clear").first.click()
    clips = page.locator("label.clip-card input")
    clips.first.check()
    clips.nth(1).check()
    page.wait_for_timeout(80)
    page.get_by_role("button", name=re.compile(r"Next: Configure")).click()
    page.wait_for_timeout(300)
    names = page.locator(".rail-item .rail-name").all_inner_texts()
    report.check("item 9: two clips produce a Batch entry plus both clips",
                 len(names) == 3, f"rail={names}")

    # Item 9: returning to clips and deselecting removes the ghost entry.
    page.get_by_role("button", name=re.compile(r"Back to clips")).click()
    page.wait_for_timeout(150)
    page.locator("label.clip-card.selected input").first.uncheck()
    page.wait_for_timeout(150)
    page.get_by_role("button", name=re.compile(r"Next: Configure")).click()
    page.wait_for_timeout(300)
    names = page.locator(".rail-item .rail-name").all_inner_texts()
    report.check("item 9: deselecting back to one clip drops the Batch entry",
                 len(names) == 1
                 and not any("Batch" in name for name in names),
                 f"rail after deselect={names}")

    # F2: discard must clear the WHOLE draft — in-memory and local — so a
    # later "New" opens an empty clip grid with nothing pre-checked.
    page.get_by_role("button", name="Discard draft").first.click()
    page.wait_for_timeout(150)
    page.locator(".modal").get_by_role("button", name="Discard draft").click()
    page.wait_for_selector(".wizard-modal", state="detached", timeout=10_000)
    report.check("F2: discard closes the New modal",
                 page.locator(".wizard-modal").count() == 0
                 and page.locator(".rail").count() == 0,
                 "wizard still open after discard")
    page.get_by_role("button", name=re.compile("New")).first.click()
    page.wait_for_selector(".wizard-modal", timeout=10_000)
    selected = page.locator("label.clip-card.selected").count()
    report.check("F2: 'New' after discard shows an empty, unchecked clip grid",
                 selected == 0, f"pre-checked cards={selected}")
    # And a fresh single-clip selection still yields no Batch entry.
    page.get_by_role("button", name="Clear").first.click()
    page.locator("label.clip-card input").first.check()
    page.wait_for_timeout(80)
    page.get_by_role("button", name=re.compile(r"Next: Configure")).click()
    page.wait_for_timeout(300)
    report.check("F2: fresh single-clip selection still has no Batch entry",
                 page.locator(".rail-item", has_text="Batch").count() == 0,
                 "Batch resurrected after discard")


def main() -> int:
    from playwright.sync_api import sync_playwright

    report = Reporter()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        with harness.workspace("empty") as server:
            page = browser.new_page(viewport=dict(VIEWPORTS["laptop"]))
            run_empty_board(page, server.url, report)
            run_empty_prompts(page, server.url, report)
            page.close()
        with harness.workspace("states") as server:
            page = browser.new_page(viewport=dict(VIEWPORTS["desktop"]))
            run_scroll_model(page, server.url, report)
            run_board_state_checks(page, server.url, report)
            run_column_expand_and_back(page, server.url, report)
            run_single_clip_and_discard(page, server.url, report)
            run_artifact_row_menu(page, server.url, report)
            page.close()
        browser.close()

    print(f"board verification: {len(report.passes)} passed, "
          f"{len(report.failures)} failed")
    for failure in report.failures:
        print(f"  FAIL {failure}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
