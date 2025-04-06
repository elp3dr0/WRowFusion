import threading
from gpiozero import DigitalOutputDevice
from time import sleep
from src.heart_rate import HeartRateMonitor

# Define GPIO pin
HEARTBEAT_PIN = 18
heartbeat_signal = DigitalOutputDevice(HEARTBEAT_PIN, active_high=True, initial_value=False)


def s4_heart_beat_task(hrm: HeartRateMonitor):
    """Simulate continuous ANT+ heart rate signal."""
    while True:
        hr = hrm.get_heart_rate

        if hr > 0:
            hr_period = 60000 / hr  # Convert BPM to ms

            # Generate a 10ms pulse
            heartbeat_signal.on()
            sleep(0.01)  # 10ms pulse
            heartbeat_signal.off()

            # Wait for the rest of the heartbeat interval
            sleep((hr_period - 10) / 1000.0)
        else:
            # If no valid HR data, keep the signal off and wait 500ms
            heartbeat_signal.off()
            sleep(0.5)