import os
import sys
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .data.logger import setup_gui_logging


def main():
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    setup_gui_logging(log_dir, filename="app.log")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
