"""Central configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "").rstrip("/")
CANVAS_API_TOKEN = os.environ.get("CANVAS_API_TOKEN", "")

CANVAS_USERNAME = os.environ.get("CANVAS_USERNAME", "")
CANVAS_PASSWORD = os.environ.get("CANVAS_PASSWORD", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DRAFT_MODEL = os.environ.get("CANVAS_ASSISTANT_DRAFT_MODEL", "claude-opus-4-8")

DATA_DIR = Path(os.environ.get("CANVAS_ASSISTANT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
RAW_DIR = DATA_DIR / "raw"
DRAFTS_DIR = DATA_DIR / "drafts"
VECTOR_STORE_DIR = DATA_DIR / "vector_store"
STATE_DIR = DATA_DIR / "state"
DASHBOARD_DIR = DATA_DIR / "dashboard"

DEADLINE_WARNING_DAYS = int(os.environ.get("CANVAS_ASSISTANT_DEADLINE_WARNING_DAYS", "7"))

for _dir in (RAW_DIR, DRAFTS_DIR, VECTOR_STORE_DIR, STATE_DIR, DASHBOARD_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


def require_canvas_credentials() -> None:
    if not CANVAS_BASE_URL or not CANVAS_API_TOKEN:
        raise RuntimeError(
            "CANVAS_BASE_URL and CANVAS_API_TOKEN must be set (see .env.example). "
            "The Canvas API token is the primary connection method; the Playwright "
            "login fallback is only used when a token cannot be issued."
        )
