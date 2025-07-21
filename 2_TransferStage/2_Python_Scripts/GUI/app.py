from PySide6.QtWidgets import QApplication
from main_window import MainWindow
import sys
import logging
from logs.log_config import configure_logging

def main():
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting application...")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec()

    logger.info("Application exited with code %d", exit_code)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
