import logging
import requests
from typing import Any

from config import settings


class DatabaseApiLogHandler(logging.Handler):
    """Logging handler that forwards formatted log records to the database-api

    The handler performs a best-effort POST to the configured
    `settings.DATABASE_API_URL/automation/logline` endpoint and never raises.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            payload: dict[str, Any] = {
                "message": message,
                "level": record.levelname,
                "logger": record.name,
                "created_at": getattr(record, "created", None),
            }
            try:
                requests.post(
                    f"{settings.DATABASE_API_URL.rstrip('/')}/automation/logline",
                    json=payload,
                    timeout=2,
                )
            except Exception:
                # Best-effort: don't raise from the logging path
                return
        except Exception:
            # Protect logging from raising
            return
