# ---------------------------------------------------------------------------
# Original code from the bfritscher Repo waterrower
# https://github.com/bfritscher/waterrower
# ---------------------------------------------------------------------------
#

# -*- coding: utf-8 -*-
import threading
import logging

import time
import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)

'''
The Water Rower S4 S5 USB Protocol Iss 1 04 specs incorrectly suggest that double digit data is 
stored:
- little endian (i.e. low byte first, high byte second) for primary data (i.e. data that is
directly measured such as distance)
- big endian (i.e. high byte first, low byte second) for computed data (i.e. 'maths' data that is
computed from the directly measured data such as 500m pace)
It appears, however, that it is exactly the opposite.
'''

MEMORY_MAP = {
                '055': {'type': 'total_distance_m', 'size': 'double', 'base': 16, 'endian': 'big'},
                '140': {'type': 'total_strokes', 'size': 'double', 'base': 16, 'endian': 'big'},
                '088': {'type': 'watts', 'size': 'double', 'base': 16, 'endian': 'big'},
                '08A': {'type': 'total_kcal', 'size': 'triple', 'base': 16, 'endian': 'big'},
                '14A': {'type': 'avg_distance_cmps', 'size': 'double', 'base': 16, 'endian': 'big'},        # instant average distance in cm
                '148': {'type': 'total_speed_cmps', 'size': 'double', 'base': 16, 'endian': 'big'},         # total distance per second in cm
                '1E0': {'type': 'display_sec_dec', 'size': 'single', 'base': 10, 'endian': 'big'},
                '1E1': {'type': 'display_sec', 'size': 'single', 'base': 10, 'endian': 'big'},
                '1E2': {'type': 'display_min', 'size': 'single', 'base': 10, 'endian': 'big'},
                '1E3': {'type': 'display_hr', 'size': 'single', 'base': 10, 'endian': 'big'},
                # from zone math
                '1A0': {'type': 'heart_rate', 'size': 'single', 'base': 16, 'endian': 'big'},
                '1A5': {'type': '500mps', 'size': 'double', 'base': 16, 'endian': 'little'},                # 500m Pace (secs)
                '1A9': {'type': 'stroke_rate', 'size': 'single', 'base': 16, 'endian': 'big'},
                # explore
                # Stroke_pull is first subtracted from stroke_average then a modifier of 
                # 1.25 multiplied by the result to generate the ratio value for display.
                '142': {'type': 'avg_time_stroke_whole', 'size': 'single', 'base': 16, 'endian': 'big'},    # average time for a whole stroke
                '143': {'type': 'avg_time_stroke_pull', 'size': 'single', 'base': 16, 'endian': 'big'},     # average time for a pull (acc to dec)
                #other
                '0A9': {'type': 'tank_volume', 'size': 'single', 'base': 16, 'endian': 'big', 'not_in_loop': True},
             }

# Packet identifiers as speicified in Water Rower S4 S5 USB Protocol Iss 1 04.pdf.

# ACH values = Ascii coded hexadecimal
# REQUEST sent from PC to device
# RESPONSE sent from device to PC

USB_REQUEST = "USB"                # First packet to be sent in order to instruct S4 to establish communications
WR_RESPONSE = "_WR_"               # Hardware Type response to acknowledge USB_REQUEST and initiate sending packets
EXIT_REQUEST = "EXIT"              # Application is exiting, stop sending packets
OK_RESPONSE = "OK"                 # Packet Accepted - Sent in cases where no other reply would otherwise be given.
ERROR_RESPONSE = "ERROR"           # Unknown packet recieved.
PING_RESPONSE = "PING"             # Ping sent once per second while no rowing is occuring
RESET_REQUEST = "RESET"            # Request the rowing computer to reset (equivalent to user holding on button for 2 secs), disable interactive mode
MODEL_INFORMATION_REQUEST = "IV?"  # Request Model Information
MODEL_INFORMATION_RESPONSE = "IV"  # Current model information IV+Model(4 or 5)+Firmware Version High+Firmware Version Low (e.g for Firmware 02.10, High is 02, low is 10)
READ_MEMORY_REQUEST = "IR"         # Read a memory location IR+(S=Single,D=Double,T=Triple) + XXX (XXX is in ACH format)
READ_MEMORY_RESPONSE = "ID"        # Value from a memory location ID +(type) + Y3 Y2 Y1
STROKE_START_RESPONSE = "SS"       # Start of stroke (just a packet - no data. Can be sent with very minor movement of paddle even if no rowing is occuring.)
STROKE_END_RESPONSE = "SE"         # End of stroke (just a packet - no data. Can be sent with very minor movement of paddle even if no rowing is occuring.)
PULSE_COUNT_RESPONSE = "P"         # Pulse Count XX in the last 25mS, ACH value. Pulses are triggered by pins on the pulley and so pulse count corresponds to pulley rotation.

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

INTERACTIVE_MODE_START_RESPONSE = "AIS"        # interactive mode requested by device
INTERACTIVE_MODE_START_ACCEPT_REQUEST = "AIA"  # confirm interactive mode, key input is redirect to PC
INTERACTIVE_MODE_END_REQUEST = "AIE"           # cancel interactive mode
INTERACTIVE_KEYPAD_RESET_RESPONSE = "AKR"      # RESET key pressed, interactive mode will be cancelled
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

SIZE_MAP = {'single': 'IRS',
            'double': 'IRD',
            'triple': 'IRT',}

UNIT_MAP = {'meters': 1,
            'miles': 2,
            'km': 3,
            'strokes': 4}

SIZE_PARSE_MAP = {'single': lambda cmd: cmd[6:8],
                  'double': lambda cmd: cmd[6:10],
                  'triple': lambda cmd: cmd[6:12]}

# PROGRAM CONTROL DELAYS
PORT_SCAN_RETRY_DELAY = 5
SERIAL_OPEN_RETRY_DELAY = 5

def find_port():
    attempts = 0
    while True:
        attempts += 1
        ports = serial.tools.list_ports.comports()
        for (i, (path, name, _)) in enumerate(ports):
            if "WR-S4" in name:
                logger.info("port found: %s" % path)
                return path
        # If a port isn't found, the code will remain in this loop.
        # This will have the effect that any code asking for Rower.open() will
        # not recieve control back until:
        # - the port is found, otherwise the code loops here
        # - and the serial is open without error, otherwise the code loops in _find_serial()
        #  
        #print("port not found retrying in 5s")
        if ((attempts - 1) % 360) == 0: # message every ~30 minutes
          logger.warning("port not found in %d attempts; retrying every 5s",
              attempts)
        time.sleep(PORT_SCAN_RETRY_DELAY)


def build_daemon(target):
    t = threading.Thread(target=target)
    t.daemon = True
    return t


def build_event(type, value=None, raw=None):
    return {"type": type,
            "value": value,
            "raw": raw,
            "at": int(round(time.time() * 1000))}


def is_live_thread(t):
    return t and t.is_alive()


def read_reply(cmd):
    address = cmd[3:6]
    memory = MEMORY_MAP.get(address)
    if memory:
        size = memory['size']
        endian = memory.get('endian', 'big')  # Default to big if unspecified
        value_fn = SIZE_PARSE_MAP.get(size, lambda cmd: None)
        value_str = value_fn(cmd)

        if value_str is None:
            logger.error('unknown size: %s', size)
        else:
            value = int(value_str, base=memory['base'])

            if endian == 'little':
                # Swap bytes if necessary (only for double and triple types)
                if size == 'double' and len(value_str) == 4:
                    high = int(value_str[0:2], 16)
                    low = int(value_str[2:4], 16)
                    value = (low << 8) | high
                elif size == 'triple' and len(value_str) == 6:
                    high = int(value_str[0:2], 16)
                    mid  = int(value_str[2:4], 16)
                    low  = int(value_str[4:6], 16)
                    value = (low << 16) | (mid << 8) | high

            return build_event(memory['type'], value, cmd)
    else:
        logger.error('cannot read reply for %s', cmd)


def event_from(line):
    try:
        cmd = line.strip()  # to ensure no space are in front or at the back call the function strip()
        cmd = cmd.decode('utf8')  # decode from bytes to utf8 string to remove b' prefix
        logger.debug(f"Reading line captured from S4: {cmd}")
        if cmd == STROKE_START_RESPONSE:  # "SS" packet received from waterrower
            return build_event(type='stroke_start', raw=cmd)  # Create a dict with the name stroke_start and the raw command used for it "SS"
        elif cmd == STROKE_END_RESPONSE:  # "SE" packet received from waterrower
            return build_event(type='stroke_end', raw=cmd)  # Create a dict with the name stroke_end and the raw command used for it "SE"
        elif cmd == OK_RESPONSE:  # If waterrower response "OK" do nothing
            return None
        elif cmd[:2] == MODEL_INFORMATION_RESPONSE:  # If MODEL information has been request, the model responce would be "IV"
            return build_event(type='model', raw=cmd)
        elif cmd[:2] == READ_MEMORY_RESPONSE:  # if after memory request the response comes from the waterrower
            return read_reply(cmd)  # proced to the function read_reply which strips away everything and keeps the value and create the event dict for that request
        elif cmd[:4] == PING_RESPONSE:  # WaterRower sends PING every second when the the rower is in standstill
            return build_event(type='ping', raw=cmd)
        elif cmd[:1] == PULSE_COUNT_RESPONSE:  # Pulse count the amount of 25 teeth passed 25teeth passed = P1
            return build_event(type='pulse', raw=cmd)
        elif cmd == ERROR_RESPONSE:  # If Waterrower responds with an error
            return build_event(type='error', raw=cmd) 
        else:
            logger.debug(f"Unhandled line captured from S4: {cmd}")
            return None
    except Exception as e:
        logger.error('could not build event for: %s %s', line, e)


class Rower(object):
    def __init__(self, options=None):
        logger.debug("Rower._init_")
        self._callbacks = set()
        self._stop_event = threading.Event()
        self._demo = False
        # if options and options.demo:
        #     from demo import FakeS4
        #     self._serial = FakeS4()
        #     self._demo = True
        # else:
        self._serial = serial.Serial()
        self._serial.baudrate = 19200

        self._request_thread = build_daemon(target=self.start_requesting)
        self._capture_thread = build_daemon(target=self.start_capturing)
        self._request_thread.start()
        self._capture_thread.start()

    def is_connected(self):
        return self._serial.isOpen() and is_live_thread(self._request_thread) and \
            is_live_thread(self._capture_thread)

    def _find_serial(self):
        if not self._demo:
            logger.debug("Rower._find_serial: Calling ._find_port")
            self._serial.port = find_port()

        try:
            logger.debug("Rower._find_serial: Calling ._serial.open")
            self._serial.open()
            logger.info("serial open")
        except serial.SerialException as e:
            print("serial open error waiting")
            time.sleep(SERIAL_OPEN_RETRY_DELAY)
            self._serial.close()
            self._find_serial()

    def open(self):
        logger.debug("Rower.open: Testing for existing connection")
        if self._serial and self._serial.isOpen():
            logger.debug("Rower.open: Calling ._serial._close")
            self._serial.close()
        logger.debug("Rower.open: Calling _find_serial")
        self._find_serial()

        logger.debug("Rower.open: Calling _is_set")
        if self._stop_event.is_set():
            #print("reset threads")
            logger.info("Rower.open: reset threads")
            self._stop_event.clear()
            self._request_thread = build_daemon(target=self.start_requesting)
            self._capture_thread = build_daemon(target=self.start_capturing)
            self._request_thread.start()
            logger.info("Thread daemon _request started")
            self._capture_thread.start()
            logger.info("Thread daemon _capture started")

        logger.debug("Rower.open: Write USB_Request")
        self.write(USB_REQUEST)

    def close(self):
        self.notify_callbacks(build_event("exit"))
        if self._stop_event:
            self._stop_event.set()
        if self._serial and self._serial.isOpen():
            self.write(EXIT_REQUEST)
            time.sleep(0.1)  # time for capture and request loops to stop running
            self._serial.close()

    def write(self, raw):
        try:
            self._serial.write(str.encode(raw.upper() + '\r\n'))
            self._serial.flush()
        except Exception as e:
            print(e)
            #print("Serial error try to reconnect")
            logger.error("Serial error try to reconnect")
            self.open()

    def start_capturing(self):
        while not self._stop_event.is_set():
            if self._serial.isOpen():
                try:
                    line = self._serial.readline()
                    event = event_from(line)
                    if event:
                        self.notify_callbacks(event)
                except Exception as e:
                    #print("could not read %s" % e)
                    logger.error("could not read %s" % e)
                    try:
                        self._serial.reset_input_buffer()
                    except Exception as e2:
                        #print("could not reset_input_buffer %s" % e2)
                        logger.error("could not reset_input_buffer %s" % e2)

            else:
                self._stop_event.wait(0.1)

    def start_requesting(self):
        while not self._stop_event.is_set():
            if self._serial.isOpen():
                for address in MEMORY_MAP:
                    if 'not_in_loop' not in MEMORY_MAP[address]:
                        self.request_address(address)
                        self._stop_event.wait(0.025)
            else:
                self._stop_event.wait(0.1)


    def reset_request(self):
        self.write(RESET_REQUEST)
        self.notify_callbacks(build_event('reset'))
        logger.info("Rower.reset_request: Reset requested")

    def request_info(self):
        self.write(MODEL_INFORMATION_REQUEST)
        self.request_address('0A9')

    def request_address(self, address):
        size = MEMORY_MAP[address]['size']
        cmd = SIZE_MAP[size]
        self.write(cmd + address)

    def register_callback(self, cb):
        logger.debug(f"Rower.register_callback: Registering callback - {cb}")
        self._callbacks.add(cb)

    def remove_callback(self, cb):
        self._callbacks.remove(cb)

    def notify_callbacks(self, event):
#        logger.debug(f"Rower.notify_callbacks: Notifing callbacks of event {event}")
        for cb in self._callbacks:
#            logger.debug(f"Rower.notify_callbacks: Notifying callback {cb} of event {event}")
            cb(event)