import logging
import os
import sys
import time

from hardware.device_manager import DeviceManager

logger = logging.getLogger(__name__)

def main():
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)  # Create logs/ if it doesn't exist
    log_file = os.path.join(log_dir, 'test_dvm.log')
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
    dvm = DeviceManager()
    dvm.valves_filtration()
    dvm.set_pressure(pressure=25, channel=1)
    #time.sleep(1)
    #dvm.get_pressure(channel=1)
if __name__ == "__main__":
    main()