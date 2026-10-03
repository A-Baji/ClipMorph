"""One CLI progress bar for a whole upload submission.

A submission is coalesced into bindings by frozen upload slice, so any
per-platform upload option (a different privacy level, a different content
kind) runs its own pipeline call. A bar per binding therefore meant that one
deliberate per-platform override silently gave the user a second, separate bar
instead of one bar per submission. This bar is owned by the submission and
shared by every binding's pipeline call.

Platforms register themselves through :meth:`SubmissionProgress.include` instead
of being listed up front, so the total only counts platforms that will actually
upload: one whose adapter failed to initialize or whose authentication failed is
never a slot, and a later binding's platforms grow the same bar rather than
starting another one.
"""

import logging
from threading import Lock
from typing import Any, Iterable

from tqdm import tqdm


class SubmissionProgress:
    """A submission-scoped bar with one 100% slot per uploading platform.

    Adapters report ``(platform_name, percent)``; each report advances that
    platform's own slot by its own delta, so the bar only moves as much as the
    platforms actually did. Every write happens under one lock: tqdm is not
    thread-safe by itself and the platforms upload in parallel threads.
    """

    def __init__(self) -> None:
        self._bar: Any = None
        self._percents: dict[str, int] = {}
        self._described = 0
        self._lock = Lock()

    def include(self, platform_names: Iterable[str]) -> None:
        """Register one pipeline call's platforms and size the bar for them."""
        with self._lock:
            added = self._add(platform_names)
            if self._bar is None:
                if not self._percents:
                    return
                self._bar = tqdm(
                    total=100 * len(self._percents),
                    desc=self._description(),
                    unit="%",
                    bar_format="{l_bar}{bar}| {percentage:3.0f}% "
                               "[{elapsed}<{remaining}] {postfix}",
                    leave=True,
                    position=0,
                    disable=None)
                self._render()
            elif added:
                self._render()

    def report(self, platform_name: str, percent: int) -> None:
        """Advance one platform's slot to ``percent`` (0-100)."""
        target = max(0, min(100, int(percent)))
        with self._lock:
            bar = self._bar
            # A name the caller never included still gets a slot rather than
            # pushing the bar past its total.
            self._add([platform_name])
            if bar is None:
                # Nothing has registered a platform yet, so there is no bar to
                # draw on; the first ``include`` sizes the bar for everyone.
                return
            previous = self._percents[platform_name]
            if target <= previous:
                return
            self._percents[platform_name] = target
            bar.update(target - previous)
            self._render()

    def write(self, message: str, level: int = logging.INFO) -> None:
        """Print a message above the bar, or log it when no bar is drawn.

        tqdm's ``write`` bypasses logging even on a bar it disabled, so a
        non-terminal run would otherwise see progress chatter on stderr instead
        of in the log stream where the rest of the run's records go.
        """
        bar = self._bar
        if bar is not None and not bar.disable:
            bar.write(message)
        else:
            logging.log(level, message)

    def close(self) -> None:
        """Close the bar; safe when no platform ever registered."""
        with self._lock:
            if self._bar is not None:
                self._bar.close()
                self._bar = None

    def _add(self, platform_names: Iterable[str]) -> bool:
        """Add slots for unseen platforms; return whether any were added."""
        added = False
        for name in platform_names:
            if name not in self._percents:
                self._percents[name] = 0
                added = True
        if added and self._bar is not None:
            self._bar.total = 100 * len(self._percents)
        return added

    def _description(self) -> str:
        count = len(self._percents)
        return f"Uploading {count} platform{'s' if count != 1 else ''}"

    def _render(self) -> None:
        """Redraw the postfix, and the description when the slot count moved."""
        if len(self._percents) != self._described:
            self._bar.set_description(self._description())
            self._described = len(self._percents)
        self._bar.set_postfix_str(" | ".join(
            f"{name} {value}%" for name, value in self._percents.items()))