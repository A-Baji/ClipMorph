"""ClipMorph command-line entry point."""

import sys


def main() -> None:
    from clipmorph.cli import run_cli

    result = run_cli(sys.argv[1:])
    if result:
        raise SystemExit(result)


if __name__ == "__main__":
    main()