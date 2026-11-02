import logging
from logging.config import dictConfig


def configure_logging(level: str = "INFO") -> None:
    """Configure concise logs that avoid including uploaded file contents."""

    normalized_level = level.upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": normalized_level,
                }
            },
            "root": {"handlers": ["console"], "level": normalized_level},
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
