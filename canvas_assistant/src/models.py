"""Plain data models for Canvas objects the assistant tracks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Course:
    id: int
    name: str
    course_code: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "Course":
        return cls(
            id=data["id"],
            name=data.get("name") or data.get("course_code") or f"Course {data['id']}",
            course_code=data.get("course_code", ""),
        )


@dataclass
class Attachment:
    id: int
    display_name: str
    url: str
    content_type: str = ""


@dataclass
class Assignment:
    id: int
    course_id: int
    name: str
    description: str = ""
    due_at: Optional[datetime] = None
    lock_at: Optional[datetime] = None
    unlock_at: Optional[datetime] = None
    html_url: str = ""
    has_submitted_submissions: bool = False
    submission_types: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    points_possible: Optional[float] = None
    is_quiz: bool = False

    @classmethod
    def from_api(cls, data: dict, course_id: int) -> "Assignment":
        attachments = []
        for att in (data.get("attachments") or []):
            attachments.append(
                Attachment(
                    id=att["id"],
                    display_name=att.get("display_name", f"attachment_{att['id']}"),
                    url=att.get("url", ""),
                    content_type=att.get("content-type", att.get("content_type", "")),
                )
            )
        submission = data.get("submission") or {}
        return cls(
            id=data["id"],
            course_id=course_id,
            name=data.get("name", f"Assignment {data['id']}"),
            description=data.get("description") or "",
            due_at=_parse_dt(data.get("due_at")),
            lock_at=_parse_dt(data.get("lock_at")),
            unlock_at=_parse_dt(data.get("unlock_at")),
            html_url=data.get("html_url", ""),
            has_submitted_submissions=bool(submission.get("workflow_state") == "submitted"
                                            or submission.get("submitted_at")),
            submission_types=data.get("submission_types", []),
            attachments=attachments,
            points_possible=data.get("points_possible"),
            is_quiz="online_quiz" in (data.get("submission_types") or []),
        )


@dataclass
class Quiz:
    id: int
    course_id: int
    title: str
    description: str = ""
    due_at: Optional[datetime] = None
    unlock_at: Optional[datetime] = None
    lock_at: Optional[datetime] = None
    html_url: str = ""
    question_count: int = 0
    points_possible: Optional[float] = None

    @classmethod
    def from_api(cls, data: dict, course_id: int) -> "Quiz":
        return cls(
            id=data["id"],
            course_id=course_id,
            title=data.get("title", f"Quiz {data['id']}"),
            description=data.get("description") or "",
            due_at=_parse_dt(data.get("due_at")),
            unlock_at=_parse_dt(data.get("unlock_at")),
            lock_at=_parse_dt(data.get("lock_at")),
            html_url=data.get("html_url", ""),
            question_count=data.get("question_count", 0),
            points_possible=data.get("points_possible"),
        )


@dataclass
class Discussion:
    id: int
    course_id: int
    title: str
    message: str = ""
    due_at: Optional[datetime] = None
    html_url: str = ""
    posted_at: Optional[datetime] = None

    @classmethod
    def from_api(cls, data: dict, course_id: int) -> "Discussion":
        return cls(
            id=data["id"],
            course_id=course_id,
            title=data.get("title", f"Discussion {data['id']}"),
            message=data.get("message") or "",
            due_at=_parse_dt((data.get("assignment") or {}).get("due_at")),
            html_url=data.get("html_url", ""),
            posted_at=_parse_dt(data.get("posted_at")),
        )


@dataclass
class Announcement:
    id: int
    course_id: int
    title: str
    message: str = ""
    posted_at: Optional[datetime] = None
    html_url: str = ""

    @classmethod
    def from_api(cls, data: dict, course_id: int) -> "Announcement":
        return cls(
            id=data["id"],
            course_id=course_id,
            title=data.get("title", f"Announcement {data['id']}"),
            message=data.get("message") or "",
            posted_at=_parse_dt(data.get("posted_at")),
            html_url=data.get("html_url", ""),
        )


@dataclass
class CourseFile:
    id: int
    course_id: int
    display_name: str
    url: str
    content_type: str = ""
    folder_path: str = ""

    @classmethod
    def from_api(cls, data: dict, course_id: int) -> "CourseFile":
        return cls(
            id=data["id"],
            course_id=course_id,
            display_name=data.get("display_name", f"file_{data['id']}"),
            url=data.get("url", ""),
            content_type=data.get("content-type", data.get("content_type", "")),
            folder_path=data.get("folder_path", ""),
        )
