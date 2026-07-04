"""
Tracks what the scraper found and diffs it against the previous run to
surface new assignments, changed due dates, missing (past-due) work, and
upcoming deadlines. Writes its bookkeeping to data/state/ only.

Note on "missing work": in browser-only mode the assistant doesn't read your
submission history, so anything past due is flagged for your attention —
check the dashboard row before assuming it's actually unsubmitted.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from config import DEADLINE_WARNING_DAYS, STATE_DIR
from src.models import Assignment, Course

logger = logging.getLogger("canvas_assistant.tracker")

STATE_FILE = STATE_DIR / "tracked_state.json"


@dataclass
class ChangeEvent:
    kind: str  # "new_assignment" | "due_date_changed"
    course_name: str
    title: str
    detail: str = ""


@dataclass
class TrackedWork:
    courses: list[Course] = field(default_factory=list)
    assignments: dict[int, list[Assignment]] = field(default_factory=dict)  # by course id

    new_items: list[ChangeEvent] = field(default_factory=list)
    due_date_changes: list[ChangeEvent] = field(default_factory=list)
    past_due: list[Assignment] = field(default_factory=list)
    upcoming: list[Assignment] = field(default_factory=list)

    def all_assignments(self) -> list[Assignment]:
        return [a for items in self.assignments.values() for a in items]


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            logger.warning("State file was corrupt; starting fresh.")
    return {"assignments": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def track(courses: list[Course], assignments_by_course: dict[int, list[Assignment]]
           ) -> TrackedWork:
    prev = _load_state()
    new_state: dict = {"assignments": {}}
    work = TrackedWork(courses=courses, assignments=assignments_by_course)
    now = datetime.now()

    for course in courses:
        for a in assignments_by_course.get(course.id, []):
            key = str(a.id)
            snapshot = {
                "name": a.name,
                "due_at": a.due_at.isoformat() if a.due_at else None,
                "due_text": a.due_text,
            }
            new_state["assignments"][key] = snapshot

            prev_snapshot = prev.get("assignments", {}).get(key)
            if prev_snapshot is None:
                work.new_items.append(ChangeEvent("new_assignment", course.name, a.name))
            elif prev_snapshot.get("due_at") != snapshot["due_at"]:
                work.due_date_changes.append(
                    ChangeEvent(
                        "due_date_changed", course.name, a.name,
                        detail=f"{prev_snapshot.get('due_at')} -> {snapshot['due_at']}",
                    )
                )

            if a.is_past_due(now):
                work.past_due.append(a)
            elif a.is_upcoming(DEADLINE_WARNING_DAYS, now):
                work.upcoming.append(a)

    _save_state(new_state)
    return work
