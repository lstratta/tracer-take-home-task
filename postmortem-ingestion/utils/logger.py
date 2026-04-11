import logging

import structlog


def configure_logging() -> None:
    """Configure structlog to output structured JSON logs to stdout.

    Every log entry includes: timestamp, log level, component name.
    When processing a specific record, callers should bind record_id to
    the logger so all log lines for that record can be grepped together.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
    )


def get_logger(component: str):
    """Return a bound structlog logger for the given component name.

    Usage:
        log = get_logger('markdown_parser')
        log.info('Parsing complete', records=42)
        log.bind(record_id='abc123').warning('Low confidence', confidence=0.1)
    """
    return structlog.get_logger(component=component)
