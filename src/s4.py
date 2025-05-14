# ---------------------------------------------------------------------------
# Based on the inonoob repo "pirowflo"
# https://github.com/inonoob/pirowflo
# Extensively refactored and expanded for WRowFusion
# ---------------------------------------------------------------------------


import threading
import logging
import time
from gpiozero import DigitalOutputDevice
from copy import deepcopy
#from datetime import timedelta

from src.s4if import (
    Rower,
    S4Event,
    WorkoutMode, 
)
from src.heart_rate import HeartRateMonitor

logger = logging.getLogger(__name__)

'''
This module:
1) Simulates a heart beat ant+ signal on a GPIO pin to feed into the S4 monitor via the 3.5mm plug
2) Captures the data from the s4 using the Rower class defined in s4if.py.

In the case of 2)
3 callback functions are registered to the s4if.Rower class. Those functions get exectuted as soon as any of the 
events for which we watch is recieved from the s4 via the Rower._start_capturing() method.
Each of the three callback functions create a dict of WaterRower data, each with a different value set. 
1) reset_requested: Intention is to reset the S4, so all values should be set to 0 even if old values persist in the WR memory.
   These 'reset' values are stored in the WRValues_rst dictionary.
2) pulse_monitor: Caters for the periods of no rowing (e.g. during rest intervals). Set all instantaneous values to 0 e.g power, pace, 
   stroke rate. Other values are not set to 0 in the WR memory. These 'standstill' values are stored in the WRValues_standstill dictionary.
3) on_rower_event: Normal rowing, so capture data from WR memory without modification. These 'normal' rowing values are stored
   in the WRValues dictionary.

Depeding on thoses cases, load the appropriate values into the TXValues dictionary for transmission via BLE/ANT. 

Note: As all three callback functions take event as an arguement, they could be written as one callback function. 
Design choice for 3 callbacks brings these benefits:
Clean separation: Each function does one job. Easier to read and test.
Modular expansion: You can add/remove handlers without changing others.
Avoids bloated functions: A single on_event() could become long and messy.
Allows early returns: Each callback can quickly return if the event is not relevant.
'''

# Watts calculation configuration
# * True to use the Concept2 formula for calculating watts, or 
# * False to use the rolling average of values reported by the Waterrower
USE_CONCEPT2_POWER = False  

# Smooth the displayed power and bridge gaps in reported Watts by finding the average max power output over a number of strokes 
NUM_STROKES_FOR_ROLLING_AVG_WATTS = 4

# Define GPIO pin
HEARTBEAT_PIN = 18
heartbeat_signal = DigitalOutputDevice(HEARTBEAT_PIN, active_high=True, initial_value=False)

# The time between pulses after which the paddle is assumed to be stationary and no rowing is happening
# Specified in milliseconds
NO_ROWING_PULSE_GAP = 300

IGNORE_LIST = [
    'wr', 'ok', 'ping', 'model', 'pulse', 'error', 'exit', 'reset',
    'none',
    #'total_distance_dec',
    #'total_distance',
    #'watts',
    #'total_kcal',
    #'tank_volume',      # Recommend ignore
    #'stroke_count',
    #'avg_time_stroke_whole',
    #'avg_time_stroke_pull',
    #'total_speed_cmps',
    #'avg_distance_cmps',
    #'heart_rate',
    '500m_pace',           # Recommend ignore
    #'stroke_rate', 
    #'display_hr', 
    #'display_min', 
    #'display_sec',
    #'display_sec_dec',
    #'workout_total_time',
    #'workout_total_metres',
    #'workout_total_strokes',
    #'workout_limit',
    ]

class DataLogger(object):
    def __init__(self, rower_interface=None):
        self._rower_interface = None
        self._stop_event = threading.Event()
        self._wr_lock = threading.RLock()

        self._RecentStrokesMaxPower = None
        self._StrokeMaxPower = None
        self._DrivePhase = None         # Our _DrivePhase is set to True at when the S4 determines pulley accelleration
                                        # and set to False when S4 detects pulley decelleration. It is therefore True
                                        # throughout the whole Drive phase of the stroke and False during recovery phase. 
        self._WattsEventValue = None
        self._RollingAvgWatts = None
        self._Concept2Watts = None
        self._500mPace = None
        self._LastCheckForPulse = None
        self._PulseEventTime = None
        self._PaddleTurning = None
        self._RowerReset = None
        self._secondsWR = None
        self._minutesWR = None
        self._hoursWR = None
        self._secdecWR = None
        self._TotalDistanceM = None     # The total distance in m, ignoring the value in the dec register
        self._TotalDistanceDec = None   # The cm component of the total distance (i.e. the component that would follow a decimal point)
        self._TotalDistanceCM = None    # The total distance in cm (i.e. _TotalDistanceM * 100 + _TotalDistanceDec)
        self._StrokeDuration = None     # Units: ms
        self._DriveDuration = None      # Units: ms
        self.TankVolume = None
        self.WRWorkout = None
        self._TempLowFreq = None
        self.WRValues_rst = None
        self.WRValues = None
        self.WRValues_standstill = None
        self.TXValues = None


        self.data_logger = logging.getLogger('wrowfusion.data')
        self.data_logger.setLevel(logging.INFO)

        # Create file handler
        data_handler = logging.FileHandler('/tmp/wrowfusion_data.log')
        data_handler.setLevel(logging.INFO)

        # Optional: simple format
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        data_handler.setFormatter(formatter)

        # Avoid adding multiple handlers if already configured
        if not self.data_logger.handlers:
            self.data_logger.addHandler(data_handler)

        if rower_interface is not None:
            self.initialise(rower_interface)

    def initialise(self, rower_interface: Rower):
        with self._wr_lock:
            """Initialise the DataLogger once a rower interface becomes available."""
            self._rower_interface = rower_interface
            self._rower_interface.register_callback(self.reset_requested)
            self._rower_interface.register_callback(self.pulse_monitor)
            self._rower_interface.register_callback(self.on_rower_event)
        logger.info("DataLogger successfully initialised with rower_interface.")

        # Initialise the attributes, particularly the WRValues dictionaries because subsequent
        # code tries to update the values of the dictionaries and so expect the dictionary keys
        # to exist already.
        self._reset_state()

    @property
    def is_initialised(self):
        """Return True if the rower interface has been set."""
        with self._wr_lock:
            return self._rower_interface is not None
    
    def _reset_state(self):
        logger.debug("DataLogger._reset_state: Attempting lock")
        with self._wr_lock:
            logger.debug("DataLogger._reset_state: Lock attained, setting values")
            self._RecentStrokesMaxPower = []
            self._StrokeMaxPower = 0
            self._DrivePhase = False
            self._WattsEventValue = 0
            self._RollingAvgWatts = 0
            self._Concept2Watts = 0
            self._500mPace = 0
            self._LastCheckForPulse = 0
            self._PulseEventTime = 0
            self._PaddleTurning = False
            self._RowerReset = True
            self._secondsWR = 0
            self._minutesWR = 0
            self._hoursWR = 0
            self._secdecWR = 0
            self._TotalDistanceM = 0
            self._TotalDistanceDec = 0
            self._TotalDistanceCM = 0
            self._StrokeDuration = 0
            self._DriveDuration = 0
            self.TankVolume = 0
            self.WRWorkout = {
                'type': None,
                'intervals': False,
                'total_time': 0,
                'total_metres': 0,
                'total_strokes': 0,
                'limit': 0,
                }
            self._TempLowFreq = {}
            self.WRValues_rst = {
                'stroke_rate': 0,
                'stroke_count': 0,
                'total_distance': 0,
                'instant_500m_pace': 0,
                'speed_cmps': 0,
                'watts': 0,
                'total_kcal': 0,
                'total_kcal_hour': 0,
                'total_kcal_min': 0,
                'heart_rate': 0,
                'elapsed_time': 0.0,
                'stroke_ratio': 0.0,
                }
            self.WRValues = deepcopy(self.WRValues_rst)
            self.WRValues_standstill = deepcopy(self.WRValues_rst)
            self.TXValues = deepcopy(self.WRValues_rst)
            logger.debug("DataLogger._reset_state: Values set")
            logger.debug(f"DataLogger._reset_state: WRValues = {self.WRValues}")
            logger.debug("DataLogger._reset_state: Releasing lock")
        logger.debug("DataLogger._reset_state: Lock released.")

    def on_rower_event(self, event: S4Event):
        #logger.debug(f"Received event: {event}")

        if event.type in IGNORE_LIST:
            #logger.debug(f"Ignoring event in ignore list: {event.type}")
            return

        handlers = {
            'stroke_start': lambda evt: setattr(self, '_DrivePhase', True),
            'stroke_end': lambda evt: setattr(self, '_DrivePhase', False),
            'workout_flags': lambda evt: self._handle_workout_flags(evt),
            'distance1_flags': lambda evt: self._print_data(evt),
            'distance2_flags': lambda evt: self._print_data(evt),
            'total_distance': lambda evt: self._handle_total_distance(evt),
            'total_distance_dec': lambda evt: self._handle_total_distance_dec(evt),
            'watts': lambda evt: self._handle_watts(evt),
            'total_kcal': lambda evt: self.WRValues.update({'total_kcal': (evt.value + 500) / 1000}),
            'tank_volume': lambda evt: setattr(self, 'TankVolume', evt.value),
            'stroke_count': lambda evt: self.WRValues.update({'stroke_count': evt.value}),
            'avg_time_stroke_whole': lambda evt: setattr(self, '_StrokeDuration', evt.value * 25),
            'avg_time_stroke_pull': lambda evt: setattr(self, '_DriveDuration', evt.value * 25),
            'avg_distance_cmps': lambda evt: self._handle_avg_distance_cmps(evt),
            'heart_rate': lambda evt: self.WRValues.update({'heart_rate': evt.value}),
            '500m_pace': lambda evt: self._handle_500m_pace(evt),
            'stroke_rate': lambda evt: self.WRValues.update({'stroke_rate': evt.value * 2}),
            'display_sec': lambda evt: setattr(self, '_secondsWR', evt.value),
            'display_min': lambda evt: setattr(self, '_minutesWR', evt.value),
            'display_hr': lambda evt: setattr(self, '_hoursWR', evt.value),
            'display_sec_dec': lambda evt: setattr(self, '_secdecWR', evt.value),
            #'workout_total_time': lambda evt: self.WRWorkout.update({'total_time': evt.value}),
            #'workout_total_metres': lambda evt: self.WRWorkout.update({'total_metres': evt.value}),
            #'workout_total_strokes': lambda evt: self.WRWorkout.update({'total_strokes': evt.value}),
            #'workout_limit': lambda evt: self.WRWorkout.update({'limit': evt.value}),
            'workout_total_time': lambda evt: self._print_data (evt),
            'workout_total_metres': lambda evt: self._print_data (evt),
            'workout_total_strokes': lambda evt: self._print_data (evt),
            'workout_limit': lambda evt: self._print_data (evt),
            'workout_total_time': lambda evt: self._print_data(evt),
            'workout_work1': lambda evt: self._print_data(evt),
            'workout_rest1': lambda evt: self._print_data(evt),
            'workout_work2': lambda evt: self._print_data(evt),
            'workout_rest2': lambda evt: self._print_data(evt),
            'workout_work3': lambda evt: self._print_data(evt),
            'workout_rest3': lambda evt: self._print_data(evt),
            'workout_work4': lambda evt: self._print_data(evt),
            'workout_rest4': lambda evt: self._print_data(evt),
            'workout_work5': lambda evt: self._print_data(evt),
            'workout_rest5': lambda evt: self._print_data(evt),
            'workout_work6': lambda evt: self._print_data(evt),
            'workout_rest6': lambda evt: self._print_data(evt),
            'workout_work7': lambda evt: self._print_data(evt),
            'workout_rest7': lambda evt: self._print_data(evt),
            'workout_work8': lambda evt: self._print_data(evt),
            'workout_rest8': lambda evt: self._print_data(evt),
            'workout_work9': lambda evt: self._print_data(evt),
            'workout_inter': lambda evt: self._print_data(evt),
        }

        with self._wr_lock:
            handler = handlers.get(event.type)
            if not handler:
                logger.warning(f"On Rower Event received unhandled event type: {event.type}")
                return
            
            handler(event)
            # In the memory map, the time components are listed in order of increasing signficance: dec, sec, min, hr
            # and so are requested and also responded in that order. Therefore the elapsed time can be calculated
            # on receipt of the hr response.
            if event.type == 'display_sec':
                self._compute_elapsed_time()
            elif event.type == 'avg_time_stroke_pull':
                self._compute_stroke_ratio()

    def _handle_workout_flags(self, evt: S4Event):

        self._print_data(evt)
        mode = WorkoutMode(evt.value)

        is_duration = WorkoutMode.WORKOUT_DURATION in mode or WorkoutMode.WORKOUT_DURATION_INTERVAL in mode
        is_distance = WorkoutMode.WORKOUT_DISTANCE in mode or WorkoutMode.WORKOUT_DISTANCE_INTERVAL in mode
        is_interval = WorkoutMode.WORKOUT_DURATION_INTERVAL in mode or WorkoutMode.WORKOUT_DISTANCE_INTERVAL in mode

        with self._wr_lock:
            if is_duration:
                self.WRWorkout['type'] = "duration"
            elif is_distance:
                self.WRWorkout['type'] = "distance"

            self.WRWorkout['intervals'] = is_interval
                
    def _handle_total_distance(self, evt: S4Event):
        with self._wr_lock:
            self.WRValues['total_distance'] = evt.value
            self._TotalDistanceM = evt.value

    def _handle_total_distance_dec(self, evt: S4Event):
        with self._wr_lock:
            self._TotalDistanceDec = evt.value
            self._TotalDistanceCM = max(self._TotalDistanceCM, self._TotalDistanceM * 100 + evt.value)

    def _handle_avg_distance_cmps(self, evt: S4Event):
        speed = evt.value   # cm per sec
        
        with self._wr_lock:
            if speed == 0:
                updates = {'instant_500m_pace': 0, 'speed_cmps': 0}
                if USE_CONCEPT2_POWER:
                    updates['watts'] = 0
                self.WRValues.update(updates)
                return
            
            self.WRValues['speed_cmps'] = speed

            # Prefer using the 500mPace from the S4 if it is being captured and not ignored.
            # Otherwise compute the 500m pace from the speed.
            if not self._500mPace:
                pace_500m = 50000 / speed
                self.WRValues['instant_500m_pace'] = pace_500m

            C2watts = 2.80 / pow((100/speed), 3)
            self._Concept2Watts = C2watts
            
            if USE_CONCEPT2_POWER:
                self.WRValues['watts'] = C2watts

    def _handle_watts(self, evt: S4Event):
        with self._wr_lock:
            self._WattsEventValue = evt.value
            self._update_rolling_avg_watts(self._WattsEventValue)

    def _handle_500m_pace(self, evt: S4Event):
        # The WR will report 500m pace only when it is the selected intensity display value
        # on the S4. If the S4 is being reporting a non-zero value, then this function will
        # prefer the value reported by the S4 over the value derived from the cm/s speed.
        # To always use the value derived from speed, add 500m_pace to the IGNORE_LIST. 
        with self._wr_lock:
            self._500mPace = evt.value
            if evt.value:
                self.WRValues['instant_500m_pace'] = evt.value


    def _compute_elapsed_time(self):
        with self._wr_lock:
            #self.elapsetime = timedelta(seconds=self.secondsWR, minutes=self.minutesWR, hours=self.hoursWR)
            #self.elapsetime = int(self.elapsetime.total_seconds())
            elapsed_time = int(self._hoursWR * 3600 + self._minutesWR * 60 + self._secondsWR + (1 if self._secdecWR >= 5 else 0))
            self.WRValues['elapsed_time'] = elapsed_time

    def _compute_stroke_ratio(self):
        with self._wr_lock:
            if self._StrokeDuration and self._DriveDuration:
                # Use the documented WR formula, which has a 1.25 multiplier
                strokeratio = (self._StrokeDuration - self._DriveDuration) / (self._DriveDuration * 1.25)
                self.WRValues['stroke_ratio'] = strokeratio

    def _update_rolling_avg_watts(self,watts):
        with self._wr_lock:
            if self._DrivePhase:
                self._StrokeMaxPower = max(self._StrokeMaxPower, watts)
            else:
                if self._StrokeMaxPower:
                    self._RecentStrokesMaxPower.append(self._StrokeMaxPower)
                    self._StrokeMaxPower = 0
                while len(self._RecentStrokesMaxPower) > NUM_STROKES_FOR_ROLLING_AVG_WATTS:
                    self._RecentStrokesMaxPower.pop(0)
                # Start reporting power from the first received value, rather than waiting for the buffer to fill
                if self._RecentStrokesMaxPower:
                    rolling_avg_watts = int(sum(self._RecentStrokesMaxPower) / len(self._RecentStrokesMaxPower))
                    self._RollingAvgWatts = rolling_avg_watts
                    if USE_CONCEPT2_POWER == False:
                        self.WRValues['watts'] = rolling_avg_watts
                    
    def _print_data(self, evt: S4Event):
        eventtype = evt.type
        value = evt.value
        oldvalue = self._TempLowFreq.get(eventtype)
        if oldvalue is not None:
            if oldvalue != value:
                self.data_logger.info(f"{eventtype} updated to: {value!r} from {oldvalue!r}")
                self._TempLowFreq[eventtype] = value
        else:
            self.data_logger.info(f"{eventtype} initialised at: {value!r}")
            self._TempLowFreq[eventtype] = value

    def pulse_monitor(self,event: S4Event):
        # As a callback, this function is called by the notifier each time any event 
        # is captured from the S4. The function detects when the paddle is stationary
        # by checking when the S4 last reported a pulse event (pulses are triggered as
        # the pulley rotates). Even when there is no rowing, the S4 at the very least
        # issues Ping events every second, so this function will continue to be called
        # even in the absence of a pulse event as long as the com remains open,
        # thereby allowing the time since the last pulse to be computed. If this is
        # longer than the NO_ROWING_PULSE_GAP in milliseconds (e.g. 300ms), then the 
        # paddle is assumed to be stationary and no rowing is taking place.
        self._LastCheckForPulse = int(round(time.time() * 1000))
        with self._wr_lock:
            if event.type == 'pulse':
                self._PulseEventTime = event.at
                self._RowerReset = False

            if self._PulseEventTime:
                pulse_gap = self._LastCheckForPulse - self._PulseEventTime
            else:
                pulse_gap = float('inf')  # Assume paddle is not turning yet

            if pulse_gap <= NO_ROWING_PULSE_GAP:
                self._PaddleTurning = True
            else:
                self._PaddleTurning = False
                self._DrivePhase = False
                self._RecentStrokesMaxPower = []
                self.WRValuesStandstill()

    def reset_requested(self,event: S4Event):
        if event.type == 'reset':
            logger.debug("DataLogger.reset_requested: Requesting Lock")
            with self._wr_lock:
                logger.debug("DataLogger.reset_requested: Lock attained")
                logger.debug("DataLogger.reset_requested: Calling _reset_state")
                self._reset_state()
                logger.info("value reseted")


    def WRValuesStandstill(self):
        with self._wr_lock:
            self.WRValues_standstill = deepcopy(self.WRValues)
            self.WRValues_standstill.update({
                'stroke_rate': 0,
                'instant_500m_pace': 0,
                'speed_cmps': 0,
                'watts': 0,
            })



    def get_WRValues(self):
        logger.debug("getWRValues starting lock")
        with self._wr_lock:
            logger.debug("getWRValues lock started")                
            if self._RowerReset:
                #logger.debug("getWRValues handling rowerreset")
                values = deepcopy(self.WRValues_rst)
            elif self._PaddleTurning:
                #logger.debug("getWRValues handling PaddleTurning")
                values = deepcopy(self.WRValues)
            else:
                #logger.debug("getWRValues handling standstill")
                values = deepcopy(self.WRValues_standstill)
            #logger.debug("getWRValues ending lock")
        logger.debug("getWRValues lock ended")
        return values

    def inject_HR(self, values, hrm: HeartRateMonitor):
        if not isinstance(values, dict):
            logger.warning("inject_HR recieved invalid values input: %s", values)
            return None
        
        if values['heart_rate'] == 0 and (ext_hr := hrm.get_heart_rate()) != 0:
            values['heart_rate'] = ext_hr
        return values

    def CueBLEANT(self, ble_out_q, ant_out_q, hrm: HeartRateMonitor):
        #logger.debug("CueBLEANT calling get_WRValues")
        values = self.get_WRValues()
        #logger.debug("CueBLEANT returning from get_WRValues")
        if values:
            #logger.debug("CueBLEANT calling inject_HR")
            values = self.inject_HR(values, hrm)
            #logger.debug("CueBLEANT returning from inject_HR")
            with self._wr_lock:
                self.TXValues = values
            logger.debug(f"CueBLEANT got values to append to dqueues from S4: {values}")
            ble_out_q.append(values)
            ant_out_q.append(values)


def s4_heart_beat_task(hrm: HeartRateMonitor):
    """Simulate continuous ANT+ heart rate signal to transmit to the S4 via 3.5mm jack."""
    while True:
        hr = hrm.get_heart_rate()

        if hr > 0:
            hr_period = 60000 / hr  # Convert BPM to ms

            # Generate a 10ms pulse
            heartbeat_signal.on()
            time.sleep(0.01)  # 10ms pulse
            heartbeat_signal.off()

            # Wait for the rest of the heartbeat interval
            time.sleep((hr_period - 10) / 1000.0)
        else:
            # If no valid HR data, keep the signal off and wait 500ms
            heartbeat_signal.off()
            time.sleep(0.5)


def s4_data_task(in_q, ble_out_q, ant_out_q, hrm: HeartRateMonitor, wr_data_logger: DataLogger):
    logger.debug("s4_data_task: Initialising Rower class")
    S4 = Rower()
    logger.debug("s4_data_task: Opening Rower class")
    S4.open()
    # Control will not return until a connection has been succesfully opened
    # This means the thread will stay alive, but the code below and the loop
    # which polls the S4 will not be executed unecessarily before an S4 is
    # connected
    
    S4.request_reset()
    logger.debug("s4_data_task: Initialising DataLogger")

    wr_data_logger.initialise(S4)
    logger.info("Waterrower Ready and sending data to BLE and ANT Thread")

    while True:
        start = time.time()
        try:
            if not in_q.empty():
                ResetRequest_ble = in_q.get()
                parts = ResetRequest_ble.split()
                cmd = parts[0]
                if cmd == "reset_ble":
                    S4.request_reset()
                #elif cmd == "hr":
                #    new_hr = int(parts[1])
                #    if new_hr != ext_hr:
                #        ext_hr = new_hr
                #        ext_hr_time = time.time()
                #        print("ext_hr", ext_hr)

            #logger.debug("Calling CueBLEANT")
            
            #WRtoBLEANT.CueBLEANT(ble_out_q, ant_out_q, hrm)
            #logger.debug("Returned from CueBLEANT")
        except Exception as e:
            logger.exception(f"Exception in s4_data_task loop: {e}")
        
        duration = time.time() - start
        if duration > 1:
            logger.warning(f"CueBLEANT took too long: {duration:.2f}s")

        #print(type(ant_out_q))
        #print(ant_out_q)
        #logger.info(WRtoBLEANT.BLEvalues)
        #ant_out_q.append(WRtoBLEANT.ANTvalues)
        time.sleep(0.1)


# def maintest():
#     S4 = WaterrowerInterface.Rower()
#     S4.open()
#     S4.reset_request()
#     WRtoBLEANT = DataLogger(S4)
#
#     def MainthreadWaterrower():
#         while True:
#         #print(WRtoBLEANT.BLEvalues)
#             #ant_out_q.append(WRtoBLEANT.ANTvalues)
#             #print("Rowering_value  {0}".format(WRtoBLEANT.WRValues))
#             #print("Rowering_value_rst  {0}".format(WRtoBLEANT.WRValues_rst))
#             #print("Rowering_value_standstill  {0}".format(WRtoBLEANT.WRValues_standstill))
#             print("Reset  {0}".format(WRtoBLEANT.rowerreset))
#             #print("Paddleturning  {0}".format(WRtoBLEANT.PaddleTurning))
#             #print("Lastcheck {0}".format(WRtoBLEANT._LastCheckForPulse))
#             #print("last pulse {0}".format(WRtoBLEANT._PulseEventTime))
#             #print("is connected {}".format(S4.is_connected()))
#             time.sleep(0.1)
#
#
#     t1 = threading.Thread(target=MainthreadWaterrower)
#     t1.start()
#
#
# if __name__ == '__main__':
#     maintest()