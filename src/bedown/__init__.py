"""Bedown — download an entire Behance portfolio with a single click."""

__version__ = "0.1.0"

# Set Playwright env vars before any submodule imports playwright. No-op
# outside a PyInstaller bundle.
from bedown.runtime import setup_bundle_env as _setup_bundle_env

_setup_bundle_env()
