"""
Scrape all projects from a Behance profile using Playwright.

For each project:
  - save title, description, and tags to meta.json
  - download all images, resized to max 1200px wide
  - organise into /foram-portfolio/<project-slug>/

Also writes a top-level projects.json summarising all projects.

Usage:
    pip install playwright httpx pillow
    playwright install chromium
    python scrape_behance.py
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

PROFILE_URL = "https://www.behance.net/foramdivrania"
OUT_ROOT = Path("foram-portfolio")
MAX_WIDTH = 1200
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "untitled"


def slug_from_url(url: str) -> str:
    # Behance project URL: https://www.behance.net/gallery/<id>/<slug>
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "gallery":
        return f"{parts[1]}-{parts[2]}"
    return slugify(url)


async def auto_scroll(page: Page, pause_ms: int = 800, max_idle: int = 4) -> None:
    """Scroll to the bottom, repeatedly, until the page height stops growing."""
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


async def collect_project_urls(page: Page) -> list[str]:
    await page.goto(PROFILE_URL, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("a[href*='/gallery/']", timeout=15000)
    except PWTimeout:
        pass
    await auto_scroll(page)
    urls = await page.eval_on_selector_all(
        "a[href*='/gallery/']",
        "els => Array.from(new Set(els.map(e => e.href.split('?')[0])))",
    )
    # Filter out non-project links (e.g. /gallery/<id>/<slug> only)
    return [u for u in urls if re.search(r"/gallery/\d+/", u)]


async def scrape_project(page: Page, url: str) -> dict:
    await page.goto(url, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("h1", timeout=15000)
    except PWTimeout:
        pass
    # Trigger lazy-loaded images
    await auto_scroll(page, pause_ms=600, max_idle=3)

    title = (await page.eval_on_selector("h1", "el => el.textContent")).strip()

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

    # Image URLs — Behance serves project media via <img> tags inside the project body.
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


async def download_and_resize(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
    try:
        r = await client.get(url, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"  ! failed {url}: {e}")
        return False

    try:
        img = Image.open(io.BytesIO(r.content))
    except Exception as e:
        print(f"  ! not an image {url}: {e}")
        return False

    if img.width > MAX_WIDTH:
        ratio = MAX_WIDTH / img.width
        new_size = (MAX_WIDTH, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    dest = dest.with_suffix(".jpg")
    img.save(dest, "JPEG", quality=88, optimize=True)
    return True


async def main() -> None:
    OUT_ROOT.mkdir(exist_ok=True)
    summary: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        print(f"Collecting project URLs from {PROFILE_URL} …")
        project_urls = await collect_project_urls(page)
        print(f"Found {len(project_urls)} project URLs.")

        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Referer": "https://www.behance.net/"}) as client:
            for i, url in enumerate(project_urls, 1):
                print(f"[{i}/{len(project_urls)}] {url}")
                try:
                    data = await scrape_project(page, url)
                except Exception as e:
                    print(f"  ! scrape failed: {e}")
                    continue

                slug = slug_from_url(url)
                project_dir = OUT_ROOT / slug
                project_dir.mkdir(parents=True, exist_ok=True)

                saved_files: list[str] = []
                for j, img_url in enumerate(data["image_urls"], 1):
                    dest = project_dir / f"{j:03d}"
                    ok = await download_and_resize(client, img_url, dest)
                    if ok:
                        saved_files.append(dest.with_suffix(".jpg").name)

                meta = {
                    "title": data["title"],
                    "url": url,
                    "description": data["description"],
                    "tags": data["tags"],
                    "images": saved_files,
                }
                (project_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

                summary.append({
                    "slug": slug,
                    "title": data["title"],
                    "url": url,
                    "tags": data["tags"],
                    "image_count": len(saved_files),
                })

        await browser.close()

    (OUT_ROOT / "projects.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nDone. {len(summary)} projects saved to {OUT_ROOT}/")


if __name__ == "__main__":
    asyncio.run(main())
