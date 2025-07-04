import logging

logger = logging.getLogger(__name__)

class DummyPressureController:
    def __init__(self, config=None):
        self.pressure = 0.0
        self.pressure_limit = config.get("Pressure Limit", None) if config else None
        logger.info("DummyPressureController initialized with limit %.1f bar", self.pressure_limit)

    def set_pressure(self, p=0, ch=1):
        if 0 <= p <= self.pressure_limit:
            self.pressure = p
            logger.debug("Set dummy pressure to %.2f bar on channel %d", p, ch)
        else:
            logger.warning("Attempted to set pressure out of range: %.2f", p)

    def get_pressure(self, ch=1):
        logger.debug("Read dummy pressure: %.2f bar", self.pressure)
        return self.pressure