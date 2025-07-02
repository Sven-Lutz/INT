from PySide6.QtWidgets import QApplication
from main_window import MainWindow
import sys
import logging
import os

def main():
    # Setup global logging
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)  # Create logs/ if it doesn't exist

    log_file = os.path.join(log_dir, 'app.log')
    logging.basicConfig(
        level=logging.DEBUG,  # Use logging.INFO or logging.WARNING in production
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),  # Print to console
            # Uncomment this to also log to a file:
            logging.FileHandler(log_file, mode='w')
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
