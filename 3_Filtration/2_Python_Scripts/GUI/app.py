from PySide6.QtWidgets import QApplication
from main_window import MainWindow
import sys
import logging

def main():
    # Setup global logging
    logging.basicConfig(
        level=logging.DEBUG,  # Use logging.INFO or logging.WARNING in production
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),  # Print to console
            # Uncomment this to also log to a file:
            # logging.FileHandler("app.log", mode='w')
        ]
    )

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
