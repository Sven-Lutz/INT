import threading

pause_event = threading.Event()  # Event to signal pause and resume
stop_event = threading.Event()  # Event to signal stop
measurement_event = threading.Event()