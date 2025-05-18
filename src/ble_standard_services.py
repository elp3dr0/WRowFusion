import dbus
import logging
import struct
from enum import Enum, IntFlag
from dataclasses import dataclass
from typing import Any

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
            response = self._build_response(opcode_value, result_code=0x02)  # Op code not recognised so return unsupported response.
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': response}, [])
            return
        
        if self.command_handler:
            result = self.command_handler(opcode, payload)
            logger.debug(f"Got result from command_handler {result}")
            if isinstance(result, tuple):
                result_code, response_param = result
            else:
                result_code, response_param = result, []
        else:
            logger.warning("Recieved FitnessMachineControlPoint request, but no command handler has been set by your application logic so the request cannot be processed.")
            result_code, response_param = 0x01, []  # Operation failed

        # BLE FitnessMachineControlPoint specs expect a response as follows:
        # Response code 0x80 followed by the request code and the result code:
        # 0x01 Success, 0x02 opcode not supported, 0x03 invalid parameter, 0x04 operation failed, 0x05 control not permitted
        response = self._build_response(opcode_value, result_code, response_param)
        logger.debug(f"Setting FMCP response: {bytes(response)}")
        self.PropertiesChanged(
            GATT_CHRC_IFACE,
            {'Value': response},
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
class BLEField:
    name: str
    format: str  # Format of the data (e.g. 'B', 'H', 'h', 'I') using the standard format chars of the struct module.
    size: int
    signed: bool = False

    def to_bytes(self, value: int) -> bytes:
        if self.size == 3:
            # struct doesn't support 3-byte fields, so use to_bytes directly
            return value.to_bytes(3, byteorder='little', signed=self.signed)
        else:
            return struct.pack('<' + self.format, value)
        
# Map of BLE Rower Data flags defining the content of each BLE transmission.
# The code currently does not robustly support legacy or limited devices which utilise a small MTU (the max number of 
# octets that can be passed in any single bluetooth payload). To be compliant with Bluetooth specs, a device must accept
# at least an MTU of 23. To support all fields of the RowerData characteristic in one payload, an MTU of 33: (28 data 
# octets, 2 flag octets, and 3 ATT headers). 
# Most modern devices are understood to negotiate an MTN > 50 when the bluetooth connection is made, though it is unknown
# if this is true for limited devices like fitness watches. 
# If the payload exceeds the MTU of a connection, it is not known what behaviour to expect:
# * the bluetooth stack of the sending device might truncate the payload (in which case it will likely be malformed because 
# the flags will no longer reflect the payload, if indeed the flags are not the part that is truncated).
# * the payload might be not be sent at all.
# * something else might happen. 
# 
# Some untested potential options to cater for low MTU environments (listed easy to complex):
# * Remove (or comment out) field groups from the FIELD_GROUPS list, such that the remaining fields total five less than the MTU
#   to allow for the flags and ATT headers. The application will then not support those commented out fields and so the 
#   supported Fitness Machine Feature Flags of the bluetooth advertisement should be adjusted accordingly.
# * Assume MTU = 23 and add logic to send the data in two payloads (the RowerData characteristic has a maximum of 28 octets, so
#   will always fit in two payloads).
# * Determine the actual MTU that is negotiated, or try to negotiate a higher MTU, and then tailor the payload to the actual
#   MTU.

# The field sizes and units were sourced from: https://developer.huawei.com/consumer/en/doc/hmscore-guides/rd-0000001050725868
# because the specifications could not be found in the bluetooth.com specs. 


FIELD_GROUPS = [                                                                            ### CORRESPONDING Fitness Machine Feature Support bit ###
    (RowingFieldFlags.STROKE_INFO, [                                                        # No corresponding Feature bit
        BLEField("stroke_rate", "B", 1),    # uint8    
        BLEField("stroke_count", "H", 2),   # uint16
    ]),
    (RowingFieldFlags.AVERAGE_STROKE_RATE, [BLEField("avg_stroke_rate", "B", 1)]),             # Cadence Supported (bit 1)
    (RowingFieldFlags.TOTAL_DISTANCE, [BLEField("total_distance", "I", 3)]),       # 24-bit    # Total Distance Supported (bit 2)
    (RowingFieldFlags.INSTANT_PACE, [BLEField("instant_pace", "H", 2)]),                       # Pace Supported (bit 5)
    (RowingFieldFlags.AVERAGE_PACE, [BLEField("avg_pace", "H", 2)]),                           # Pace Supported (bit 5)
    (RowingFieldFlags.INSTANT_POWER, [BLEField("instant_power", "h", 2, True)]),   # sint16    # Power Measurement Supported (bit 14)
#    (RowingFieldFlags.AVERAGE_POWER, [BLEField("avg_power", "h", 2, True)]),       # sint16    # Power Measurement Supported (bit 14)
#    (RowingFieldFlags.RESISTANCE_LEVEL, [BLEField("resistance", "h", 2, True)]),                     # Resistance Level Supported (bit 7)
    (RowingFieldFlags.EXPENDED_ENERGY, [                                                    # Expended Energy Supported (bit 9)
        BLEField("total_energy", "H", 2),
        BLEField("energy_per_hour", "H", 2),
        BLEField("energy_per_min", "B", 1),
    ]),
    (RowingFieldFlags.HEART_RATE, [BLEField("heart_rate", "B", 1)]),                           # Heart Rate Measurement Supported (bit 10)
#    (RowingFieldFlags.METABOLIC_EQUIVALENT, [BLEField("metabolic_equivalent", "B", 1)]),       # Metabolic Equivalent Supported (bit 11)
    (RowingFieldFlags.ELAPSED_TIME, [BLEField("elapsed_time", "H", 2)]),                       # Elapsed Time Supported (bit 12)
#    (RowingFieldFlags.REMAINING_TIME, [BLEField("remaining_time", "H", 2)]),                   # Remaining Time Supported (bit 13)
]

class RowerData(Characteristic):
    UUID = '2ad1'

    def __init__(self, bus, index, service):
        super().__init__(
            bus, index,
            self.UUID,
            ['notify'],
            service)
        self.notifying = False

    def encode(self, field_values: dict) -> bytes:
        """
        Determine what flags are supported from the contents of the field_values dict and
        encode the characteristic value accordingly."""
        flags, fields_to_encode = self._prepare_fields_and_flags(field_values)
        # Flip Stroke Info bit, since it has inverted meaning in spec
        flags ^= RowingFieldFlags.STROKE_INFO
        
        output = bytearray()
        output += struct.pack("<H", flags)  # 2-byte flags field

        logger.debug("Encode loop - starting iteration through fields groups")

        for field, value in fields_to_encode:
            logger.debug(f"Build output byte array. Append field: {field.name}")
            output += field.to_bytes(value)

        logger.debug(f"Bluetooth payload complete: {output}")
        return bytes(output)
    
    def _prepare_fields_and_flags(self, field_values: dict[str, Any]) -> tuple[RowingFieldFlags, list[tuple[BLEField, Any]]]:
        '''Determine the RowerData characteristic flags depending on what fields are present in the data'''
        flags = RowingFieldFlags(0)
        fields_to_encode: list[tuple[BLEField, Any]] = []

        for flag, field_group in FIELD_GROUPS:
            group_values = []

            if flag == RowingFieldFlags.STROKE_INFO:
                present_fields = [ble_field for ble_field in field_group if ble_field.name in field_values]
                if not present_fields:
                    continue  # Skip group entirely if none are present
                for ble_field in field_group:
                    value = field_values.get(ble_field.name, 0)  # Default missing fields to 0
                    group_values.append((ble_field, value))
                flags |= flag
                fields_to_encode.extend(group_values)

            elif flag == RowingFieldFlags.EXPENDED_ENERGY:
                any_present = any(ble_field.name in field_values for ble_field in field_group)
                if not any_present:
                    continue  # Skip group entirely
                for ble_field in field_group:
                    if ble_field.name in field_values:
                        value = field_values[ble_field.name]
                    else:
                        value = 0xFFFF if ble_field.size == 2 else 0xFF  # Sentinel for missing values
                    group_values.append((ble_field, value))
                flags |= flag
                fields_to_encode.extend(group_values)

            else:
                ble_field = field_group[0]  # Single-field group
                if ble_field.name in field_values:
                    group_values.append((ble_field, field_values[ble_field.name]))
                    flags |= flag
                    fields_to_encode.extend(group_values)

        return flags, fields_to_encode

    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        self._update()

    def StopNotify(self):
        self.notifying = False

    def _update(self):
        raise NotImplementedError("Must be implemented in subclass or injected")
