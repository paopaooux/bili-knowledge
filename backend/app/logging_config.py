from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Settings

LOG_FILE_NAME = "backend.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5


class HealthCheckFilter(logging.Filter):
    """Drop frequent health probes while preserving useful API access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/health" not in record.getMessage()


def configure_runtime_logging(settings: Settings) -> None:
    log_directory = settings.data_dir / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / LOG_FILE_NAME

    error_logger = logging.getLogger("uvicorn.error")
    for handler in list(error_logger.handlers):
        if getattr(handler, "_bili_knowledge_file_handler", False):
            if getattr(handler, "baseFilename", None) == str(log_path.resolve()):
                break
            error_logger.removeHandler(handler)
            handler.close()
    else:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler._bili_knowledge_file_handler = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        error_logger.addHandler(handler)
    error_logger.setLevel(logging.INFO)

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, HealthCheckFilter) for item in access_logger.filters):
        access_logger.addFilter(HealthCheckFilter())
