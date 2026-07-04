"""
Downloads and organizes course materials (files, module attachments,
assignment attachments) into a predictable local folder structure so the
knowledge base builder and draft generator can find them:

data/raw/<course>/
    files/                  <- everything under Canvas "Files"
    modules/<module_name>/  <- module-attached files (slides, notes, rubrics)
    assignments/<assignment>/ <- assignment attachments
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from config import RAW_DIR
from src.canvas_client import CanvasClient
from src.models import Assignment, Course
from src.utils import slugify

logger = logging.getLogger("canvas_assistant.downloader")

DOWNLOADABLE_EXTENSIONS = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt", ".md",
    ".csv", ".xlsx", ".xls", ".rtf", ".odt",
}


@dataclass
class DownloadedMaterial:
    path: Path
    course_id: int
    course_name: str
    category: str  # "course_file" | "module_file" | "assignment_attachment"
    source_name: str


def _course_dir(course: Course) -> Path:
    return RAW_DIR / f"{course.id}_{slugify(course.name)}"


def _is_indexable(name: str) -> bool:
    return Path(name).suffix.lower() in DOWNLOADABLE_EXTENSIONS


class FileDownloader:
    def __init__(self, client: CanvasClient):
        self.client = client

    def download_course_files(self, course: Course) -> list[DownloadedMaterial]:
        """Everything listed under the course's Files section."""
        results: list[DownloadedMaterial] = []
        dest_root = _course_dir(course) / "files"
        for f in self.client.get_files(course.id):
            name = f.get("display_name", f"file_{f.get('id')}")
            if not _is_indexable(name):
                continue
            dest = dest_root / name
            if not dest.exists():
                try:
                    self.client.download_file(f["url"], dest)
                except Exception:
                    logger.exception("Failed to download course file %s", name)
                    continue
            results.append(DownloadedMaterial(dest, course.id, course.name, "course_file", name))
        return results

    def download_module_files(self, course: Course) -> list[DownloadedMaterial]:
        """Slides, instructor notes, and other files attached to modules."""
        results: list[DownloadedMaterial] = []
        for module in self.client.get_modules(course.id):
            module_name = slugify(module.get("name", f"module_{module.get('id')}"))
            for item in module.get("items", []) or []:
                if item.get("type") != "File":
                    continue
                content_id = item.get("content_id")
                if content_id is None:
                    continue
                # Module items reference a file by id; fetch its metadata via the
                # course files listing already cached on the client is avoided here
                # to keep this call simple — Canvas exposes a direct file endpoint.
                try:
                    file_meta = self.client.get_file_metadata(content_id)
                except Exception:
                    logger.exception("Could not resolve module file %s", content_id)
                    continue
                name = file_meta.get("display_name", f"file_{content_id}")
                if not _is_indexable(name):
                    continue
                dest = _course_dir(course) / "modules" / module_name / name
                if not dest.exists():
                    try:
                        self.client.download_file(file_meta["url"], dest)
                    except Exception:
                        logger.exception("Failed to download module file %s", name)
                        continue
                results.append(
                    DownloadedMaterial(dest, course.id, course.name, "module_file", name)
                )
        return results

    def download_assignment_attachments(
        self, course: Course, assignment: Assignment
    ) -> list[DownloadedMaterial]:
        """Attachments on an assignment (instructions, rubric files, templates)."""
        results: list[DownloadedMaterial] = []
        if not assignment.attachments:
            return results
        dest_root = _course_dir(course) / "assignments" / slugify(assignment.name)
        for att in assignment.attachments:
            if not _is_indexable(att.display_name):
                continue
            dest = dest_root / att.display_name
            if not dest.exists():
                try:
                    self.client.download_file(att.url, dest)
                except Exception:
                    logger.exception("Failed to download attachment %s", att.display_name)
                    continue
            results.append(
                DownloadedMaterial(
                    dest, course.id, course.name, "assignment_attachment", att.display_name
                )
            )
        return results

    def download_all(self, courses: list[Course], assignments_by_course: dict[int, list[Assignment]]
                      ) -> list[DownloadedMaterial]:
        """Convenience entry point used by the CLI's `sync` command."""
        all_materials: list[DownloadedMaterial] = []
        for course in courses:
            all_materials += self.download_course_files(course)
            all_materials += self.download_module_files(course)
            for assignment in assignments_by_course.get(course.id, []):
                all_materials += self.download_assignment_attachments(course, assignment)
        return all_materials
