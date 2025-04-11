import asyncio
import threading
import logging
import contextlib

from bleak import BleakClient, BleakScanner, BleakError
from src.heart_rate import HeartRateMonitor

logger = logging.getLogger(__name__)

# BLE Heart Rate Service and Characteristic UUIDs
HRM_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HRM_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
HRM_BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
HRM_SENSOR_LOCATION_CHAR_UUID = "00002a38-0000-1000-8000-00805f9b34fb"
HRM_MANUFACTURER_CHAR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
HRM_MODEL_CHAR_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
HRM_SERIAL_CHAR_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
LOW_FREQ_POLL_DELAY = 30
RECONNECT_DELAY = 10
RESCAN_DELAY = 30

class HeartRateBLEScanner(threading.Thread):
    def __init__(self, hr_monitor: HeartRateMonitor):
        super().__init__()
        self.hr_monitor = hr_monitor
        self.daemon = True
        self._stop_event = threading.Event()

    def run(self):
        asyncio.run(self.monitor_loop())

    async def monitor_loop(self):
        while not self._stop_event.is_set():
            try:
                logger.info("Scanning for BLE heart rate monitors (HRMs)...")
                device = await self.scan_for_hrm()
                if device:
                    await self.connect_and_monitor(device)
                else:
                    logger.info("No BLE HRM found. Retrying in 30 seconds.")
                    await asyncio.sleep(RESCAN_DELAY)
            except Exception as e:
                logger.warning(f"HeartRateBLEScanner Monitor loop error: {e}")
                await asyncio.sleep(10)

    async def scan_for_hrm(self):
        devices = await BleakScanner.discover(timeout=5.0)
        for d in devices:
            if HRM_SERVICE_UUID.lower() in [uuid.lower() for uuid in d.advertisement_data.service_uuids]:
                logger.info(f"Found HRM: {d.name} [{d.address}]")
                return d
        return None

    async def connect_and_monitor(self, device):
        logger.info(f"Connecting as client to {device.name} [{device.address}]...")
        try:
            async with BleakClient(device.address) as client:
                if not await client.is_connected():
                    logger.warning("Failed to connect to BLE HRM.")
                    return
                
                logger.info("Connected to BLE HRM. Logging GATT services and characteristics...")
                await self.log_services_and_characteristics(client)

                logger.info("Connected to BLE HRM. Fetching static BLE data...")
                await self.fetch_static_info(client)

                logger.info("Subscribing to heart rate notifications...")
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

                logger.warning("Disconnected from HRM.")

        except BleakError as e:
            logger.warning(f"BLE client connection failed: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error during BLE HRM connection: {e}")

        logger.info("Reconnecting to BLE HRM in 10 seconds...")
        await asyncio.sleep(RECONNECT_DELAY)

    async def fetch_static_info(self, client: BleakClient):
        try:
            manufacturer = await client.read_gatt_char(HRM_MANUFACTURER_CHAR_UUID)
            logger.info(f"Manufacturer: {manufacturer.decode('utf-8').strip()}")
        except Exception as e:
            logger.warning(f"BLE HRM: Failed to read manufacturer: {e}")

        try:
            model_number = await client.read_gatt_char()
            logger.info(f"Model Number: {model_number.decode('utf-8').strip(HRM_MODEL_CHAR_UUID)}")
        except Exception as e:
            logger.warning(f"BLE HRM: Failed to read model number: {e}")

        try:
            serial_number = await client.read_gatt_char()
            logger.info(f"Serial Number: {serial_number.decode('utf-8').strip()}")
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
                logger.info(f"[Low-Freq] Battery level: {battery_pct}%")
            except Exception as e:
                logger.warning(f"[Low-Freq] Battery poll failed: {e}")

            try:
                # Sensor contact status (parse flags from HR measurement characteristic)
                raw = await client.read_gatt_char(HRM_MEASUREMENT_CHAR_UUID)
                flags = raw[0]
                contact_status = (flags >> 1) & 0b11

                contact_status_meaning = {
                    0b00: "Not supported",
                    0b01: "Not supported",
                    0b10: "No skin contact detected",
                    0b11: "Skin contact detected",
                }
                logger.info(f"[Low-Freq] HRM sensor skin contact: {contact_status_meaning.get(contact_status)}")

            except Exception as e:
                logger.warning(f"[Low-Freq] Sensor contact poll failed: {e}")

            await asyncio.sleep(LOW_FREQ_POLL_DELAY)

    async def log_services_and_characteristics(self, client):
        if not client or not client.is_connected:
            logger.warning("Cannot log services — HRM not connected.")
            return

        try:
            services = await client.get_services()
            for service in services:
                logger.debug(f"Service: {service.uuid} — {service.description}")
                for char in service.characteristics:
                    logger.debug(f"  Characteristic: {char.uuid} — {char.description}")
        except Exception as e:
            logger.warning(f"Failed to log GATT services: {e}")

    def handle_heart_rate(self, sender, data: bytearray):
        """
        Handle incoming heart rate data, including optional parameters like RR intervals
        and energy expenditure.
        """
        try:
        
            flags = data[0]
            hr_format_16bit = flags & 0x01
            energy_exp_present = flags & 0x08
            rr_present = flags & 0x10

            index = 1

            # Heart rate value
            if hr_format_16bit:
                hr_value = int.from_bytes(data[index:index + 2], byteorder="little")
                index += 2
            else:
                hr_value = data[index]
                index += 1
        
            # Record the heart rate in the HeartRateMonitor class
            self.hr_monitor.update_bluetooth_hr(hr_value)
            logger.debug(f"Heart rate received: {hr_value} bpm")

            # TODO: Consider adding the following data to the HeartRateMonitor class or recording it as data somewhere rather
            # than just logging it.
            
            # Energy expenditure (2 bytes)
            energy_exp = None
            if energy_exp_present:
                if index + 2 <= len(data):
                    energy_exp = int.from_bytes(data[index:index + 2], byteorder="little")
                    index += 2
                    logger.debug(f"Energy expenditure: {energy_exp} kcal")
                else:
                    logger.warning("Energy expenditure flag set but data is too short.")

            # RR-Intervals (each is 2 bytes)
            rr_intervals = []
            if rr_present:
                while index + 1 < len(data):
                    rr = int.from_bytes(data[index:index + 2], byteorder="little")
                    rr_intervals.append(rr)
                    index += 2
                logger.debug(f"RR Intervals: {rr_intervals}")

        except Exception as e:
            logger.warning(f"Failed to handle heart rate data: {e}")


    def stop(self):
        self._stop_event.set()
