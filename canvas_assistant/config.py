"""Central configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# The only required setting: your institution's Canvas root URL.
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "").rstrip("/")

# Anthropic key — needed only for `draft --confirm` (draft generation).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DRAFT_MODEL = os.environ.get("CANVAS_ASSISTANT_DRAFT_MODEL", "claude-opus-4-8")

# Optional legacy API mode. OFF by default — the assistant is browser-only
# unless you deliberately set CANVAS_USE_API=1 and provide a token.
CANVAS_USE_API = os.environ.get("CANVAS_USE_API", "0") == "1"
CANVAS_API_TOKEN = os.environ.get("CANVAS_API_TOKEN", "")

DATA_DIR = Path(os.environ.get("CANVAS_ASSISTANT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
RAW_DIR = DATA_DIR / "raw"
DRAFTS_DIR = DATA_DIR / "drafts"
VECTOR_STORE_DIR = DATA_DIR / "vector_store"
STATE_DIR = DATA_DIR / "state"
DASHBOARD_DIR = DATA_DIR / "dashboard"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"  # persistent Chrome profile (saved login)

DEADLINE_WARNING_DAYS = int(os.environ.get("CANVAS_ASSISTANT_DEADLINE_WARNING_DAYS", "7"))

# Cap on how many course Pages to read per course when building the knowledge base.
MAX_PAGES_PER_COURSE = int(os.environ.get("CANVAS_ASSISTANT_MAX_PAGES_PER_COURSE", "25"))

for _dir in (RAW_DIR, DRAFTS_DIR, VECTOR_STORE_DIR, STATE_DIR, DASHBOARD_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


def require_base_url() -> None:
    if not CANVAS_BASE_URL:
        raise RuntimeError(
            "CANVAS_BASE_URL must be set in .env (e.g. https://your-school.instructure.com)."
        )
