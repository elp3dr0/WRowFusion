#!/usr/bin/env python3

# ---------------------------------------------------------------------------
# Original code from the PunchThrough Repo espresso-ble
# https://github.com/PunchThrough/espresso-ble
# ---------------------------------------------------------------------------
#
import logging
from queue import Empty
import signal
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import struct

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
    RowingFieldFlags,
    RowerData, 
)

from src.heart_rate import HeartRateMonitor
from src.s4 import DataLogger

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

MainLoop = None

try:
    from gi.repository import GLib

    MainLoop = GLib.MainLoop

except ImportError:
    import gobject as GObject

    MainLoop = GObject.MainLoop

mainloop = None

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"
    logger.error(f"Encountered DBus exception in BLE Server: {_dbus_error_name}")


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"
    logger.error(f"Encountered DBus exception in BLE Server: {_dbus_error_name}")


class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"
    logger.error(f"Encountered DBus exception in BLE Server: {_dbus_error_name}")


class InvalidValueLengthException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidValueLength"
    logger.error(f"Encountered DBus exception in BLE Server: {_dbus_error_name}")


class FailedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.Failed"
    logger.error(f"Encountered DBus exception in BLE Server: {_dbus_error_name}")

###########################
## GATT helper functions ##
###########################

def register_app_cb():
    logger.info("GATT application registered.")


def register_app_error_cb(error):
    logger.critical("Failed to register GATT application: " + str(error))
    mainloop.quit()


def register_ad_cb():
    logger.info("GATT advertisement registered.")


def register_ad_error_cb(error):
    logger.critical("Failed to register GATT advertisement: " + str(error))
    mainloop.quit()


###########################################
## FTM Service helper functions & config ##
###########################################

def request_reset_ble():
    # Cues up a reset of the waterrower following an instruction recieved via the FTM Control Point. 
    # Puts "reset_ble" into the queue (FIFO), to be handled by S4 thread.
    logger.debug("Entering request_reset_ble")
    out_q_reset.put("reset_ble")

def fmcp_request_control_handler(payload):
    return 0x01  # Success

def fmcp_reset_handler(payload):
    request_reset_ble()
    return 0x01  # Success

def fmcp_command_handler(opcode, payload):
    handler = FTM_SUPPORTED_OPCODES.get(opcode)
    if handler:
        return handler(payload)
    logger.warning(f"Recieved valid but unsupported OpCode: {opcode}")
    return 0x02  # Op code not supported


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
)

ROWER_SUPPORTED_FIELDS = (
    RowingFieldFlags.STROKE_INFO 
    | RowingFieldFlags.TOTAL_DISTANCE
    | RowingFieldFlags.INSTANT_PACE
    | RowingFieldFlags.INSTANT_POWER
    | RowingFieldFlags.EXPENDED_ENERGY
    | RowingFieldFlags.HEART_RATE
    | RowingFieldFlags.ELAPSED_TIME
)


class AppRowerData(RowerData):
    def __init__(self, bus, index, service, wr_data_logger: DataLogger):
        super().__init__(bus, index, service, supported_fields=ROWER_SUPPORTED_FIELDS)
        self.last_payload = None
        self.data_logger = wr_data_logger

    def rowerdata_cb(self):
        logger.debug("Running ApplicationRowerData.rowerdata_cb")
        if not self.data_logger.is_initialised:
            logger.debug("No WaterRower values available yet.")
            return self.notifying
        
        field_values = self.data_logger.get_WRValues()
        if not field_values:
            logger.warning("No WaterRower values available yet.")
            return self.notifying
        
        payload_bytes = self.encode(field_values)
        if self.last_payload != payload_bytes:
            self.last_payload = payload_bytes
            value = [dbus.Byte(b) for b in payload_bytes]
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])

        return self.notifying

    def _update(self):
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
        mainloop.quit()
    else:
        raise ValueError("Undefined handler for '{}' ".format(sig))

WaterrowerValuesRaw_polled = None

def Waterrower_poll():
    #logger.debug("Entering Waterrower_poll")
    global WaterrowerValuesRaw
    global WaterrowerValuesRaw_polled

    if ble_in_q_value:
        logger.debug("Waterrower_poll: ble_q is not none, getting values...")
        WaterrowerValuesRaw = ble_in_q_value.pop()
        logger.debug(f"Waterrower_poll: WaterrowerValuesRaw = {WaterrowerValuesRaw}")
        for keys in WaterrowerValuesRaw:
            WaterrowerValuesRaw[keys] = int(WaterrowerValuesRaw[keys])

        if WaterrowerValuesRaw_polled != WaterrowerValuesRaw:
            WaterrowerValuesRaw_polled = WaterrowerValuesRaw
            print("rower", WaterrowerValuesRaw_polled)

    return True

def ble_server_task(out_q,ble_in_q, hr_monitor: HeartRateMonitor, wr_data_logger: DataLogger): #out_q
    logger.debug("main: Entering main")
    global mainloop
    global out_q_reset
    global ble_in_q_value
    out_q_reset = out_q
    ble_in_q_value = ble_in_q

    logger.debug("main: Calling dbus.mainloop.glib.DBusGMainLoop")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    logger.debug("main: Getting System bus")
    # get the system bus
    bus = dbus.SystemBus()

    logger.debug("main: Getting ble controller")
    # get the ble controller
    adapter = find_adapter(bus)

    if not adapter:
        logger.critical("main: GattManager1 interface not found")
        return

    logger.debug("main: Getting Bluez service")
    adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter)

    logger.debug("main: Getting Bluez properties")
    adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

    # powered property on the controller to on
    logger.debug("main: Set bluez powered property to on")
    adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))

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
    agent = Agent(bus, AGENT_PATH)

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
    ftm_service.add_characteristic(AppRowerData(bus, 1, ftm_service, wr_data_logger))

    ftm_cp = FitnessMachineControlPoint(bus, 2, ftm_service)

    ftm_cp.command_handler = fmcp_command_handler
    ftm_service.add_characteristic(ftm_cp)

    logger.debug("main: Calling add_service - FTMservice")
    app.add_service(ftm_service)
    
    logger.debug("main: Calling add_service - HeartRate")
    app.add_service(AppHeartRate(bus,3,hr_monitor))

    # Set a callback function to poll the WaterRower data every 100ms 
    logger.debug("main: Set up Waterrower_poll recurring task")
    GLib.timeout_add(100, Waterrower_poll)

    logger.debug("main: associate Mainloop to mainloop")
    mainloop = MainLoop()

    logger.debug("main: Set agent manager")
    agent_manager = dbus.Interface(obj, AGENT_MANAGER_IFACE)
    logger.debug("main: Register bluetooth agent with noinputnooutput")
    agent_manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput") # register the bluetooth agent with no input and output which should avoid asking for pairing 

    logger.debug("main: calling admanager.RegisterAdvertisement")
    ad_manager.RegisterAdvertisement(
        advertisement.get_path(),
        {},
        reply_handler=register_ad_cb,
        error_handler=register_ad_error_cb,
    )

    logger.info("main: Calling service_manager.RegisterApplication to Registering GATT application...")

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

