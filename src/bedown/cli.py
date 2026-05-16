"""Bedown CLI — argparse wrapper around the scraper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tqdm import tqdm

from bedown import __version__
from bedown.scraper import (
    ScrapeOptions,
    default_output_dir,
    is_valid_behance_url,
    run,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bedown",
        description="Download a Behance portfolio or individual project (images + metadata).",
    )
    p.add_argument(
        "url",
        help=(
            "Behance profile URL (e.g. https://www.behance.net/username) "
            "or single project URL (e.g. https://www.behance.net/gallery/12345/Name)"
        ),
    )
    p.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output directory (default: derived from the URL in the current directory)",
    )
    p.add_argument(
        "--max-width",
        type=int,
        default=1200,
        help="Resize images to this max width in pixels (default: 1200)",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between projects (default: 2.0)",
    )
    p.add_argument("--version", action="version", version=f"bedown {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not is_valid_behance_url(args.url):
        print(
            f"Error: '{args.url}' does not look like a valid Behance URL.\n"
            "Expected a profile (behance.net/username) "
            "or project (behance.net/gallery/ID/name) URL.",
            file=sys.stderr,
        )
        return 2

    output_dir = args.output or default_output_dir(args.url)

    opts = ScrapeOptions(
        url=args.url,
        output_dir=output_dir,
        max_width=args.max_width,
        delay=args.delay,
    )

    bar: tqdm | None = None

    def log(msg: str) -> None:
        if bar is not None:
            bar.write(msg)
        else:
            print(msg)

    def progress(done: int, total: int) -> None:
        nonlocal bar
        if bar is None:
            bar = tqdm(total=total, unit="proj", desc="Projects")
        if bar.total != total:
            bar.total = total
            bar.refresh()
        bar.n = done
        bar.refresh()

    try:
        result = run(opts, log=log, progress=progress)
    finally:
        if bar is not None:
            bar.close()

    print(
        f"\n{result.saved} projects saved, "
        f"{result.images} images downloaded, "
        f"{result.skipped} skipped"
        + (f", {result.failed} failed" if result.failed else "")
    )
    print(f"Output: {output_dir.resolve()}")
    return 0 if not result.errors or result.errors == ["cancelled"] else 1


if __name__ == "__main__":
    sys.exit(main())
