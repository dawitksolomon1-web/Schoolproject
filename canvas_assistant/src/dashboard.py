"""Builds the human-facing summary dashboard (Markdown + CSV + console table)."""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from config import DASHBOARD_DIR, DRAFTS_DIR
from src.tracker import TrackedWork

logger = logging.getLogger("canvas_assistant.dashboard")

DASHBOARD_MD = DASHBOARD_DIR / "dashboard.md"
DASHBOARD_CSV = DASHBOARD_DIR / "dashboard.csv"

HEADER = ["Course", "Assignment", "Due Date", "Status", "Draft Location",
          "Confidence", "Manual Review Needed"]


@dataclass
class DashboardRow:
    course: str
    title: str
    due_date: str
    status: str
    draft_location: str
    confidence: str
    manual_review_needed: str


def _load_metadata_index() -> dict:
    """(course_id, assignment_id) -> draft metadata dict."""
    index: dict = {}
    for meta_path in DRAFTS_DIR.glob("**/metadata.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "assignment_id" in meta:
            index[(meta["course_id"], meta["assignment_id"])] = meta
    return index


class DashboardBuilder:
    def build(self, work: TrackedWork) -> list[DashboardRow]:
        metadata_index = _load_metadata_index()
        now = datetime.now()
        rows: list[DashboardRow] = []

        for course in work.courses:
            for a in work.assignments.get(course.id, []):
                meta = metadata_index.get((course.id, a.id))
                due = a.due_text or (a.due_at.isoformat() if a.due_at else "No due date")
                if meta:
                    status = meta.get("status", "ready_for_student_review")
                    draft_location = meta.get("draft_path", "")
                    confidence = meta.get("confidence", "n/a")
                    review = str(meta.get("manual_review_needed", True))
                elif a.is_past_due(now):
                    status, draft_location, confidence, review = "past_due_no_draft", "", "n/a", "True"
                else:
                    status, draft_location, confidence, review = "no_draft_yet", "", "n/a", "True"
                rows.append(
                    DashboardRow(course.name, a.name, due, status,
                                 draft_location, confidence, review)
                )

        rows.sort(key=lambda r: (r.course, r.due_date))
        return rows

    def write(self, rows: list[DashboardRow]) -> None:
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

        with open(DASHBOARD_CSV, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(HEADER)
            for r in rows:
                writer.writerow([r.course, r.title, r.due_date, r.status,
                                  r.draft_location, r.confidence, r.manual_review_needed])

        lines = [
            "# Canvas Academic Assistant — Dashboard",
            "",
            f"_Generated: {datetime.now(timezone.utc).isoformat()}_",
            "",
            "Everything below is prepared for your review. Nothing has been submitted to Canvas.",
            "",
            "| " + " | ".join(HEADER) + " |",
            "|" + "---|" * len(HEADER),
        ]
        for r in rows:
            lines.append(
                "| " + " | ".join([
                    r.course, r.title, r.due_date, r.status,
                    r.draft_location or "—", r.confidence, r.manual_review_needed,
                ]) + " |"
            )
        DASHBOARD_MD.write_text("\n".join(lines) + "\n")
        logger.info("Dashboard written to %s and %s", DASHBOARD_MD, DASHBOARD_CSV)

    @staticmethod
    def print_console(rows: list[DashboardRow]) -> None:
        if not rows:
            print("No assignments found.")
            return
        widths = [
            max(len(HEADER[i]), max(len(getattr(r, f)) for r in rows))
            for i, f in enumerate(
                ["course", "title", "due_date", "status", "draft_location",
                 "confidence", "manual_review_needed"]
            )
        ]
        widths = [min(w, 45) for w in widths]

        def fmt(values):
            return "  ".join(v[:w].ljust(w) for v, w in zip(values, widths))

        print(fmt(HEADER))
        print(fmt(["-" * w for w in widths]))
        for r in rows:
            print(fmt([r.course, r.title, r.due_date, r.status,
                        r.draft_location or "—", r.confidence, r.manual_review_needed]))
