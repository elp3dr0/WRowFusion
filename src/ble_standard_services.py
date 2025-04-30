from src.bleif import Service, Characteristic
import dbus
import logging

logger = logging.getLogger(__name__)

class DeviceInformation(Service):
    UUID = '180A'

    def __init__(self, bus, index):
        super().__init__(bus, index, self.UUID, True)
        self.manufacturer = ManufacturerNameString(bus, 0, self)
        self.model = ModelNumberString(bus, 1, self)
        self.serial = SerialNumberString(bus, 2, self)
        self.hardware = HardwareRevisionString(bus, 3, self)
        self.firmware = FirmwareRevisionString(bus, 4, self)
        self.software = SoftwareRevisionString(bus, 5, self)

        self.add_characteristic(self.manufacturer)
        self.add_characteristic(self.model)
        self.add_characteristic(self.serial)
        self.add_characteristic(self.hardware)
        self.add_characteristic(self.firmware)
        self.add_characteristic(self.software)

class ManufacturerNameString(Characteristic):
    UUID = '2A29'

    def __init__(self, bus, index, service):
        super().__init__(bus, index, self.UUID, ['read'], service)
        self.value = dbus.Array([], signature='y')

    def ReadValue(self, options):
        return self.value

class ModelNumberString(Characteristic):
    UUID = '2A24'

    def __init__(self, bus, index, service):
        super().__init__(bus, index, self.UUID, ['read'], service)
        self.value = dbus.Array([], signature='y')

    def ReadValue(self, options):
        return self.value

class SerialNumberString(Characteristic):
    UUID = '2A25'

    def __init__(self, bus, index, service):
        super().__init__(bus, index, self.UUID, ['read'], service)
        self.value = dbus.Array([], signature='y')

    def ReadValue(self, options):
        return self.value

class HardwareRevisionString(Characteristic):
    UUID = '2A27'

    def __init__(self, bus, index, service):
        super().__init__(bus, index, self.UUID, ['read'], service)
        self.value = dbus.Array([], signature='y')

    def ReadValue(self, options):
        return self.value

class FirmwareRevisionString(Characteristic):
    UUID = '2A26'

    def __init__(self, bus, index, service):
        super().__init__(bus, index, self.UUID, ['read'], service)
        self.value = dbus.Array([], signature='y')

    def ReadValue(self, options):
        return self.value

class SoftwareRevisionString(Characteristic):
    UUID = '2A28'

    def __init__(self, bus, index, service):
        super().__init__(bus, index, self.UUID, ['read'], service)
        self.value = dbus.Array([], signature='y')

    def ReadValue(self, options):
        return self.value
