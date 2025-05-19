# ---------------------------------------------------------------------------
# Based on the inonoob repo "pirowflo"
# https://github.com/inonoob/pirowflo
# Which in turn was based on the PunchThrough Repo espresso-ble
# https://github.com/PunchThrough/espresso-ble
# Extensively refactored and expanded for WRowFusion
# ---------------------------------------------------------------------------

import logging
from queue import Empty
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import dbus                     # pyright: ignore[reportMissingImports]
    import dbus.exceptions          # pyright: ignore[reportMissingImports]
    import dbus.mainloop.glib       # pyright: ignore[reportMissingImports]
    import dbus.service             # pyright: ignore[reportMissingImports]
    from gi.repository import GLib  # pyright: ignore[reportMissingImports]
    import gobject as GObject       # pyright: ignore[reportMissingImports]
else:
    import dbus
    import dbus.exceptions
    import dbus.mainloop.glib
    import dbus.service


import struct
import time
from typing import Callable

from src.bleif import (
    Advertisement,
    Characteristic,
    Service,
    Application,
    find_adapter,
    Descriptor,
    Agent,
)

from src.ble_standard_services import (
    DeviceInformation, 
    FTMService, 
    FitnessMachineControlPoint,
    FitnessMachineFeature,
    HeartRateService,
    HeartRateMeasurementCharacteristic,
    RowerData, 
)

from src.heart_rate import HeartRateMonitor
from src.s4 import RowerState

logger = logging.getLogger(__name__)


DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE = "org.bluez.GattDescriptor1"

LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
AGENT_PATH = "/com/wrowfusion/agent"

MainLoop: type | None = None

try:
    from gi.repository import GLib  # pyright: ignore[reportMissingImports]

    MainLoop = GLib.MainLoop

except ImportError:
    import gobject as GObject       # pyright: ignore[reportMissingImports]

    MainLoop = GObject.MainLoop

mainloop: GLib.MainLoop | GObject.MainLoop | None = None

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"


class InvalidValueLengthException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidValueLength"


class FailedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.Failed"


###########################
## GATT helper functions ##
###########################

def register_app_cb():
    logger.info("GATT application registered.")


def register_app_error_cb(error):
    logger.critical("Failed to register GATT application: " + str(error))
    if mainloop:
        mainloop.quit()


def register_ad_cb():
    logger.info("GATT advertisement registered.")


def register_ad_error_cb(error):
    logger.critical("Failed to register GATT advertisement: " + str(error))
    if mainloop:
        mainloop.quit()


###########################################
## FTM Service helper functions & config ##
###########################################

def fmcp_request_control_handler(payload: list[dbus.Byte], rower_state: RowerState) -> int:
    logger.debug(f"Started control handler")
    return 0x01  # Success

def fmcp_reset_handler(payload: list[dbus.Byte], rower_state: RowerState) -> int:
    logger.debug("started reset rower handler")
    rower_state.reset_rower()
    return 0x01  # Success

# Create an enclosure to give the command handlers access to the RowerState without having to modify the generic
# Fitness Machine Control Point class.
def make_fmcp_command_handler(rower_state: RowerState) -> Callable[[FitnessMachineControlPoint.FTMControlOpCode, list[int]], int]:
    def fmcp_command_handler(opcode: FitnessMachineControlPoint.FTMControlOpCode, payload: list[int]) -> int:
        logger.debug(f"Started commnand handler")
        handler = FTM_SUPPORTED_OPCODES.get(opcode)
        if handler:
            return handler(payload, rower_state)
        logger.warning(f"Recieved valid but unsupported OpCode: {opcode}")
        return 0x02  # Op code not supported
    return fmcp_command_handler


# Specify which Fitness Machine Control Point OpCodes our application supports, 
# and specify which function should be called in each case.
FTM_SUPPORTED_OPCODES = {
    FitnessMachineControlPoint.FTMControlOpCode.FTMC_REQUEST_CONTROL: fmcp_request_control_handler,
    FitnessMachineControlPoint.FTMControlOpCode.FTMC_RESET: fmcp_reset_handler,
}

# Specify which Fitness Machine Features our application supports
FTM_SUPPORTED_FEATURES = (
    FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_CADENCE_SUPPORTED
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_TOTAL_DISTANCE_SUPPORTED 
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_PACE_SUPPORTED 
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_EXPENDED_ENERGY_SUPPORTED 
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_HEART_RATE_MEASUREMENT_SUPPORTED 
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_ELAPSED_TIME_SUPPORTED 
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_POWER_MEASUREMENT_SUPPORTED
    | FitnessMachineFeature.FitnessMachineFeatureFlags.FTMF_REMAINING_TIME_SUPPORTED
)

TransformMap = dict[str, Callable[[dict], int | None]]

BLE_FIELD_MAP: TransformMap = {
    "stroke_rate": lambda wr_values: wr_values.get("stroke_rate_pm", 0) * 2,   # BLE specifies units as 0.5 strokes per min.
    "stroke_count": lambda wr_values: wr_values.get("stroke_count", 0),
    "total_distance": lambda wr_values: wr_values.get("total_distance", 0),
    "instant_pace": lambda wr_values: wr_values.get("instant_500m_pace", 0),
    "instant_power": lambda wr_values: wr_values.get("instant_watts", 0),
    "elapsed_time": lambda wr_values: wr_values.get("elapsed_time", 0),
    "total_energy": lambda wr_values: int(wr_values.get("total_calories", 0) / 1000),
    "energy_per_hour": lambda wr_values: int(3.6 * wr_values.get("total_calories", 0) / wr_values["elapsed_time"]) if wr_values.get("elapsed_time") else 0,
    "energy_per_min": lambda wr_values: int(0.06 * wr_values.get("total_calories", 0) / wr_values["elapsed_time"]) if wr_values.get("elapsed_time") else 0,
    "heart_rate": lambda wr_values: wr_values.get("heart_rate", 0),
    #"remaining_time",
    #"metabolic_equivalent",
    #"resistance",
    "avg_stroke_rate": lambda wr_values: int(60 * wr_values.get("stroke_count", 0) / wr_values["elapsed_time"]) if wr_values.get("elapsed_time") else 0,
    "avg_pace": lambda wr_values: int(500 * wr_values.get("elapsed_time", 0) / wr_values["total_distance"]) if wr_values.get("total_distance") else 0,
    #"avg_power": lambda wr_values: int(60 * wr_values.get("total_watts")/wr_values.get("elapsed_time")),   # WR does not support total power applied, only an instantaneous power. Bluetooth spec requires the average power since the beginning of the training session.
}

class AppRowerData(RowerData):
    def __init__(self, bus, index, service, rower_state: RowerState, hr_monitor: HeartRateMonitor):
        super().__init__(bus, index, service)
        self.last_payload = None
        self.rower_state = rower_state
        self.hr_monitor = hr_monitor

    def rowerdata_cb(self):
        logger.debug("Running AppRowerData.rowerdata_cb")
        if not self.rower_state.is_initialised:
            logger.debug("No WaterRower values available yet.")
            return self.notifying
        
        wr_values = self.rower_state.get_WRValues()
        if not wr_values:
            logger.warning("No WaterRower values available yet.")
            return self.notifying
        
        logger.debug(f"Got values: {wr_values}")
        wr_values = inject_heart_rate(wr_values, self.hr_monitor)
        ble_rower_data = {
            ble_key: int(func(wr_values) or 0) 
            for ble_key, func in BLE_FIELD_MAP.items()
        }
        logger.debug(f"Mapped rower values to ble fields: {ble_rower_data}")
        payload_bytes = self.encode(ble_rower_data)
        logger.debug(f"Generated payload: {payload_bytes}")
        if self.last_payload != payload_bytes:
            logger.debug("Changed values in payload, so starting transmission")
            self.last_payload = payload_bytes
            value = [dbus.Byte(b) for b in payload_bytes]
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])

        logger.debug("Exiting rowerdata_cb")
        return self.notifying

    def _update(self):
        logger.debug("Entering AppRowerData _update to schedule rowerdata_cb")
        GLib.timeout_add(200, self.rowerdata_cb)
            
###### todo: function needed to get all the date from waterrower
# 20 byte is max data send
# example : 0x 2C-0B-00-00-00-00-FF-FF-00-00-00-00-00-00-00-00-00-00-00-00
# first 2 bytes: are for rowing machine details: 0B


class FTMPAdvertisement(Advertisement):
    '''
    Wrapper around the generic Advertisement class which will be used to configure
    the Fitness Machine Profile Advertisement as appropriate for this application.
    '''
    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, "peripheral")
        # Set Company Identifier code as FFFF, which is defined by Bluetooth SIG as a reserved/testID 
        # often used for development or internal testing. The [0x77, 0x72] bytes are 'wr' in ASCII
        # for waterrower
        self.add_manufacturer_data(
            0xFFFF, [0x77, 0x72],
        )
        # Set the name that our bluetooth server will appear as
        self.add_local_name("WRowFusion")
        # Advertise the application as a Rower-type Fitness Machine.
        self.add_service_data(
            "1826",  # 16-bit UUID for FTMS, passed as a string
            [0x01, 0b00010000, 0b00000000]  # 0x01 = Supported Modes, 0x10 = Rowing supported
        )

        self.add_service_uuid(DeviceInformation.UUID)
        self.add_service_uuid(FTMService.UUID)
        self.add_service_uuid(AppHeartRate.UUID)

        self.include_tx_power = True
        # Advertise as LE only, no BD/EDR to try and sidestep MITM input/output requirements.
        # Sadly this doesn't work. Possibly because Bluez wants full control over setting this flag.
        #self.add_data(0x01, [dbus.Byte(0x06)])


class AppHeartRateMeasurement(HeartRateMeasurementCharacteristic):
    '''Wrapper around the generic heart rate measurement characteristic to allow app-specific configuration'''
    def __init__(self, bus, index, service, hr_monitor):
        super().__init__(bus, index, service)
        self.hr_monitor = hr_monitor
        self.last_hr = 0

    def _update(self):
        GLib.timeout_add(1000, self._hrm_cb)

    def _hrm_cb(self):
        hr = self.hr_monitor.get_heart_rate()
        if hr and hr > 0 and self.last_hr != hr:
            self.last_hr = hr
            value = [dbus.Byte(0), dbus.Byte(hr & 0xff)]
            self.PropertiesChanged(GATT_CHRC_IFACE, { 'Value': value }, [])
        return self.notifying


class AppHeartRate(HeartRateService):
    '''Wrapper around the generic heart rate service to allow app-specific configuration'''
    def __init__(self, bus, index, hr_monitor):
        super().__init__(bus, index)
        self.add_characteristic(AppHeartRateMeasurement(bus, 0, self, hr_monitor))


def sigint_handler(sig, frame):
    if sig == signal.SIGINT:
        logger.info("SIGINT received. Quitting ble_server dbus mainloop.")
        if mainloop:
            mainloop.quit()
    else:
        raise ValueError("Undefined handler for '{}' ".format(sig))

def inject_heart_rate(values, hrm: HeartRateMonitor):
    """
    Update the 'heart_rate' key in the values dictionary using the external
    HRM if it's currently zero and the HRM provides a non-zero value.
    Modifies the input dictionary in-place and returns it.
    """
    if not isinstance(values, dict):
        logger.warning("inject_heart_rate recieved invalid values input: %s", values)
        return values
    
    logger.debug("inject heart rate received valid dict")
    if values.get('heart_rate', 0) == 0:
        logger.debug("heart rate in dict is 0 so getting external hr")
        ext_hr = hrm.get_heart_rate()
        logger.debug(f"external heart rate got at: {ext_hr}")
        if ext_hr:
            values['heart_rate'] = ext_hr
    return values

def ble_server_task(hr_monitor: HeartRateMonitor, rower_state: RowerState):
    logger.debug("main: Entering main")
    global mainloop

    logger.debug("main: Calling dbus.mainloop.glib.DBusGMainLoop")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    logger.debug("main: Getting System bus")
    # get the system bus
    bus = dbus.SystemBus()

    if MainLoop is None:
        logger.error("MainLoop class is not set. Exiting BLE server task.")
        return

    try:
        mainloop = MainLoop()
    except Exception as e:
        logger.error(f"Exception starting main loop: {e}")
        return

    assert mainloop is not None
    
    logger.debug("main: Getting ble controller")
    # get the ble controller
    adapter = find_adapter(bus)

    if not adapter:
        logger.error("main: GattManager1 interface not found")
        return

    logger.debug("main: Getting Bluez service")
    adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter)

    logger.debug("main: Getting Bluez properties")
    adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

    # powered property on the controller to on
    logger.debug("main: Set bluez powered property to on")
    adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))
    time.sleep(1.0)

    # Get manager objs
    logger.debug("main: Getting Bluez GATT MANAGER IFACE")
    service_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
    logger.debug("main: Getting Bluez ADVERTISING MANAGER IFACE")
    ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)

    logger.debug("main: Calling FTMPAdvertisement")
    advertisement = FTMPAdvertisement(bus, 0)

    logger.debug("main: Get bus object for bluez service")
    obj = bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez")

    # Instantiates the Agent class. It creates the actual agent service object 
    # on the D-Bus, implementing org.bluez.Agent1. This is essential, even though
    # the agent variable is not referred to later on.
    logger.debug("main: Get Agent")
    agent = Agent(bus, AGENT_PATH, on_release=mainloop.quit)

    logger.debug("main: Set app object")
    app = Application(bus)

    device_info = DeviceInformation(bus, 1)
    device_info.manufacturer.value = dbus.Array(b'Waterrower', signature='y')
    device_info.model.value = dbus.Array(b'4', signature='y')
    device_info.serial.value = dbus.Array(b'0000', signature='y')
    device_info.hardware.value = dbus.Array(b'2.2BLE', signature='y')
    device_info.firmware.value = dbus.Array(b'0.30', signature='y')
    device_info.software.value = dbus.Array([dbus.Byte(0x34), dbus.Byte(0x2E), dbus.Byte(0x33)], signature='y')

    logger.debug("main: Calling add_service - DeviceInformation")
    app.add_service(device_info)

    ftm_service = FTMService(bus, 2)

    ftm_features = FitnessMachineFeature(bus, 0, ftm_service, supported_features=FTM_SUPPORTED_FEATURES)

    ftm_service.add_characteristic(ftm_features)
    ftm_service.add_characteristic(AppRowerData(bus, 1, ftm_service, rower_state, hr_monitor))

    ftm_cp = FitnessMachineControlPoint(bus, 2, ftm_service)

    logger.debug("assigning command handler to fitness machine ")
    ftm_cp.command_handler = make_fmcp_command_handler(rower_state)
    ftm_service.add_characteristic(ftm_cp)

    logger.debug("main: Calling add_service - FTMservice")
    app.add_service(ftm_service)
    
    logger.debug("main: Calling add_service - HeartRate")
    app.add_service(AppHeartRate(bus,3,hr_monitor))

    logger.debug("main: Set agent manager")
    agent_manager = dbus.Interface(obj, AGENT_MANAGER_IFACE)
    logger.debug("main: Register bluetooth agent with noinputnooutput")
    agent_manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput") # register the bluetooth agent with no input and output which should avoid asking for pairing 

    logger.debug("main: calling admanager.RegisterAdvertisement")
    time.sleep(0.5)
    ad_manager.RegisterAdvertisement(
        advertisement.get_path(),
        {},
        reply_handler=register_ad_cb,
        error_handler=register_ad_error_cb,
    )

    logger.info("main: Calling service_manager.RegisterApplication to Registering GATT application...")
    time.sleep(0.5)
    service_manager.RegisterApplication(
        app.get_path(),
        {},
        reply_handler=register_app_cb,
        error_handler=[register_app_error_cb],
    )

    logger.debug("main: agent_manager.RequestDefaultAgent")
    agent_manager.RequestDefaultAgent(AGENT_PATH)

    logger.debug("main: mainloop.run")
    mainloop.run()
    # ad_manager.UnregisterAdvertisement(advertisement)
    # dbus.service.Object.remove_from_connection(advertisement)

#
# if __name__ == "__main__":
#     signal.signal(signal.SIGINT, sigint_handler)

