import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_gui_logging(log_dir: str, filename: str = "app.log", level: int = logging.DEBUG) -> None:
    """Configure root logger with a rotating file handler and a stdout stream handler.

    The rotating handler keeps up to 5 × 10 MB backup files so previous sessions
    survive across restarts (replaces the old mode="w" truncating handler).
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, filename)

    rotating = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            rotating,
        ],
    )


def start_run_log(log_dir: str, level: int = logging.DEBUG) -> logging.Handler:
    """Attach a timestamped per-run log file to the root logger.

    Returns the handler so the caller can remove it when the run ends.
    The file is written to <log_dir>/runs/YYYYMMDD_HHMMSS.log.
    """
    run_dir = os.path.join(log_dir, "runs")
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log = os.path.join(run_dir, f"{stamp}.log")

    handler = logging.FileHandler(run_log, mode="w", encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
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
