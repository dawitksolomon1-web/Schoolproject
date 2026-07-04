"""
Optional Playwright fallback for institutions that block personal API tokens.

This is NOT used by default — `main.py` only calls into this module if you
explicitly pass `--use-browser-login`. Prefer the Canvas API (see
canvas_client.py) whenever a token is available; it's simpler, faster, and
easier to reason about.

Scope, by design: this module can only log in and download files from pages
it navigates to. It has no method that clicks "Submit", "Turn In", "Post
Reply", or any other action button — that functionality is intentionally
not implemented anywhere in this project.
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import CANVAS_BASE_URL, CANVAS_PASSWORD, CANVAS_USERNAME

logger = logging.getLogger("canvas_assistant.browser_login")


class ReadOnlyCanvasBrowser:
    """A read-only Playwright session against Canvas's web UI.

    Use this only when a Canvas API token cannot be issued (some
    institutions restrict token creation). It logs in, can navigate to a
    course page, and can download a file the current page links to. It
    does not fill out or submit any form.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or CANVAS_BASE_URL).rstrip("/")
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> "ReadOnlyCanvasBrowser":
        from playwright.sync_api import sync_playwright

        if not CANVAS_USERNAME or not CANVAS_PASSWORD:
            raise RuntimeError(
                "CANVAS_USERNAME and CANVAS_PASSWORD must be set in .env to use "
                "the browser login fallback."
            )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(accept_downloads=True)
        self.page = self._context.new_page()
        self._login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _login(self) -> None:
        """Standard Canvas username/password login form.

        Institutions using SSO (Google, Okta, Shibboleth, etc.) will need a
        custom login flow — this covers Canvas's native login form only.
        """
        page = self.page
        page.goto(f"{self.base_url}/login/canvas")
        page.fill("#pseudonym_session_unique_id", CANVAS_USERNAME)
        page.fill("#pseudonym_session_password", CANVAS_PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        if "/login" in page.url:
            raise RuntimeError(
                "Canvas login did not appear to succeed — check credentials, "
                "or your institution may require SSO (not supported by this "
                "fallback)."
            )
        logger.info("Logged in to Canvas via browser session.")

    def download_linked_file(self, page_url: str, link_text: str, dest_path: Path) -> Path:
        """Navigate to a page and download a file it links to by visible text.

        Read-only: this only follows a download link, it never interacts
        with any submission control.
        """
        page = self.page
        page.goto(page_url)
        with page.expect_download() as download_info:
            page.get_by_text(link_text, exact=False).first.click()
        download = download_info.value
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(dest_path))
        logger.info("Downloaded (via browser) %s -> %s", link_text, dest_path)
        return dest_path
