"""Capture the #259 screenshot sweep (Phase 0 "before", Phase 3 "after").

Deterministic, model-free Playwright drive of the seeded fixtures across the
three audit viewports from issue #259 section 0.2. The Phase 0 audit and the
Phase 3 re-audit *interpret* these PNGs; capturing them here keeps the paid
vision pass small (interpret a bounded set) instead of paying it to drive a
browser and read every state.

The full run is not committed: it is uploaded as a CI artifact and cited as a
plain-text path. Only findings/A-F evidence is copied under
``docs/ux-audit-259/evidence/``.

Usage::

    python tests/e2e/capture.py --out <dir> --label before
    python tests/e2e/capture.py --out <dir> --label after --scenarios states large
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
for candidate in (str(TESTS_DIR), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import harness  # noqa: E402

VIEWPORT_ORDER = ("desktop", "laptop", "small")


def _shot(page, out_dir: Path, label: str, surface: str, viewport: str) -> str:
    target = out_dir / f"{label}-{surface}-{viewport}.png"
    page.screenshot(path=str(target))
    return target.name


def _wait_ready(page) -> None:
    page.wait_for_selector(".shell", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Loading workspace')",
        timeout=15_000,
    )


def _capture_view(page, out_dir: Path, label: str, surface: str, viewport: str,
                  captures: list[str]) -> None:
    page.wait_for_timeout(250)
    captures.append(_shot(page, out_dir, label, surface, viewport))


def _run_surface(page, out_dir: Path, label: str, surface: str,
                 viewport: str, captures: list[str], navigate) -> None:
    navigate(page)
    _capture_view(page, out_dir, label, surface, viewport, captures)


def capture(out_dir: Path, label: str, scenarios: list[str]) -> list[str]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    captures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for scenario in scenarios:
                with harness.workspace(scenario) as server:
                    for viewport in VIEWPORT_ORDER:
                        size = harness.VIEWPORTS[viewport]
                        context = browser.new_context(
                            viewport={"width": size["width"], "height": size["height"]},
                            reduced_motion="reduce",
                        )
                        page = context.new_page()
                        page.goto(server.url, wait_until="domcontentloaded")
                        _wait_ready(page)

                        if scenario == "empty":
                            # B20: the fresh entry is the Completed sub-tab; its
                            # mandated empty prompt is a capture surface, and the
                            # four-column board lives behind the Queue sub-tab.
                            _capture_view(page, out_dir, label, "jobs-completed",
                                          viewport, captures)
                            page.get_by_role("tab", name="Queue").click()
                            page.wait_for_timeout(250)
                            _capture_view(page, out_dir, label, "board-empty",
                                          viewport, captures)
                            context.close()
                            continue

                        _capture_view(page, out_dir, label,
                                      f"jobs-completed-{scenario}", viewport, captures)
                        page.get_by_role("tab", name="Queue").click()
                        page.wait_for_timeout(250)
                        _capture_view(page, out_dir, label,
                                      f"board-{scenario}", viewport, captures)

                        # Detail/nav/wizard surfaces are captured once, from the
                        # representative "states" workspace.
                        if scenario != "states":
                            context.close()
                            continue

                        # Job detail modal: a review gate and a completed job.
                        try:
                            page.locator(".column", has_text="Awaiting review") \
                                .locator(".card-main").first.click()
                            page.wait_for_selector(".detail-modal", timeout=5_000)
                            _capture_view(page, out_dir, label, "modal-review",
                                          viewport, captures)
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(200)
                        except Exception as error:  # noqa: BLE001 - best effort
                            print(f"  modal-review skipped: {error}")

                        for view in ("metrics", "layouts", "settings"):
                            try:
                                page.locator(".nav-item", has_text=view.capitalize()) \
                                    .first.click()
                                _capture_view(page, out_dir, label, view,
                                              viewport, captures)
                            except Exception as error:  # noqa: BLE001
                                print(f"  {view} skipped: {error}")

                        # Wizard: clip selection then configure.
                        try:
                            page.locator(".nav-item", has_text="Jobs").first.click()
                            page.locator(".btn-primary", has_text="New").first.click()
                            page.wait_for_selector(".wizard", timeout=5_000)
                            _capture_view(page, out_dir, label, "wizard-clips",
                                          viewport, captures)
                            page.locator("button", has_text="Select all").first.click()
                            _capture_view(page, out_dir, label, "wizard-clips-selected",
                                          viewport, captures)
                            page.locator("button", has_text="Next: Configure").first.click()
                            page.wait_for_selector(".rail", timeout=5_000)
                            _capture_view(page, out_dir, label, "wizard-configure",
                                          viewport, captures)
                        except Exception as error:  # noqa: BLE001
                            print(f"  wizard skipped: {error}")

                        context.close()
        finally:
            browser.close()
    return captures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClipMorph #259 screenshot sweep")
    parser.add_argument("--out", required=True, help="output directory for PNGs")
    parser.add_argument("--label", default="before", help="before|after")
    parser.add_argument("--scenarios", nargs="*", default=["states", "empty", "large"],
                        choices=["states", "empty", "large", "errors", "long"])
    args = parser.parse_args(argv)

    captures = capture(Path(args.out), args.label, args.scenarios)
    index = Path(args.out) / f"{args.label}-index.json"
    index.write_text(json.dumps(captures, indent=2), encoding="utf-8")
    print(f"captured {len(captures)} screenshots into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
