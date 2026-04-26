# Bedown

**Download an entire Behance portfolio — images, titles, descriptions, and tags — with a single click.**

> *Screenshot coming soon.*

Bedown is a small open-source Mac app for designers who want their Behance work as a tidy folder of images and JSON, not as 200 browser tabs and a screen-recorder. Point it at any public Behance profile, click Download, and walk away.

---

## Quick start

### Just download my portfolio (no Terminal required)

1. Grab the latest `Bedown.app.zip` from the [Releases page](../../releases) and unzip it.
2. **First launch only:** right-click `Bedown.app` → **Open** → confirm. (macOS Gatekeeper blocks unsigned apps on first launch — this is the standard one-time bypass.)
3. Paste a Behance profile URL (e.g. `https://www.behance.net/yourname`).
4. Click **Download**. Files land in `~/Desktop/<username>-portfolio/`.

### For developers (CLI)

```bash
git clone https://github.com/YOUR-USERNAME/bedown.git
cd bedown
python3 -m venv .venv
source .venv/bin/activate
pip install .
playwright install chromium

bedown https://www.behance.net/yourname
```

The same scraper is used by both the CLI and the GUI — see [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture.

---

## What you get

```
yourname-portfolio/
├── projects.json                              # summary of all projects
├── 12345678-Project-Slug/
│   ├── meta.json                              # title, description, tags, image list
│   ├── 001.jpg
│   ├── 002.jpg
│   └── ...
├── 12345679-Another-Project/
│   ├── meta.json
│   └── ...
```

Each `meta.json` looks like:

```json
{
  "title": "Project Title",
  "url": "https://www.behance.net/gallery/12345678/Project-Slug",
  "description": "Short description from the page meta tag.",
  "tags": ["branding", "typography"],
  "images": ["001.jpg", "002.jpg"]
}
```

---

## CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `profile_url` | (required) | A Behance profile URL like `https://www.behance.net/yourname` |
| `-o`, `--output` | `<username>-portfolio` in cwd | Where to save everything |
| `--max-width` | `1200` | Resize images to this max width (px). Smaller = smaller files. |
| `--no-headless` | off | Show the Chromium browser window (useful for debugging) |
| `--delay` | `2.0` | Seconds to wait between projects (be polite to Behance) |
| `--version` | — | Print the version and exit |

Re-runs are resumable: any project whose folder already has a valid `meta.json` plus its images on disk is skipped, so you can interrupt with Cmd-C and pick up where you left off.

---

## Limitations (read these before filing a bug)

- **Login-required and adult-content projects are skipped.** Bedown runs in a logged-out browser; projects behind Behance's age gate or login wall are reported as "unavailable, skipping".
- **Behance can change its HTML at any time.** The selectors in [`src/bedown/scraper.py`](src/bedown/scraper.py) are best-effort against the current layout. If a new version of Behance ships and Bedown stops finding images or tags, please open an issue with the URL of a project that broke.
- **Large portfolios take time.** A 100-project portfolio with hundreds of images can easily take 15–30 minutes. The default 2-second inter-project delay is intentional — please don't lower it to something rude.
- **Mac only for now.** The bundled `.app` is built for macOS arm64 (Apple Silicon). The CLI works anywhere Python and Playwright run. Intel Macs and Windows builds are welcome PRs.
- **Unsigned and unnotarized.** First launch needs the right-click → Open dance. If you'd like to help set up code signing, see the issue tracker.

---

## Contributing

Contributions are welcome — bug reports, feature ideas, and PRs all. Check the open [issues](../../issues) first; if your thing isn't there, [open a new one](../../issues/new/choose). For code changes, see [CONTRIBUTING.md](CONTRIBUTING.md) — it covers how the CLI and GUI layers fit together and how to build the .app locally.

---

## License

MIT — see [LICENSE](LICENSE).
