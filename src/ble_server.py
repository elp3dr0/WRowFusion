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
)

MainLoop = None

try:
    from gi.repository import GLib

    MainLoop = GLib.MainLoop

except ImportError:
    import gobject as GObject

    MainLoop = GObject.MainLoop

DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE = "org.bluez.GattDescriptor1"

LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"

logger = logging.getLogger(__name__)

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


def register_app_cb():
    logger.info("GATT application registered")


def register_app_error_cb(error):
    logger.critical("Failed to register GATT application: " + str(error))
    mainloop.quit()

# Function is needed to trigger the reset of the waterrower. It puts the "reset_ble" into the queue (FIFO) in order
# for the WaterrowerInterface thread to get the signal to reset the waterrower.

def request_reset_ble():
    logger.debug("Entering request_reset_ble")
    out_q_reset.put("reset_ble")

def Convert_Waterrower_raw_to_byte():
    logger.debug(f"Entering Conert_Waterrower_raw_to_byte on WaterrowerValuesRaw:") # {WaterrowerValuesRaw}")
    WRBytearray = []
    #print("Ble Values: {0}".format(WaterrowerValuesRaw))
    #todo refactor this part with the correct struct.pack e.g. 2 bytes use "H" instand of bitshifiting ?
    #print(WaterrowerValuesRaw)
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['stroke_rate'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_strokes'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_strokes'] & 0xff00) >> 8))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_distance_m'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_distance_m'] & 0xff00) >> 8))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_distance_m'] & 0xff0000) >> 16))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['instantaneous pace'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['instantaneous pace'] & 0xff00) >> 8))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['watts'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['watts'] & 0xff00) >> 8))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_kcal'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_kcal'] & 0xff00) >> 8))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_kcal_hour'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_kcal_hour'] & 0xff00) >> 8))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['total_kcal_min'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['heart_rate'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['elapsedtime'] & 0xff)))
    WRBytearray.append(struct.pack("B", (WaterrowerValuesRaw['elapsedtime'] & 0xff00) >> 8))
    logger.debug(f"{WRBytearray}")
    return WRBytearray


class FitnessMachineFeature(Characteristic):
    '''
    Define the 8-byte flag array for the FTMS Feature Characteristic.
    The flags specify what fields the Fitness Machine will provide (and what ).
    See Bluetooth_FTMS_v1.0.1.pdf 4.3.1.1 bit field definition.
    The octets are little endian.
    0x26 0x56 translates to a bit field of 0101 0110 0010 0110
    which specifies:
    Bit	Value	Feature
    0	0  	    Average Speed Supported
    1	1 	    Cadence Supported
    2	1 	    Total Distance Supported
    3	0	    Inclination Supported
    4	0	    Elevation Gain Supported
    5	1 	    Pace Supported
    6	0	    Step Count Supported
    7	0	    Resistance Level Supported
    8	1 	    Stride Count Supported
    9	1 	    Expended Energy Supported
    10	0	    Heart Rate Measurement Supported
    11	1 	    Metabolic Equivalent (MET) Supported
    12	0	    Elapsed Time Supported
    13	1 	    Remaining Time Supported
    14	0	    Power Measurement Supported
    15	1 	    Force Measurement Supported
    '''

    FITNESS_MACHINE_FEATURE_UUID = '2acc'

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            self.FITNESS_MACHINE_FEATURE_UUID,
            ['read'],
            service)
        self.notifying = False
        self.value = [dbus.Byte(0),dbus.Byte(0),dbus.Byte(0),dbus.Byte(0),dbus.Byte(0),dbus.Byte(0),dbus.Byte(0),dbus.Byte(0)]

        self.value[0] = 0x26
        self.value[1] = 0x56
        self.value[2] = 0x00
        self.value[3] = 0x00
        self.value[4] = 0x00
        self.value[5] = 0x00
        self.value[6] = 0x00
        self.value[7] = 0x00


    def ReadValue(self, options):
        logger.debug("Entering FitnessMachineFeature.ReadValue")
        print('Fitness Machine Feature: ' + repr(self.value))
        return self.value


class RowerData(Characteristic):
    logger.debug("Entering Class RowerData")
    ROWING_UUID = '2ad1'
    last_values = {}

    def __init__(self, bus, index, service):
        logger.debug("Entering RowerData.init")
        Characteristic.__init__(
            self, bus, index,
            self.ROWING_UUID,
            ['notify'],
            service)
        self.notifying = False
        self.iter = 0

    def rowerdata_cb(self):
        logger.debug("Entering RowerData.rowerdata_cb")
        if not WaterrowerValuesRaw:
            logger.warning("RowerData.rowerdata_cb: WaterrowerValuesRaw is empty or not yet initialised.")
            return self.notifying
        
        Waterrower_byte_values = Convert_Waterrower_raw_to_byte()
        logger.debug(f"Rower.rowerdata: Got Waterrower_byte_values: {Waterrower_byte_values}")
        if self.last_values != Waterrower_byte_values:
            self.last_values = Waterrower_byte_values 
            value = [dbus.Byte(0x2C), dbus.Byte(0x0B),
                dbus.Byte(Waterrower_byte_values[0]), dbus.Byte(Waterrower_byte_values[1]), dbus.Byte(Waterrower_byte_values[2]),
                dbus.Byte(Waterrower_byte_values[3]), dbus.Byte(Waterrower_byte_values[4]), dbus.Byte(Waterrower_byte_values[5]),
                dbus.Byte(Waterrower_byte_values[6]), dbus.Byte(Waterrower_byte_values[7]),
                dbus.Byte(Waterrower_byte_values[8]), dbus.Byte(Waterrower_byte_values[9]),
                dbus.Byte(Waterrower_byte_values[10]), dbus.Byte(Waterrower_byte_values[11]),dbus.Byte(Waterrower_byte_values[12]),dbus.Byte(Waterrower_byte_values[13]),dbus.Byte(Waterrower_byte_values[14]),
                dbus.Byte(Waterrower_byte_values[15]),
                dbus.Byte(Waterrower_byte_values[16]), dbus.Byte(Waterrower_byte_values[17]),
                ]
            self.PropertiesChanged(GATT_CHRC_IFACE, { 'Value': value }, [])
        return self.notifying

    def _update_rowerdata_cb_value(self):
        logger.debug("Entering RowerData.update_rowerdata_cb_value")
        #print('Update Waterrower Rower Data')

        if not self.notifying:
            return

        GLib.timeout_add(200, self.rowerdata_cb)

    def StartNotify(self):
        logger.debug("Entering RowerData.StartNotify")
        if self.notifying:
            print('Already notifying, nothing to do')
            return

        self.notifying = True
        self._update_rowerdata_cb_value()

    def StopNotify(self):
        logger.debug("Entering RowerData.StopNotify")
        if not self.notifying:
            print('Not notifying, nothing to do')
            return

        self.notifying = False
        self._update_rowerdata_cb_value()


###### todo: function needed to get all the date from waterrower
# 20 byte is max data send
# example : 0x 2C-0B-00-00-00-00-FF-FF-00-00-00-00-00-00-00-00-00-00-00-00
# first 2 bytes: are for rowing machine details: 0B

def fmcp_request_control_handler(payload):
    return 0x01  # Success

def fmcp_reset_handler(payload):
    request_reset_ble()
    return 0x01  # Success

# Specify which Fitness Machine Control Point OpCodes our application supports, 
# and specify which function should be called in each case.
opcode_handlers = {
    FitnessMachineControlPoint.FTMControlOpCode.FTMC_REQUEST_CONTROL: fmcp_request_control_handler,
    FitnessMachineControlPoint.FTMControlOpCode.FTMC_RESET: fmcp_reset_handler,
}

def fmcp_command_handler(opcode, payload):
    handler = opcode_handlers.get(opcode)
    if handler:
        return handler(payload)
    logger.warning(f"Recieved valid but unsupported OpCode: {opcode}")
    return 0x02  # Op code not supported


class HeartRate(Service):
    logger.debug("Entering Class HeartRate")
    HEART_RATE = '180D'

    def __init__(self, bus, index):
        logger.debug("Entering HeartRate.init")
        Service.__init__(self, bus, index, self.HEART_RATE, True)
        self.add_characteristic(HeartRateMeasurement(bus, 0, self))

class HeartRateMeasurement(Characteristic):
    logger.debug("Entering Class HeartRateMeasurement")
    HEART_RATE_MEASUREMENT = '2a37'
    last_hr = 0

    def __init__(self, bus, index, service):
        logger.debug("Entering HeartRateMeasurement.init")
        Characteristic.__init__(
            self, bus, index,
            self.HEART_RATE_MEASUREMENT,
            ['notify'],
            service)
        self.notifying = False

    def hrm_cb(self):
        logger.debug("Entering HeartRateMeasurement.hrm_cb")
        if not WaterrowerValuesRaw:
            logger.warning("HeartRateMeasurement.hrm_cb: WaterrowerValuesRaw is empty or not yet initialised.")
            return self.notifying

        hr = WaterrowerValuesRaw['heart_rate'];
        if self.last_hr != hr:
            self.last_hr = hr
            print("new ble hr: %d" % self.last_hr)
            value = [dbus.Byte(0),dbus.Byte(self.last_hr & 0xff)]

            self.PropertiesChanged(GATT_CHRC_IFACE, { 'Value': value }, [])
        return self.notifying

    def _update_hrm_cb_value(self):
        logger.debug("Entering HeartRateMeasurement.update_hrm_cb_values")
        print('Update Waterrower HR Data')

        if not self.notifying:
            return

        GLib.timeout_add(1000, self.hrm_cb)

    def StartNotify(self):
        logger.debug("Entering HeartRateMeasurement.StartNotify")
        if self.notifying:
            print('Already notifying, nothing to do')
            return

        print('Start HR Notify')
        self.notifying = True
        self._update_hrm_cb_value()
        
    def StopNotify(self):
        logger.debug("Entering HeartRateMeasurement.StopNotify")
        if not self.notifying:
            print('Not notifying, nothing to do')
            return

        self.notifying = False


class FTMPAdvertisement(Advertisement):
    logger.debug("Entering Class FTMPAdvertisement")
    def __init__(self, bus, index):
        logger.debug("Entering FTMPAdvertisement.init")
        Advertisement.__init__(self, bus, index, "peripheral")
        self.add_manufacturer_data(
            0xFFFF, [0x77, 0x72],
        )
        self.add_service_uuid(DeviceInformation.UUID)
        self.add_service_uuid(FTMService.UUID)
        self.add_service_uuid(HeartRate.HEART_RATE)

        self.add_local_name("WRowFusion")
        self.include_tx_power = True
        # Advertise as LE only, no BD/EDR to try and sidestep MITM input/output requirements.
        # Sadly this doesn't work. Possibly because Bluez wants full control over setting this flag.
        #self.add_data(0x01, [dbus.Byte(0x06)])

def register_ad_cb():
    logger.debug("Entering FTMPAdvertisement.register_ad_cb")
    logger.info("Advertisement registered")


def register_ad_error_cb(error):
    logger.debug("Entering FTMPAdvertisement.register_ad_error_cb")
    logger.critical("Failed to register advertisement: " + str(error))
    mainloop.quit()

def sigint_handler(sig, frame):
    logger.debug("Entering FTMPAdvertisement.sigint_handler")
    if sig == signal.SIGINT:
        mainloop.quit()
    else:
        raise ValueError("Undefined handler for '{}' ".format(sig))

AGENT_PATH = "/com/wrowfusion/agent"

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

def ble_server_task(out_q,ble_in_q): #out_q
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
    adapter_props = dbus.Interface(adapter_obj, "org.freedesktop.DBus.Properties")

    # powered property on the controller to on
    logger.debug("main: Set bluez powered property to on")
    adapter_props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))

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
    ftm_service.add_characteristic(FitnessMachineFeature(bus, 0, ftm_service))
    ftm_service.add_characteristic(RowerData(bus, 1, ftm_service))

    ftm_cp = FitnessMachineControlPoint(bus, 2, ftm_service)

    ftm_cp.command_handler = fmcp_command_handler
    ftm_service.add_characteristic(ftm_cp)

    logger.debug("main: Calling add_service - FTMservice")
    app.add_service(ftm_service)
    
    logger.debug("main: Calling add_service - HeartRate")
    app.add_service(HeartRate(bus,3))

    # Set a callback function to poll the WaterRower data every 100ms 
    logger.debug("main: Set up Waterrower_poll recurring task")
    GLib.timeout_add(100, Waterrower_poll)

    logger.debug("main: associate Mainloop to mainloop")
    mainloop = MainLoop()

    logger.debug("main: Set agent manager")
    agent_manager = dbus.Interface(obj, "org.bluez.AgentManager1")
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

