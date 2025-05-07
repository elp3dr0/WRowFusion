import dbus
import logging
import struct
from enum import Enum, IntFlag
from dataclasses import dataclass

from src.bleif import Service, Characteristic

logger = logging.getLogger(__name__)

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

class DeviceInformation(Service):
    UUID = '180A'

    def __init__(self, bus, index):
        super().__init__(bus, index, self.UUID, True)
        self.manufacturer = self.ManufacturerNameString(bus, 0, self)
        self.model = self.ModelNumberString(bus, 1, self)
        self.serial = self.SerialNumberString(bus, 2, self)
        self.hardware = self.HardwareRevisionString(bus, 3, self)
        self.firmware = self.FirmwareRevisionString(bus, 4, self)
        self.software = self.SoftwareRevisionString(bus, 5, self)
        self.system_id = self.SystemID(bus, 6, self)

        self.add_characteristic(self.manufacturer)
        self.add_characteristic(self.model)
        self.add_characteristic(self.serial)
        self.add_characteristic(self.hardware)
        self.add_characteristic(self.firmware)
        self.add_characteristic(self.software)
        self.add_characteristic(self.system_id)

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

    class SystemID(Characteristic):
        UUID = '2A23'

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
    # Currently this supports only the Fitness Machine Field, not the Target Setting Features Field
    # The caller application should ensure that it sets the Feature bits and the RowerData flags such
    # that they are in agreement (see RowerData class to which flags correspond to which feature bits)
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
    

class HeartRateService(Service):
    UUID = '180D'

    def __init__(self, bus, index):
        super().__init__(bus, index, self.UUID, True)

class HeartRateMeasurementCharacteristic(Characteristic):
    UUID = '2a37'

    def __init__(self, bus, index, service):
        super().__init__(
            bus, index,
            self.UUID,
            ['notify'],
            service)
        self.notifying = False

    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        self._update()

    def StopNotify(self):
        self.notifying = False

    def _update(self):
        raise NotImplementedError("Must be implemented in subclass or injected")


# Flag bitmask for all defined field groups
class RowingFieldFlags(IntFlag):
    STROKE_INFO = 1 << 0  # Shared: stroke rate & count (inverted flag)
    AVERAGE_STROKE_RATE = 1 << 1
    TOTAL_DISTANCE = 1 << 2
    INSTANT_PACE = 1 << 3
    AVERAGE_PACE = 1 << 4
    INSTANT_POWER = 1 << 5
    AVERAGE_POWER = 1 << 6
    RESISTANCE_LEVEL = 1 << 7
    EXPENDED_ENERGY = 1 << 8  # Shared: total energy, per hour, per min
    HEART_RATE = 1 << 9
    METABOLIC_EQUIVALENT = 1 << 10
    ELAPSED_TIME = 1 << 11
    REMAINING_TIME = 1 << 12

# Metadata describing how to encode each group of fields
@dataclass
class Field:
    name: str
    format: str  # Format of the data (e.g. 'B', 'H', 'h', 'I') using the standard format chars of the struct module.
    size: int
    signed: bool = False

# Map from flags to the fields in each group
FIELD_GROUPS = [                                                                            ### CORRESPONDING Fitness Machine Feature Support bit ###
    (RowingFieldFlags.STROKE_INFO, [                                                         # No corresponding Feature bit
        Field("stroke_rate", "B", 1),    # uint8    
        Field("stroke_count", "H", 2),   # uint16
    ]),
    (RowingFieldFlags.AVERAGE_STROKE_RATE, [Field("avg_stroke_rate", "B", 1)]),               # Cadence Supported (bit 1)
    (RowingFieldFlags.TOTAL_DISTANCE, [Field("total_distance", "I", 3)]),  # 24-bit           # Total Distance Supported (bit 2)
    (RowingFieldFlags.INSTANT_PACE, [Field("instant_pace", "H", 2)]),                         # Pace Supported (bit 5)
    (RowingFieldFlags.AVERAGE_PACE, [Field("avg_pace", "H", 2)]),                             # Pace Supported (bit 5)
    (RowingFieldFlags.INSTANT_POWER, [Field("instant_power", "h", 2, True)]),  # sint16       # Power Measurement Supported (bit 14)
    (RowingFieldFlags.AVERAGE_POWER, [Field("avg_power", "h", 2, True)]),         # sint16    # Power Measurement Supported (bit 14)
    (RowingFieldFlags.RESISTANCE_LEVEL, [Field("resistance", "B", 1)]),                       # Resistance Level Supported (bit 7)
    (RowingFieldFlags.EXPENDED_ENERGY, [                                                     # Expended Energy Supported (bit 9)
        Field("total_energy", "H", 2),
        Field("energy_per_hour", "H", 2),
        Field("energy_per_min", "B", 1),
    ]),
    (RowingFieldFlags.HEART_RATE, [Field("heart_rate", "B", 1)]),                             # Heart Rate Measurement Supported (bit 10)
    (RowingFieldFlags.METABOLIC_EQUIVALENT, [Field("metabolic_equivalent", "B", 1)]),         # Metabolic Equivalent Supported (bit 11)
    (RowingFieldFlags.ELAPSED_TIME, [Field("elapsed_time", "I", 3)]),  # 24-bit               # Elapsed Time Supported (bit 12)
    (RowingFieldFlags.REMAINING_TIME, [Field("remaining_time", "I", 3)]),                     # Remaining Time Supported (bit 13)
]

class RowerData(Characteristic):
    UUID = '2ad1'

    def __init__(self, bus, index, service, supported_fields=RowingFieldFlags(0)):
        super().__init__(
            bus, index,
            self.UUID,
            ['notify'],
            service)
        self.notifying = False
        self._fields = supported_fields

    def encode(self, field_values: dict) -> bytes:
        """Encode the characteristic value based on supported flags and current data."""
        output = bytearray()
        output += struct.pack("<H", self._fields)  # 2-byte flags field

        for flag, fields in self.FIELD_GROUPS.items():
            include = bool(self._fields & flag)

            # STROKE_INFO is inverted — included when the bit is NOT set
            if flag == RowingFieldFlags.STROKE_INFO:
                include = not include

            if include:
                for field in fields:
                    val = field_values.get(field.name, 0)
                    if field.size == 3:
                        # Struct doesn't support 3-byte values, so fall back to to_bytes which requires us to 
                        # handle signedness manually.
                        output += val.to_bytes(3, byteorder='little', signed=field.signed)
                    else:
                        output += struct.pack('<' + field.format, val)

        return bytes(output)

    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        self._update()

    def StopNotify(self):
        self.notifying = False

    def _update(self):
        raise NotImplementedError("Must be implemented in subclass or injected")
