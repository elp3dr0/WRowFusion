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
        self._bluetooth_hr = 0
        self._bluetooth_ts = 0
        self._ant_hr = 0
        self._ant_ts = 0

    def update_bluetooth_hr(self, hr: int) -> None:
        with self._lock:
            self._bluetooth_hr = hr
            self._bluetooth_ts = time.time()
        logger.debug(f"Bluetooth HR updated: {hr} at {self._bluetooth_ts}")

    def update_ant_hr(self, hr: int) -> None:
        with self._lock:
            self._ant_hr = hr
            self._ant_ts = time.time()
        logger.debug(f"ANT+ HR updated: {hr} at {self._ant_ts}")

    def get_heart_rate(self) -> int:
        """Return the most recently updated and still-valid heart rate."""
        now = time.time()
        
        with self._lock:
            bt_age = f"{now - self._bluetooth_ts:.2f}" if self._bluetooth_ts else "N/A"
            bt_hr = self._bluetooth_hr
            bt_valid = now - self._bluetooth_ts < HRM_TIMEOUT and bt_hr > 0

            ant_age = f"{now - self._ant_ts:.2f}" if self._ant_ts else "N/A"
            ant_hr = self._ant_hr 
            ant_valid = now - self._ant_ts < HRM_TIMEOUT and ant_hr > 0

            if bt_valid and (not ant_valid or self._bluetooth_ts >= self._ant_ts):
                hr = bt_hr
            elif ant_valid:
                hr = ant_hr
            else:
                hr = 0  # No valid source

        if bt_valid:
            logger.debug(f"Bluetooth HR is valid: {bt_hr} (age: {bt_age}s)")
        else:
            logger.debug(f"Bluetooth HR is invalid or stale (age: {bt_age}s)")

        if ant_valid:
            logger.debug(f"ANT+ HR is valid: {ant_hr} (age: {ant_age}s)")
        else:
            logger.debug(f"ANT+ HR is invalid or stale (age: {ant_age}s)")

        if hr == 0:
            logger.debug("No valid heart rate data available.")

        return hr

    def __repr__(self):
        """Return a string representation of the current state of heart rate data."""
        bt_time = datetime.fromtimestamp(self._bluetooth_ts).strftime('%Y-%m-%d %H:%M:%S') if self._bluetooth_ts else "N/A"
        ant_time = datetime.fromtimestamp(self._ant_ts).strftime('%Y-%m-%d %H:%M:%S') if self._ant_ts else "N/A"

        return (
            f"<HeartRateMonitor bt_hr={self._bluetooth_hr}, bt_ts={bt_time}, "
            f"ant_hr={self._ant_hr}, ant_ts={ant_time}>"
        )