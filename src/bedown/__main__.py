"""Allow `python -m bedown` to invoke the CLI."""

from bedown.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
