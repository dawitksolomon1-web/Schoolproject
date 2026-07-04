"""Builds the human-facing summary dashboard (Markdown + CSV)."""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import DASHBOARD_DIR, DRAFTS_DIR
from src.tracker import SyncResult

logger = logging.getLogger("canvas_assistant.dashboard")

DASHBOARD_MD = DASHBOARD_DIR / "dashboard.md"
DASHBOARD_CSV = DASHBOARD_DIR / "dashboard.csv"


@dataclass
class DashboardRow:
    course: str
    item_type: str  # "Assignment" | "Quiz"
    title: str
    due_date: str
    status: str
    draft_location: str
    confidence: str
    manual_review_needed: str


def _load_metadata_index() -> dict:
    """Key: (course_id, 'assignment'|'quiz', item_id) -> metadata dict."""
    index: dict = {}
    for meta_path in DRAFTS_DIR.glob("**/metadata.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "assignment_id" in meta:
            index[(meta["course_id"], "assignment", meta["assignment_id"])] = meta
        elif "quiz_id" in meta:
            index[(meta["course_id"], "quiz", meta["quiz_id"])] = meta
    return index


class DashboardBuilder:
    def build(self, sync_result: SyncResult) -> list[DashboardRow]:
        metadata_index = _load_metadata_index()
        now = datetime.now(timezone.utc)
        rows: list[DashboardRow] = []

        for course in sync_result.courses:
            for a in sync_result.assignments.get(course.id, []):
                meta = metadata_index.get((course.id, "assignment", a.id))
                due = a.due_at.isoformat() if a.due_at else "No due date"
                if meta:
                    status = meta.get("status", "ready_for_student_review")
                    draft_location = meta.get("draft_path", "")
                    confidence = meta.get("confidence", "n/a")
                    review = str(meta.get("manual_review_needed", True))
                elif a.has_submitted_submissions:
                    status, draft_location, confidence, review = "already_submitted", "", "n/a", "False"
                elif a.due_at and a.due_at < now:
                    status, draft_location, confidence, review = "missing_no_draft", "", "n/a", "True"
                else:
                    status, draft_location, confidence, review = "no_draft_yet", "", "n/a", "True"
                rows.append(
                    DashboardRow(course.name, "Assignment", a.name, due, status,
                                 draft_location, confidence, review)
                )

            for q in sync_result.quizzes.get(course.id, []):
                meta = metadata_index.get((course.id, "quiz", q.id))
                due = q.due_at.isoformat() if q.due_at else "No due date"
                if meta:
                    status = meta.get("status", "study_notes_ready_for_review")
                    draft_location = meta.get("notes_path", "")
                    confidence = meta.get("confidence", "n/a")
                    review = str(meta.get("manual_review_needed", True))
                else:
                    status, draft_location, confidence, review = "no_study_notes_yet", "", "n/a", "True"
                rows.append(
                    DashboardRow(course.name, "Quiz", q.title, due, status,
                                 draft_location, confidence, review)
                )

        rows.sort(key=lambda r: r.due_date)
        return rows

    def write(self, rows: list[DashboardRow]) -> None:
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

        header = ["Course", "Type", "Title", "Due Date", "Status", "Draft Location",
                  "Confidence", "Manual Review Needed"]
        with open(DASHBOARD_CSV, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for r in rows:
                writer.writerow([r.course, r.item_type, r.title, r.due_date, r.status,
                                  r.draft_location, r.confidence, r.manual_review_needed])

        lines = [
            "# Canvas Academic Assistant — Dashboard",
            "",
            f"_Generated: {datetime.now(timezone.utc).isoformat()}_",
            "",
            "Everything below is prepared for your review. Nothing has been submitted to Canvas.",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "---|" * len(header),
        ]
        for r in rows:
            lines.append(
                "| " + " | ".join([
                    r.course, r.item_type, r.title, r.due_date, r.status,
                    r.draft_location or "—", r.confidence, r.manual_review_needed,
                ]) + " |"
            )
        DASHBOARD_MD.write_text("\n".join(lines) + "\n")
        logger.info("Dashboard written to %s and %s", DASHBOARD_MD, DASHBOARD_CSV)
