"""One CLI progress bar for a whole upload submission.

A submission is coalesced into bindings by (artifact, shared upload slice),
where the shared slice is the frozen snapshot minus each platform's prefixed
adapter options: every option is frozen under its own ``{platform}_`` prefix,
so platforms that differ in nothing but those options ride ONE parallel
pipeline call, and the options never leak across adapters. A remaining
binding split (a different artifact, or a different unprefixed slice) is a
transport detail: this bar belongs to the submission and is shared by every
binding's pipeline call.

The submission knows every platform it will upload before the first binding
runs, so it declares them all when it creates the bar: the total and the
description are then fixed for as long as the bar is on screen, and a platform
whose binding runs later shows 0% rather than appearing halfway through a bar
that had already reached 100%. A caller that cannot declare up front (a
directly constructed ``UploadPipeline``) still registers as it goes, and an
undeclared name gets a slot instead of pushing the bar past its total.
"""

import logging
from threading import Lock
from typing import Any, Iterable

from tqdm import tqdm

from clipmorph.platforms import PLATFORM_TITLE


def _slot_key(platform_name: str) -> str:
    """Fold every spelling of a platform name onto one slot key.

    The submission declares platforms in lowercase while an adapter reports its
    own spelling ("Twitter"), and both must land on the same slot.
    """
    return str(platform_name).strip().lower()


class SubmissionProgress:
    """A submission-scoped bar with one 100% slot per uploading platform.

    Adapters report ``(platform_name, percent)``; each report advances that
    platform's own slot by its own delta, so the bar only moves as much as the
    platforms actually did. Every write happens under one lock: tqdm is not
    thread-safe by itself and the platforms upload in parallel threads.
    """

    def __init__(self, planned_platforms: Iterable[str] = ()) -> None:
        """Create the bar's surface; ``planned_platforms`` fixes its total.

        Declaring the whole submission up front is what keeps the total and the
        description from moving under the user while the bar is on screen.
        """
        self._bar: Any = None
        self._percents: dict[str, int] = {}
        self._labels: dict[str, str] = {}
        self._described = 0
        self._lock = Lock()
        self.include(planned_platforms)

    def include(self, platform_names: Iterable[str]) -> None:
        """Add slots for these platforms and size the bar for them."""
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
            self._add([platform_name])
            bar = self._bar
            if bar is None:
                # Nothing has registered a platform yet, so there is no bar to
                # draw on; the first ``include`` sizes the bar for everyone.
                return
            key = _slot_key(platform_name)
            previous = self._percents[key]
            if target <= previous:
                return
            self._percents[key] = target
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
            key = _slot_key(name)
            if key not in self._percents:
                self._percents[key] = 0
                # One canonical label per platform, so a slot declared by the
                # submission and reported by an adapter reads the same way.
                self._labels[key] = PLATFORM_TITLE.get(key, str(name))
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
            f"{self._labels[key]} {value}%"
            for key, value in self._percents.items()))