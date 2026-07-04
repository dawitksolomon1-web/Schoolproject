"""Data models for what the browser scraper finds on Canvas."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Course:
    id: int
    name: str
    url: str = ""


@dataclass
class Attachment:
    name: str
    url: str


@dataclass
class Assignment:
    id: int
    course_id: int
    course_name: str
    name: str
    url: str
    due_at: Optional[datetime] = None      # naive local time, parsed from page text
    due_text: str = ""                      # raw text as shown on Canvas
    description: str = ""                   # instructions, filled in during sync
    attachments: list[Attachment] = field(default_factory=list)
    is_discussion: bool = False

    def is_past_due(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        return self.due_at is not None and self.due_at < now

    def is_upcoming(self, days: int, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        return (
            self.due_at is not None
            and now <= self.due_at <= now + timedelta(days=days)
        )


_DUE_FORMATS = (
    "%b %d, %Y %I:%M%p",
    "%b %d %I:%M%p",
    "%b %d, %Y",
    "%b %d",
    "%m/%d/%Y %I:%M%p",
    "%m/%d/%Y",
)


def parse_due_text(text: str) -> Optional[datetime]:
    """Best-effort parse of Canvas due-date strings like 'Due Jun 5 at 11:59pm'."""
    if not text:
        return None
    cleaned = text.strip()
    if "multiple" in cleaned.lower():
        return None
    cleaned = re.sub(r"^\s*due\b[:\s]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(" at ", " ").replace(" by ", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    now = datetime.now()
    for fmt in _DUE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if dt.year == 1900:  # format had no year — assume this school year
            dt = dt.replace(year=now.year)
            if dt < now - timedelta(days=180):
                dt = dt.replace(year=now.year + 1)
        return dt
    return None
