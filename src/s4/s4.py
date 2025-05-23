# ---------------------------------------------------------------------------
# Based on the inonoob repo "pirowflo"
# https://github.com/inonoob/pirowflo
# Extensively refactored and expanded for WRowFusion
# ---------------------------------------------------------------------------


import threading
import logging
import time
import re
from gpiozero import DigitalOutputDevice
from copy import deepcopy
from typing import Any, Callable

from src.s4.s4if import (
    Rower,
    S4Event,
)
from src.s4.s4_workouts import (
    Workout,
    Zone,
)
from src.hr.heart_rate import HeartRateMonitor

from src.rows.row_tracker import RowSessionTracker

from src.rows.row_signals import (
    StrokeStarted, SpeedChanged, ResetDetected, IntervalStarted,
    IntervalEnded, WorkoutCompleted, ZoneChanged,
)

logger = logging.getLogger(__name__)

'''
This module:
1) Simulates a heart beat ant+ signal on a GPIO pin to feed into the S4 monitor via the 3.5mm plug
2) Captures the data from the s4 using the Rower class defined in s4if.py.

In the case of 2)
Two callback functions are registered to the s4if.Rower class. Those functions get exectuted as soon as any of the 
events for which we watch is recieved from the s4 via the Rower._start_capturing() method.
Each of the three callback functions create a dict of WaterRower data, each with a different value set. 
1) reset_requested: Intention is to reset the S4, so all values should be set to 0 even if old values persist in the WR memory.
   These 'reset' values are stored in the WRValues_rst dictionary.
2) pulse_monitor: Caters for the periods of no rowing (e.g. during rest intervals). Set all instantaneous values to 0 e.g power, pace, 
   stroke rate. Other values are not set to 0 in the WR memory. These 'standstill' values are stored in the WRValues_standstill dictionary.
3) on_rower_event: This callback handles the commands received from the rower. During normal rowing, it will capture data from WR memory 
   storing rowing data in the WRValues dictionary and store values used for various computations in appropriate attributes. It also handles
   the constructed 'reset' event which is not received from the   

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
# It appears empirically that the Waterrower algorithms apply a form of averaging over 16 strokes.
# An entry of 4 strokes can provide a more responsive watts reading. 
NUM_STROKES_FOR_ROLLING_AVG_WATTS = 4

# Define GPIO pin
HEARTBEAT_PIN = 18
heartbeat_signal = DigitalOutputDevice(HEARTBEAT_PIN, active_high=True, initial_value=False)

# The time between pulses after which the paddle is assumed to be stationary and no rowing is happening
# Specified in milliseconds
NO_ROWING_PULSE_GAP = 300

IGNORE_LIST = [
    'wr', 'ok', 'ping', 'model', 'pulse', 'exit', #'error', 
    'none',
    #'workout_flags',
    #'intensity2_disp_flags', 
    #'distance1_disp_flags',
    #'distance2_disp_flags',
    #'program_disp_flags',
    #'total_distance_dec',
    #'total_distance',
    #'watts',
    #'total_calories',
    #'zone_hr_upper',
    #'zone_hr_lower', 
    #'zone_int_mps_upper',
    #'zone_int_mps_lower',
    #'zone_int_mph_upper',
    #'zone_int_mph_lower',
    #'zone_int_500m_upper',
    #'zone_int_500m_lower',
    #'zone_int_2km_upper',
    #'zone_int_2km_lower',
    #'zone_sr_upper',
    #'zone_sr_lower',
    #'tank_volume',
    #'stroke_count',
    #'avg_time_stroke_whole',
    #'avg_time_stroke_pull',
    'total_speed_cmps',     # Recommend ignore (useful only for s4 monitor's internal logic)
    #'instant_avg_speed_cmps',
    'ms_stored'             # Recommend ignore (useful only for s4 monitor's internal logic)
    #'heart_rate',
    '500m_pace',            # Recommend ignore (derive from avg_time_stroke_whole instead)
    'stroke_rate',          # Recommend ignore (derive from avg_time_stroke_whole instead)
    #'display_hr', 
    #'display_min', 
    #'display_sec',
    #'display_sec_dec',
    #'workout_total_time',
    #'workout_total_metres',
    #'workout_total_strokes',
    'workout_limit',        # Recommend ignore (useful only for s4 monitor's internal logic)
    #'workout_work1',
    #'workout_rest1',
    #'workout_work2',
    #'workout_rest2',
    #'workout_work3',
    #'workout_rest3',
    #'workout_work4',
    #'workout_rest4',
    #'workout_work5',
    #'workout_rest5',
    #'workout_work6',
    #'workout_rest6',
    #'workout_work7',
    #'workout_rest7',
    #'workout_work8',
    #'workout_rest8',
    #'workout_work9',
    #'workout_intervals',
    ]

class RowerState(object):
    def __init__(self, rower_interface=None):
        self._rower_interface: Rower | None = None
        self._stop_event = threading.Event()
        self._wr_lock = threading.RLock()

        self._recent_strokes_max_power: list[int] = []
        self._stroke_max_power: int | None = None
        self._drive_phase: bool | None = None         # Our _drive_phase is set to True at when the S4 determines pulley accelleration
                                        # and set to False when S4 detects pulley decelleration. It is therefore True
                                        # throughout the whole Drive phase of the stroke and False during recovery phase. 
        self._watts_event_value: int | None = None
        self._rolling_avg_watts: int | None = None
        self._concept2_watts: float | None = None
        self._500m_pace: int | None = None
        self._last_check_for_pulse: int | None = None  # Timestamp in ms of last check for pulse 
        self._pulse_event_time: int | None = None
        self._paddle_turning: bool | None = None
        self._seconds_wr: int | None = None
        self._minutes_wr: int | None = None
        self._hours_wr: int | None = None
        self._secdecWR: int | None = None
        self._elapsed_time: float | None = None      # Elapsed time in seconds with 1 decimal place (note though that this is likely false accuracy due to serial communication process)
        self._total_distance_m: int | None = None     # The total distance in m, ignoring the value in the dec register
        self._total_distance_dec: int | None = None   # The cm component of the total distance (i.e. the component that would follow a decimal point)
        self._total_distance_cm: int | None = None    # The total distance in cm (i.e. _total_distance_m * 100 + _total_distance_dec)
        self._stroke_duration: int | None = None     # Units: ms
        self._drive_duration: int | None = None      # Units: ms
        self._workout_flags: int | None = None       # Hold the workout flags to allow the code to detect a change in the flags
        self._capture_work_targets: dict[int, int] = {} # Temporary dictionaries to capture the workout program as the intervals are recieved via the serial connection
        self._capture_rest_durations: dict[int, int] = {} # Temporary dictionaries to capture the workout program as the intervals are recieved via the serial connection
        self._workout_builder: Workout = Workout()
        self.workout: Workout | None = None
        self._zone_builder: Zone = Zone()
        self.zone: Zone | None = None
        self.tank_volume: int | None = None          # Units: Decilitres
        self.WRValues_rst: dict[str, Any] = {}
        self.WRValues: dict[str, Any] = {}
        self.WRValues_standstill: dict[str, Any] = {}

        self.session_tracker = RowSessionTracker()

        self._logger_cache: dict[str, Any] = {}
        self._data_logger = logging.getLogger('s4data')

        if rower_interface is not None:
            self.initialise(rower_interface)

    def initialise(self, rower_interface: Rower) -> None:
        # Initialise the attributes, particularly the WRValues dictionaries because subsequent
        # code tries to update the values of the dictionaries and so expect the dictionary keys
        # to exist already.
        self._zero_state()

        with self._wr_lock:
            """Initialise RowerState once a rower interface becomes available."""
            self._rower_interface = rower_interface
            self._rower_interface.register_callback(self.pulse_monitor)
            self._rower_interface.register_callback(self.on_rower_event)
        logger.info("RowerState successfully initialised with rower_interface.")

    @property
    def is_initialised(self) -> bool:
        """Return True if the rower interface has been set."""
        with self._wr_lock:
            return self._rower_interface is not None
    
    def _zero_state(self) -> None:
        logger.debug("RowerState._zero_state: Attempting lock")
        with self._wr_lock:
            logger.debug("RowerState._zero_state: Lock attained, setting values")
            self._recent_strokes_max_power = []
            self._stroke_max_power = 0
            self._drive_phase = False
            self._watts_event_value = 0
            self._rolling_avg_watts = 0
            self._concept2_watts = 0.0
            self._500m_pace = 0
            self._last_check_for_pulse = 0
            self._pulse_event_time = 0
            self._paddle_turning = False
            self._seconds_wr = 0
            self._minutes_wr = 0
            self._hours_wr = 0
            self._secdecWR = 0
            self._elapsed_time = 0.0
            self._total_distance_m = 0
            self._total_distance_dec = 0
            self._total_distance_cm = 0
            self._stroke_duration = 0
            self._drive_duration = 0
            self._workout_builder.reset()
            self.workout = None
            self._zone_builder.reset()
            self.zone = None
            self.tank_volume = 0
            self._logger_cache = {}
            self.WRValues_rst = {
                'paddle_turning': False,  #TK Undo
                'stroke_rate_pm': 0.0,
                'stroke_count': 0,
                'total_distance_m': 0,
                'instant_500m_pace_secs': 0,
                'speed_cmps': 0,
                'instant_watts': 0,
                'total_calories': 0,
                'heart_rate_bpm': 0,
                'elapsed_time_secs': 0,
                'stroke_ratio': 0.0,
                }
            self.WRValues = deepcopy(self.WRValues_rst)
            self.WRValues_standstill = deepcopy(self.WRValues_rst)
            logger.debug("RowerState._zero_state: Values set")
            logger.debug(f"RowerState._zero_state: WRValues = {self.WRValues}")
            logger.debug("RowerState._zero_state: Releasing lock")
        logger.debug("RowerState._zero_state: Lock released.")

    def on_rower_event(self, event: S4Event) -> None:
        #logger.debug(f"Received event: {event}")

        if event.type in IGNORE_LIST:
            #logger.debug(f"Ignoring event in ignore list: {event.type}")
            return

        handlers: dict[str, tuple[Callable[[S4Event], None] | None, int | None]] = {
            'error': (lambda evt: self._handle_error(evt), logging.INFO),
            'screen_sub_mode': (None, logging.INFO),
            'screen_mode': (None, logging.INFO),
            'intervals_remaining': (None, logging.INFO),
            'function_flags': (None, logging.INFO),
            'misc_disp_flags': (lambda evt: self._handle_misc_disp_flags(evt), logging.INFO),
            'reset': (lambda evt: self._zero_state(), logging.INFO),
            'stroke_start': (lambda evt: setattr(self, '_drive_phase', True), logging.DEBUG),
            'stroke_end': (lambda evt: setattr(self, '_drive_phase', False), logging.DEBUG),
            'workout_flags': (lambda evt: self._handle_workout_flags(evt), logging.INFO),
            'intensity2_disp_flags': (lambda evt: self._handle_zone_program(evt), logging.INFO), 
            'distance1_disp_flags': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'distance2_disp_flags': (None, logging.INFO),
            'program_disp_flags': (None, logging.INFO),
            'misc_disp_flags': (None, logging.INFO),
            'total_distance': (lambda evt: self._handle_total_distance(evt), logging.DEBUG),
            'total_distance_dec': (lambda evt: self._handle_total_distance_dec(evt), logging.DEBUG),
            'watts': (lambda evt: self._handle_watts(evt), logging.DEBUG),
            'total_calories': (lambda evt: self.WRValues.update({'total_calories': evt.value}), logging.DEBUG),
            'zone_hr_upper': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_hr_lower': (lambda evt: self._handle_zone_program(evt), logging.INFO), 
            'zone_int_mps_upper': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_mps_lower': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_mph_upper': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_mph_lower': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_500m_upper': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_500m_lower': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_2km_upper': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_int_2km_lower': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_sr_upper': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'zone_sr_lower': (lambda evt: self._handle_zone_program(evt), logging.INFO),
            'tank_volume': (lambda evt: setattr(self, 'tank_volume', evt.value), logging.INFO),
            'stroke_count': (lambda evt: self.WRValues.update({'stroke_count': evt.value}), logging.DEBUG),
            'avg_time_stroke_whole': (lambda evt: self._handle_avg_time_stroke_whole(evt), logging.DEBUG),       # used to calculate the stroke rate more accurately than the stroke rate event
            'avg_time_stroke_pull': (lambda evt: setattr(self, '_drive_duration', evt.value * 25) if evt.value is not None else None, logging.DEBUG),
            'instant_avg_speed_cmps': (lambda evt: self._handle_instant_avg_speed_cmps(evt), logging.DEBUG),
            'heart_rate': (lambda evt: self.WRValues.update({'heart_rate_bpm': evt.value}), logging.DEBUG),
            '500m_pace': (lambda evt: self._handle_500m_pace(evt), logging.DEBUG),
            #'stroke_rate': (lambda evt: self.WRValues.update({'stroke_rate_pm': evt.value}), logging.DEBUG),    # use avg_time_stroke_whole instead 
            'display_sec': (lambda evt: setattr(self, '_seconds_wr', evt.value), logging.DEBUG),
            'display_min': (lambda evt: setattr(self, '_minutes_wr', evt.value), logging.DEBUG),
            'display_hr': (lambda evt: setattr(self, '_hours_wr', evt.value), logging.DEBUG),
            'display_sec_dec': (lambda evt: setattr(self, '_secdecWR', evt.value), logging.DEBUG),
            #'workout_total_time': (lambda evt: self.WRWorkout.update({'total_time': evt.value}), logging.DEBUG),
            #'workout_total_metres': (lambda evt: self.WRWorkout.update({'total_metres': evt.value}), logging.DEBUG),
            #'workout_total_strokes': (lambda evt: self.WRWorkout.update({'total_strokes': evt.value}), logging.DEBUG),
            #'workout_limit': (lambda evt: self.WRWorkout.update({'limit': evt.value}), logging.DEBUG),
            'workout_total_time': (None, logging.INFO),
            'workout_total_metres': (None, logging.INFO),
            'workout_total_strokes': (None, logging.INFO),
            'workout_work1': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest1': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work2': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest2': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work3': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest3': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work4': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest4': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work5': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest5': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work6': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest6': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work7': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest7': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work8': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_rest8': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_work9': (lambda evt: self._handle_workout_program(evt), logging.INFO),
            'workout_intervals': (lambda evt: self._handle_workout_program(evt), logging.INFO),
        }

        with self._wr_lock:
            handler = handlers.get(event.type)
            if not handler:
                logger.warning(f"On Rower Event received unhandled event type: {event.type}")
                return
            
            handler_func, log_level = handler
            if handler_func is not None:
                handler_func(event)
            if log_level is not None:
                self._log_s4data(event, log_level)
            # In the memory map, the time components are listed in order of increasing signficance: dec, sec, min, hr
            # and so are requested and also responded in that order. Therefore the elapsed time can be calculated
            # on receipt of the hr response.
            if event.type == 'display_sec_dec':
                self._compute_elapsed_time()
                
    def _handle_error(self, evt: S4Event) -> None:
        logger.warning(f"Recieved error packet from S4: {evt}")

    def _handle_workout_flags(self, evt: S4Event) -> None:

        if evt.value is None:
            return # No bit field recieved. Cannot assume no flags are set and so discard this event.
        
        with self._wr_lock:
            if self._workout_builder.update_if_flags_changed(evt.value):
                self.workout = None
                if self._rower_interface: 
                    self._rower_interface.set_request_category("workout", True)
                    self._rower_interface.set_request_category("distance", True)

            if self._zone_builder.update_type_if_flags_changed(evt.value):
                self.zone = None
                if self._rower_interface:
                    self._rower_interface.set_request_category("zone", True)
                    self._rower_interface.set_request_category("intensity", True)

    def _handle_misc_disp_flags(self, evt: S4Event) -> None:
        if evt.value is None:
            return # No bit field recieved. Cannot assume no flags are set and so discard this event.

        with self._wr_lock:
            if self._zone_builder.reset_bounds_if_flags_changed(evt.value):
                self.zone = None
                if self._rower_interface:
                    self._rower_interface.set_request_category("zone", True)
                    self._rower_interface.set_request_category("intensity", True)


    def _handle_workout_program(self, evt: S4Event) -> None:

        with self._wr_lock:
            self._workout_builder.update_from_event(evt)
            if self._workout_builder.is_valid():
                if self._rower_interface:
                    self._rower_interface.set_request_category("workout", False)
                    self._rower_interface.set_request_category("distance", False)
                self.workout = deepcopy(self._workout_builder)

    def _handle_zone_program(self, evt: S4Event) -> None:
        
        with self._wr_lock:
            self._zone_builder.update_from_event(evt)
            if self._zone_builder.is_valid():
                if self._rower_interface:
                    self._rower_interface.set_request_category("zone", False)
                    self._rower_interface.set_request_category("intensity", False)
                self.zone = deepcopy(self._zone_builder)
        
    def _handle_total_distance(self, evt: S4Event) -> None:
        with self._wr_lock:
            self.WRValues['total_distance_m'] = evt.value
            self._total_distance_m = evt.value

    def _handle_total_distance_dec(self, evt: S4Event) -> None:
        with self._wr_lock:
            value = evt.value
            self._total_distance_dec = value
            self._total_distance_cm = max(self._total_distance_cm or 0, (self._total_distance_m or 0) * 100 + (value or 0))

    def _handle_avg_time_stroke_whole(self, evt: S4Event) -> None:
        with self._wr_lock:
            duration_ms = (evt.value or 0) * 25
            self._stroke_duration = duration_ms
            self.WRValues['stroke_rate_pm'] = round(60000 / duration_ms if duration_ms else 0, 2)
            self._compute_stroke_ratio()

    def _handle_instant_avg_speed_cmps(self, evt: S4Event) -> None:
        speed = evt.value   # cm per sec

        with self._wr_lock:
            if not speed:
                updates = {'instant_500m_pace_secs': 0, 'speed_cmps': 0}
                if USE_CONCEPT2_POWER:
                    updates['instant_watts'] = 0
                self.WRValues.update(updates)
                return
            
            self.WRValues['speed_cmps'] = speed

            # Prefer using the 500mPace from the S4 if it is being captured and not ignored.
            # Otherwise compute the 500m pace from the speed.
            if not self._500m_pace:
                pace_500m = 50000 / speed
                self.WRValues['instant_500m_pace_secs'] = round(pace_500m)

            C2watts = round(2.80 / pow((100/speed), 3))
            self._concept2_watts = C2watts
            
            if USE_CONCEPT2_POWER:
                self.WRValues['instant_watts'] = C2watts

    def _handle_watts(self, evt: S4Event) -> None:
        with self._wr_lock:
            watts = evt.value
            self._watts_event_value = watts
            if self._drive_phase:
                self._stroke_max_power = max(self._stroke_max_power or 0, watts or 0)
            else:
                if self._stroke_max_power:
                    self._recent_strokes_max_power.append(self._stroke_max_power)
                    self._stroke_max_power = 0
                while len(self._recent_strokes_max_power) > NUM_STROKES_FOR_ROLLING_AVG_WATTS:
                    self._recent_strokes_max_power.pop(0)
                # Start reporting power from the first received value, rather than waiting for the buffer to fill
                if self._recent_strokes_max_power:
                    rolling_avg_watts = round(sum(self._recent_strokes_max_power) / len(self._recent_strokes_max_power))
                    self._rolling_avg_watts = rolling_avg_watts
                    if USE_CONCEPT2_POWER == False:
                        self.WRValues['instant_watts'] = rolling_avg_watts

    def _handle_500m_pace(self, evt: S4Event) -> None:
        # The WR will report 500m pace only when it is the selected intensity display value
        # on the S4. If the S4 is being reporting a non-zero value, then this function will
        # prefer the value reported by the S4 over the value derived from the cm/s speed.
        # To always use the value derived from speed, add 500m_pace to the IGNORE_LIST. 
        with self._wr_lock:
            self._500m_pace = evt.value
            if evt.value:
                self.WRValues['instant_500m_pace_secs'] = evt.value


    def _compute_elapsed_time(self) -> None:
        with self._wr_lock:
            #self.elapsetime = timedelta(seconds=self.secondsWR, minutes=self.minutesWR, hours=self.hoursWR)
            #self.elapsetime = int(self.elapsetime.total_seconds())
            compiled_time = (self._hours_wr or 0) * 3600 + (self._minutes_wr or 0) * 60 + (self._seconds_wr or 0) + (self._secdecWR or 0)/10
            # Try to mitigate the effects of the situation where the second ticks on in between getting all the components of time, which
            # can lead to large apparent jumps backwards in time (e.g. 1:59:59:59 going to 1:00:00:00 if the second ticks on between the
            # hour and the minute being fetched) 
            elapsed_time = max((self._elapsed_time or 0), compiled_time)
            self._elapsed_time = elapsed_time
            self.WRValues['elapsed_time_secs'] = int(elapsed_time)

    def _compute_stroke_ratio(self) -> None:
        with self._wr_lock:
            if self._stroke_duration and self._drive_duration:
                # Use the documented WR formula, which has a 1.25 multiplier
                strokeratio = round((self._stroke_duration - self._drive_duration) / (self._drive_duration * 1.25) , 2)
                self.WRValues['stroke_ratio'] = strokeratio
                    
    def _log_s4data(self, evt: S4Event, level: int = logging.INFO) -> None:
        '''
        Logs changes in values of the data from the s4 to the s4data logger defined in logging.conf.
        How much data is logged is determined by the combination of the 'level' argument sent to this
        function and the level of the s4data logger specified in logging.conf.
        Primarily of use for debugging/developing, e.g. to by watching the values change at the terminal like:
        less +F /opt/wrowfusion/logs/wrowfusion_s4_data.log
        Args:
            evt: the data from the S4
            level: the logging level which the event will be treated as
        Usage:
            self._log_s4data(evt, logging.DEBUG)  # Logged only if DEBUG is enabled
            self._log_s4data(evt, logging.INFO)   # Logged only if INFO is enabled
        '''
        
        if not self._data_logger.isEnabledFor(level):
            #logger.debug("Debug level {level} is not enabled, so not logging {evt}")
            return
        
        eventtype = evt.type
        value = evt.value
        oldvalue = self._logger_cache.get(eventtype)
        
        if oldvalue is not None:
            if oldvalue != value:
                self._data_logger.info(f"{eventtype} updated to: {value!r} from {oldvalue!r}")
                self._logger_cache[eventtype] = value
            else:
                logger.debug(f"No change in value for {evt}")
        else:
            self._data_logger.info(f"{eventtype} initialised at: {value!r}")
            self._logger_cache[eventtype] = value


    def _emit_session_signal(self, event: S4Event) -> None:
        match event.type:
            case 'stroke_start':
                self.session_tracker.process(StrokeStarted(event.at))
            case 'instant_avg_speed_cmps':
                speed = event.value  # Adjust to how you extract it
                if speed is not None:
                    self.session_tracker.process(SpeedChanged(event.at, speed))
            case 'reset':
                self.session_tracker.process(ResetDetected(event.at))
            case 'interval_start':
                self.session_tracker.process(IntervalStarted(index=event.data["index"], is_rest=False))
            case 'interval_rest':
                self.session_tracker.process(IntervalStarted(index=event.data["index"], is_rest=True))
            case 'interval_end':
                self.session_tracker.process(IntervalEnded(index=event.data["index"]))
            case 'workout_end':
                self.session_tracker.process(WorkoutCompleted(event.at))
            case 'zone':
                self.session_tracker.process(ZoneChanged(zone=event.data["zone"]))


    def pulse_monitor(self,event: S4Event) -> None:
        # As a callback, this function is called by the notifier each time any event 
        # is captured from the S4. The function detects when the paddle is stationary
        # by checking when the S4 last reported a pulse event (pulses are triggered as
        # the pulley rotates). Even when there is no rowing, the S4 at the very least
        # issues Ping events every second, so this function will continue to be called
        # even in the absence of a pulse event as long as the com remains open,
        # thereby allowing the time since the last pulse to be computed. If this is
        # longer than the NO_ROWING_PULSE_GAP in milliseconds (e.g. 300ms), then the 
        # paddle is assumed to be stationary and no rowing is taking place.
        self._last_check_for_pulse = int(round(time.time() * 1000))
        with self._wr_lock:
            if event.type == 'pulse':
                self._pulse_event_time = event.at

            if self._pulse_event_time:
                pulse_gap = self._last_check_for_pulse - self._pulse_event_time
            else:
                pulse_gap = float('inf')  # Assume paddle is not turning yet

            if pulse_gap <= NO_ROWING_PULSE_GAP:
                self._paddle_turning = True
            else:
                self._paddle_turning = False
                self._drive_phase = False
                self._recent_strokes_max_power = []
                self.WRValuesStandstill()
            self.WRValues["paddle_turning"] = self._paddle_turning  #TK

    def reset_rower(self):
        if self._rower_interface:
            self._rower_interface.request_reset()
        self._zero_state()

    def WRValuesStandstill(self) -> None:
        with self._wr_lock:
            self.WRValues_standstill = deepcopy(self.WRValues)
            self.WRValues_standstill.update({
                'stroke_rate_pm': 0.0,
                'instant_500m_pace_secs': 0,
                'speed_cmps': 0,
                'instant_watts': 0,
            })


    def get_WRValues(self) -> dict[str, Any]:
        logger.debug("getWRValues starting lock")
        with self._wr_lock:               
            if self._paddle_turning:
                logger.debug("getWRValues handling PaddleTurning")
                values = deepcopy(self.WRValues)
            else:
                logger.debug("getWRValues handling standstill")     
                #values = deepcopy(self.WRValues_standstill)    #tk undo
                values = deepcopy(self.WRValues)                #tk undo
            #logger.debug("getWRValues ending lock")
        logger.debug("getWRValues lock ended")
        return values


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


def s4_data_task(rower_state: RowerState):
    logger.debug("s4_data_task: Initialising Rower class")
    S4 = Rower()
    logger.debug("s4_data_task: Opening Rower class")
    S4.open()
    # Control will not return until a connection has been succesfully opened
    # This means the thread will stay alive, but the code below and the loop
    # which polls the S4 will not be executed unecessarily before an S4 is
    # connected
    
    #S4.request_reset()
    #logger.debug("s4_data_task: Initialising RowerState")

    rower_state.initialise(S4)
    logger.info("Waterrower Ready and sending data to BLE and ANT Thread")

    while True:
 #       start = time.time()
#        try:
#            if not in_q.empty():
#                ResetRequest_ble = in_q.get()
#                parts = ResetRequest_ble.split()
#                cmd = parts[0]
#                if cmd == "reset_ble":
#                    S4.request_reset()
                #elif cmd == "hr":
                #    new_hr = int(parts[1])
                #    if new_hr != ext_hr:
                #        ext_hr = new_hr
                #        ext_hr_time = time.time()
                #        print("ext_hr", ext_hr)

            #logger.debug("Calling CueBLEANT")
            
            #WRtoBLEANT.CueBLEANT(ble_out_q, ant_out_q, hrm)
            #logger.debug("Returned from CueBLEANT")
#        except Exception as e:
#            logger.exception(f"Exception in s4_data_task loop: {e}")
        
#        duration = time.time() - start
#        if duration > 1:
#            logger.warning(f"CueBLEANT took too long: {duration:.2f}s")

        #print(type(ant_out_q))
        #print(ant_out_q)
        #logger.info(WRtoBLEANT.BLEvalues)
        #ant_out_q.append(WRtoBLEANT.ANTvalues)
        time.sleep(0.1)
