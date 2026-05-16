"""Runtime helpers — detect PyInstaller bundle and pick output paths.

Bedown no longer ships any external runtime (Chromium / Node.js / Playwright)
inside the bundle, so this module's only job now is to (a) tell other code
whether it's running inside a bundled .app, and (b) suggest a Desktop output
directory in that case.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_bundled() -> bool:
    """True when running inside a PyInstaller-built bundle."""
    return bool(getattr(sys, "frozen", False))


def default_app_output_dir(url: str) -> Path:
    """Sensible default output directory when running as a bundled app.

    - Profile URL → ~/Desktop/<username>-portfolio
    - Project URL → ~/Desktop/<project-slug>
    Falls back to ~ if there is no Desktop directory.
    """
    from bedown.scraper import username_from_url, slug_from_url, is_valid_behance_project_url

    desktop = Path.home() / "Desktop"
    base = desktop if desktop.is_dir() else Path.home()
    if is_valid_behance_project_url(url):
        return base / slug_from_url(url)
    return base / f"{username_from_url(url)}-portfolio"
