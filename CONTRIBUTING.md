# Contributing to Bedown

Thanks for considering a contribution. Bedown is a small project — bug reports, design ideas, and PRs are all welcome.

## How the codebase is laid out

Two layers, both in `src/bedown/`:

- **`scraper.py`** — the actual Playwright-driven scrape, plus `run()`, the single entry point. Takes a `ScrapeOptions` dataclass and optional `log` / `progress` / `cancel_event` callbacks. The CLI passes a `tqdm` writer for `log`; the GUI passes a queue.
- **`cli.py`** — the `bedown` command. Argparse plus a `tqdm` progress bar. Calls `scraper.run()` directly.
- **`gui.py`** + **`gui_main.py`** — the CustomTkinter window. The Download button starts a worker thread that calls the same `scraper.run()`. Log lines and progress events flow back via a `queue.Queue`; the main thread polls every 100 ms and updates the UI.
- **`runtime.py`** — bundle-aware path helpers. Sets `PLAYWRIGHT_BROWSERS_PATH` before any `playwright` import when running inside a PyInstaller .app, and picks `~/Desktop` as the default output dir in that case.

The CLI works without the GUI dependencies, so a server install can do `pip install bedown` and use the CLI alone.

## Local development

```bash
git clone https://github.com/YOUR-USERNAME/bedown.git
cd bedown
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install .
playwright install chromium
```

Then:

```bash
# CLI
bedown https://www.behance.net/foramdivrania --no-headless

# GUI
bedown-gui

# Or run modules directly
python -m bedown https://www.behance.net/foramdivrania
python -m bedown.gui_main
```

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

This runs `pyinstaller bedown.spec` and then post-copies the local Playwright Chromium cache (both `chromium-NNNN` and `chromium_headless_shell-NNNN`) into `dist/Bedown.app/Contents/Resources/ms-playwright/`.

We can't ship Chromium via the spec's `datas` because PyInstaller's binary processor tries to re-sign every Mach-O it sees and chokes on the nested `Google Chrome for Testing.app`. The post-copy is the workaround.

The result is unsigned. First launch on any new Mac requires right-click → Open. If you'd like to help set up signing + notarization, that would be a great PR.

## Filing issues

Please use the issue templates (bug or feature). For Behance-selector breakage, including the URL of a project that broke makes the fix immediate.
