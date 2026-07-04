"""
Read-only Canvas web scraper.

Everything in here works through the logged-in browser session: it navigates
to Canvas pages exactly like you would, reads what's on them, and follows
file download links. It never fills in a form, clicks a submit/start/reply
button, or changes anything on Canvas.

Scraped surfaces:
- Dashboard course cards (fallback: the /courses list) -> enrolled courses
- /courses/<id>/assignments                            -> assignments + due dates
  (discussions that are graded appear on this page too and are picked up)
- individual assignment pages                          -> instructions + attachments
- /courses/<id>/modules                                -> module files & linked pages
- /courses/<id>/files                                  -> course files (best-effort)
- /courses/<id>/pages                                  -> page text for the knowledge base

Canvas themes vary by institution, so every selector here is best-effort and
failures are logged and skipped rather than fatal.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from config import MAX_PAGES_PER_COURSE
from src.browser_session import BrowserSession
from src.models import Assignment, Attachment, Course, parse_due_text

logger = logging.getLogger("canvas_assistant.scraper")

PAGE_TIMEOUT_MS = 20000


@dataclass
class PageContent:
    """A Canvas wiki page's readable text (for the knowledge base)."""
    course_id: int
    title: str
    url: str
    text: str


@dataclass
class RemoteFile:
    """A downloadable file discovered on Canvas (not yet downloaded)."""
    course_id: int
    name: str
    url: str
    category: str  # "module_file" | "course_file" | "assignment_attachment"


@dataclass
class PlannerItem:
    """An item read off the Planner/Timeline dashboard (fallback summary only)."""
    title: str
    due_text: str
    course_hint: str = ""
    points_text: str = ""


class CanvasScraper:
    def __init__(self, session: BrowserSession):
        self.session = session
        self.page = session.page
        self.base_url = session.base_url

    def _goto(self, url: str) -> bool:
        if url.startswith("/"):
            url = self.base_url + url
        for attempt in (1, 2):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                return True
            except Exception:
                if attempt == 1:
                    # A failed navigation (e.g. an error page still loading) can
                    # interrupt the next goto — settle the tab and retry once.
                    try:
                        self.page.goto("about:blank", timeout=5000)
                    except Exception:
                        pass
                else:
                    logger.warning("Could not open %s", url)
        return False

    # -- courses ------------------------------------------------------------

    def get_courses(self) -> list[Course]:
        """Enrolled courses. The /courses page is the primary source of truth
        (it exists for every user regardless of dashboard layout); dashboard
        course cards are only a fallback."""
        courses = self._courses_from_courses_page()
        if not courses:
            logger.info("/courses yielded nothing — falling back to dashboard cards.")
            courses = self._courses_from_dashboard_cards()
        logger.info("Found %d course(s).", len(courses))
        return courses

    def _courses_from_dashboard_cards(self) -> list[Course]:
        if not self._goto("/"):
            return []
        try:
            self.page.wait_for_selector(".ic-DashboardCard__link", timeout=8000)
        except Exception:
            return []
        courses = []
        for card in self.page.locator("a.ic-DashboardCard__link").all():
            href = card.get_attribute("href") or ""
            match = re.search(r"/courses/(\d+)", href)
            if not match:
                continue
            name = (card.get_attribute("aria-label") or card.inner_text() or "").strip()
            courses.append(Course(int(match.group(1)), name or f"Course {match.group(1)}",
                                    urljoin(self.base_url, href)))
        return courses

    def _courses_from_courses_page(self) -> list[Course]:
        if not self._goto("/courses"):
            return []
        courses: dict[int, Course] = {}

        def collect(scope_selector: str, active: bool) -> None:
            for link in self.page.locator(f"{scope_selector} a[href*='/courses/']").all():
                try:
                    href = link.get_attribute("href") or ""
                    match = re.fullmatch(r".*?/courses/(\d+)", href)
                    if not match:
                        continue
                    cid = int(match.group(1))
                    name = (link.inner_text() or "").strip()
                    if cid not in courses and name:
                        courses[cid] = Course(cid, name, urljoin(self.base_url, href), active=active)
                except Exception:
                    continue

        # Which ids belong to past enrollments (to exclude from fallbacks)?
        past_ids: set[int] = set()
        for link in self.page.locator("#past_enrollments_table a[href*='/courses/']").all():
            try:
                match = re.fullmatch(r".*?/courses/(\d+)", link.get_attribute("href") or "")
                if match:
                    past_ids.add(int(match.group(1)))
            except Exception:
                continue

        # Current enrollments first ("My Courses" table).
        collect("#my_courses_table", active=True)
        if not courses:
            # Theme without the classic table — take any course link in the
            # content area, minus known past enrollments.
            collect("#content", active=True)
            for pid in past_ids:
                courses.pop(pid, None)
        return list(courses.values())

    # -- assignments ---------------------------------------------------------

    def get_assignments(self, course: Course) -> list[Assignment]:
        """Scrape <course_url>/assignments (graded discussions included)."""
        if not self._goto(f"/courses/{course.id}/assignments"):
            return []
        try:
            self.page.wait_for_selector("div.assignment, .ig-row", timeout=10000)
        except Exception:
            logger.info("No assignments visible for %s", course.name)
            return []

        assignments: list[Assignment] = []
        groups = self.page.locator("div.assignment_group").all()
        if groups:
            for group in groups:
                group_name = ""
                header = group.locator(".ig-header-title, .ig-header h2, .ig-header h3")
                if header.count() > 0:
                    try:
                        group_name = (header.first.inner_text() or "").strip()
                    except Exception:
                        pass
                for item in group.locator("div.assignment").all():
                    parsed = self._parse_assignment_row(item, course, group_name)
                    if parsed:
                        assignments.append(parsed)
        else:
            for item in self.page.locator("div.assignment").all():
                parsed = self._parse_assignment_row(item, course, "")
                if parsed:
                    assignments.append(parsed)
        logger.info("%s: %d assignment(s) found.", course.name, len(assignments))
        return assignments

    def _parse_assignment_row(self, item, course: Course, group_name: str
                                ) -> Assignment | None:
        try:
            elem_id = item.get_attribute("id") or ""
            match = re.search(r"assignment_(\d+)", elem_id)
            title_link = item.locator("a.ig-title").first
            href = title_link.get_attribute("href") or ""
            name = (title_link.inner_text() or "").strip()
            if not name or not href:
                return None
            if not match:
                match = re.search(r"/assignments/(\d+)", href)
                if not match:
                    return None
            due_text = ""
            due_locator = item.locator(".assignment-date-due")
            if due_locator.count() > 0:
                due_text = (due_locator.first.inner_text() or "").strip()

            row_text = ""
            try:
                row_text = item.inner_text() or ""
            except Exception:
                pass
            points_match = re.search(r"(\d[\d,.]*)\s*pts", row_text)
            points_text = f"{points_match.group(1)} pts" if points_match else ""

            status_text = ""
            status_locator = item.locator(".submission-status, [class*='submission_status']")
            if status_locator.count() > 0:
                try:
                    status_text = (status_locator.first.inner_text() or "").strip()
                except Exception:
                    pass

            is_discussion = "/discussion_topics/" in href or item.locator(
                "i.icon-discussion"
            ).count() > 0
            return Assignment(
                id=int(match.group(1)),
                course_id=course.id,
                course_name=course.name,
                name=name,
                url=urljoin(self.base_url, href),
                due_at=parse_due_text(due_text),
                due_text=due_text,
                is_discussion=is_discussion,
                points_text=points_text,
                group=group_name,
                status_text=status_text,
            )
        except Exception:
            logger.exception("Failed to parse an assignment row in %s", course.name)
            return None

    # -- planner / timeline dashboard (fallback summary only) ----------------

    _PLANNER_LINE = re.compile(
        r"^(?:assignment|discussion|graded discussion)\s+(?P<title>.+?),\s*due\s+(?P<due>.+)$",
        re.IGNORECASE,
    )
    _COURSE_CONTEXT = re.compile(r"^[A-Z]{2,}[\w-]*\s*[:—-]\s+\S")

    def get_planner_summary(self) -> list[PlannerItem]:
        """Read assignment items off the Planner/Timeline dashboard.

        This is a FALLBACK/quick summary only — the Courses page ->
        Assignments page path is the primary source of truth. Works off the
        rendered text so it survives Planner markup changes:

            ENAE441-WB11: Space Navigation and Guidance-Summer I 2026
            Assignment Homework 4, due Monday, July 6, 2026 11:00 PM
            Homework 4
            100 pts
        """
        if not self._goto("/"):
            return []
        try:
            body_text = self.page.locator("body").inner_text(timeout=8000)
        except Exception:
            return []

        items: list[PlannerItem] = []
        seen: set[str] = set()
        course_hint = ""
        lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if self._COURSE_CONTEXT.match(line):
                course_hint = line
                continue
            match = self._PLANNER_LINE.match(line)
            if not match:
                continue
            title = match.group("title").strip()
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            points_text = ""
            for follow in lines[i + 1:i + 4]:  # points usually follow within a couple lines
                points_match = re.fullmatch(r"(\d[\d,.]*)\s*pts", follow, re.IGNORECASE)
                if points_match:
                    points_text = f"{points_match.group(1)} pts"
                    break
            items.append(
                PlannerItem(
                    title=title,
                    due_text=match.group("due").strip(),
                    course_hint=course_hint,
                    points_text=points_text,
                )
            )
        logger.info("Planner summary: %d item(s).", len(items))
        return items

    def fill_assignment_detail(self, assignment: Assignment) -> Assignment:
        """Open the assignment page and read its instructions + attachments."""
        if not self._goto(assignment.url):
            return assignment
        desc = self.page.locator(".description.user_content, .description")
        if desc.count() > 0:
            try:
                assignment.description = (desc.first.inner_text() or "").strip()
            except Exception:
                pass
        # Discussions render the prompt in a different container.
        if not assignment.description:
            body = self.page.locator(".discussion-section .message, .user_content")
            if body.count() > 0:
                try:
                    assignment.description = (body.first.inner_text() or "").strip()
                except Exception:
                    pass

        seen = set()
        for link in self.page.locator(
            "a.instructure_file_link, #content a[href*='/files/']"
        ).all():
            try:
                href = link.get_attribute("href") or ""
                if not href or href in seen:
                    continue
                seen.add(href)
                name = (link.inner_text() or "").strip() or href.rsplit("/", 1)[-1]
                assignment.attachments.append(
                    Attachment(name=name, url=self._downloadable(href))
                )
            except Exception:
                continue
        return assignment

    # -- course materials -----------------------------------------------------

    def get_module_materials(self, course: Course) -> tuple[list[RemoteFile], list[str]]:
        """Files and page-links found on the course's Modules page.

        Returns (files, page_urls)."""
        files: list[RemoteFile] = []
        page_urls: list[str] = []
        if not self._goto(f"/courses/{course.id}/modules"):
            return files, page_urls
        try:
            self.page.wait_for_selector(".context_module_item", timeout=8000)
        except Exception:
            return files, page_urls

        for item in self.page.locator(".context_module_item").all():
            try:
                classes = item.get_attribute("class") or ""
                link = item.locator("a.ig-title, a.item_link").first
                if link.count() == 0:
                    continue
                href = link.get_attribute("href") or ""
                name = (link.inner_text() or "").strip()
                if not href or not name:
                    continue
                if "attachment" in classes:
                    files.append(
                        RemoteFile(course.id, name, self._downloadable(href), "module_file")
                    )
                elif "wiki_page" in classes:
                    page_urls.append(urljoin(self.base_url, href))
            except Exception:
                continue
        logger.info("%s: %d module file(s), %d module page(s).",
                    course.name, len(files), len(page_urls))
        return files, page_urls

    def get_course_files(self, course: Course) -> list[RemoteFile]:
        """Best-effort scrape of the Files section (a JS app; theme-dependent)."""
        files: list[RemoteFile] = []
        if not self._goto(f"/courses/{course.id}/files"):
            return files
        try:
            self.page.wait_for_selector(".ef-item-row", timeout=8000)
        except Exception:
            logger.info("%s: Files section not scrapable (hidden or restricted).", course.name)
            return files
        for link in self.page.locator("a.ef-name-col__link").all():
            try:
                href = link.get_attribute("href") or ""
                name = (link.inner_text() or "").strip()
                if href and name and "/files/" in href:
                    files.append(
                        RemoteFile(course.id, name, self._downloadable(href), "course_file")
                    )
            except Exception:
                continue
        logger.info("%s: %d file(s) listed under Files.", course.name, len(files))
        return files

    def get_course_pages(self, course: Course, extra_page_urls: list[str] | None = None
                          ) -> list[PageContent]:
        """Read course wiki pages (syllabus-style content) for the knowledge base."""
        urls: list[str] = list(extra_page_urls or [])
        if self._goto(f"/courses/{course.id}/pages"):
            try:
                self.page.wait_for_selector("a[href*='/pages/']", timeout=8000)
                for link in self.page.locator("#content a[href*='/pages/']").all():
                    href = link.get_attribute("href") or ""
                    if href:
                        urls.append(urljoin(self.base_url, href))
            except Exception:
                pass

        deduped = list(dict.fromkeys(urls))[:MAX_PAGES_PER_COURSE]
        pages: list[PageContent] = []
        for url in deduped:
            if not self._goto(url):
                continue
            body = self.page.locator(".show-content, .user_content")
            if body.count() == 0:
                continue
            try:
                text = (body.first.inner_text() or "").strip()
                title = (self.page.title() or url).split(":")[0].strip()
            except Exception:
                continue
            if text:
                pages.append(PageContent(course.id, title, url, text))
        logger.info("%s: read %d course page(s).", course.name, len(pages))
        return pages

    # -- helpers ---------------------------------------------------------------

    def _downloadable(self, href: str) -> str:
        """Turn a Canvas file link into its direct-download form."""
        url = urljoin(self.base_url, href)
        if "/files/" in url and "download" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}download_frd=1"
        return url
