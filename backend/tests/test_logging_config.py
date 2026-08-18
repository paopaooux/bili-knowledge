import logging

from app.logging_config import HealthCheckFilter, configure_runtime_logging


def test_runtime_logging_writes_backend_log(settings):
    configure_runtime_logging(settings)
    logger = logging.getLogger("uvicorn.error")
    logger.info("job-log-test")
    for handler in logger.handlers:
        handler.flush()

    assert "job-log-test" in (settings.data_dir / "logs" / "backend.log").read_text(
        encoding="utf-8"
    )


def test_health_check_filter_only_drops_health_requests():
    filter_ = HealthCheckFilter()
    health = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, 'GET /api/health HTTP/1.1', (), None
    )
    jobs = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "GET /api/jobs HTTP/1.1", (), None
    )

    assert filter_.filter(health) is False
    assert filter_.filter(jobs) is True
