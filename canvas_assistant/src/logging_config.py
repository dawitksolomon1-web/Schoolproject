"""Shared logging setup for the assistant."""
from __future__ import annotations

import logging
import sys

from config import DATA_DIR


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    log_path = DATA_DIR / "assistant.log"
    logger = logging.getLogger("canvas_assistant")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
