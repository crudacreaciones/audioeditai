"""Operation log: rotating log file + queryable `logs` table."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .db import Database, now

_logger = logging.getLogger("swc")


def setup_file_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "operations.log"
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == path for h in _logger.handlers):
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    return path


class OpLog:
    def __init__(self, db: Database):
        self.db = db

    def _write(self, level: str, category: str, message: str, details=None) -> None:
        det = "" if details is None else (details if isinstance(details, str) else json.dumps(details, ensure_ascii=False, default=str))
        self.db.execute(
            "INSERT INTO logs(ts, level, category, message, details) VALUES (?,?,?,?,?)",
            (now(), level, category, message, det),
        )
        _logger.log(getattr(logging, level.upper(), logging.INFO), "[%s] %s %s", category, message, det)

    def info(self, category: str, message: str, details=None) -> None:
        self._write("info", category, message, details)

    def warning(self, category: str, message: str, details=None) -> None:
        self._write("warning", category, message, details)

    def error(self, category: str, message: str, details=None) -> None:
        self._write("error", category, message, details)

    def list(self, level: str | None = None, category: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        sql, params = "SELECT * FROM logs WHERE 1=1", []
        if level:
            sql += " AND level=?"
            params.append(level)
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return self.db.query(sql, params)

    def clear(self) -> None:
        self.db.execute("DELETE FROM logs")
