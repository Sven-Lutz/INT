import logging
import os
import sys
from pathlib import Path


def setup_gui_logging(log_dir: str, filename: str = "app.log", level: int = logging.DEBUG) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, filename)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),
        ],
    )

logging.getLogger("matplotlib").setLevel(logging.WARNING)