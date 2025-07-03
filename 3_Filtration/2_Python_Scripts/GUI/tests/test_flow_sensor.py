import propar
import time


# Replace with your actual serial port (e.g., "COM3" on Windows or "/dev/ttyUSB0" on Linux)
PORT = "COM5"

flow = propar.instrument(PORT)

print(flow.id)


