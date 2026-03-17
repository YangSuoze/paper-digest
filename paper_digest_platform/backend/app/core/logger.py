from __future__ import annotations

import logging
from logging.config import dictConfig

from app.core.config import Settings


def setup_logging(settings: Settings) -> None:
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_file = settings.log_file_path
    log_file.parent.mkdir(parents=True, exist_ok=True)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level_name,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": level_name,
                    "filename": str(log_file),
                    "maxBytes": max(1024, int(settings.log_max_bytes or 0)),
                    "backupCount": max(1, int(settings.log_backup_count or 0)),
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": level,
                "handlers": ["console", "file"],
            },
        }
    )

