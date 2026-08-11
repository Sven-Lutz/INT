from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class _LogEmitter(QObject):
    record_received = Signal(str, str, str)


class QtLogHandler(logging.Handler):
    """Forwards standard Python log records into the Qt event loop."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.emitter = _LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.record_received.emit(
                record.levelname,
                record.name,
                record.getMessage(),
            )
        except Exception:
            self.handleError(record)


def configure_runtime_logging(
    log_path: Path,
) -> tuple[logging.Logger, QtLogHandler]:
    """Configure the ``aqua`` logger for console, file, and GUI output."""

    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("aqua")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Reconfiguration is useful during interactive development/restarts.
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
    )

    qt_handler = QtLogHandler()
    qt_handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.addHandler(qt_handler)

    logger.debug("Runtime logging configured: %s", log_path)
    return logger, qt_handler
