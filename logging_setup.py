"""Structured JSONL logging with rotation."""
from __future__ import annotations

import csv
import io
import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def setup_logging(log_dir: Path, log_level: str = "INFO",
                  max_bytes: int = 10_485_760, backup_count: int = 10) -> logging.Logger:
    """Configure and return the docman logger with JSONL rotation."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("docman")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "docman.jsonl",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    return logger


def log_operation(logger: logging.Logger, **fields: Any) -> None:
    """Append a single JSONL record."""
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    record.update(fields)
    logger.info(json.dumps(record, ensure_ascii=False))


class CSVSummaryWriter:
    """Write human-readable CSV summaries per operation."""

    def __init__(self, log_dir: Path, operation: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = log_dir / f"docman_{ts}_{operation}.csv"
        self._file: io.TextIOWrapper | None = None
        self._writer: csv.writer | None = None

    def open(self, fieldnames: list[str]) -> None:
        self._file = open(self._path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(fieldnames)

    def writerow(self, row: list) -> None:
        if self._writer:
            self._writer.writerow(row)

    def close(self) -> Path:
        if self._file:
            self._file.close()
        return self._path
