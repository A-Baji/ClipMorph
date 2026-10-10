"""Shared local-server harness for the #259 UX audit, re-audit, and CI smoke test.

Boots ``clipmorph.web.create_app`` against a seeded fixture workspace (see
``tests/ux_fixtures.py``) and exposes the base URL plus the three audit
viewports. The Phase 0 audit and the Phase 3 re-audit drive this from Python;
``tests/e2e/harness.js`` spawns the ``--serve`` CLI so the node smoke test can
reuse the same workspace and server.

CLI (used by the node wrapper)::

    python tests/e2e/harness.py --serve --scenario states

prints one JSON line ``{"url": ..., "port": ..., "data_dir": ..., "viewports": ...}``
and then blocks until killed.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from ux_fixtures import SCENARIOS, seed_workspace  # noqa: E402

# The three audit viewports from issue #259 section 0.2.
VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080},
    "laptop": {"width": 1366, "height": 768},
    "small": {"width": 1024, "height": 768},
}


def build_workspace(scenario: str = "states",
                    data_dir: str | Path | None = None) -> Path:
    """Seed ``scenario`` into ``data_dir`` (a temp dir when omitted)."""
    if data_dir is None:
        data_dir = Path(tempfile.mkdtemp(prefix=f"clipmorph-ux-{scenario}-"))
    return seed_workspace(Path(data_dir), scenario)


def start(data_dir: str | Path, host: str = "127.0.0.1", port: int | None = None):
    """Start the local UI service and wait for readiness."""
    from clipmorph.ui_launcher import start_local_server

    return start_local_server(host=host, port=port, data_dir=Path(data_dir))


@contextlib.contextmanager
def workspace(scenario: str = "states", data_dir: str | Path | None = None):
    """Context manager yielding a running server against seeded fixtures."""
    seeded = build_workspace(scenario, data_dir)
    server = start(seeded)
    try:
        yield server
    finally:
        server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClipMorph UX audit harness")
    parser.add_argument("--serve", action="store_true",
                        help="boot, print the URL as JSON, then block until killed")
    parser.add_argument("--scenario", default="states", choices=SCENARIOS)
    parser.add_argument("--data-dir", default=None,
                        help="seed into this directory instead of a temp dir")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    seeded = build_workspace(args.scenario, args.data_dir)
    server = start(seeded, port=args.port)
    print(json.dumps({
        "url": server.url,
        "port": server.port,
        "data_dir": str(seeded),
        "viewports": VIEWPORTS,
    }), flush=True)
    if args.serve:
        try:
            server.thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    else:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
