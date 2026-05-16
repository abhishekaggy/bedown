"""
Behance portfolio scraper — httpx + embedded JSON state.

Behance renders every page server-side and embeds the full SSR state as a
JSON blob in the HTML. That blob carries all project metadata and the
direct URLs for every image at every resolution, so we don't need a
browser to scrape anything: a plain HTTP fetch + JSON parse is enough.

For each project on a Behance profile (or a single project URL) we:
  - save title, description, and tags to meta.json
  - download every image at its highest available resolution, resized to
    a configurable max width
  - organise into <output>/<project-slug>/

For profile runs we also write a top-level projects.json.

Public surface used by cli.py / gui.py:
  - ScrapeOptions, ScrapeResult, CancelledError
  - run(opts, log, cancel_event, progress)
  - is_valid_behance_url / is_valid_behance_profile_url / is_valid_behance_project_url
  - default_output_dir, username_from_url, slug_from_url, slugify
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
from PIL import Image

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


@dataclass
class ScrapeOptions:
    url: str
    output_dir: Path
    max_width: int = 1200
    # Kept for API compatibility with previous Playwright-backed scraper.
    # Ignored — there is no browser any more.
    headless: bool = True
    delay: float = 2.0


@dataclass
class ScrapeResult:
    saved: int = 0
    images: int = 0
    skipped: int = 0
    failed: int = 0
    # True when the profile listing was truncated (Behance only exposes the
    # first ~12 projects to anonymous visitors). Power users can paste each
    # remaining project URL directly.
    profile_truncated: bool = False
    errors: list[str] = field(default_factory=list)


class CancelledError(Exception):
    """Raised when the user cancels mid-run."""


# --------------------------------------------------------------------- helpers


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "untitled"


def slug_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "gallery":
        return f"{parts[1]}-{parts[2]}"
    return slugify(url)


def username_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0] if parts else "behance"


def is_valid_behance_profile_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if not u.netloc.endswith("behance.net"):
        return False
    parts = [p for p in u.path.split("/") if p]
    if not parts:
        return False
    if parts[0] in ("gallery", "search", "galleries"):
        return False
    return True


def is_valid_behance_project_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if not u.netloc.endswith("behance.net"):
        return False
    parts = [p for p in u.path.split("/") if p]
    return len(parts) >= 2 and parts[0] == "gallery" and parts[1].isdigit()


def is_valid_behance_url(url: str) -> bool:
    return is_valid_behance_profile_url(url) or is_valid_behance_project_url(url)


def default_output_dir(url: str) -> Path:
    if is_valid_behance_project_url(url):
        return Path.cwd() / slug_from_url(url)
    return Path.cwd() / f"{username_from_url(url)}-portfolio"


# --------------------------------------------------------- Behance HTML parser

_STATE_RE = re.compile(
    r'<script type="application/json" id="beconfig-store_state">(.+?)</script>',
    re.DOTALL,
)
_GALLERY_RE = re.compile(r"/gallery/(\d+)/([A-Za-z0-9\-_%()]+)")


def _extract_state(html: str) -> Optional[dict]:
    """Parse the embedded SSR JSON state from a Behance page."""
    match = _STATE_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _collect_project_urls_from_html(html: str) -> list[str]:
    """Find every /gallery/<id>/<slug> URL referenced in the HTML."""
    seen: dict[str, str] = {}
    for match in _GALLERY_RE.finditer(html):
        gid, slug = match.group(1), match.group(2)
        seen.setdefault(gid, f"https://www.behance.net/gallery/{gid}/{slug}")
    return list(seen.values())


def _profile_has_more(state: dict) -> bool:
    try:
        return bool(
            state.get("profile", {})
            .get("activeSection", {})
            .get("work", {})
            .get("hasMore")
        )
    except Exception:
        return False


def _pick_best_image_url(image_module: dict) -> Optional[str]:
    """Return the highest-resolution JPG URL for an ImageModule, falling
    back to module.src if the imageSizes structure is missing."""
    sizes = (image_module.get("imageSizes") or {}).get("allAvailable") or []
    jpgs = [
        s for s in sizes
        if isinstance(s, dict) and s.get("type") == "JPG" and s.get("url")
    ]
    if jpgs:
        return max(jpgs, key=lambda s: s.get("width") or 0)["url"]
    return image_module.get("src")


def _extract_tags(proj: dict) -> list[str]:
    """Behance's tag/category fields have moved around over the years; pull
    from whichever shape is present and dedupe."""
    tags: list[str] = []
    for key in ("tools", "tags", "creativeFields", "fields"):
        v = proj.get(key)
        if not isinstance(v, list):
            continue
        for item in v:
            if isinstance(item, str):
                tags.append(item.strip())
            elif isinstance(item, dict):
                tag = item.get("title") or item.get("name") or item.get("label")
                if isinstance(tag, str):
                    tags.append(tag.strip())
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _extract_project(state: dict, url: str) -> Optional[dict]:
    """Pull title / description / tags / image-URLs out of the project state."""
    proj = state.get("project", {}).get("project")
    if not isinstance(proj, dict):
        return None

    image_urls: list[str] = []
    for mod in proj.get("modules") or []:
        if not isinstance(mod, dict):
            continue
        if mod.get("__typename") == "ImageModule":
            img_url = _pick_best_image_url(mod)
            if img_url:
                image_urls.append(img_url)

    return {
        "url": url,
        "title": (proj.get("name") or "").strip(),
        "description": (proj.get("description") or "").strip(),
        "tags": _extract_tags(proj),
        "image_urls": image_urls,
    }


# ----------------------------------------------------------- HTTP / image I/O


async def _fetch_html(
    client: httpx.AsyncClient,
    url: str,
    log: LogFn,
    attempts: int = 3,
) -> Optional[str]:
    """GET a page, returning the body or None for permanent failures.

    Returns None for 404, login/onboarding redirects, and persistent network
    errors. Transient errors are retried with exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, timeout=30)
        except Exception as e:
            if attempt < attempts:
                await asyncio.sleep(1.5 ** attempt)
                continue
            log(f"  ! fetch failed: {e}")
            return None

        if response.status_code == 404:
            return None

        final_url = str(response.url).lower()
        if "/onboarding" in final_url or "adobeid" in final_url:
            return None

        if response.status_code >= 400:
            if attempt < attempts:
                await asyncio.sleep(1.5 ** attempt)
                continue
            log(f"  ! HTTP {response.status_code}")
            return None

        return response.text
    return None


async def download_and_resize(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    max_width: int,
    log: LogFn,
    attempts: int = 3,
) -> bool:
    """Download an image with retries and resize to max_width. Saves as JPEG."""
    content: Optional[bytes] = None
    last_err: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            r = await client.get(url, timeout=60)
            r.raise_for_status()
            content = r.content
            break
        except Exception as e:
            last_err = e
            if attempt < attempts:
                await asyncio.sleep(1.5 ** attempt)
    if content is None:
        log(f"  ! failed {url}: {last_err}")
        return False

    try:
        img = Image.open(io.BytesIO(content))
    except Exception as e:
        log(f"  ! not an image {url}: {e}")
        return False

    if img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    dest = dest.with_suffix(".jpg")
    img.save(dest, "JPEG", quality=88, optimize=True)
    return True


# ------------------------------------------------------------------ run loop


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError()


def _project_already_done(project_dir: Path) -> bool:
    """Return True if this project directory already has a valid meta.json
    plus at least one image on disk (a previous run completed it)."""
    meta_file = project_dir / "meta.json"
    if not meta_file.exists():
        return False
    try:
        meta = json.loads(meta_file.read_text())
    except Exception:
        return False
    images = meta.get("images") or []
    if not isinstance(images, list):
        return False
    if images:
        return any((project_dir / name).exists() for name in images)
    return True


async def _save_images(
    client: httpx.AsyncClient,
    dest_dir: Path,
    image_urls: list[str],
    max_width: int,
    cancel_event: Optional[threading.Event],
    log: LogFn,
) -> list[str]:
    saved: list[str] = []
    for j, img_url in enumerate(image_urls, 1):
        _check_cancel(cancel_event)
        dest = dest_dir / f"{j:03d}"
        if await download_and_resize(client, img_url, dest, max_width, log):
            saved.append(dest.with_suffix(".jpg").name)
    return saved


async def _run_async(
    opts: ScrapeOptions,
    log: LogFn,
    cancel_event: Optional[threading.Event],
    progress: Optional[ProgressFn],
) -> ScrapeResult:
    result = ScrapeResult()
    opts.output_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Referer": "https://www.behance.net/"},
        follow_redirects=True,
    ) as client:
        if is_valid_behance_project_url(opts.url):
            await _download_single_project(client, opts, log, cancel_event, progress, result)
        else:
            await _download_profile(client, opts, log, cancel_event, progress, result)

    return result


async def _download_single_project(
    client: httpx.AsyncClient,
    opts: ScrapeOptions,
    log: LogFn,
    cancel_event: Optional[threading.Event],
    progress: Optional[ProgressFn],
    result: ScrapeResult,
) -> None:
    log(f"Loading project {opts.url} …")
    if progress:
        progress(0, 1)

    html = await _fetch_html(client, opts.url, log)
    if html is None:
        log("! Project unavailable (404 or login required)")
        result.errors.append("unavailable")
        return

    state = _extract_state(html)
    if state is None:
        log("! Could not parse Behance page data")
        result.errors.append("parse_failed")
        return

    data = _extract_project(state, opts.url)
    if data is None:
        log("! No project data found")
        result.errors.append("no_data")
        return

    if not data["image_urls"]:
        log("! No images in this project (video-only / embed-only)")
        result.errors.append("no_images")
        return

    saved = await _save_images(
        client, opts.output_dir, data["image_urls"], opts.max_width, cancel_event, log
    )

    meta = {
        "title": data["title"],
        "url": opts.url,
        "description": data["description"],
        "tags": data["tags"],
        "images": saved,
    }
    (opts.output_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )

    result.saved = 1
    result.images = len(saved)
    log(f"✓ {slug_from_url(opts.url)}: {len(saved)} images")
    if progress:
        progress(1, 1)


async def _download_profile(
    client: httpx.AsyncClient,
    opts: ScrapeOptions,
    log: LogFn,
    cancel_event: Optional[threading.Event],
    progress: Optional[ProgressFn],
    result: ScrapeResult,
) -> None:
    summary: list[dict] = []

    log(f"Loading profile {opts.url} …")
    html = await _fetch_html(client, opts.url, log)
    if html is None:
        log("! Could not load profile")
        result.errors.append("profile_unavailable")
        return

    project_urls = _collect_project_urls_from_html(html)
    state = _extract_state(html)
    if state is not None and _profile_has_more(state):
        result.profile_truncated = True

    total = len(project_urls)
    if total == 0:
        log("! No projects found on this profile")
        result.errors.append("no_projects")
        return

    log(f"Found {total} project URLs.")
    if result.profile_truncated:
        log(
            "  Note: Behance only lists the first set of projects publicly. "
            "If you're missing older ones, paste each project URL directly."
        )

    if progress:
        progress(0, total)

    for i, project_url in enumerate(project_urls, 1):
        _check_cancel(cancel_event)

        slug = slug_from_url(project_url)
        project_dir = opts.output_dir / slug

        if _project_already_done(project_dir):
            log(f"[{i}/{total}] {slug} — already downloaded, skipping")
            result.skipped += 1
            try:
                existing = json.loads((project_dir / "meta.json").read_text())
                summary.append({
                    "slug": slug,
                    "title": existing.get("title", ""),
                    "url": project_url,
                    "tags": existing.get("tags", []),
                    "image_count": len(existing.get("images", []) or []),
                })
            except Exception:
                pass
            if progress:
                progress(i, total)
            continue

        log(f"[{i}/{total}] {project_url}")
        page_html = await _fetch_html(client, project_url, log)
        if page_html is None:
            log("  ! unavailable, skipping")
            result.skipped += 1
            if progress:
                progress(i, total)
            continue

        project_state = _extract_state(page_html)
        if project_state is None:
            log("  ! parse failed, skipping")
            result.failed += 1
            result.errors.append(f"{project_url}: parse failed")
            if progress:
                progress(i, total)
            continue

        data = _extract_project(project_state, project_url)
        if data is None:
            log("  ! no project data, skipping")
            result.skipped += 1
            if progress:
                progress(i, total)
            continue

        project_dir.mkdir(parents=True, exist_ok=True)

        saved = await _save_images(
            client, project_dir, data["image_urls"], opts.max_width, cancel_event, log
        )

        meta = {
            "title": data["title"],
            "url": project_url,
            "description": data["description"],
            "tags": data["tags"],
            "images": saved,
        }
        (project_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False)
        )

        summary.append({
            "slug": slug,
            "title": data["title"],
            "url": project_url,
            "tags": data["tags"],
            "image_count": len(saved),
        })
        result.saved += 1
        result.images += len(saved)
        log(f"  ✓ {slug}: {len(saved)} images")

        if progress:
            progress(i, total)

        if i < total and opts.delay > 0:
            slept = 0.0
            while slept < opts.delay:
                _check_cancel(cancel_event)
                step = min(0.2, opts.delay - slept)
                await asyncio.sleep(step)
                slept += step

    (opts.output_dir / "projects.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )


def run(
    opts: ScrapeOptions,
    log: Optional[LogFn] = None,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[ProgressFn] = None,
) -> ScrapeResult:
    """Synchronous entry point. Runs the asyncio event loop internally so
    callers (CLI, GUI worker thread) don't have to manage asyncio."""
    if log is None:
        log = print
    try:
        return asyncio.run(_run_async(opts, log, cancel_event, progress))
    except CancelledError:
        log("Cancelled.")
        return ScrapeResult(errors=["cancelled"])
