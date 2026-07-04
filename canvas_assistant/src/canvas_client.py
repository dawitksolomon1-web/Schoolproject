"""
Read-only Canvas API client.

This module only ever issues HTTP GET requests against the Canvas REST API.
It has no method that creates, updates, or submits anything — there is no
POST/PUT/DELETE call anywhere in this file. That is intentional: the whole
assistant is built to prepare drafts for a human to review and submit
themselves, never to touch Canvas's submission endpoints.
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

import requests

from config import CANVAS_API_TOKEN, CANVAS_BASE_URL, require_canvas_credentials

logger = logging.getLogger("canvas_assistant.canvas_client")

PER_PAGE = 100


class CanvasAPIError(RuntimeError):
    pass


class CanvasClient:
    """Thin wrapper around the Canvas REST API (read-only)."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        require_canvas_credentials()
        self.base_url = (base_url or CANVAS_BASE_URL).rstrip("/")
        self.token = token or CANVAS_API_TOKEN
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    # -- low-level helpers ------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}/api/v1{path}"
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code >= 400:
            raise CanvasAPIError(f"GET {url} failed: {resp.status_code} {resp.text[:300]}")
        return resp

    def _paginated(self, path: str, params: Optional[dict] = None) -> Iterator[dict]:
        params = dict(params or {})
        params.setdefault("per_page", PER_PAGE)
        url: Optional[str] = path
        first = True
        while url:
            resp = self._get(url, params=params if first else None)
            first = False
            data = resp.json()
            if isinstance(data, list):
                yield from data
            else:
                yield data
            url = resp.links.get("next", {}).get("url")

    # -- courses ------------------------------------------------------

    def get_courses(self, enrollment_state: str = "active") -> list[dict]:
        """List enrolled courses (defaults to currently active enrollments)."""
        return list(
            self._paginated(
                "/courses",
                {"enrollment_state": enrollment_state, "include[]": ["term", "total_scores"]},
            )
        )

    # -- assignments / quizzes / discussions / announcements -----------

    def get_assignments(self, course_id: int) -> list[dict]:
        return list(
            self._paginated(
                f"/courses/{course_id}/assignments",
                {"include[]": ["submission", "attachments"], "order_by": "due_at"},
            )
        )

    def get_quizzes(self, course_id: int) -> list[dict]:
        return list(self._paginated(f"/courses/{course_id}/quizzes"))

    def get_discussions(self, course_id: int) -> list[dict]:
        return list(self._paginated(f"/courses/{course_id}/discussion_topics"))

    def get_announcements(self, course_id: int) -> list[dict]:
        return list(
            self._paginated(
                "/announcements",
                {"context_codes[]": [f"course_{course_id}"]},
            )
        )

    def get_missing_submissions(self, user_id: str = "self") -> list[dict]:
        return list(self._paginated(f"/users/{user_id}/missing_submissions"))

    # -- modules / files -------------------------------------------------

    def get_modules(self, course_id: int) -> list[dict]:
        return list(self._paginated(f"/courses/{course_id}/modules", {"include[]": ["items"]}))

    def get_files(self, course_id: int) -> list[dict]:
        return list(self._paginated(f"/courses/{course_id}/files"))

    def get_file_metadata(self, file_id: int) -> dict:
        return self._get(f"/files/{file_id}").json()

    # -- downloads --------------------------------------------------------

    def download_file(self, url: str, dest_path) -> None:
        """Stream a file (module file, submission attachment, etc.) to disk."""
        resp = self.session.get(url, stream=True, timeout=60)
        if resp.status_code >= 400:
            raise CanvasAPIError(f"Download failed for {url}: {resp.status_code}")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        logger.info("Downloaded %s -> %s", url, dest_path)
