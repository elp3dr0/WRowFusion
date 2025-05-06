import asyncio
import threading
import logging
import time
import contextlib

from dbus_next.aio import MessageBus
from dbus_next import Message
from dbus_next.constants import MessageType

from bleak import BleakClient, BleakScanner, BleakError
from bleak.backends.device import BLEDevice
from src.heart_rate import HeartRateMonitor

logger = logging.getLogger(__name__)

# Settings for Heart Rate Monitor (HRM) discovery
RSSI_THRESHOLD = -80        # Minimum signal strength of device to be considered elibible for connection
INITIAL_SCAN_TIMEOUT = 300  # Number of seconds for which initial scan will stay alive constantly unless an eligible device is found
BONUS_SCAN_WINDOW = 15      # Additional window to discover other HRMs after the first HRM has been discovered and before a device is selected
                            # based on signal strength.
RECHECK_INTERVAL = 60       # Time between periodic scans after initial scan
RECHECK_DURATION = 30       # Duration of each periodic scan

LOW_FREQ_POLL_DELAY = 30    # Delay between polls of low frequency HRM data such as battery level 

# BLE Heart Rate Service and Characteristic UUIDs
HRM_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
HRM_BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
HRM_SENSOR_LOCATION_CHAR_UUID = "00002a38-0000-1000-8000-00805f9b34fb"
HRM_MANUFACTURER_CHAR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
HRM_MODEL_CHAR_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
HRM_SERIAL_CHAR_UUID = "00002a25-0000-1000-8000-00805f9b34fb"

CONTACT_STATUS_MEANING = {
    0b00: "Not supported",
    0b01: "Not supported",
    0b10: "No skin contact detected",
    0b11: "Skin contact detected",
}

class HeartRateBLEScanner(threading.Thread):
    def __init__(self, hr_monitor: HeartRateMonitor):
        super().__init__()
        self.hr_monitor = hr_monitor
        self.daemon = True
        self._stop_event = threading.Event()
        self.target_device = None
        self.connected = False
        self.scanning = None

    def run(self):
        asyncio.run(self.monitor_loop())

    async def monitor_loop(self):
        scan_window = INITIAL_SCAN_TIMEOUT
        # Stop any existing discovery process on the hci0 adapter to avoid
        # encountering an error when we start the new discovery process
        self.stop_ble_discovery
        while not self._stop_event.is_set():
            try:
                await self.scan_for_hrm(scan_window)
                if self.target_device:
                    try:
                        # Try to connect, and then block until disconnected
                        await self.connect_and_monitor(self.target_device)
                    except Exception as e:
                        logger.error(f"BLE scanner connection error: {e}")
                    self.connected = False
                    self.target_device = None

            except Exception as e:
                logger.error(f"HeartRateBLEScanner Monitor loop error: {e}. Retrying in {RECHECK_INTERVAL} seconds.")

            scan_window = RECHECK_DURATION
            await asyncio.sleep(RECHECK_INTERVAL)

    async def scan_for_hrm(self, timeout) -> BLEDevice | None:
        logger.info("Starting device discovery scan for BLE Heart Rate Monitor...")
        self.scanning = True
        devices: dict[str, BLEDevice] = {}
        rssi_map: dict[str, int] = {}

        async with BleakScanner() as scanner:
            start_time = time.time()
            found_good_device = False
            bonus_window_start = None

            adv_iterator = scanner.advertisement_data()

            while self.scanning:
                
                now = time.time()
                if now - start_time > timeout:
                    logger.debug("BLE HRM discovery scan timeout reached.")
                    self.scanning = False
                    break
                if bonus_window_start and (now -bonus_window_start > BONUS_SCAN_WINDOW):
                    logger.debug("BLE HRM disovery scan bonus window expired.")
                    self.scanning = False
                    break

                if self._stop_event.is_set():
                    self.scanning = False
                    break

                # Ask for the next item from the iterator, but give it a timelimit
                # to return the item, afterwhich move on even if a new device hasn't been found.
                # This it to prevent the code from hanging here if no additional 
                # devices ever appear. 
                try:
                    d, adv = await asyncio.wait_for(adv_iterator.__anext__(), timeout=1.0)
                except (TimeoutError, StopAsyncIteration):
                    continue  # No new device seen in this window so go back to the top of the while loop


                if not self._is_heart_rate_monitor(adv):
                    logger.debug(f"BLE scan found device {d.address} is not a HRM.")
                    # Ignore this device and go back to the top of the while loop
                    continue

                if d.rssi < RSSI_THRESHOLD:
                    logger.debug(f"BLE scan ignoring HRM {d.address} because signal strength {d.rssi} dB < {RSSI_THRESHOLD} dB threshold.")
                    # Ignore this device and go back to the top of the while loop
                    continue

                devices[d.address] = d
                rssi_map[d.address] = d.rssi
                logger.debug(f"BLE Scanner found HRM device: {d.address} ({d.rssi} dB)")

                if not found_good_device:
                    logger.info(f"Found a BLE HRM, extending search for {BONUS_SCAN_WINDOW} seconds in case there are other HRM devices.")
                    bonus_window_start = time.time()
                    found_good_device = True
        
        if not devices:
            logger.info(f"No BLE Heart Rate Monitor found during scan window.")
            return None

        # Pick device with strongest RSSI
        best_address = max(rssi_map, key=rssi_map.get)
        best_rssi = rssi_map[best_address]
        logger.info(f"HRM with the strongest signal selected: ({best_rssi}db): {best_address}")
        self.target_device = devices[best_address]


    def _is_heart_rate_monitor(self, adv) -> bool:
        # Heart Rate Service UUID is 0x180D (16-bit), represented as 0000180d-0000-1000-8000-00805f9b34fb
        return HRM_SERVICE_UUID.lower() in [uuid.lower() for uuid in adv.service_uuids]
    

    async def connect_and_monitor(self, device):
        logger.info(f"Connecting as client to ble device: {device.name} [{device.address}]...")
        try:
            async with BleakClient(device.address) as client:
                if not await client.is_connected():
                    logger.warning("Failed to connect to BLE HRM.")
                    return
                
                self.connected = True
                self.hr_monitor.update_address(device.address)
                self.hr_monitor.update_source("bluetooth")

                logger.info("Connected to BLE HRM. Logging GATT services and characteristics...")
                await self.log_services_and_characteristics(client)

                logger.info("Connected to BLE HRM. Fetching static BLE data...")
                await self.fetch_static_info(client)

                logger.info("Subscribing to heart rate notifications from BLE HRM...")
                await client.start_notify(HRM_MEASUREMENT_CHAR_UUID, self.handle_heart_rate)

                # Start low-frequency polling as a background task
                low_freq_task = asyncio.create_task(self.poll_low_frequency_data(client))

                try:
                    while await client.is_connected():
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass
                finally:
                    # Cleanly cancel the low-frequency polling task (HRM is handled by a notify so doesn't need to be cxld)
                    low_freq_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await low_freq_task

                self.connected = False
                logger.warning("Disconnected from HRM.")

        except BleakError as e:
            logger.warning(f"BLE client connection failed: {e}")
        except asyncio.TimeoutError:
            logger.warning("BLE connection attempt timed out.")
        except asyncio.CancelledError:
            logger.warning("BLE connection task was cancelled.")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during BLE HRM connection: {e}")
            

    async def log_services_and_characteristics(self, client):
        if not client or not client.is_connected:
            logger.warning("Cannot log services — HRM not connected.")
            return

        try:
            services = await client.get_services()
            if services:
                logger.debug(f"Connected BLE HRM supports:")
            for service in services:
                logger.debug(f" Service: {service.uuid} — {service.description}")
                for char in service.characteristics:
                    logger.debug(f"  Characteristic: {char.uuid} — {char.description}")
        except Exception as e:
            logger.warning(f"Failed to log GATT services: {e}")


    async def fetch_static_info(self, client: BleakClient):
        try:
            manufacturer = await client.read_gatt_char(HRM_MANUFACTURER_CHAR_UUID)
            manufacturer_str = manufacturer.decode('utf-8').strip()
            self.hr_monitor.update_manufacturer(manufacturer_str)
            logger.info(f"Manufacturer: {manufacturer_str}")
        except Exception as e:
            logger.warning(f"BLE HRM: Failed to read manufacturer: {e}")

        try:
            model = await client.read_gatt_char(HRM_MODEL_CHAR_UUID)
            model_str = model.decode('utf-8').strip()
            self.hr_monitor.update_model(model_str)
            logger.info(f"Model Number: {model_str}")
        except Exception as e:
            logger.warning(f"BLE HRM: Failed to read model number: {e}")

        try:
            serial_number = await client.read_gatt_char(HRM_SERIAL_CHAR_UUID)
            serial_str = serial_number.decode('utf-8').strip()
            self.hr_monitor.update_serial_nr(serial_str)
            logger.info(f"Serial Number: {serial_str}")
        except Exception as e:
            logger.warning(f"BLE HRM: Failed to read serial number: {e}")

        try:
            # Read sensor location 
            sensor_location = await client.read_gatt_char(HRM_SENSOR_LOCATION_CHAR_UUID)
            location_code = int(sensor_location[0])
            location_lookup = {
                0: "Other",
                1: "Chest",
                2: "Wrist",
                3: "Finger",
                4: "Hand",
                5: "Ear Lobe",
                6: "Foot"
            }
            logger.info(f"Sensor location: {location_lookup.get(location_code, 'Unknown')}")

        except Exception as e:
            logger.warning(f"BLE HRM: Failed to read sensor location data: {e}")


    async def poll_low_frequency_data(self, client: BleakClient):
        while await client.is_connected():
            try:
                # Battery level
                battery = await client.read_gatt_char(HRM_BATTERY_LEVEL_CHAR_UUID)
                battery_pct = int(battery[0])
                logger.debug(f"[Low-Freq Poll] HRM battery level: {battery_pct}%")
            except Exception as e:
                logger.warning(f"[Low-Freq Poll] HRM battery poll failed: {e}")

            await asyncio.sleep(LOW_FREQ_POLL_DELAY)


    def handle_heart_rate(self, sender, data: bytearray):
        """
        Handle incoming heart rate data, including optional parameters like RR intervals
        and energy expenditure.
        """
        try:
        
            # Note that the value of the flags can change from one notification to the next:
            # i.e., whether the contact is detected, whether RR intervals are included, etc.
            # — can change from one notification to the next, depending on what the device is reporting.
            flags = data[0]
            hr_format_16bit = flags & 0x01
            energy_exp_present = flags & 0x08
            rr_present = flags & 0x10
            contact_status = (flags >> 1) & 0b11

            index = 1

            # Heart rate value
            if hr_format_16bit:
                hr_value = int.from_bytes(data[index:index + 2], byteorder="little")
                index += 2
            else:
                hr_value = data[index]
                index += 1
        
            # Record the heart rate in the HeartRateMonitor class
            self.hr_monitor.update_heart_rate(hr_value)
            logger.debug(f"Heart rate received: {hr_value} bpm")
            
            contact_status_str = CONTACT_STATUS_MEANING.get(contact_status)
            self.hr_monitor.update_skin_contact_detected(contact_status_str)
            logger.debug(f"HRM sensor skin contact: {contact_status_str}")
            
            # Energy expenditure (2 bytes)
            # If supported, typically sent once every 10 measurements at regular intervals 
            energy_exp = None
            if energy_exp_present:
                if index + 2 <= len(data):
                    energy_exp = int.from_bytes(data[index:index + 2], byteorder="little")
                    index += 2
                    self.hr_monitor.update_energy_expended(energy_exp)
                    logger.debug(f"Energy expenditure: {energy_exp} kcal")
                else:
                    logger.warning("Energy expenditure flag set but data is too short.")

            # RR-Intervals (each is 2 bytes)
            # RR Intervals are recorded at a higher frequncy than heart beat, so mulitple
            # readings (up to a max of 9) are passed in each payload.  
            rr_intervals = []
            if rr_present:
                while index + 1 < len(data):
                    rr = int.from_bytes(data[index:index + 2], byteorder="little")
                    rr_intervals.append(rr)
                    index += 2
                self.hr_monitor.update_rr_intervals(rr_intervals)
                logger.debug(f"RR Intervals: {rr_intervals}")

        except Exception as e:
            logger.warning(f"Failed to handle heart rate data: {e}")


    def stop(self):
        logger.debug("Stopping BLE Heart Rate Monitor Scanner")
        self._stop_event.set()
        self.scanning = False
        self.stop_ble_discovery


    async def stop_ble_discovery():
        bus = await MessageBus(system=True).connect()

        introspect = await bus.introspect('org.bluez', '/org/bluez/hci0')
        obj = bus.get_proxy_object('org.bluez', '/org/bluez/hci0', introspect)
        adapter = obj.get_interface('org.bluez.Adapter1')

        try:
            await adapter.call_stop_discovery()
        except Exception as e:
            if "org.bluez.Error.NotReady" in str(e) or "org.bluez.Error.Failed" in str(e):
                pass  # Likely already stopped or inactive adapter
            else:
                raise
