from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from config import create_required_directories, validate_configuration
from gui.main_window import ProcessControlWindow


__all__ = ["ProcessControlWindow", "main"]


def main() -> int:
    application = QApplication(sys.argv)

    try:
        validate_configuration()
        create_required_directories()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Process Control",
            "The configuration is not usable:\n\n"
            f"{type(exc).__name__}: {exc}",
        )
        return 1

    # Imported late so a configuration problem is reported in the GUI
    # rather than as an import error on the console.
    from main import build_controller

    window = ProcessControlWindow(
        controller_factory=build_controller
    )
    window.show()

    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
