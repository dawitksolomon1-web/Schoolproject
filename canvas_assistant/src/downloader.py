"""
Downloads and organizes materials the scraper discovered, and supports a
dry-run mode that only reports what WOULD be downloaded.

Layout:
data/raw/<course>/
    assignments/<assignment>/instructions.md   <- saved assignment instructions
    assignments/<assignment>/<attachment>      <- assignment attachments
    modules/<file>                             <- module-attached files
    files/<file>                               <- files from the Files section
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from config import RAW_DIR
from src.browser_session import BrowserSession
from src.models import Assignment, Course
from src.scraper import RemoteFile
from src.utils import slugify

logger = logging.getLogger("canvas_assistant.downloader")

INDEXABLE_EXTENSIONS = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt", ".md",
    ".csv", ".xlsx", ".xls", ".rtf", ".odt",
}


@dataclass
class DownloadedMaterial:
    path: Path
    course_id: int
    course_name: str
    category: str  # "module_file" | "course_file" | "assignment_attachment" | "instructions"
    source_name: str


def course_dir(course: Course) -> Path:
    return RAW_DIR / f"{course.id}_{slugify(course.name)}"


def _wanted(name: str) -> bool:
    return Path(name).suffix.lower() in INDEXABLE_EXTENSIONS


class MaterialDownloader:
    def __init__(self, session: BrowserSession, dry_run: bool = False):
        self.session = session
        self.dry_run = dry_run
        self.planned: list[str] = []  # human-readable dry-run report lines

    def save_instructions(self, course: Course, assignment: Assignment
                            ) -> DownloadedMaterial | None:
        if not assignment.description.strip():
            return None
        dest = course_dir(course) / "assignments" / slugify(assignment.name) / "instructions.md"
        if self.dry_run:
            self.planned.append(f"[instructions] {course.name} / {assignment.name}")
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            f"# {assignment.name}\n\nCourse: {course.name}\n"
            f"Due: {assignment.due_text or 'not listed'}\nURL: {assignment.url}\n\n"
            f"{assignment.description}\n"
        )
        return DownloadedMaterial(dest, course.id, course.name, "instructions", assignment.name)

    def download_assignment_attachments(self, course: Course, assignment: Assignment
                                          ) -> list[DownloadedMaterial]:
        results: list[DownloadedMaterial] = []
        for att in assignment.attachments:
            dest = course_dir(course) / "assignments" / slugify(assignment.name) / att.name
            if self.dry_run:
                self.planned.append(f"[attachment] {course.name} / {assignment.name} / {att.name}")
                continue
            material = self._fetch(att.url, dest, course, "assignment_attachment", att.name)
            if material:
                results.append(material)
        return results

    def download_remote_files(self, course: Course, files: list[RemoteFile]
                                ) -> list[DownloadedMaterial]:
        results: list[DownloadedMaterial] = []
        for rf in files:
            if not _wanted(rf.name):
                continue
            subdir = "modules" if rf.category == "module_file" else "files"
            dest = course_dir(course) / subdir / rf.name
            if self.dry_run:
                self.planned.append(f"[{rf.category}] {course.name} / {rf.name}")
                continue
            material = self._fetch(rf.url, dest, course, rf.category, rf.name)
            if material:
                results.append(material)
        return results

    def _fetch(self, url: str, dest: Path, course: Course, category: str, name: str
                ) -> DownloadedMaterial | None:
        if dest.exists():
            return DownloadedMaterial(dest, course.id, course.name, category, name)
        body = self.session.fetch_binary(url)
        if body is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        logger.info("Downloaded %s -> %s", name, dest)
        return DownloadedMaterial(dest, course.id, course.name, category, name)
