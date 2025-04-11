import logging
import logging.config
import pathlib
import threading
import signal
import sys
from queue import Queue
from collections import deque
from src.s4 import s4_heart_beat_task
from src.s4 import s4_data_task
from src.ble_server import ble_server_task
from src.heart_rate import HeartRateMonitor
from src.ble_client import HeartRateBLEScanner

loggerconfigpath = str(pathlib.Path(__file__).parent.absolute()) +'/logging.conf'
logging.config.fileConfig(loggerconfigpath)
logger = logging.getLogger(__name__)

# List to keep track of running threads
threads = []

def start_threads():
    """Start all necessary background tasks."""
    hr_monitor = HeartRateMonitor()

    # Queues for passing data between S4 and ANT/BLE 
    q = Queue()
    ble_q = deque(maxlen=1)
    ant_q = deque(maxlen=1)

    # Thread to connect as a client to BLE heart rate monitor
    # This is an object that manages its own lifecycle with asyncio so can be started using a different
    # syntax to the other threads    
    ble_hrm_scanner = HeartRateBLEScanner(hr_monitor)
    threads.append(ble_hrm_scanner)
    
    # Thread for simulating heart beat to send to S4 
    # This construct is an explicit request to run a function in a separate thread (unlike ble_hrm_scanner).
    s4_heartbeat_thread = threading.Thread(target=s4_heart_beat_task, args=(hr_monitor,), daemon=True)
    threads.append(s4_heartbeat_thread)

    # Thread for S4 polling and collating data for transmission via BLE/ANT 
    s4_data_thread = threading.Thread(target=s4_data_task, args=(q, ble_q, ant_q, hr_monitor), daemon=True)
    threads.append(s4_data_thread)

    # Thread for advertising and connecting the RPi to external clients and sending the data
    # to connected clients 
    ble_server_thread = threading.Thread(target=ble_server_task, args=(q, ble_q), daemon=True)
    threads.append(ble_server_thread)


    for thread in threads:
        thread.start()

    # Optionally return or store monitor/scanner if needed elsewhere
    # return hr_monitor

def stop_threads(signal_received, frame):
    """Handle graceful shutdown on Ctrl+C."""
    print("\nStopping WRowFusion...")
    sys.exit(0)

if __name__ == "__main__":
    print("Starting WRowFusion...")
    
    # Handle Ctrl+C to stop gracefully
    signal.signal(signal.SIGINT, stop_threads)
    
    start_threads()
    
    # Keep main thread running
    while True:
        signal.pause()