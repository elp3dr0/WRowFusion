import threading
import logging
import time
from gpiozero import DigitalOutputDevice
from copy import deepcopy
#from datetime import timedelta

from src.s4if import Rower
from src.heart_rate import HeartRateMonitor

logger = logging.getLogger(__name__)

'''
This module:
1) Simulates a heart beat ant+ signal on a GPIO pin to feed into the S4 monitor via the 3.5mm plug
2) Captures the data from the s4 using the Rower class defined in s4if.py.

In the case of 2)
3 callback functions are registered to the s4if.Rower class. Those functions get exectuted as soon as any of the 
events for which we watch is recieved from the s4 via the Rower.start_capturing() method.
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


# Define GPIO pin
HEARTBEAT_PIN = 18
heartbeat_signal = DigitalOutputDevice(HEARTBEAT_PIN, active_high=True, initial_value=False)

# The time between pulses after which the paddle is assumed to be stationary and no rowing is happening
# Specified in milliseconds
NO_ROWING_PULSE_GAP = 300

IGNORE_LIST = ['graph', 'tank_volume']

# Smooth the displayed power by finding the average max power output over a number of strokes 
NUM_STROKES_FOR_POWER_AVG = 4

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
        self._LastCheckForPulse = None
        self._PulseEventTime = None
        self._PaddleTurning = None
        self._RowerReset = None
        self._secondsWR = None
        self._minutesWR = None
        self._hoursWR = None
        self._secdecWR = None
        self.WRValues_rst = None
        self.WRValues = None
        self.WRValues_standstill = None
        self.TXValues = None

        if rower_interface is not None:
            self.initialise(rower_interface)

    def initialise(self, rower_interface):
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
            self._LastCheckForPulse = 0
            self._PulseEventTime = 0
            self._PaddleTurning = False
            self._RowerReset = True
            self._secondsWR = 0
            self._minutesWR = 0
            self._hoursWR = 0
            self._secdecWR = 0
            self.WRValues_rst = {
                    'stroke_rate': 0,
                    'total_strokes': 0,
                    'total_distance_m': 0,
                    'instant_pace': 0,
                    'speed': 0,
                    'watts': 0,
                    'total_kcal': 0,
                    'total_kcal_hour': 0,
                    'total_kcal_min': 0,
                    'heart_rate': 0,
                    'elapsedtime': 0.0,
                }
            self.WRValues = deepcopy(self.WRValues_rst)
            self.WRValues_standstill = deepcopy(self.WRValues_rst)
            self.TXValues = deepcopy(self.WRValues_rst)
            logger.debug("DataLogger._reset_state: Values set")
            logger.debug(f"DataLogger._reset_state: WRValues = {self.WRValues}")
            logger.debug("DataLogger._reset_state: Releasing lock")
        logger.debug("DataLogger._reset_state: Lock released.")

    def on_rower_event(self, event):

        logger.debug(f"Received event: {event}")
        with self._wr_lock:
            if event['type'] in IGNORE_LIST:
                return
            if event['type'] == 'stroke_start':
                self._DrivePhase = True
            if event['type'] == 'stroke_end':
                self._DrivePhase = False
            if event['type'] == 'stroke_rate':
                self.WRValues.update({'stroke_rate': (event['value']*2)})
            if event['type'] == 'total_strokes':
                self.WRValues.update({'total_strokes': event['value']})
            if event['type'] == 'total_distance_m':
                self.WRValues.update({'total_distance_m': (event['value'])})
            if event['type'] == 'avg_distance_cmps':
                if event['value'] == 0:
                    self.WRValues.update({'instant_pace': 0})
                    self.WRValues.update({'speed':0})
                else:
                    PaceFromSpeed = (500 * 100) / event['value']
                    #print(f{PaceFromSpeed})
                    self.WRValues.update({'instantaneous pace': PaceFromSpeed})
                    self.WRValues.update({'speed':event['value']})
            if event['type'] == 'watts':
                self._WattsEventValue = event['value']
                self.update_live_avg_power(self._WattsEventValue)
            if event['type'] == 'total_kcal':
                self.WRValues.update({'total_kcal': ((event['value']+500)/1000)})  # convert calories into kCal (add 500 first to implement arithmetic rounding rather than rounding down)
            if event['type'] == 'total_kcal_h':  # must calclatre it first
                self.WRValues.update({'total_kcal': 0})
            if event['type'] == 'total_kcal_min':  # must calclatre it first
                self.WRValues.update({'total_kcal': 0})
            if event['type'] == 'heart_rate':
                self.WRValues.update({'heart_rate': (event['value'])})
            if event['type'] == 'display_sec':
                self._secondsWR = event['value']
            if event['type'] == 'display_min':
                self._minutesWR = event['value']
            if event['type'] == 'display_hr':
                self._hoursWR = event['value']
            if event['type'] == 'display_sec_dec':
                self._secdecWR = event['value']
        self.TimeElapsedcreator()


    def pulse_monitor(self,event):
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
            if event['type'] == 'pulse':
                self._PulseEventTime = event['at']
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

    def reset_requested(self,event):
        if event['type'] == 'reset':
            logger.debug("DataLogger.reset_requested: Requesting Lock")
            with self._wr_lock:
                logger.debug("DataLogger.reset_requested: Lock attained")
                logger.debug("DataLogger.reset_requested: Calling _reset_state")
                self._reset_state()
                logger.info("value reseted")

    def TimeElapsedcreator(self):
        with self._wr_lock:
            #self.elapsetime = timedelta(seconds=self.secondsWR, minutes=self.minutesWR, hours=self.hoursWR)
            #self.elapsetime = int(self.elapsetime.total_seconds())
            elapsed_time = int(self._hoursWR * 3600 + self._minutesWR * 60 + self._secondsWR + (1 if self._secdecWR >= 5 else 0))
            self.WRValues.update({'elapsedtime': elapsed_time})

    def WRValuesStandstill(self):
        with self._wr_lock:
            self.WRValues_standstill = deepcopy(self.WRValues)
            self.WRValues_standstill.update({
                'stroke_rate': 0,
                'instant_pace': 0,
                'speed': 0,
                'watts': 0,
            })

    def update_live_avg_power(self,watts):
        with self._wr_lock:
            if self._DrivePhase:
                self._StrokeMaxPower = max(self._StrokeMaxPower, watts)
            else:
                if self._StrokeMaxPower:
                    self._RecentStrokesMaxPower.append(self._StrokeMaxPower)
                    self._StrokeMaxPower = 0
                while len(self._RecentStrokesMaxPower) > NUM_STROKES_FOR_POWER_AVG:
                    self._RecentStrokesMaxPower.pop(0)
                if len(self._RecentStrokesMaxPower) == NUM_STROKES_FOR_POWER_AVG:
                    live_avg_power = int(sum(self._RecentStrokesMaxPower) / len(self._RecentStrokesMaxPower))
                    self.WRValues.update({'watts': live_avg_power})


    def get_WRValues(self):
        #logger.debug("getWRValues starting lock")
        with self._wr_lock:
            #logger.debug("getWRValues lock started")                
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
        #logger.debug("getWRValues lock ended")
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
    
    S4.reset_request()
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
                    S4.reset_request()
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