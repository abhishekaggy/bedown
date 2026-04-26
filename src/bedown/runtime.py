"""Runtime helpers for working inside a PyInstaller bundle.

The single most important thing this module does is set
PLAYWRIGHT_BROWSERS_PATH *before* any code imports `playwright`, so the
bundled Chromium under <bundle>/Resources/ms-playwright/ is found at launch.

Importing `bedown.runtime` early — via bedown/__init__.py — ensures the env
var is in place by the time bedown.scraper does its `from playwright...`
import.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_bundled() -> bool:
    """True when running inside a PyInstaller-built bundle."""
    return bool(getattr(sys, "frozen", False))


def _bundle_resource_root() -> Path | None:
    """Where bundled data files live at runtime.

    PyInstaller exposes the unpacked-data directory via sys._MEIPASS. For a
    onedir build (which we use for Playwright), this is also where 'datas'
    entries from the spec land.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def _candidate_browsers_dirs() -> list[Path]:
    """Possible locations Chromium could live inside the bundle.

    PyInstaller's `datas` land under sys._MEIPASS, but Chromium itself is
    copied into Contents/Resources/ms-playwright by the build_app.sh
    post-build step (PyInstaller's binary processor breaks on the nested
    Chrome for Testing Mach-O)."""
    root = _bundle_resource_root()
    candidates: list[Path] = []
    if root is not None:
        candidates.append(root / "ms-playwright")
        # Walk up out of Contents/Frameworks → Contents/Resources/ms-playwright.
        # Layout: Bedown.app/Contents/Frameworks/_internal (== _MEIPASS)
        contents = root.parent.parent
        candidates.append(contents / "Resources" / "ms-playwright")
    return candidates


def setup_bundle_env() -> None:
    """If running bundled, point Playwright at the bundled Chromium and
    driver. No-op outside the bundle."""
    root = _bundle_resource_root()
    if root is None:
        return

    for browsers_path in _candidate_browsers_dirs():
        if browsers_path.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
            break

    # Playwright's Python package shells out to a Node-based driver. When
    # bundled, the package is at <root>/playwright; its driver subdir is
    # placed alongside it via the spec's datas list.
    driver_dir = root / "playwright" / "driver"
    if driver_dir.is_dir():
        # PLAYWRIGHT_DRIVER_PATH is honoured by playwright>=1.40 to override
        # the driver location.
        os.environ.setdefault("PLAYWRIGHT_DRIVER_PATH", str(driver_dir))


def default_app_output_dir(profile_url: str) -> Path:
    """Sensible default output directory when running as a bundled app:
    ~/Desktop/<username>-portfolio (falls back to ~ if no Desktop)."""
    from bedown.scraper import username_from_url

    username = username_from_url(profile_url)
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.is_dir() else Path.home()
    return base / f"{username}-portfolio"
