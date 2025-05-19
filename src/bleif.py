# ---------------------------------------------------------------------------
# Based on the inonoob repo "pirowflo"
# https://github.com/inonoob/pirowflo
# Extensively refactored and expanded for WRowFusion
# ---------------------------------------------------------------------------
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import dbus # pyright: ignore [reportMissingImports] 
else:
    import dbus

import logging
import src.ble_constants as blec

logger = logging.getLogger(__name__)

#######################
##  DBUS EXCEPTIONS  ##
#######################

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

##################
### Functions ####
##################

def find_adapter(bus):
    """
    Returns the first object that the bluez service has that has a GattManager1 interface
    """
    remote_om = dbus.Interface(bus.get_object(blec.BLUEZ_SERVICE_NAME, "/"), blec.DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if blec.GATT_MANAGER_IFACE in props.keys():
            return o

    return None


def clear_existing_advertisements(bus: dbus.Bus):
    """
    Searches for and attempts to unregister any active BLE advertisements.
    This helps avoid conflicts with newly created advertisements.
    """
    try:
        # Get the adapter path (e.g., /org/bluez/hci0)
        obj_manager = dbus.Interface(
            bus.get_object(blec.BLUEZ_SERVICE_NAME, '/'),
            blec.DBUS_OM_IFACE
        )
        managed_objects = obj_manager.GetManagedObjects()

        ad_manager_path = None
        for path, interfaces in managed_objects.items():
            if blec.LE_ADVERTISING_MANAGER_IFACE in interfaces:
                ad_manager_path = path
                break

        if not ad_manager_path:
            logger.warning("No LEAdvertisingManager1 interface found.")
            return

        ad_manager = dbus.Interface(
            bus.get_object(blec.BLUEZ_SERVICE_NAME, ad_manager_path),
            blec.LE_ADVERTISING_MANAGER_IFACE
        )

        for path, interfaces in managed_objects.items():
            if blec.LE_ADVERTISEMENT_IFACE in interfaces:
                try:
                    logger.info(f"Attempting to unregister existing advertisement: {path}")
                    ad_manager.UnregisterAdvertisement(path)

                    # If you still hold the actual Advertisement object:
                    obj = bus.get_object(blec.BLUEZ_SERVICE_NAME, path)
                    if isinstance(obj, dbus.service.Object):
                        obj.remove_from_connection()

                    logger.info(f"Unregistered advertisement at {path}")
                except dbus.exceptions.DBusException as e:
                    logger.warning(f"Could not unregister advertisement at {path}: {e}")

    except Exception as e:
        logger.error(f"Error while clearing advertisements: {e}")

########################
##  GATT APPLICATION  ##
########################

class Application(dbus.service.Object):
    """
    org.bluez.GattApplication1 interface implementation
    """

    def __init__(self, bus):
        self.path = "/"
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(blec.DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        logger.info("GetManagedObjects")

        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()

        return response


##########################
##  GATT ADVERTISEMENT  ##
##########################

class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/bluez/example/advertisement"

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = None
        self.include_tx_power = None
        self.data = None
        self.discoverable = None
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = {}
        properties["Type"] = self.ad_type
        if self.service_uuids is not None:
            properties["ServiceUUIDs"] = dbus.Array(self.service_uuids, signature="s")
        if self.solicit_uuids is not None:
            properties["SolicitUUIDs"] = dbus.Array(self.solicit_uuids, signature="s")
        if self.manufacturer_data is not None:
            properties["ManufacturerData"] = dbus.Dictionary(
                self.manufacturer_data, signature="qv"
            )
        if self.service_data is not None:
            properties["ServiceData"] = dbus.Dictionary(
                self.service_data, signature="sv"
            )
        if self.local_name is not None:
            properties["LocalName"] = dbus.String(self.local_name)
        if self.discoverable is not None and self.discoverable == True:
            properties['Discoverable'] = dbus.Boolean(self.discoverable)
        if self.include_tx_power:
            #properties["IncludeTxPower"] = dbus.Boolean(self.include_tx_power)
            properties['Includes'] = dbus.Array(["tx-power"], signature='s')
        if self.data is not None:
            properties["Data"] = dbus.Dictionary(self.data, signature="yv")
        return {blec.LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service_uuid(self, uuid):
        if not self.service_uuids:
            self.service_uuids = []
        self.service_uuids.append(uuid)

    def add_solicit_uuid(self, uuid):
        if not self.solicit_uuids:
            self.solicit_uuids = []
        self.solicit_uuids.append(uuid)

    def add_manufacturer_data(self, manuf_code, data):
        if not self.manufacturer_data:
            self.manufacturer_data = dbus.Dictionary({}, signature="qv")
        self.manufacturer_data[manuf_code] = dbus.Array(data, signature="y")

    def add_service_data(self, uuid, data):
        if not self.service_data:
            self.service_data = dbus.Dictionary({}, signature="sv")
        self.service_data[uuid] = dbus.Array(data, signature="y")

    def add_local_name(self, name):
        if not self.local_name:
            self.local_name = ""
        self.local_name = dbus.String(name)

    def add_data(self, ad_type, data):
        if not self.data:
            self.data = dbus.Dictionary({}, signature="yv")
        self.data[ad_type] = dbus.Array(data, signature="y")

    @dbus.service.method(blec.DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        logger.debug("GetAll Advertisement properties")
        if interface != blec.LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[blec.LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(blec.LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        logger.info("%s: Advertisement Released!" % self.path)

##################
##  GATT AGENT  ##
##################

def ask(prompt):
    return input(prompt)

def set_trusted(path, bus):
    props = dbus.Interface(
        bus.get_object(blec.BLUEZ_SERVICE_NAME, path), "org.freedesktop.DBus.Properties"
    )
    props.Set("org.bluez.Device1", "Trusted", True)


def dev_connect(path, bus):
    dev = dbus.Interface(bus.get_object(blec.BLUEZ_SERVICE_NAME, path), "org.bluez.Device1")
    dev.Connect()


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.Rejected"


class Agent(dbus.service.Object):
    exit_on_release = True

    # Pass mainloop.quit as the on_release argument in order to allow the Release method to clean up
    # resources when the agent is no longer needed
    def __init__(self, bus, path, on_release=None):
        super().__init__(bus, path)
        self.bus = bus  # Store the bus for later use
        self._on_release = on_release

    def set_exit_on_release(self, exit_on_release):
        self.exit_on_release = exit_on_release

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        logger.info("Release")
        if self.exit_on_release and self._on_release:
            self._on_release()

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        logger.info("AuthorizeService (%s, %s)" % (device, uuid))
        set_trusted(device, self.bus)
        authorize = "yes" # ask("Authorize connection (yes/no): ")
        if authorize == "yes":
            return
        raise Rejected("Connection rejected by user")

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        logger.info("RequestPinCode (%s) - Just Works, rejecting PIN" % device)
        raise Rejected("No PIN code available for Just Works")
        #logger.info("RequestPinCode (%s)" % (device))
        #set_trusted(device, self.bus)
        #return ask("Enter PIN Code: ")

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        logger.info("RequestPasskey (%s) - Just Works, rejecting passkey" % device)
        raise Rejected("No passkey available for Just Works")
        #logger.info("RequestPasskey (%s)" % (device))
        #set_trusted(device, self.bus)
        #passkey = ask("Enter passkey: ")
        #return dbus.UInt32(passkey)

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        logger.info("DisplayPasskey (%s, %06u entered %u)" % (device, passkey, entered))

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        logger.info("DisplayPinCode (%s, %s)" % (device, pincode))

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        logger.info("Auto-confirming Just Works pairing with passkey %06d for device %s" % (passkey, device))
        set_trusted(device, self.bus)
        return
        #logger.info("RequestConfirmation (%s, %06d)" % (device, passkey))
        #confirm = "yes" #ask("Confirm passkey (yes/no): ")
        #if confirm == "yes":
        #    set_trusted(device, self.bus)
        #    return
        #raise Rejected("Passkey doesn't match")

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        logger.info("RequestAuthorization (%s)" % (device))
        set_trusted(device, self.bus)
        auth = "yes" #ask("Authorize? (yes/no): ")
        if auth == "yes":
            return
        raise Rejected("Pairing rejected")

    @dbus.service.method(blec.BT_AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self):
        logger.info("Agent request cancelled")


####################
##  GATT SERVICE  ##
####################

class Service(dbus.service.Object):
    """
    org.bluez.GattService1 interface implementation
    """

    PATH_BASE = "/org/bluez/example/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            blec.GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(
                    self.get_characteristic_paths(), signature="o"
                ),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(blec.DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != blec.GATT_SERVICE_IFACE:
            raise InvalidArgsException()

        return self.get_properties()[blec.GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    """
    org.bluez.GattCharacteristic1 interface implementation
    """

    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + "/char" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            blec.GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
                "Descriptors": dbus.Array(self.get_descriptor_paths(), signature="o"),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_descriptor_paths(self):
        result = []
        for desc in self.descriptors:
            result.append(desc.get_path())
        return result

    def get_descriptors(self):
        return self.descriptors

    @dbus.service.method(blec.DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != blec.GATT_CHRC_IFACE:
            raise InvalidArgsException()

        return self.get_properties()[blec.GATT_CHRC_IFACE]

    @dbus.service.method(blec.GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        logger.info("Default ReadValue called, returning error")
        raise NotSupportedException()

    @dbus.service.method(blec.GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        logger.info("Default WriteValue called, returning error")
        raise NotSupportedException()

    @dbus.service.method(blec.GATT_CHRC_IFACE)
    def StartNotify(self):
        logger.info("Default StartNotify called, returning error")
        raise NotSupportedException()

    @dbus.service.method(blec.GATT_CHRC_IFACE)
    def StopNotify(self):
        logger.info("Default StopNotify called, returning error")
        raise NotSupportedException()

    @dbus.service.signal(blec.DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class Descriptor(dbus.service.Object):
    """
    org.bluez.GattDescriptor1 interface implementation
    """

    def __init__(self, bus, index, uuid, flags, characteristic):
        self.path = characteristic.path + "/desc" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.chrc = characteristic
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            blec.GATT_DESC_IFACE: {
                "Characteristic": self.chrc.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(blec.DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != blec.GATT_DESC_IFACE:
            raise InvalidArgsException()

        return self.get_properties()[blec.GATT_DESC_IFACE]

    @dbus.service.method(blec.GATT_DESC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        logger.info("Default ReadValue called, returning error")
        raise NotSupportedException()

    @dbus.service.method(blec.GATT_DESC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        logger.info("Default WriteValue called, returning error")
        raise NotSupportedException()