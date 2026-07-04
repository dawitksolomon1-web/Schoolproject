"""
Persistent, read-only Chrome session against Canvas.

Design constraints (enforced across this file and scraper.py):
- Uses a persistent browser profile under data/browser_profile so you log in
  once with `python main.py login` and the session is reused afterwards.
- Read-only: the assistant only navigates, reads page content, and follows
  download links with GET requests. There is no code anywhere that clicks
  "Submit", "Start Quiz", "Reply", uploads a file, or fills a Canvas form
  other than nothing at all — login is done manually by YOU in the opened
  browser window.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from config import BROWSER_PROFILE_DIR, CANVAS_BASE_URL, require_base_url

logger = logging.getLogger("canvas_assistant.browser")

LOGGED_IN_MARKERS = (
    "#global_nav_profile_link",   # Canvas global left nav (logged-in only)
    ".ic-DashboardCard",          # dashboard course cards
    "#dashboard",
)


class BrowserSession:
    """Wraps a Playwright persistent Chrome context pointed at Canvas."""

    def __init__(self, headless: bool = True):
        require_base_url()
        self.base_url = CANVAS_BASE_URL
        self.headless = headless
        self._playwright = None
        self.context = None
        self.page = None

    # -- lifecycle --------------------------------------------------------

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        launch_kwargs = dict(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=self.headless,
            accept_downloads=True,
        )
        # Optional explicit browser binary (e.g. a system Chromium install).
        explicit_path = os.environ.get("CANVAS_ASSISTANT_CHROME_PATH")
        if explicit_path:
            self.context = self._playwright.chromium.launch_persistent_context(
                executable_path=explicit_path, **launch_kwargs
            )
        else:
            try:
                self.context = self._playwright.chromium.launch_persistent_context(
                    channel="chrome", **launch_kwargs
                )
            except Exception:
                logger.info("System Chrome not available, falling back to bundled Chromium.")
                self.context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.context:
            self.context.close()
        if self._playwright:
            self._playwright.stop()

    # -- login ------------------------------------------------------------

    def interactive_login(self) -> None:
        """Open Canvas and let the user log in manually; the persistent
        profile keeps the session for future headless runs."""
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        if self._looks_logged_in():
            print("You already have a saved Canvas session — no login needed.")
            return
        print(
            "\nA Chrome window is open at your Canvas login page.\n"
            "Log in normally (including SSO / 2FA if your school uses it).\n"
            "When you can see your Canvas dashboard, come back here.\n"
        )
        input("Press Enter once you are logged in and can see your dashboard... ")
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        if self._looks_logged_in():
            print("Login session saved. Future commands will reuse it automatically.")
        else:
            raise RuntimeError(
                "Could not confirm a logged-in Canvas session. Make sure you "
                "finished logging in in the opened window, then run "
                "`python main.py login` again."
            )

    def ensure_logged_in(self) -> None:
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        if not self._looks_logged_in():
            raise RuntimeError(
                "No valid Canvas session found. Run `python main.py login` first "
                "to log in through Chrome and save your session."
            )

    def _looks_logged_in(self) -> bool:
        if "/login" in self.page.url:
            return False
        for selector in LOGGED_IN_MARKERS:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    # -- read-only fetch helper --------------------------------------------

    def fetch_binary(self, url: str) -> Optional[bytes]:
        """GET a file using the browser session's cookies. Returns None if the
        response looks like an HTML page instead of a downloadable file."""
        if url.startswith("/"):
            url = self.base_url + url
        try:
            resp = self.context.request.get(url, max_redirects=10)
        except Exception:
            logger.exception("Download request failed for %s", url)
            return None
        if resp.status >= 400:
            logger.warning("Download failed (%s) for %s", resp.status, url)
            return None
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type and "attachment" not in resp.headers.get(
            "content-disposition", ""
        ):
            logger.debug("Skipping %s — response is an HTML page, not a file", url)
            return None
        return resp.body()
