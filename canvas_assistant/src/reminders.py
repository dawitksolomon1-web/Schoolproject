"""Turns tracker/draft output into a flat, human-readable reminder feed."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from config import STATE_DIR
from src.tracker import ChangeEvent, SyncResult

logger = logging.getLogger("canvas_assistant.reminders")

REMINDERS_FILE = STATE_DIR / "reminders.json"


@dataclass
class Reminder:
    category: str  # new_assignment | upcoming_deadline | ready_for_review | missing_submission | due_date_changed
    course_name: str
    title: str
    detail: str = ""
    due_at: Optional[str] = None


class ReminderEngine:
    def build(
        self,
        sync_result: SyncResult,
        ready_for_review: Sequence[dict] = (),
    ) -> list[Reminder]:
        reminders: list[Reminder] = []

        for event in sync_result.new_items:
            kind_map = {
                "new_assignment": "new_assignment",
                "new_quiz": "new_assignment",
                "new_discussion": "new_assignment",
                "new_announcement": "new_announcement",
            }
            reminders.append(
                Reminder(
                    category=kind_map.get(event.kind, event.kind),
                    course_name=event.course_name,
                    title=event.title,
                    detail=f"New {event.kind.replace('new_', '')} posted",
                )
            )

        for event in sync_result.due_date_changes:
            reminders.append(
                Reminder(
                    category="due_date_changed",
                    course_name=event.course_name,
                    title=event.title,
                    detail=event.detail,
                )
            )

        for a in sync_result.upcoming:
            reminders.append(
                Reminder(
                    category="upcoming_deadline",
                    course_name=self._course_name(sync_result, a.course_id),
                    title=a.name,
                    detail="Due soon",
                    due_at=a.due_at.isoformat() if a.due_at else None,
                )
            )

        for a in sync_result.missing_work:
            reminders.append(
                Reminder(
                    category="missing_submission",
                    course_name=self._course_name(sync_result, a.course_id),
                    title=a.name,
                    detail="Past due with no recorded submission",
                    due_at=a.due_at.isoformat() if a.due_at else None,
                )
            )

        for item in ready_for_review:
            reminders.append(
                Reminder(
                    category="ready_for_review",
                    course_name=item.get("course_name", ""),
                    title=item.get("assignment_name") or item.get("quiz_title", ""),
                    detail=f"Draft ready — confidence: {item.get('confidence', 'unknown')}",
                    due_at=item.get("due_at"),
                )
            )

        return reminders

    @staticmethod
    def _course_name(sync_result: SyncResult, course_id: int) -> str:
        for c in sync_result.courses:
            if c.id == course_id:
                return c.name
        return f"Course {course_id}"

    def save(self, reminders: list[Reminder], path: Path = REMINDERS_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "reminders": [asdict(r) for r in reminders],
        }
        path.write_text(json.dumps(payload, indent=2))
        logger.info("Saved %d reminder(s) to %s", len(reminders), path)
