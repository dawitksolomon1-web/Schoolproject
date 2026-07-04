"""
Detects enrolled courses and every piece of upcoming work (assignments,
quizzes, discussions, announcements), and diffs against the previously
saved state to surface what's new, what changed, and what's missing.

This module only reads from Canvas (via CanvasClient) and writes its own
bookkeeping JSON to data/state/ — it never touches a submission endpoint.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import DEADLINE_WARNING_DAYS, STATE_DIR
from src.canvas_client import CanvasClient
from src.models import Announcement, Assignment, Course, Discussion, Quiz

logger = logging.getLogger("canvas_assistant.tracker")

STATE_FILE = STATE_DIR / "tracked_state.json"


@dataclass
class ChangeEvent:
    kind: str  # "new_assignment" | "new_quiz" | "new_discussion" | "new_announcement" | "due_date_changed"
    course_id: int
    course_name: str
    item_id: int
    title: str
    detail: str = ""


@dataclass
class SyncResult:
    courses: list[Course] = field(default_factory=list)
    assignments: dict[int, list[Assignment]] = field(default_factory=dict)
    quizzes: dict[int, list[Quiz]] = field(default_factory=dict)
    discussions: dict[int, list[Discussion]] = field(default_factory=dict)
    announcements: dict[int, list[Announcement]] = field(default_factory=dict)

    new_items: list[ChangeEvent] = field(default_factory=list)
    due_date_changes: list[ChangeEvent] = field(default_factory=list)
    missing_work: list[Assignment] = field(default_factory=list)
    upcoming: list[Assignment] = field(default_factory=list)


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"assignments": {}, "quizzes": {}, "discussions": {}, "announcements": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


class DeadlineTracker:
    def __init__(self, client: CanvasClient):
        self.client = client

    def sync(self) -> SyncResult:
        prev_state = _load_state()
        new_state: dict = {"assignments": {}, "quizzes": {}, "discussions": {}, "announcements": {}}
        result = SyncResult()

        courses = [Course.from_api(c) for c in self.client.get_courses()]
        result.courses = courses

        now = datetime.now(timezone.utc)

        for course in courses:
            assignments = [
                Assignment.from_api(a, course.id) for a in self.client.get_assignments(course.id)
            ]
            quizzes = [Quiz.from_api(q, course.id) for q in self.client.get_quizzes(course.id)]
            discussions = [
                Discussion.from_api(d, course.id) for d in self.client.get_discussions(course.id)
            ]
            announcements = [
                Announcement.from_api(a, course.id) for a in self.client.get_announcements(course.id)
            ]

            result.assignments[course.id] = assignments
            result.quizzes[course.id] = quizzes
            result.discussions[course.id] = discussions
            result.announcements[course.id] = announcements

            self._diff_assignments(course, assignments, prev_state, new_state, result)
            self._diff_quizzes(course, quizzes, prev_state, new_state, result)
            self._diff_discussions(course, discussions, prev_state, new_state, result)
            self._diff_announcements(course, announcements, prev_state, new_state, result)

            for a in assignments:
                if a.due_at is None:
                    continue
                if a.due_at < now and not a.has_submitted_submissions:
                    result.missing_work.append(a)
                elif now <= a.due_at <= now + timedelta(days=DEADLINE_WARNING_DAYS):
                    result.upcoming.append(a)

        _save_state(new_state)
        return result

    # -- per-type diffing -------------------------------------------------

    def _diff_assignments(self, course, assignments, prev_state, new_state, result):
        for a in assignments:
            key = str(a.id)
            snapshot = {"name": a.name, "due_at": _iso(a.due_at), "submitted": a.has_submitted_submissions}
            new_state["assignments"][key] = snapshot
            prev = prev_state.get("assignments", {}).get(key)
            if prev is None:
                result.new_items.append(
                    ChangeEvent("new_assignment", course.id, course.name, a.id, a.name)
                )
            elif prev.get("due_at") != snapshot["due_at"]:
                result.due_date_changes.append(
                    ChangeEvent(
                        "due_date_changed", course.id, course.name, a.id, a.name,
                        detail=f"{prev.get('due_at')} -> {snapshot['due_at']}",
                    )
                )

    def _diff_quizzes(self, course, quizzes, prev_state, new_state, result):
        for q in quizzes:
            key = str(q.id)
            snapshot = {"title": q.title, "due_at": _iso(q.due_at)}
            new_state["quizzes"][key] = snapshot
            prev = prev_state.get("quizzes", {}).get(key)
            if prev is None:
                result.new_items.append(
                    ChangeEvent("new_quiz", course.id, course.name, q.id, q.title)
                )
            elif prev.get("due_at") != snapshot["due_at"]:
                result.due_date_changes.append(
                    ChangeEvent(
                        "due_date_changed", course.id, course.name, q.id, q.title,
                        detail=f"{prev.get('due_at')} -> {snapshot['due_at']}",
                    )
                )

    def _diff_discussions(self, course, discussions, prev_state, new_state, result):
        for d in discussions:
            key = str(d.id)
            snapshot = {"title": d.title, "due_at": _iso(d.due_at)}
            new_state["discussions"][key] = snapshot
            prev = prev_state.get("discussions", {}).get(key)
            if prev is None:
                result.new_items.append(
                    ChangeEvent("new_discussion", course.id, course.name, d.id, d.title)
                )

    def _diff_announcements(self, course, announcements, prev_state, new_state, result):
        for a in announcements:
            key = str(a.id)
            snapshot = {"title": a.title, "posted_at": _iso(a.posted_at)}
            new_state["announcements"][key] = snapshot
            prev = prev_state.get("announcements", {}).get(key)
            if prev is None:
                result.new_items.append(
                    ChangeEvent("new_announcement", course.id, course.name, a.id, a.title)
                )
