"""GUI entry point. Bound to the `bedown-gui` console script."""

from bedown.gui import launch


def main() -> int:
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
