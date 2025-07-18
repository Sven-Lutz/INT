from PySide6.QtWidgets import QApplication              # Import the QApplication class for the Qt event loop
from main_window import MainWindow                      # Import your custom MainWindow class
import sys                                              # Import sys to access command-line args and exit
import logging                                          # Import logging module for logging events
import os                                               # Import os module to work with file paths and directories


def main():
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')           # Define the path to the 'logs' directory next to this script
    os.makedirs(log_dir, exist_ok=True)                                 # Create the 'logs' directory if it doesn't already exist

    log_file = os.path.join(log_dir, 'app.log')                         # Full path to the log file

    logging.basicConfig(                                                # Set up the logging configuration
        level=logging.DEBUG,                                            # Set the logging level to DEBUG (can be changed to INFO in production)
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Define the log message format
        handlers=[
            logging.StreamHandler(sys.stdout),                          # Log messages to the console
            logging.FileHandler(log_file, mode='w')                     # Log messages to a file (overwrite each time)
        ]
    )

    logger = logging.getLogger(__name__)                                    # Create a logger instance for this module

    logger.info("Starting application...")                                  # Log the application start

    app = QApplication(sys.argv)            # Create the Qt application with command-line arguments
    window = MainWindow()                   # Instantiate your main application window
    window.show()                           # Display the main window
    exit_code = app.exec()                  # Start the Qt event loop and wait for app exit

    logger.info("Application exited with code %d", exit_code)    # Log the exit code
    sys.exit(exit_code)                                                     # Exit the script with the same exit code


if __name__ == "__main__":          # If this script is run directly (not imported)
    main()                          # Call the main function to start the application
