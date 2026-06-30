import sys

from loguru import logger as _loguru_logger

_initialized = False


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
    )
    if log_file:
        _loguru_logger.add(
            log_file,
            level=level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        )


def get_logger(name: str):
    return _loguru_logger.bind(name=name)
