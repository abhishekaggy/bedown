# Bedown

**Download an entire Behance portfolio — images, titles, descriptions, and tags — with a single click.**

> *Screenshot coming soon.*

Bedown is a small open-source Mac app for designers who want their Behance work as a tidy folder of images and JSON, not as 200 browser tabs and a screen-recorder. Point it at any public Behance profile, click Download, and walk away.

---

## Quick start

### Just download my portfolio (no Terminal required)

1. Grab the latest `Bedown.app.zip` from the [Releases page](../../releases) and unzip it.
2. **First launch only:** right-click `Bedown.app` → **Open** → confirm. (macOS Gatekeeper blocks unsigned apps on first launch — this is the standard one-time bypass.)
3. Paste a Behance profile URL (e.g. `https://www.behance.net/yourname`) or a single project URL (e.g. `https://www.behance.net/gallery/12345/Name`).
4. Click **Download**. Files land in `~/Desktop/<username>-portfolio/` (or `~/Desktop/<project-slug>/` for a single project).

### For developers (CLI)

```bash
git clone https://github.com/abhishekaggy/bedown.git
cd bedown
python3 -m venv .venv
source .venv/bin/activate
pip install .

bedown https://www.behance.net/yourname
# or
bedown https://www.behance.net/gallery/12345/Name
```

No browser install required — the scraper is pure-Python (httpx + Pillow).

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
| `url` | (required) | A Behance profile URL (`behance.net/yourname`) or single project URL (`behance.net/gallery/12345/Name`) |
| `-o`, `--output` | derived from URL in cwd | Where to save everything |
| `--max-width` | `1200` | Resize images to this max width (px). Smaller = smaller files. |
| `--delay` | `2.0` | Seconds to wait between projects (be polite to Behance) |
| `--version` | — | Print the version and exit |

Re-runs are resumable: any project whose folder already has a valid `meta.json` plus its images on disk is skipped, so you can interrupt with Cmd-C and pick up where you left off.

---

## Limitations (read these before filing a bug)

- **Login-required and adult-content projects are skipped.** Bedown fetches public pages only; projects behind Behance's age gate or login wall are reported as "unavailable, skipping".
- **Profile downloads are limited to what Behance lists publicly.** Behance only exposes the first set of projects to anonymous visitors (no infinite-scroll without a browser session). For older projects, paste each project URL directly — Bedown handles individual gallery URLs end-to-end.
- **Behance can change its HTML at any time.** The JSON parser in [`src/bedown/scraper.py`](src/bedown/scraper.py) targets the SSR state Behance ships today. If the format changes and Bedown stops finding images or tags, please open an issue with the URL of a project that broke.
- **Mac only for now.** The bundled `.app` is built for macOS arm64 (Apple Silicon). The CLI is pure-Python and runs anywhere Python 3.10+ runs. Intel Macs and Windows builds are welcome PRs.
- **Unsigned and unnotarized.** First launch needs the right-click → Open dance. If you'd like to help set up code signing, see the issue tracker.

---

## Contributing

Contributions are welcome — bug reports, feature ideas, and PRs all. Check the open [issues](../../issues) first; if your thing isn't there, [open a new one](../../issues/new/choose). For code changes, see [CONTRIBUTING.md](CONTRIBUTING.md) — it covers how the CLI and GUI layers fit together and how to build the .app locally.

---

## License

MIT — see [LICENSE](LICENSE).
