import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Tolerable timeframe in seconds for heart rate (e.g., 10 seconds)
HRM_TIMEOUT = 10

class HeartRateMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self.manufacturer = None
        self.model = None
        self.serial_nr = None
        self.protocol = None
        self.address = None
        self.body_sensor_location = None
        self.skin_contact_detected = None
        self.battery_level = None
        self.heart_rate = None
        self.heart_rate_ts = None
        self.rr_intervals = None
        self.rr_intervals_ts = None
        self.energy_expended = None
        self.energy_expended_ts = None

    def update_manufacturer(self, data) -> None:
        with self._lock:
            self.manufacturer = data
        logger.debug(f"HRM manufacturer updated: {data}")

    def update_model(self, data) -> None:
        with self._lock:
            self.model = data
        logger.debug(f"HRM model updated: {data}")

    def update_serial_nr(self, data) -> None:
        with self._lock:
            self.serial_nr = data
        logger.debug(f"HRM serial_nr updated: {data}")

    def update_protocol(self, data) -> None:
        with self._lock:
            self.protocol = data
        logger.debug(f"HRM protocol updated: {data}")

    def update_address(self, data) -> None:
        with self._lock:
            self.address = data
        logger.debug(f"HRM address updated: {data}")

    def update_body_sensor_location(self, data) -> None:
        with self._lock:
            self.body_sensor_location = data
        logger.debug(f"HRM body_sensor_location updated: {data}")

    def update_skin_contact_detected(self, data) -> None:
        with self._lock:
            self.skin_contact_detected = data
        logger.debug(f"HRM skin_contact_detected updated: {data}")

    def update_battery_level(self, data) -> None:
        with self._lock:
            self.battery_level = data
        logger.debug(f"HRM battery level updated: {data}")

    def update_heart_rate(self, hr: int) -> None:
        with self._lock:
            self.heart_rate = hr
            self.heart_rate_ts = time.time()
        logger.debug(f"HRM heart rate updated: {hr} at {self.heart_rate_ts}")

    def update_rr_intervals(self, data) -> None:
        with self._lock:
            self.rr_intervals = data
            self.rr_intervals_ts = time.time()
        logger.debug(f"HRM rr_intervals updated: {data} at {self.rr_intervals_ts}")

    def update_energy_expended(self, data) -> None:
        with self._lock:
            self.energy_expended = data
            self.energy_expended_ts = time.time()
        logger.debug(f"HRM energy_expended updated: {data} at {self.energy_expended_ts}")

    def get_heart_rate(self) -> int:
        """
        Return the heart rate if a valid rate has been captured within the acceptable timeframe.
        Otherwise return 0
        """
        hr = 0
        with self._lock:
            if self.heart_rate and self.heart_rate > 0:
                if self.heart_rate_ts is not None:
                    age_seconds = time.time() - self.heart_rate_ts
                    age = f"{age_seconds:.2f}"

                    if age_seconds < HRM_TIMEOUT:
                        hr = self.heart_rate
                        logger.debug(f"Got valid heart rate: {hr} (age: {age}s)")
                    else:
                        logger.debug(f"Heart rate data is stale: age: {age}s")
                else:
                    logger.debug("Heart rate data has invalid timestamp.")
            else:
                logger.debug("No heart rate data available.")
        
        return hr

    def __repr__(self):
        """Return a string representation of the current state of heart rate data."""
        ts_str = datetime.fromtimestamp(self.heart_rate_ts).strftime('%Y-%m-%d %H:%M:%S') if self.heart_rate_ts else "N/A"

        hr = self.heart_rate if self.heart_rate is not None else "N/A"
        
        return (
            f"<HeartRateMonitor hr={hr}, ts={ts_str}>"
        )