import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _ShortNameFormatter(logging.Formatter):
    """Show only the last two dotted segments of the module name."""

    def format(self, record: logging.LogRecord) -> str:
        parts = record.name.split(".")
        record.shortname = ".".join(parts[-2:]) if len(parts) >= 2 else record.name
        return super().format(record)


_CONSOLE_FMT = "%(asctime)s  %(levelname)-8s  %(shortname)-26s  %(message)s"
_FILE_FMT = "%(asctime)s  %(levelname)-8s  %(name)-40s  %(message)s"
_DATE_FMT = "%H:%M:%S"


def setup_gui_logging(log_dir: str, filename: str = "app.log", level: int = logging.DEBUG) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, filename)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(_ShortNameFormatter(_CONSOLE_FMT, datefmt=_DATE_FMT))

    rotating = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    rotating.setLevel(logging.DEBUG)
    rotating.setFormatter(logging.Formatter(_FILE_FMT, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(rotating)


def start_run_log(log_dir: str, level: int = logging.DEBUG) -> logging.Handler:
    """Attach a timestamped per-run log file to the root logger."""
    run_dir = os.path.join(log_dir, "runs")
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log = os.path.join(run_dir, f"{stamp}.log")

    handler = logging.FileHandler(run_log, mode="w", encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FILE_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(handler)
    logging.getLogger(__name__).info("Run log started: %s", run_log)
    return handler


def stop_run_log(handler: logging.Handler) -> None:
    """Detach and close the per-run log handler returned by start_run_log()."""
    try:
        logging.getLogger().removeHandler(handler)
        handler.close()
    except Exception:
        pass


logging.getLogger("matplotlib").setLevel(logging.WARNING)
