# ---------------------------------------------------------------------------
# Based on the inonoob repo "pirowflo"
# https://github.com/inonoob/pirowflo
# Which in turn was based on the bfritscher Repo "waterrower"
# https://github.com/bfritscher/waterrower
# Extensively refactored and expanded for WRowFusion
# ---------------------------------------------------------------------------

import threading
import logging

import time
import serial
import serial.tools.list_ports

from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(__name__)

'''
The MEMORY_MAP details the organisation of data within the S4 memory registers, how many bytes each datum
occupies, the numerical base of its encoding, the LSB/MSB byte order (endianess), and whether the datum 
should be requested as part of the high-frequency thread that requests data from the S4.

By configuring a datum in the MEMORY MAP and equiping it with a key: value pair of 'exclude_from_poll_loop': True (e.g. for tank size), 
the application can still request the a read of the datum on demand. However it will not be requested as part of the
high frequency request thread, leading to improved efficiency. 

Note: The Water Rower S4 S5 USB Protocol Iss 1 04 specs incorrectly suggests that double digit data is 
stored:
- little endian (i.e. low byte first, high byte second) for primary data (i.e. data that is
directly measured such as distance)
- big endian (i.e. high byte first, low byte second) for computed data (i.e. 'maths' data that is
computed from the directly measured data such as 500m pace)
It appears, however, that it is exactly the opposite.
'''

MEMORY_MAP = {
                '055': {'type': 'total_distance', 'size': 'double', 'base': 16, 'endian': 'big'},           # distance in metres since reset
                '054': {'type': 'total_distance_dec', 'size': 'single', 'base': 16, 'endian': 'big'},       # centimetres component of distance to nearest 5cm (i.e. 0-95).
                '088': {'type': 'watts', 'size': 'double', 'base': 16, 'endian': 'big'},                    # instantaneous power
                '08A': {'type': 'total_kcal', 'size': 'triple', 'base': 16, 'endian': 'big'},               # calories since reset
                '0A9': {'type': 'tank_volume', 'size': 'single', 'base': 16, 'endian': 'big', 'exclude_from_poll_loop': True}, # tank volume in litres
                # Stroke counter
                '140': {'type': 'stroke_count', 'size': 'double', 'base': 16, 'endian': 'big'},             # total strokes since reset
                '142': {'type': 'avg_time_stroke_whole', 'size': 'single', 'base': 16, 'endian': 'big'},    # average time for a whole stroke measured in number of 25ms periods
                '143': {'type': 'avg_time_stroke_pull', 'size': 'single', 'base': 16, 'endian': 'big'},     # average time for a pull (acc to dec) measured in number of 25ms periods
                # Speed
                '148': {'type': 'total_speed_cmps', 'size': 'double', 'base': 16, 'endian': 'big'},         # total distance per second in cm
                '14A': {'type': 'avg_distance_cmps', 'size': 'double', 'base': 16, 'endian': 'big'},        # instantaneous average distance in cm
                # Values stored for zone maths
                '1A0': {'type': 'heart_rate', 'size': 'single', 'base': 16, 'endian': 'big'},               # instantaneous heart rate
                '1A5': {'type': '500mps', 'size': 'double', 'base': 16, 'endian': 'little', 'exclude_from_poll_loop': True},   # instantaneious 500m Pace (secs)
                '1A9': {'type': 'stroke_rate', 'size': 'single', 'base': 16, 'endian': 'big'},              # instantaneous strokes per min
                # Clock Display - Capture time components in reverse order for time elapsed accuracy  
                '1E3': {'type': 'display_hr', 'size': 'single', 'base': 10, 'endian': 'big'},               # hours 0-9
                '1E2': {'type': 'display_min', 'size': 'single', 'base': 10, 'endian': 'big'},              # minutes 0-59
                '1E1': {'type': 'display_sec', 'size': 'single', 'base': 10, 'endian': 'big'},              # seconds 0-59
                '1E0': {'type': 'display_sec_dec', 'size': 'single', 'base': 10, 'endian': 'big', 'exclude_from_poll_loop': True},          # tenths of seconds 0-9
                # Workout total times/distances/limits
                '1E8': {'type': 'workout_total_time', 'size': 'double', 'base': 16, 'endian': 'big'},       # total workout time
                '1EA': {'type': 'workout_total_mps', 'size': 'double', 'base': 16, 'endian': 'big'},        # total workout m/s
                '1EC': {'type': 'workout_total_strokes', 'size': 'double', 'base': 16, 'endian': 'big'},    # total workout strokes
                '1EE': {'type': 'workout_limit', 'size': 'double', 'base': 16, 'endian': 'big'},            # limit value for workouts
             }

'''
Notes:
(*) total_distance_dec holds the centimetres part of the distance to the nearest 5cm, not "0.1m count (only counts up from 0-9)"
    as documented in Water Rower S4 S5 USB Protocol Iss 1 04.pdf.
(*) Any effort to combine the cm value with the metres value will be complicated by the serial delivery. As the values are recieved 
    one after the other, care must be taken to retrieve the cm component and the metres component with minimal delay in between. 
    Consider a request being written to the serial for the cms component when the actual distance is 138.95 cms. The rower will 
    respond with 95cms. If the distance were to change by just 5cm before the second request for the metres component is received, 
    then the rower will report a metres component of 139m. Combining the components would make the distance appear to be 139.95
    - neither reflecting the 138.95m at the time of the first request, nor the 139.0m at the time of the second request. 
(*) Watts are available intermittently. The overwhelming majority of requests for Watts receive a response with value 0.
    Non-zero Watts are sometimes returned for one or two readings per stroke (typically at the same value), but often with
    no non-zero readings for one or two strokes at a time. To have availability at all times, average the watts over a number
    of non-zero readings for a number of different strokes. Averaging readings from 4 different strokes appears to match the
    S4 watts display closely. Or use the concept2 formula which derives power from 500m pace.
(*) stroke_average and stroke_pull appear to be measured in number of 25ms periods. 
(*) From the documenation in Water Rower S4 S5 USB Protocol Iss 1 04.pdf:
    "Stroke_pull is first subtracted from stroke_average then a modifier of 1.25 multiplied by the result to generate the ratio 
    value for display." It is unclear where this ratio is ever displayed, or what it intends to signify. The naming as a ratio
    does not match the computation that is described.
(*) total_speed_cmps is highly volatile. On the test rower, it appeared to oscilate between a bigger reading and a smaller reading.
    During light rowing, a single drive phase of the stroke might see values of 140 +/-35 (smaller reading) and 350 +/-35 (higher 
    reading), while a single recovery phase might see values of 35 +/-35 (smaller reading) 210 +/-35 (higher reading).
    The avg_distance_cmps is much smoother, and might be more useful for computing meaningful speed/pace etc. 
(*) 500m Pace is computed by the S4 only when units of /500m are selected on screen. If other units are being displayed, the 
    value of 0 is stored in the 500m pace memory register and 0 is returned over the serial connection. To have availability
    at all times, compute the 500m pace from the avg_distance_cmps.
(*) Because the time components are sent in separate packets, the delays between packets being recieved can result in errors
    when recombining the time elements. Consider the two scenarios below. In practice, there's a 25ms gap between each response
    even when the requests are made immediately one after the other. The tables illustrate the errors encountered when the
    components are requested in order of significance and reverse order.
                                    Recieved component
    Time of request         Big to small        Small to big
    1.59.59.925             hr:     01          dec:     9 (wr min resolution is 100ms)
    1.59.59.950             min:    59          sec:    59 
    1.59.59.975             sec:    59          min:    59
    2.00.00.000             dec:     0          hr:     02
    Apparent time:          01:59:59:0          02:59:59:9
    Innaccuracy:           -00:00:01:0         +00:59:59:9

    Time of request         Big to small        Small to big
    1.59.59.850             hr:     01          dec:     8 (wr min resolution is 100ms)
    2.00.00.100             min:    00          sec:    00 
    2.00.00.350             sec:    00          min:    00
    2.00.00.600             dec:     6          hr:     02
    Apparent time:          01:00:00:6          02:00:00:8
    Innaccuracy:           -01:00:00:0         +00:00:00:2

    Therefore, large albeit short-lived errors can occur irrespective of which order you request the components.
    Applications that cannot tolerate such errors will have to implement strategies to eliminate them, for example
    by comparing the difference in compiled times since last computed and ignoring unlikely values, or comparing time 
    components since last received and being confident only in values that match the last reported set.
    As the most significant components (hr and min) are least volatile, it makes sense to request them first because
    they are less likely to change over the short period of time when you are requesting and receiving the time components.
'''

# Packet identifiers as speicified in Water Rower S4 S5 USB Protocol Iss 1 04.pdf.

# ACH values = Ascii coded hexadecimal
# REQUEST sent from PC to device
# RESPONSE sent from device to PC

USB_REQUEST = "USB"                # First packet to be sent in order to instruct S4 to establish communications
MODEL_INFORMATION_REQUEST = "IV?"  # Request Model Information
READ_MEMORY_REQUEST = "IR"         # Read a memory location IR+(S=Single,D=Double,T=Triple) + XXX (XXX is in ACH format)
RESET_REQUEST = "RESET"            # Request the rowing computer to reset (equivalent to user holding on button for 2 secs), disable interactive mode
EXIT_REQUEST = "EXIT"              # Application is exiting, stop sending packets

WR_RESPONSE = "_WR_"               # Hardware Type response to acknowledge USB_REQUEST and initiate sending packets
MODEL_INFORMATION_RESPONSE = "IV"  # Current model information IV+Model(4 or 5)+Firmware Version High+Firmware Version Low (e.g for Firmware 02.10, High is 02, low is 10)
READ_MEMORY_RESPONSE = "ID"        # Value from a memory location ID +(type) + Y3 Y2 Y1
STROKE_START_RESPONSE = "SS"       # Start of stroke (just a packet - no data. Can be sent with very minor movement of paddle even if no rowing is occuring.)
STROKE_END_RESPONSE = "SE"         # End of stroke (just a packet - no data. Can be sent with very minor movement of paddle even if no rowing is occuring.)
PULSE_COUNT_RESPONSE = "P"         # Pulse Count XX in the last 25mS, ACH value. Pulses are triggered by pins on the pulley and so pulse count corresponds to pulley rotation.
OK_RESPONSE = "OK"                 # Packet Accepted - Sent in cases where no other reply would otherwise be given.
PING_RESPONSE = "PING"             # Ping sent once per second while no rowing is occuring
ERROR_RESPONSE = "ERROR"           # Unknown packet recieved.


# Display Settings (not used) allow the PC to set the required display parameters.
DISPLAY_SET_INTENSITY_MPS_REQUEST = "DIMS"          # Set Intensity - Metres per second
DISPLAY_SET_INTENSITY_MPH_REQUEST = "DIMPH"         # Set Intenisty - MPH
DISPLAY_SET_INTENSITY_500M_REQUEST = "DI500"        # Set Intensity - 500m split
DISPLAY_SET_INTENSITY_2KM_REQUEST = "DI2KM"         # Set Intensity - 2km split
DISPLAY_SET_INTENSITY_WATTS_REQUEST = "DIWA"        # Set Intensity - Watts
DISPLAY_SET_INTENSITY_CALHR_REQUEST = "DICH"        # Set Intensity - Cal/Hr
DISPLAY_SET_INTENSITY_AVG_MPS_REQUEST = "DAMS"      # Set Intensity - Average metres per sec
DISPLAY_SET_INTENSITY_AVG_MPH_REQUEST = "DAMPH"     # Set Intensity - Average MPH
DISPLAY_SET_INTENSITY_AVG_500M_REQUEST = "DA500"    # Set Intensity - Average 500m split
DISPLAY_SET_INTENSITY_AVG_2KM_REQUEST = "DA2KM"     # Set Intensity - Average 2km split
DISPLAY_SET_DISTANCE_METERS_REQUEST = "DDME"        # Set Distance - Metres 
DISPLAY_SET_DISTANCE_MILES_REQUEST = "DDMI"         # Set Distance - Miles
DISPLAY_SET_DISTANCE_KM_REQUEST = "DDKM"            # Set Distance - Km
DISPLAY_SET_DISTANCE_STROKES_REQUEST = "DDST"       # Set Distance - Strokes

# Interactive mode

INTERACTIVE_MODE_START_RESPONSE = "AIS"        # interactive mode requested by S4 user (sent from S4 to PC)
INTERACTIVE_MODE_START_ACCEPT_REQUEST = "AIA"  # confirm interactive mode (sent from PC to S4). S4 key input will be redirected to PC.
INTERACTIVE_MODE_END_REQUEST = "AIE"           # cancel interactive mode (sent from PC to S4)
INTERACTIVE_KEYPAD_RESET_RESPONSE = "AKR"      # RESET key pressed, interactive mode will be cancelled (sent from S4 to PC)
INTERACTIVE_KEYPAD_UNITS_RESPONSE = "AK1"      # Units button pressed
INTERACTIVE_KEYPAD_ZONES_RESPONSE = "AK2"      # Zones button pressed
INTERACTIVE_KEYPAD_WORKOUT_RESPONSE = "AK3"    # Workout button pressed
INTERACTIVE_KEYPAD_UP_RESPONSE = "AK4"         # Up arrow button pressed
INTERACTIVE_KEYPAD_OK_RESPONSE = "AK5"         # Ok button pressed
INTERACTIVE_KEYPAD_DOWN_RESPONSE = "AK6"       # Down arrow button pressed
INTERACTIVE_KEYPAD_ADVANCED_RESPONSE = "AK7"   # Advanced button pressed
INTERACTIVE_KEYPAD_STORED_RESPONSE = "AK8"     # Stored Programs button pressed
INTERACTIVE_KEYPAD_HOLD_RESPONSE = "AK9"       # Hold/cancel button pressed

# Workout
WORKOUT_SET_DISTANCE_REQUEST = "WSI"                 # Define a distance workout + x(unit, 1-4) + YYYY = ACH
WORKOUT_SET_DURATION_REQUEST = "WSU"                 # Define a duration workout + YYYY = ACH seconds
WORKOUT_INTERVAL_START_SET_DISTANCE_REQUEST = "WII"  # Define an interval distance workout
WORKOUT_INTERVAL_START_SET_DURATION_REQUEST = "WIU"  # Define an interval duration workout
WORKOUT_INTERVAL_ADD_END_REQUEST = "WIN"             # Add/End an interval to a workout XXXX(==FFFFF to end) + YYYY

# UNITS
UNIT_METERS = 1
UNIT_MILES = 2
UNIT_KM = 3
UNIT_STROKES = 4

SIZE_MAP = {
    'single': {'request': 'IRS', 'response': 'IDS'},
    'double': {'request': 'IRD', 'response': 'IDD'},
    'triple': {'request': 'IRT', 'response': 'IDT'},
    }

UNIT_MAP = {
    'meters': 1,
    'miles': 2,
    'km': 3,
    'strokes': 4,
    }

SIZE_PARSE_MAP = {'single': lambda cmd: cmd[6:8],
                  'double': lambda cmd: cmd[6:10],
                  'triple': lambda cmd: cmd[6:12]}

EXPECTED_RESPONSE_MAP = {
    USB_REQUEST: WR_RESPONSE, 
    MODEL_INFORMATION_REQUEST: MODEL_INFORMATION_RESPONSE, 
    EXIT_REQUEST: OK_RESPONSE, 
    RESET_REQUEST: OK_RESPONSE,
    READ_MEMORY_REQUEST: READ_MEMORY_RESPONSE,
}

# PROGRAM CONTROL DELAYS
PORT_SCAN_RETRY_DELAY = 5   
SERIAL_OPEN_RETRY_DELAY = 5

# CUSTOM EXCEPTIONS
class SerialNotConnectedError(Exception):
    pass

class EventParseError(Exception):
    pass

# CUSTOM DATACLASS
@dataclass
class S4Event:
    type: str
    value: Optional[int] = None
    raw: Optional[str] = None
    at: int = int(round(time.time() * 1000))  # timestamp in ms

    @staticmethod
    def build(type: str, value: Optional[int] = None, raw: Optional[str] = None) -> 'S4Event':
        return S4Event(type=type, value=value, raw=raw, at=int(round(time.time() * 1000)))

    @classmethod
    def parse_line(cls, line: bytes) -> Optional['S4Event']:
        try:
            cmd = line.strip().decode('utf8')
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode line from S4: {line!r}, error: {e}")
            return None

        if cmd == STROKE_START_RESPONSE:
            return cls.build(type='stroke_start', raw=cmd)
        elif cmd == STROKE_END_RESPONSE:
            return cls.build(type='stroke_end', raw=cmd)
        elif cmd == OK_RESPONSE:
            return cls.build(type='ok', raw=cmd)
        elif cmd.startswith(MODEL_INFORMATION_RESPONSE):
            return cls.build(type='model', raw=cmd)
        elif cmd.startswith(READ_MEMORY_RESPONSE):
            return read_reply(cmd)
        elif cmd == PING_RESPONSE:
            return cls.build(type='ping', raw=cmd)
        elif cmd.startswith(PULSE_COUNT_RESPONSE):
            return cls.build(type='pulse', raw=cmd)
        elif cmd == ERROR_RESPONSE:
            return cls.build(type='error', raw=cmd)
        elif cmd == WR_RESPONSE:
            return cls.build(type='wr', raw=cmd)
        else:
            logger.warning(f"Unrecognised command line captured from S4: {cmd}")
            return None

# HELPER FUNCTIONS
def find_port():
    logger.info(f"Searching for serial port...")
    attempts = 0
    while True:
        # If a port isn't found, the code will remain in this loop.
        attempts += 1
        ports = serial.tools.list_ports.comports()
        for (i, (path, name, _)) in enumerate(ports):
            if "WR-S4" in name:
                logger.info(f"Serial port found: {path}")
                return path
        
        if ((attempts - 1) % 360) == 0: # message every ~30 minutes
            logger.warning(f"Serial port not found in {attempts}; retrying every {PORT_SCAN_RETRY_DELAY}s")
        time.sleep(PORT_SCAN_RETRY_DELAY)


def get_address_of_data_type(data_type: str) -> str:
    """
    Gets the S4 memory address for a data type.
    Args: data_type (str): The type of the datum as defined in MEMORY_MAP (e.g., 'total_distance').
    Returns:
        str: The register address where the data type is stored in S4 memory
    """
    for address, data in MEMORY_MAP.items():
        if data['type'] == data_type:
            return address
    logger.error(f"Cannot request data type {data_type} via serial connection because the data type has not been configured in MEMORY_MAP.")
    raise ValueError(f"Data type {data_type} not found in MEMORY MAP")
    

def build_daemon(target):
    t = threading.Thread(target=target)
    t.daemon = True
    return t


def is_live_thread(t):
    return t and t.is_alive()


def read_reply(cmd: str) -> Optional[S4Event]:
    if len(cmd) < 6:
        logger.warning(f"Failed to parse S4 read memory response: the received command was too short to contain address: {cmd!r}")
        return None
    
    address = cmd[3:6]
    memory = MEMORY_MAP.get(address)
    if not memory:
        logger.warning(f"Failed to parse S4 read memory response: MEMORY_MAP has not been configured for the recieved command: {cmd!r}.")
        return None

    size = memory['size']
    endian = memory.get('endian', 'big')  # Default to big if unspecified
    # Get the appropriate function to extract the value from the command string depending on whether it's single, double, triple.
    # Default to None if size isn't found in PARSE_MAP
    value_fn = SIZE_PARSE_MAP.get(size, lambda cmd: None) 

    if not value_fn:
        logger.warning(f"Failed to parse S4 read memory response: Unsupported size '{size}' for address {address} in command: {cmd!r}")
        return None
    
    # Apply the function to extract the value from the command (will return zero length str if cmd is too short for example)
    value_str = value_fn(cmd)

    if value_str is None:
        logger.warning(f"Failed to parse S4 read memory reponse: Could not extract a value of size: {size} from command: {cmd!r}")
        return None
    
    try:
        value = int(value_str, base=memory['base'])
    except ValueError as e:
        logger.warning(f"Failed to parse S4 read memory reponse: Invalid number format in value '{value_str}' from command: {cmd!r} — Error: {e}")
        return None
    
    # Swap bytes if necessary (not applicable for single, so only for double and triple types)
    if endian == 'little':
        try:
            if size == 'double' and len(value_str) == 4:
                high = int(value_str[0:2], 16)
                low = int(value_str[2:4], 16)
                value = (low << 8) | high
            elif size == 'triple' and len(value_str) == 6:
                high = int(value_str[0:2], 16)
                mid  = int(value_str[2:4], 16)
                low  = int(value_str[4:6], 16)
                value = (low << 16) | (mid << 8) | high
        except ValueError as e:
            logger.warning(f"Failed to parse S4 read memory reponse: Error during byte-swapping for little-endian data in command: {cmd!r} — {e}")
            return None
        
    return S4Event.build(memory['type'], value, cmd)


def get_command_string(prefix_type: str, request_type: str, address: Optional[str] = None) -> str:
    """
    Returns the string to be sent to or received from the S4 for a given request type.
    Args:
        prefix_type (str): Either "request" or "response" to specify which prefix to get.
        request_type (str): The type of request (e.g., "USB", "IR").
        address (str, optional): The memory address for READ_MEMORY_REQUEST ("IR").
    Returns:
        str: The request or response string.
    Raises:
        ValueError: If the request_type is invalid, address is missing for "IR", or prefix_type is invalid.
    """
    if prefix_type not in ('request', 'response'):
        raise ValueError(f"Invalid prefix type: {prefix_type}. Must be 'request' or 'response'.")
    
    if request_type == READ_MEMORY_REQUEST:
        if address is None:
            raise ValueError("Address is required for READ_MEMORY_REQUEST (IR)")
        if address not in MEMORY_MAP:
            raise ValueError(f"Address {address} not found in MEMORY_MAP")
        size = MEMORY_MAP[address]['size']
        if not size:
            raise ValueError(f"MEMORY_MAP is missing size definition for address {address}")
        prefix = SIZE_MAP[size][prefix_type]
        if not prefix:
            raise ValueError(f"SIZE_MAP is missing {prefix_type} definition for size '{size}'")
        return prefix + address
    elif request_type in EXPECTED_RESPONSE_MAP:
        if prefix_type == 'request':
            return request_type
        else:
            return EXPECTED_RESPONSE_MAP[request_type]
    else:
        raise ValueError(f"Invalid request type: {request_type}")
    

class Rower(object):
    def __init__(self, options=None):
        self._callbacks = set()
        self._stop_event = threading.Event()
        # if options and options.demo:
        #     from demo import FakeS4
        #     self._serial = FakeS4()
        #     self._demo = True
        # else:
        self._demo = False
        self._serial = serial.Serial()
        self._serial.baudrate = 19200
        self._request_thread = None
        self._capture_thread = None
        self._response_event = threading.Event()  # For on-demand responses
        self._current_response = None

        self._start_threads()

    def _start_threads(self):
        logger.debug("Create and start S4 data request and capture threads...")
        self._request_thread = build_daemon(target=self._start_requesting)
        self._capture_thread = build_daemon(target=self._start_capturing)
        self._request_thread.start()
        self._capture_thread.start()
        logger.debug("S4 data request and capture threads started.")

    def is_connected(self):
        return self._serial.isOpen() and is_live_thread(self._request_thread) and \
            is_live_thread(self._capture_thread)

    def _find_serial(self):
        if not self._demo:
            self._serial.port = find_port()

        try:
            logger.debug("Attempting to open serial port...")
            self._serial.open()
            logger.info("Serial port open.")
        except serial.SerialException as e:
            logger.error(f"Error encountered opening serial port: {e}. Retrying in {SERIAL_OPEN_RETRY_DELAY} seconds")
            time.sleep(SERIAL_OPEN_RETRY_DELAY)
            self._serial.close()
            self._find_serial()

    def open(self):
        # Any caller asking for Rower.open() will not recieve control back until:
        # - the port is found, otherwise the code loops in find_port()
        # - and the serial is open without error, otherwise the code loops in _find_serial()

        if self._serial and self._serial.isOpen():
            logger.debug("Closing existing serial connection.")
            self._serial.close()

        self._find_serial()

        if self._stop_event.is_set():
            logger.info("Reset S4 communication: clear stop event.")
            self._stop_event.clear()
            self._start_threads()

        logger.info("Initiating communication with S4 monitor.")
        self.write(USB_REQUEST)

    def close(self):
        logger.debug("Closing serial communications with S4.")
        self.notify_callbacks(S4Event.build("exit"))
        if self._stop_event:
            self._stop_event.set()
        if self._serial and self._serial.isOpen():
            self.write(EXIT_REQUEST)
            time.sleep(0.1)  # time for capture and request loops to stop running
            self._serial.close()

    def write(self, raw: str):
        try:
            self._serial.write(str.encode(raw.upper() + '\r\n'))
            self._serial.flush()
        except Exception as e:
            logger.error(f"Serial write communication error: {e}. Trying to reconnect.")
            self.open()

    def _start_capturing(self):
        while not self._stop_event.is_set():
            if self._serial.isOpen():
                try:
                    line = self._serial.readline()
                    event = S4Event.parse_line(line)
                    if event:
                        self.notify_callbacks(event)
                except serial.SerialException as e:
                    logger.error(f"Serial read communication error: {e}. Trying to reset input buffer.")
                    try:
                        self._serial.reset_input_buffer()
                    except serial.SerialException as e2:
                        logger.error(f"Could not reset serial input buffer: {e2}")
                    raise  # Re-raise the original serial exception
                except TypeError as e:
                    logger.error(f"TypeError  error: {e}.")
                    raise
            else:
                self._stop_event.wait(0.1)

    def _start_requesting(self):
        while not self._stop_event.is_set():
            if self._serial.isOpen():
                for address in MEMORY_MAP:
                    if 'exclude_from_poll_loop' not in MEMORY_MAP[address] or MEMORY_MAP[address]['exclude_from_poll_loop'] != True:
                        self.request_address(address)
                        self._stop_event.wait(0.025)
            else:
                self._stop_event.wait(0.1)


    def request_reset(self):
        logger.debug("Sending reset request to S4 via serial connection.")
        self.write(RESET_REQUEST)
        self.notify_callbacks(S4Event.build('reset'))


    def request_address(self, address: str):
        """
        Requests a datum from the S4 monitor by its memory address.
        Args: address (str): The address of the S4 memory register where the desired datum is stored (e.g., '055').
        """
        if not address in MEMORY_MAP:
            logger.error(f"Cannot request address {address} via serial connection because the address has not been configured in MEMORY_MAP.")
            raise ValueError(f"Address {address} not found in MEMORY_MAP")
        
        size = MEMORY_MAP[address]['size']
        cmd = SIZE_MAP[size]['request']
        self.write(cmd + address)


    def request_on_demand(self, request_type: str, address: Optional[str] = None) -> S4Event:
        """Sends a request to the S4 monitor and waits for the response.
        Constructs the request and expected response prefix using the request type and optional address.
        Sends the request via serial, clears the input buffer beforehand, and waits for the matching response.
        Args:
            request_type (str): Type of request to send (e.g., 'IR').
            address (str, optional): Memory address to query, required for memory reads.
        Returns:
            S4Event: Parsed response from the S4 monitor.
            For events that do not expect a response, the S4Event dict will be empty other than type = 'none'.
            The caller can therefore deduce that the expected response was not received if this function returns None
            and the caller can therefore take appropriate action.
        Raises:
            Exception: If any error occurs during serial I/O or response handling.
        """
        request = get_command_string('request', request_type, address)
        expected_response_prefix = get_command_string('response', request_type, address)

        try:
            self._serial.reset_input_buffer()
            self.write(request)
            if expected_response_prefix:
                return self.capture_on_demand_response(expected_response_prefix)
            else:
                return S4Event.build('none')
        except Exception:
            logger.error(f"Error during on-demand request with command: {request_type} and address: {address}")
            raise


    def capture_on_demand_response(self, expected_response_prefix: str, timeout=2) -> S4Event:
        """
        Reads from the serial port until a response with the expected prefix is received, or timeout.
        Args:
            expected_response_prefix (str): The expected beginning of the response.
            timeout (int): Maximum time to wait in seconds.
        Returns:
            S4Event: The complete parsed response if received before timeout.
        Raises:
            SerialNotConnectedError: If the serial port is not open.
            TimeoutError: If the expected response is not received within the timeout.
            serial.SerialException: If an error occurs during serial communication.
            TypeError:If a type error occurs
        """

        if not self._serial or not self._serial.isOpen():
            raise SerialNotConnectedError("Serial port is not connected.")
            
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                line = self._serial.readline()
                if not line:
                    continue    # No data received, so return to the top of the while and iterate again.
                    
                cmd = line.strip().decode('utf8')
                if cmd.startswith(expected_response_prefix):
                    return S4Event.parse_line(line)
            except serial.SerialException as e:
                logger.error(f"Serial read communication error: {e}. Trying to reset input buffer.")
                try:
                    self._serial.reset_input_buffer()
                except serial.SerialException as e2:
                    logger.error(f"Could not reset serial input buffer: {e2}")
                raise  # Re-raise the original serial exception
            except TypeError as e:
                logger.error(f"TypeError  error: {e}.")
                raise
        logger.warning(f"Timeout waiting for response with prefix {expected_response_prefix}")
        raise TimeoutError(f"Timeout waiting for response with prefix {expected_response_prefix}")

    def register_callback(self, cb):
        logger.debug(f"Registering serial communication callback - {cb}")
        self._callbacks.add(cb)

    def remove_callback(self, cb):
        logger.debug(f"De-registering serial communication callback - {cb}")
        self._callbacks.remove(cb)

    def notify_callbacks(self, event: S4Event):
#        logger.debug(f"Rower.notify_callbacks: Notifing callbacks of event {event}")
        for cb in self._callbacks:
#            logger.debug(f"Rower.notify_callbacks: Notifying callback {cb} of event {event}")
            cb(event)