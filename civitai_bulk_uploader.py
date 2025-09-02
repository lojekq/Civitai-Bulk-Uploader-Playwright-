#!/usr/bin/env python3
"""
civitai_bulk_uploader.py — debug-focused build
Changes for this build:
- ONLY uses https://civitai.com/posts/create (no /create, no homepage).
- --minimized to start Chromium minimized/off-screen (ignored during --login).
- --thumb-timeout to control how long we wait for thumbnails.
- Timestamped, ultra-detailed --debug logs (clicks, waits, durations).
- Retry filling Title after upload if the field wasn't ready at first.
"""

import asyncio
import argparse
import os
import sys
import time
import random
import hashlib
import sqlite3
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from PIL import Image, PngImagePlugin  # noqa: F401
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from playwright.async_api import async_playwright, Page, BrowserContext, Locator

# ---------------------- CONFIG ----------------------

SELECTORS = {
    # Post editor (direct URL)
    "editor_url": "https://civitai.com/posts/create",

    # Fields
    "file_input": "input[type='file']",
    "title_input": "textarea[placeholder*='Title'], input[placeholder*='Title'], textarea[name*='title'], input[name*='title']",
    "tags_input": "input[placeholder*='Tags'], input[aria-label*='Tags']",
    "publish_button": "button:has-text('Publish'), button:has-text('Post')",

    # Thumbnails after upload (best-effort)
    "thumbnail": "[data-testid*='image'], [class*='image']:not([aria-hidden='true']) img"
}

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

DEFAULT_POST_SIZE = 20
DEFAULT_CONCURRENCY = 1
DEFAULT_PAUSE_RANGE = (4, 8)
STORAGE_STATE = "storage_state.json"
SQLITE_DB = "uploaded.db"

# ---------------------- DEBUG LOGGER ----------------------

class DebugLogger:
    def __init__(self, enabled: bool, log_file: Optional[Path] = None):
        self.enabled = enabled
        self.log_file = log_file
        if self.enabled and self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def ts(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _write(self, line: str):
        if not self.enabled:
            return
        msg = f"[{self.ts()}] {line}"
        print(msg, flush=True)
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")

    def info(self, text: str): self._write(text)
    def click_try(self, selector: str, nth: Optional[int] = None):
        suf = f" [nth={nth}]" if nth is not None else ""
        self._write(f"CLICK try {selector}{suf}")
    def click_ok(self, selector: str, nth: Optional[int] = None):
        suf = f" [nth={nth}]" if nth is not None else ""
        self._write(f"CLICK ok  {selector}{suf}")
    def click_fail(self, selector: str, err: Exception, nth: Optional[int] = None):
        suf = f" [nth={nth}]" if nth is not None else ""
        self._write(f"CLICK err {selector}{suf} -> {repr(err)}")
    def wait(self, what: str, detail: str = ""):
        self._write(f"WAIT  {what} {detail}".rstrip())
    def nav(self, url: str, note: str = ""):
        self._write(f"GOTO  {url} {note}".rstrip())
    def keys(self, text: str):
        self._write(f"KEYS  {text}")
    def files(self, paths: List[str]):
        preview = "; ".join(paths[:3])
        more = f" (+{len(paths)-3} more)" if len(paths) > 3 else ""
        self._write(f"FILES {preview}{more}")
    def duration(self, label: str, seconds: float):
        self._write(f"DONE  {label} in {seconds:.2f}s")

# ---------------------- HELPERS ----------------------

async def goto(page: Page, url: str, dbg: DebugLogger, wait_until="domcontentloaded", timeout=120_000):
    dbg.nav(url, f"(wait_until={wait_until}, timeout={timeout}ms)")
    return await page.goto(url, wait_until=wait_until, timeout=timeout)

async def click(page: Page, selector: str, dbg: DebugLogger, nth: Optional[int] = None, timeout: int = 5000):
    loc: Locator = page.locator(selector).first if nth is None else page.locator(selector).nth(nth)
    dbg.click_try(selector, nth)
    try:
        await loc.click(timeout=timeout)
        dbg.click_ok(selector, nth)
        return True
    except Exception as e:
        dbg.click_fail(selector, e, nth)
        return False

async def fill(page: Page, selector: str, value: str, dbg: DebugLogger, timeout: int = 8000):
    dbg.info(f"FILL  {selector} = {value[:80]!r}")
    try:
        await page.locator(selector).first.fill(value, timeout=timeout)
        return True
    except Exception as e:
        dbg.info(f"FILL err {selector} -> {repr(e)}")
        return False

# ---------------------- CORE ----------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def init_db(db_path: str = SQLITE_DB):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256 TEXT UNIQUE,
            path TEXT,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn

def already_uploaded(conn, digest: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM uploads WHERE sha256 = ?", (digest,))
    return cur.fetchone() is not None

def mark_uploaded(conn, digest: str, path: Path):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO uploads (sha256, path) VALUES (?, ?)", (digest, str(path)))
    conn.commit()

def discover_images(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in ALLOWED_EXT:
            files.append(p)
    files.sort()
    return files

def group_batches(files: List[Path], group_by: str, post_size: int) -> List[List[Path]]:
    if group_by == "folder":
        groups: List[List[Path]] = []
        by_dir: Dict[Path, List[Path]] = {}
        for f in files:
            by_dir.setdefault(f.parent, []).append(f)
        for _, lst in by_dir.items():
            for i in range(0, len(lst), post_size):
                groups.append(lst[i:i + post_size])
        return groups
    return [files[i:i + post_size] for i in range(0, len(files), post_size)]

def title_for_group(group: List[Path], title_from: str) -> str:
    if title_from == "folder":
        return group[0].parent.name
    if title_from == "file":
        return group[0].stem
    return f"Civitai upload {time.strftime('%Y-%m-%d %H:%M')}"

def parse_args():
    ap = argparse.ArgumentParser(description="Bulk-upload images to Civitai via Playwright automation.")
    ap.add_argument("--login", action="store_true", help="Open a browser to log in and store cookies.")
    ap.add_argument("--dir", type=str, help="Folder with images to upload.")
    ap.add_argument("--post-size", type=int, default=DEFAULT_POST_SIZE, help="Max images per post.")
    ap.add_argument("--group-by", choices=["folder", "flat"], default="folder", help="Group images per post by folder or flat.")
    ap.add_argument("--title-from", choices=["folder", "file", "auto"], default="folder", help="How to auto-generate the post title.")
    ap.add_argument("--tags", type=str, default="", help="Comma-separated tags to add to each post (optional).")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="How many posts to create in parallel. Keep low.")
    ap.add_argument("--publish-timeout", type=int, default=180, help="Seconds to wait for publish to complete before one retry.")
    ap.add_argument("--thumb-timeout", type=int, default=90, help="Seconds to wait for thumbnails before falling back to networkidle.")
    ap.add_argument("--pause", type=str, default=f"{DEFAULT_PAUSE_RANGE[0]}-{DEFAULT_PAUSE_RANGE[1]}", help="Random pause seconds between key steps, e.g. '3-7'.")
    ap.add_argument("--dry-run", action="store_true", help="Do everything except clicking Publish.")
    ap.add_argument("--skip-hashes", action="store_true", help="Skip local dedupe by file hash database.")
    ap.add_argument("--verbose", action="store_true", help="High-level progress logs.")
    ap.add_argument("--debug", action="store_true", help="Ultra-detailed logs with timestamps for every action.")
    ap.add_argument("--log-file", type=str, default="debug_log.txt", help="Path to log file for --debug mode.")
    ap.add_argument("--trace", action="store_true", help="Record Playwright trace to trace.zip")
    ap.add_argument("--minimized", action="store_true", help="Start Chromium minimized/off-screen (ignored with --login).")
    return ap.parse_args()

async def do_login(play, storage_state: str, dbg: DebugLogger):
    # login requires visible window
    browser = await play.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
            "--lang=en-US",
        ]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        locale="en-US",
        timezone_id="Asia/Almaty",
    )
    page = await context.new_page()
    page.set_default_timeout(180_000)
    page.set_default_navigation_timeout(180_000)
    await goto(page, SELECTORS["editor_url"], dbg, wait_until="domcontentloaded", timeout=180_000)

    print("Пройди капчу/Cloudflare и залогинься на Civitai в открытом окне.")
    print("Когда закончил: ИЛИ нажми Enter в этой консоли, ИЛИ просто закрой браузерное окно. Я сохраню сессию автоматически.")

    import contextlib

    async def wait_console_enter():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, sys.stdin.readline)

    async def wait_page_close():
        fut = asyncio.get_running_loop().create_future()
        def _on_close():
            if not fut.done():
                fut.set_result(True)
        page.on("close", lambda: _on_close())
        return await fut

    enter_task = asyncio.create_task(wait_console_enter())
    close_task = asyncio.create_task(wait_page_close())
    timeout_task = asyncio.create_task(asyncio.sleep(600))  # 10 minutes

    done, pending = await asyncio.wait({enter_task, close_task, timeout_task}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t

    try:
        await context.storage_state(path=storage_state)
        dbg.info(f"Saved session to {storage_state}")
    finally:
        await browser.close()
        dbg.info("Browser closed.")

@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=2, max=10))
async def open_post_editor(page: Page, verbose: bool, dbg: DebugLogger):
    # Only navigate directly to editor URL
    await goto(page, SELECTORS["editor_url"], dbg, wait_until="domcontentloaded", timeout=120_000)
    if verbose or dbg.enabled:
        dbg.info("[editor] opened /posts/create")

async def upload_one_post(
    context: BrowserContext,
    images: List[Path],
    title: str,
    tags: List[str],
    pause_range: Tuple[int, int],
    dry_run: bool,
    verbose: bool,
    publish_timeout: int,
    thumb_timeout: int,
    dbg: DebugLogger
) -> bool:
    page = await context.new_page()
    await open_post_editor(page, verbose=verbose, dbg=dbg)

    # Title (first attempt)
    title_ok = await fill(page, SELECTORS["title_input"], title, dbg, timeout=8000)

    # Tags
    if tags:
        try:
            dbg.info("[post] adding tags")
            tag_input = page.locator(SELECTORS["tags_input"]).first
            for tag in tags:
                await tag_input.fill(tag.strip())
                dbg.keys("Enter (confirm tag)")
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.2)
        except Exception as e:
            dbg.info(f"[post] tags failed: {repr(e)}")

    # Upload files
    paths = [str(p) for p in images]
    t0 = time.monotonic()
    uploaded_ok = False
    try:
        inputs = page.locator(SELECTORS["file_input"])
        count = await inputs.count()
        dbg.info(f"[upload] {count} file inputs on page")
        if count == 0:
            raise RuntimeError("no file inputs found")
        for i in range(count):
            dbg.info(f"[upload] trying input #{i}")
            try:
                await inputs.nth(i).set_input_files(paths, timeout=120_000)
                dbg.files(paths)
                dbg.info(f"[upload] set files via input #{i}")
                uploaded_ok = True
                break
            except Exception as e:
                dbg.info(f"[upload] input #{i} failed: {repr(e)}")
    except Exception as e:
        dbg.info(f"[upload] Strategy A failed: {repr(e)}")

    # Wait for thumbnails with configurable timeout
    try:
        dbg.wait("selector", f"{SELECTORS['thumbnail']} (timeout={thumb_timeout}s)")
        await page.wait_for_selector(SELECTORS["thumbnail"], timeout=thumb_timeout * 1000)
        dbg.info("[upload] thumbnails appeared")
    except Exception:
        dbg.wait("networkidle (fallback)")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)
        dbg.info("[upload] continue after networkidle (fallback)")
    dbg.duration("upload+wait", time.monotonic() - t0)

    # Retry title after upload if first attempt failed
    if not title_ok:
        dbg.info("[post] retry filling title after upload")
        title_ok = await fill(page, SELECTORS["title_input"], title, dbg, timeout=8000)

    # Publish
    delay_ms = int(random.uniform(pause_range[0], pause_range[1]) * 1000)
    dbg.wait("pre-publish pause", f"{delay_ms}ms")
    await page.wait_for_timeout(delay_ms)

    if dry_run:
        dbg.info(f"[DRY-RUN] Would publish post '{title}' with {len(images)} images")
        await page.close()
        return True

    t_pub = time.monotonic()
    ok_click = await click(page, SELECTORS["publish_button"], dbg, timeout=15_000)
    if not ok_click:
        await page.close()
        return False

    import re as _re
    target_regex = _re.compile(r".*/posts/\d+(/edit)?")
    success = False
    try:
        dbg.wait("url", "posts/{id}")
        await page.wait_for_url(target_regex, timeout=publish_timeout * 1000)
        success = True
    except Exception:
        try:
            dbg.wait("networkidle after publish")
            await page.wait_for_load_state("networkidle", timeout=60_000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    if not success:
        dbg.info(f"[post] no URL change after Publish in {publish_timeout}s, retrying once")
        if await click(page, SELECTORS["publish_button"], dbg, timeout=10_000):
            try:
                await page.wait_for_url(target_regex, timeout=publish_timeout * 1000)
                success = True
            except Exception as e:
                dbg.info(f"[post] second Publish attempt did not confirm: {repr(e)}")

    dbg.duration("publish-phase", time.monotonic() - t_pub)

    if not success:
        dbg.info(f"[post] Publish not confirmed for '{title}' within timeout")
        await page.close()
        return False

    dbg.info(f"Published: {title}")
    await page.close()
    return True

async def main_async():
    args = parse_args()
    lo, hi = [int(x) for x in args.pause.split("-")]
    pause_range = (lo, hi)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    dbg = DebugLogger(enabled=args.debug, log_file=Path(args.log_file) if args.debug else None)

    async with async_playwright() as play:
        # Launch args (minimized best-effort for non-login runs)
        launch_args = ["--disable-blink-features=AutomationControlled", "--disable-gpu", "--lang=en-US"]
        if args.minimized and not args.login:
            launch_args += ["--start-minimized", "--window-position=-32000,-32000"]

        browser = await play.chromium.launch(headless=False, args=launch_args)

        if args.login:
            await do_login(play, STORAGE_STATE, dbg)
            return

        if not args.dir:
            print("Error: --dir is required unless --login is used")
            await browser.close()
            sys.exit(2)

        root = Path(args.dir).expanduser().resolve()
        if not root.exists():
            print(f"Error: directory does not exist: {root}")
            await browser.close()
            sys.exit(2)

        files = discover_images(root)
        if args.verbose or args.debug:
            dbg.info(f"[discover] found {len(files)} files under {root}")

        conn = None
        if not args.skip_hashes:
            conn = init_db(SQLITE_DB)
            filtered = []
            for f in files:
                digest = sha256_file(f)
                if not already_uploaded(conn, digest):
                    filtered.append(f)
            files = filtered
            if args.verbose or args.debug:
                dbg.info(f"[dedupe] left {len(files)} files after SHA-256 filter")
        if not files:
            print("No new images to upload. Either none found or all are already recorded.")
            await browser.close()
            return

        if os.path.exists(STORAGE_STATE):
            context = await browser.new_context(storage_state=STORAGE_STATE)
        else:
            print("No storage_state.json found. Run with --login first.")
            await browser.close()
            sys.exit(2)

        if args.trace:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)

        batches = group_batches(files, args.group_by, args.post_size)
        success_total = 0
        for idx, batch in enumerate(batches, start=1):
            title = title_for_group(batch, args.title_from)
            if args.verbose or args.debug:
                dbg.info(f"[batch {idx}/{len(batches)}] {len(batch)} files -> '{title}'")
            ok = await upload_one_post(context, batch, title, tags, pause_range, args.dry_run, args.verbose, args.publish_timeout, args.thumb_timeout, dbg)
            if ok:
                success_total += 1
                if conn:
                    for f in batch:
                        mark_uploaded(conn, sha256_file(f), f)
            await asyncio.sleep(random.uniform(pause_range[0], pause_range[1]))

        if args.trace:
            await context.tracing.stop(path="trace.zip")
            dbg.info("Trace saved to trace.zip")

        await context.storage_state(path=STORAGE_STATE)
        await browser.close()
        print(f"Done. Posts created: {success_total}/{len(batches)}")

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Interrupted by user.")
