"""
BursaSentinel — Structured Swarm Logger
=========================================
Writes JSON-lines to logs/swarm_{YYYYMMDD}.jsonl
Used by InfiltratorAgent, StrategistAgent, WatchlistAgent, and Swarm.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path


class _JsonlHandler(logging.Handler):
    """Appends one JSON object per log record to a .jsonl file."""

    def __init__(self, log_path: Path):
        super().__init__()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = log_path

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "agent": record.name,
            "event": record.getMessage(),
        }
        # Merge any extras passed via extra={}
        for k, v in record.__dict__.items():
            if k not in logging.LogRecord.__dict__ and not k.startswith("_"):
                entry[k] = v
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Never let logging crash the swarm


def get_swarm_logger(name: str) -> logging.Logger:
    """
    Return a logger that:
      - Prints INFO+ to stdout (console)
      - Appends all levels to logs/swarm_{date}.jsonl
    """
    logger = logging.getLogger(f"bursasentinel.{name}")
    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(ch)

    # JSONL file handler
    date_str = datetime.now().strftime("%Y%m%d")
    log_path = Path("logs") / f"swarm_{date_str}.jsonl"
    fh = _JsonlHandler(log_path)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    return logger
