"""Small shared helpers."""
from __future__ import annotations

import re


def slugify(value: str, max_len: int = 80) -> str:
    """Turn a course/assignment name into a filesystem-safe folder name."""
    value = re.sub(r"[^\w\s.-]", "", value, flags=re.UNICODE).strip()
    value = re.sub(r"[\s]+", "_", value)
    return value[:max_len].strip("_") or "untitled"
