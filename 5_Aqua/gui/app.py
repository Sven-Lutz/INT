from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import ProcessControlWindow


__all__ = ["ProcessControlWindow", "main"]


def main() -> int:
    application = QApplication(sys.argv)
    window = ProcessControlWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
