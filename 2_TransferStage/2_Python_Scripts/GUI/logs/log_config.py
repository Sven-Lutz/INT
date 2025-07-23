# log_config.py
import logging
import os
import sys

def configure_logging():
    log_dir = os.path.join(os.getcwd(), 'logs')                                                     # get the current directory and move to logs
    os.makedirs(log_dir, exist_ok=True)                                                             # create the directory if it doesn't exist

    log_file = os.path.join(log_dir, 'app.log')

    root_logger = logging.getLogger()                                                               # get the top-level logger
    root_logger.setLevel(logging.DEBUG)                                                             # minimum logging to debug on the escalation pyramid

    if root_logger.handlers:                                                                        # avoid duplicate handlers
        return

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")           # format the logger

    console_handler = logging.StreamHandler(sys.stdout)                                             # start console logging
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, mode='w')                                          # start file logging and overwrite each time
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)                                                         # add console logging and file logging to the top-level logger
    root_logger.addHandler(file_handler)
