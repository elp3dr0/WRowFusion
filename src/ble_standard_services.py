from src.bleif import Service, Characteristic
import dbus
import logging
from enum import Enum, IntFlag

logger = logging.getLogger(__name__)

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

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


class FTMService(Service):
    UUID = '1826'

    def __init__(self, bus, index):
        super().__init__(bus, index, self.UUID, True)


class FitnessMachineControlPoint(Characteristic):
    UUID = '2ad9'

    class FTMControlOpCode(Enum):
        """
        Enum class representing Fitness Machine Control Point (FTM) Op Codes specified in Bluetooth_FTMS_v1.0.1.pdf.
        """
        FTMC_REQUEST_CONTROL = 0x00
        FTMC_RESET = 0x01
        FTMC_SET_TARGET_SPEED = 0x02
        FTMC_SET_TARGET_INCLINATION = 0x03
        FTMC_SET_TARGET_RESISTANCE_LEVEL = 0x04
        FTMC_SET_TARGET_POWER = 0x05
        FTMC_SET_TARGET_HEART_RATE = 0x06
        FTMC_START_OR_RESUME = 0x07
        FTMC_STOP_OR_PAUSE = 0x08
        FTMC_SET_TARGETED_EXPENDED_ENERGY = 0x09
        FTMC_SET_TARGETED_NUMBER_OF_STEPS = 0x0A
        FTMC_SET_TARGETED_NUMBER_OF_STRIDES = 0x0B
        FTMC_SET_TARGETED_DISTANCE = 0x0C
        FTMC_SET_TARGETED_TRAINING_TIME = 0x0D
        FTMC_SET_TARGETED_TIME_IN_TWO_HEART_RATE_ZONES = 0x0E
        FTMC_SET_TARGETED_TIME_IN_THREE_HEART_RATE_ZONES = 0x0F
        FTMC_SET_TARGETED_TIME_IN_FIVE_HEART_RATE_ZONES = 0x10
        FTMC_SET_INDOOR_BIKE_SIMULATION_PARAMETERS = 0x11
        FTMC_SET_WHEEL_CIRCUMFERENCE = 0x12
        FTMC_SPIN_DOWN_CONTROL = 0x13
        FTMC_SET_TARGETED_CADENCE = 0x14
        FTMC_RESPONSE_CODE = 0x80

    def __init__(self, bus, index, service):
        super().__init__(
            bus, index,
            self.UUID,
            ['indicate', 'write'],
            service,
        )
        self.command_handler = None  # To be assigned by project-specific code

    def WriteValue(self, value, options):
        self.value = value
        opcode_value = int(value[0])
        payload = value[1:]
        logger.debug(f'FMCP received OpCode: Ox{opcode_value:02X}')

        try:
            opcode = self.FTMControlOpCode(opcode_value)
        except ValueError:
            logger.warning(f'FMCP OpCode not recognised: Ox{opcode_value:02X}')
            return self._build_response(opcode_value, result_code=0x02)  # Op code not recognised so return unsupported response.

        if self.command_handler:
            result = self.command_handler(opcode, payload)
            if isinstance(result, tuple):
                result_code, response_param = result
            else:
                result_code, response_param = result, []
        else:
            logger.warning("Recieved FitnessMachineControlPoint request, but no command handler has been set by your application logic so the request cannot be processed.")
            result_code, response_param = 0x01, []  # Operation failed

        self.PropertiesChanged(
            GATT_CHRC_IFACE,
            {'Value': self._build_response(opcode_value, result_code, response_param)},
            []
        )

    def _build_response(self, opcode, result_code, param=None):
        response = [dbus.Byte(0x80), dbus.Byte(opcode), dbus.Byte(result_code)]
        if param:
            response += [dbus.Byte(b) for b in param]
        return response


class FitnessMachineFeature(Characteristic):
    #Currently this supports only the Fitness Machine Field, not the Target Setting Features Field
    UUID = '2acc'
    '''
    Define the 8-byte flag array for the FTMS Feature Characteristic.
    The flags specify what fields the Fitness Machine will provide.
    See Bluetooth_FTMS_v1.0.1.pdf 4.3.1.1 for bit field definition.
    The octets are little endian.
    '''
    class FitnessMachineFeatureFlags(IntFlag):
        # Octet 0
        FTMF_AVERAGE_SPEED_SUPPORTED           = 1 << 0
        FTMF_CADENCE_SUPPORTED                 = 1 << 1
        FTMF_TOTAL_DISTANCE_SUPPORTED          = 1 << 2
        FTMF_INCLINATION_SUPPORTED             = 1 << 3
        FTMF_ELEVATION_GAIN_SUPPORTED          = 1 << 4
        FTMF_PACE_SUPPORTED                    = 1 << 5
        FTMF_STEP_COUNT_SUPPORTED              = 1 << 6
        FTMF_RESISTANCE_LEVEL_SUPPORTED        = 1 << 7

        # Octet 1
        FTMF_STRIDE_COUNT_SUPPORTED            = 1 << 8
        FTMF_EXPENDED_ENERGY_SUPPORTED         = 1 << 9
        FTMF_HEART_RATE_MEASUREMENT_SUPPORTED  = 1 << 10
        FTMF_METABOLIC_EQUIV_SUPPORTED         = 1 << 11
        FTMF_ELAPSED_TIME_SUPPORTED            = 1 << 12
        FTMF_REMAINING_TIME_SUPPORTED          = 1 << 13
        FTMF_POWER_MEASUREMENT_SUPPORTED       = 1 << 14
        FTMF_FORCE_MEASUREMENT_SUPPORTED       = 1 << 15

        # Octet 2
        FTMF_USER_DATA_RETENTION_SUPPORTED     = 1 << 16

    def __init__(self, bus, index, service, supported_features=FitnessMachineFeatureFlags(0)):
        super().__init__(
            bus, index,
            self.UUID,
            ['read'],
            service
        )
        self._features = supported_features

    def set_features(self, features: FitnessMachineFeatureFlags):
        self._features = features

    def ReadValue(self, options):
        bitfield = self._features.value.to_bytes(8, byteorder='little')  # 8 bytes required by spec
        value = [dbus.Byte(b) for b in bitfield]
        logger.debug(f'FTMS Feature Flags: {self._features} ({value})')
        return value