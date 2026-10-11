"""Issue #259 board / scroll-model / empty-state verification (finding F3).

Turns the Phase 3 re-audit's hand-driven DOM numbers from
docs/ux-audit-259.md into committed, re-runnable assertions:

- B2  the empty fixture renders exactly the four columns with "No jobs"
       placeholders inside each.
- B3  no page-level horizontal scrollbar at 1920 / 1366 / 1024; at >=1400px
       the board container itself does not scroll horizontally, below 1400px
       it scrolls internally.
- B12 no "Queued" column; the states fixture renders queued jobs under
       Running with a "queued N" sub-badge.
- B19 completed jobs render with no `.progress` elements (Completed archive).
- A1  the remaining empty-state prompts render: Completed archive, clip
       selection grid, Metrics, and Layouts.
- D10 a single-clip selection yields a rail with exactly one entry and no
      Batch entry.
- F1  the modal artifact row's "more" menu keeps the raw download (F21's
      "Download stays in the row menu" while "Open folder" is the affordance).
- F2  a discarded draft does not resurrect: "New" after a discard opens an
      empty (unchecked) clip grid, and a fresh single-clip selection still
      has no Batch entry.

Driven against the same seeded fixtures as the audit
(``tests/e2e/harness.py --scenario states|empty``). Run:

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

COLUMNS = ["Running", "Awaiting review", "Scheduled", "Failed"]
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


def _open_queue_tab(page) -> None:
    page.get_by_role("tab", name=re.compile("^Queue")).first.click()
    page.wait_for_timeout(150)


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


def run_empty_board(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    _open_queue_tab(page)
    titles = page.locator("section.column .column-title").all_inner_texts()
    report.check("B2 empty: exactly the four columns render",
                 titles == COLUMNS, f"titles={titles}")
    empties = page.locator("section.column .column-empty",
                           has_text="No jobs").count()
    report.check("B2 empty: each column shows its 'No jobs' placeholder",
                 empties == 4, f"empties={empties}")
    report.check("B12 empty: no 'Queued' column exists",
                 page.locator("section.column", has_text="Queued").count() == 0,
                 "queued column present")


def run_scroll_model(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    _open_queue_tab(page)
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
    _open_queue_tab(page)
    badge = page.locator("section.column .queued-badge").first
    report.check("B12 states: queued jobs render under Running with a "
                 "'queued N' sub-badge",
                 badge.count() >= 1
                 and re.fullmatch(r"queued \d+", badge.inner_text().strip())
                 is not None,
                 f"badge={badge.count() and badge.inner_text()}")
    # B19: the Completed archive renders completed jobs without progress bars.
    page.get_by_role("tab", name=re.compile("^Completed")).first.click()
    page.wait_for_timeout(150)
    report.check("B19: completed archive rows render no progress bars",
                 page.locator(".archive .progress").count() == 0,
                 ".progress found in archive")
    report.check("A1 archive: Completed default shows the archive",
                 page.locator(".archive-row").count() >= 1,
                 "no archive rows")


def run_artifact_row_menu(page, url: str, report: Reporter) -> None:
    """F1/F21: the modal artifact row keeps raw download in its "more" menu."""
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    # The Completed archive's first row opens the detail modal on Overview,
    # whose Artifacts card hosts the row.
    page.locator("article.archive-row button.archive-main").first.click()
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


def run_empty_prompts(page, url: str, report: Reporter) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _wait_ready(page)
    report.check("A1 archive: empty-Completed prompt renders",
                 page.get_by_text("Nothing completed yet").count() >= 1,
                 "prompt missing")
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
    page.wait_for_timeout(150)
    # D10: a single-clip selection has no Batch rail entry.
    page.get_by_role("button", name="Clear").first.click()
    first_clip = page.locator("label.clip-card input").first
    first_clip.check()
    page.wait_for_timeout(80)
    page.get_by_role("button", name=re.compile(r"Next: Configure")).click()
    page.wait_for_timeout(300)
    names = page.locator(".rail-item .rail-name").all_inner_texts()
    report.check("D10: single-clip rail has exactly one entry",
                 len(names) == 1, f"rail={names}")
    report.check("D10: single-clip rail has no Batch entry",
                 page.locator(".rail-item", has_text="Batch").count() == 0,
                 "Batch present")

    # F2: discard must clear the WHOLE draft — in-memory and local — so a
    # later "New" opens an empty clip grid with nothing pre-checked.
    page.get_by_role("button", name="Discard draft").first.click()
    page.wait_for_timeout(150)
    page.locator(".modal").get_by_role("button", name="Discard draft").click()
    page.wait_for_selector(".step-panel", state="detached", timeout=10_000)
    report.check("F2: discard returns to the Jobs view",
                 page.locator("label.clip-card").count() == 0
                 and page.locator(".rail").count() == 0,
                 "wizard still open after discard")
    page.get_by_role("button", name=re.compile("New")).first.click()
    page.wait_for_selector(".step-panel", timeout=10_000)
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