# Contributing to Bedown

Thanks for considering a contribution. Bedown is a small project — bug reports, design ideas, and PRs are all welcome.

## How the codebase is laid out

All modules live in `src/bedown/`:

- **`scraper.py`** — the pure-Python scrape. Fetches Behance pages with `httpx`, parses the embedded SSR JSON state (`<script id="beconfig-store_state">`) for titles, descriptions, tags, and image URLs, then downloads each image at the highest available resolution. Exposes `run(ScrapeOptions, log=..., progress=..., cancel_event=...)` as the single entry point. The CLI passes a `tqdm` writer for `log`; the GUI passes a queue.
- **`cli.py`** — the `bedown` command. Argparse plus a `tqdm` progress bar. Calls `scraper.run()` directly.
- **`gui.py`** + **`gui_main.py`** — the CustomTkinter window. The Download button starts a worker thread that calls the same `scraper.run()`. Log lines and progress events flow back via a `queue.Queue`; the main thread polls every 100 ms and updates the UI.
- **`runtime.py`** — bundle helpers. Detects whether we're running inside a PyInstaller `.app` and picks `~/Desktop` as the default output dir in that case.

The CLI works without the GUI dependencies, so a server install can do `pip install bedown` and use the CLI alone.

## Local development

```bash
git clone https://github.com/abhishekaggy/bedown.git
cd bedown
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install .
```

Then:

```bash
# CLI
bedown https://www.behance.net/foramdivrania

# Single project
bedown https://www.behance.net/gallery/12345/Project-Name

# GUI
bedown-gui

# Or run modules directly
python -m bedown https://www.behance.net/foramdivrania
python -m bedown.gui_main
```

No browser install required — the scraper is pure-Python (`httpx` + `Pillow`).

### Heads-up on Python 3.14 + editable installs

Python 3.14 silently skips `.pth` files that start with `_` or `.`, and setuptools' editable install creates `__editable__.<name>.pth`. The result: `pip install -e .` appears to succeed, but `import bedown` then `ModuleNotFoundError`s. Use a regular `pip install .` and re-install after edits, or use `python -m bedown` from the repo root which works regardless.

### macOS Tk

The Homebrew Python 3.14 doesn't bundle Tcl/Tk by default; the GUI needs it:

```bash
brew install python-tk@3.14
```

## Building the .app

```bash
./build_app.sh
```

This runs `pyinstaller bedown.spec`, strips extended attributes (iCloud Drive auto-stamps `com.apple.fileprovider` xattrs on anything under `~/Documents`, which breaks PyInstaller's signing pass), re-signs ad-hoc, and packages a clean `Bedown.app.zip` via `ditto` (which avoids AppleDouble `._*` pollution). Result: `dist/Bedown.app` (~40 MB) and `dist/Bedown.app.zip` (~19 MB).

The result is unsigned (ad-hoc only). First launch on any new Mac requires right-click → Open. If you'd like to help set up signing + notarization, that would be a great PR.

## Filing issues

Please use the issue templates (bug or feature). For Behance-selector breakage, including the URL of a project that broke makes the fix immediate.
