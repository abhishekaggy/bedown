"""
Behance portfolio scraper — Playwright-driven.

For each project on a Behance profile:
  - save title, description, and tags to meta.json
  - download all images, resized to a configurable max width
  - organise into <output>/<project-slug>/

Also writes a top-level projects.json summarising all projects.

This module exposes:
  - run(opts, log, cancel_event, progress) — the high-level entry point used
    by both the CLI and the GUI. It runs the asyncio event loop internally.
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
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

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
    headless: bool = True
    delay: float = 2.0


@dataclass
class ScrapeResult:
    saved: int = 0
    images: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class CancelledError(Exception):
    """Raised when the user cancels mid-run."""


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


async def auto_scroll(page: Page, pause_ms: int = 800, max_idle: int = 4) -> None:
    last_height = 0
    idle = 0
    while idle < max_idle:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)
        height = await page.evaluate("document.body.scrollHeight")
        if height == last_height:
            idle += 1
        else:
            idle = 0
            last_height = height


async def collect_project_urls(page: Page, profile_url: str) -> list[str]:
    await page.goto(profile_url, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("a[href*='/gallery/']", timeout=15000)
    except PWTimeout:
        pass
    await auto_scroll(page)
    urls = await page.eval_on_selector_all(
        "a[href*='/gallery/']",
        "els => Array.from(new Set(els.map(e => e.href.split('?')[0])))",
    )
    return [u for u in urls if re.search(r"/gallery/\d+/", u)]


async def scrape_project(page: Page, url: str) -> Optional[dict]:
    """Scrape a single project page. Returns None if the page is unavailable
    (404, login wall, redirect)."""
    response = await page.goto(url, wait_until="domcontentloaded")
    if response is not None and response.status >= 400:
        return None

    if "/onboarding" in page.url or "adobeid" in page.url.lower():
        return None

    try:
        await page.wait_for_selector("h1", timeout=15000)
    except PWTimeout:
        return None

    await auto_scroll(page, pause_ms=600, max_idle=3)

    title_raw = await page.eval_on_selector("h1", "el => el.textContent")
    title = (title_raw or "").strip()

    description = await page.evaluate(
        """() => {
            const meta = document.querySelector('meta[name="description"]');
            return meta ? meta.content : '';
        }"""
    )

    tags = await page.eval_on_selector_all(
        "a[href*='/search/projects'][href*='tracking_source=project_tags'], "
        "a[href*='/search/projects?tracking_source=project_owner_other_projects'], "
        "[class*='ProjectTags'] a, [class*='Tag'] a",
        "els => Array.from(new Set(els.map(e => e.textContent.trim()).filter(Boolean)))",
    )

    image_urls = await page.evaluate(
        """() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            const urls = imgs
                .map(i => i.currentSrc || i.src)
                .filter(u => u && /mir-s3-cdn-cf\\.behance\\.net|behance\\.net\\/.+\\/(modules|projects)/.test(u))
                .filter(u => !/\\/user\\/|avatar|profile/i.test(u));
            return Array.from(new Set(urls));
        }"""
    )

    return {
        "url": url,
        "title": title,
        "description": description,
        "tags": tags,
        "image_urls": image_urls,
    }


async def download_and_resize(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    max_width: int,
    log: LogFn,
    attempts: int = 3,
) -> bool:
    """Download an image with up to `attempts` retries (exponential backoff)
    and resize to max_width. Returns True on success."""
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


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError()


def _project_already_done(project_dir: Path) -> bool:
    """Return True if this project directory already has a valid meta.json
    plus its images on disk (a previous run completed it)."""
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


async def _run_async(
    opts: ScrapeOptions,
    log: LogFn,
    cancel_event: Optional[threading.Event],
    progress: Optional[ProgressFn],
) -> ScrapeResult:
    result = ScrapeResult()
    opts.output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=opts.headless)
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1400, "height": 900}
        )
        page = await context.new_page()

        try:
            if is_valid_behance_project_url(opts.url):
                await _download_single_project(page, opts, log, cancel_event, progress, result)
            else:
                await _download_profile(page, opts, log, cancel_event, progress, result)
        finally:
            await browser.close()

    return result


async def _download_single_project(
    page,
    opts: ScrapeOptions,
    log: LogFn,
    cancel_event: Optional[threading.Event],
    progress: Optional[ProgressFn],
    result: ScrapeResult,
) -> None:
    log(f"Loading project {opts.url} …")
    if progress:
        progress(0, 1)

    try:
        data = await scrape_project(page, opts.url)
    except Exception as e:
        log(f"! Could not load project: {e}")
        result.errors.append(str(e))
        return

    if data is None:
        log("! Project unavailable (404 or login required)")
        result.errors.append("unavailable")
        return

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Referer": "https://www.behance.net/"},
        follow_redirects=True,
    ) as client:
        saved_files: list[str] = []
        for j, img_url in enumerate(data["image_urls"], 1):
            _check_cancel(cancel_event)
            dest = opts.output_dir / f"{j:03d}"
            ok = await download_and_resize(client, img_url, dest, opts.max_width, log)
            if ok:
                saved_files.append(dest.with_suffix(".jpg").name)

    meta = {
        "title": data["title"],
        "url": opts.url,
        "description": data["description"],
        "tags": data["tags"],
        "images": saved_files,
    }
    (opts.output_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )

    result.saved = 1
    result.images = len(saved_files)
    log(f"✓ {slug_from_url(opts.url)}: {len(saved_files)} images")
    if progress:
        progress(1, 1)


async def _download_profile(
    page,
    opts: ScrapeOptions,
    log: LogFn,
    cancel_event: Optional[threading.Event],
    progress: Optional[ProgressFn],
    result: ScrapeResult,
) -> None:
    summary: list[dict] = []

    log(f"Collecting project URLs from {opts.url} …")
    try:
        project_urls = await collect_project_urls(page, opts.url)
    except Exception as e:
        log(f"! Could not load profile: {e}")
        result.errors.append(str(e))
        return

    total = len(project_urls)
    log(f"Found {total} project URLs.")
    if progress:
        progress(0, total)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Referer": "https://www.behance.net/"},
        follow_redirects=True,
    ) as client:
        for i, url in enumerate(project_urls, 1):
            _check_cancel(cancel_event)

            slug = slug_from_url(url)
            project_dir = opts.output_dir / slug

            if _project_already_done(project_dir):
                log(f"[{i}/{total}] {slug} — already downloaded, skipping")
                result.skipped += 1
                try:
                    existing = json.loads((project_dir / "meta.json").read_text())
                    summary.append({
                        "slug": slug,
                        "title": existing.get("title", ""),
                        "url": url,
                        "tags": existing.get("tags", []),
                        "image_count": len(existing.get("images", []) or []),
                    })
                except Exception:
                    pass
                if progress:
                    progress(i, total)
                continue

            log(f"[{i}/{total}] {url}")
            try:
                data = await scrape_project(page, url)
            except Exception as e:
                log(f"  ! scrape failed: {e}")
                result.failed += 1
                result.errors.append(f"{url}: {e}")
                if progress:
                    progress(i, total)
                continue

            if data is None:
                log(f"  ! unavailable (404 or login required), skipping")
                result.skipped += 1
                if progress:
                    progress(i, total)
                continue

            project_dir.mkdir(parents=True, exist_ok=True)

            saved_files: list[str] = []
            for j, img_url in enumerate(data["image_urls"], 1):
                _check_cancel(cancel_event)
                dest = project_dir / f"{j:03d}"
                ok = await download_and_resize(
                    client, img_url, dest, opts.max_width, log
                )
                if ok:
                    saved_files.append(dest.with_suffix(".jpg").name)

            meta = {
                "title": data["title"],
                "url": url,
                "description": data["description"],
                "tags": data["tags"],
                "images": saved_files,
            }
            (project_dir / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False)
            )

            summary.append({
                "slug": slug,
                "title": data["title"],
                "url": url,
                "tags": data["tags"],
                "image_count": len(saved_files),
            })
            result.saved += 1
            result.images += len(saved_files)
            log(f"  ✓ {slug}: {len(saved_files)} images")

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
