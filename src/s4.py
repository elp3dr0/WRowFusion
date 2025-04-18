import threading
import logging
import time
from gpiozero import DigitalOutputDevice
from copy import deepcopy
from datetime import timedelta

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
1) reset_requested: Intention is to reset the S4, so all values should be set to 0 even if old values persist in the WR memory 
2) pulse: Caters for the periods of no rowing (e.g. during rest intervals). Set all instantaneous values to 0 e.g power, pace, 
   stroke rate. Other values are not set to 0 in the WR memory.
3) on_rower_event: Normal rowing, so capture data from WR memory without modification 

Depeding on thoses cases, send only the value dict with the correct numbers to the bluetooth module. 

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

IGNORE_LIST = ['graph', 'tank_volume', 'display_sec_dec']
# Power 
POWER_AVG_STROKES = 4


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


class DataLogger(object):
    def __init__(self, rower_interface):
        self._rower_interface = rower_interface
        self._rower_interface.register_callback(self.reset_requested)
        self._rower_interface.register_callback(self.pulse)
        self._rower_interface.register_callback(self.on_rower_event)
        self._stop_event = threading.Event()

        self._wr_lock = threading.RLock()

        self._InstaPowerStroke = None
        self.maxpowerStroke = None
        self._StrokeStart = None        # Our _StrokeStart is set to True at when the S4 determines pulley accelleration
                                        # and set to False when S4 detects pulley decelleration. It is therefore True
                                        # throughout the whole Drive phase of the stroke and False during recover phase. 
        self._StrokeTotal = None
        self.Watts = None
        self.AvgInstaPower = None
        self.Lastcheckforpulse = None
        self.PulseEventTime = None
        self.InstantaneousPace = None
        self.DeltaPulse = None
        self.PaddleTurning = None
        self.rowerreset = None
        self.WRValues_rst = None
        self.WRValues = None
        self.WRValues_standstill = None
        self.BLEvalues = None
        self.ANTvalues = None
        self.secondsWR = None
        self.minutesWR = None
        self.hoursWR = None
        self.elapsetime = None
        self.elapsetimeprevious = None

        # Initialise the attributes, particularly the WRValues dictionaries because subsequent
        # code tries to update the values of the dictionaries and so expect the dictionary keys
        # to exist already.
        self._reset_state()

    def _reset_state(self):
        logger.debug("DataLogger._reset_state: Attempting lock")
        with self._wr_lock:
            logger.debug("DataLogger._reset_state: Lock attained, setting values")
            self._InstaPowerStroke = []
            self.maxpowerStroke = 0
            self._StrokeStart = False
            self._StrokeTotal = 0
            self.Watts = 0
            self.AvgInstaPower = 0
            self.Lastcheckforpulse = 0
            self.PulseEventTime = 0
            self.InstantaneousPace = 0
            self.DeltaPulse = 0
            self.PaddleTurning = False
            self.rowerreset = True
            self.WRValues_rst = {
                    'stroke_rate': 0,
                    'total_strokes': 0,
                    'total_distance_m': 0,
                    'instantaneous pace': 0,
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
            self.BLEvalues = deepcopy(self.WRValues_rst)
            self.ANTvalues = deepcopy(self.WRValues_rst)
            self.secondsWR = 0
            self.minutesWR = 0
            self.hoursWR = 0
            self.elapsetime = 0
            self.elapsetimeprevious = 0
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
                self._StrokeStart = True
            if event['type'] == 'stroke_end':
                self._StrokeStart = False
            if event['type'] == 'stroke_rate':
                self.WRValues.update({'stroke_rate': (event['value']*2)})
            if event['type'] == 'total_strokes':
                self._StrokeTotal = event['value']
                self.WRValues.update({'total_strokes': event['value']})
            if event['type'] == 'total_distance_m':
                self.WRValues.update({'total_distance_m': (event['value'])})
            if event['type'] == 'avg_distance_cmps':
                if event['value'] == 0:
                    self.WRValues.update({'instantaneous pace': 0})
                    self.WRValues.update({'speed':0})
                else:
                    self.InstantaneousPace = (500 * 100) / event['value']
                    #print(self.InstantaneousPace)
                    self.WRValues.update({'instantaneous pace': self.InstantaneousPace})
                    self.WRValues.update({'speed':event['value']})
            if event['type'] == 'watts':
                self.Watts = event['value']
                self.avgInstaPowercalc(self.Watts)
            if event['type'] == 'total_kcal':
                self.WRValues.update({'total_kcal': (event['value']/1000)})  # in cal now in kcal
            if event['type'] == 'total_kcal_h':  # must calclatre it first
                self.WRValues.update({'total_kcal': 0})
            if event['type'] == 'total_kcal_min':  # must calclatre it first
                self.WRValues.update({'total_kcal': 0})
            if event['type'] == 'heart_rate':
                self.WRValues.update({'heart_rate': (event['value'])})
            if event['type'] == 'display_sec':
                self.secondsWR = event['value']
            if event['type'] == 'display_min':
                self.minutesWR = event['value']
            if event['type'] == 'display_hr':
                self.hoursWR = event['value']
        self.TimeElapsedcreator()


    def pulse(self,event):
        # As a callback, this function is called by the notifier each time any event 
        # is captured from the S4. The function detects when the paddle is stationary
        # by checking when the S4 last reported a pulse event (pulses are triggered as
        # the pulley rotates). Even when there is no rowing, the S4 at the very least
        # issues Ping events every second, so this function will continue to be called
        # even in the absence of a pulse event as long as the com remains open,
        # thereby allowing the time since the last pulse to be computed. If this is
        # longer than the NO_ROWING_PULSE_GAP in milliseconds (e.g. 300ms), then the 
        # paddle is assumed to be stationary and no rowing is taking place.
        self.Lastcheckforpulse = int(round(time.time() * 1000))
        with self._wr_lock:
            if event['type'] == 'pulse':
                self.PulseEventTime = event['at']
                self.rowerreset = False

            if self.PulseEventTime is not None:
                self.DeltaPulse = self.Lastcheckforpulse - self.PulseEventTime
            else:
                self.DeltaPulse = float('inf')  # Assume paddle is not turning yet

            if self.DeltaPulse <= NO_ROWING_PULSE_GAP:
                self.PaddleTurning = True
            else:
                self.PaddleTurning = False
                self._StrokeStart = False
                self.PulseEventTime = 0
                self._InstaPowerStroke = []
                self.AvgInstaPower = 0
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
            self.elapsetime = timedelta(seconds=self.secondsWR, minutes=self.minutesWR, hours=self.hoursWR)
            self.elapsetime = int(self.elapsetime.total_seconds())
            # print('sec:{0};min:{1};hr:{2}'.format(self.secondsWR,self.minutesWR,self.hoursWR))
            self.WRValues.update({'elapsedtime': self.elapsetime})
            self.elapsetimeprevious = self.elapsetime

    def WRValuesStandstill(self):
        with self._wr_lock:
            self.WRValues_standstill = deepcopy(self.WRValues)
            self.WRValues_standstill.update({'stroke_rate': 0})
            self.WRValues_standstill.update({'instantaneous pace': 0})
            self.WRValues_standstill.update({'heart_rate': 0})
            self.WRValues_standstill.update({'speed': 0})
            self.WRValues_standstill.update({'watts': 0})

    def avgInstaPowercalc(self,watts):
        with self._wr_lock:
            if self._StrokeStart:
                self.maxpowerStroke = max(self.maxpowerStroke, watts)
            else:
                if self.maxpowerStroke:
                    self._InstaPowerStroke.append(self.maxpowerStroke)
                    self.maxpowerStroke = 0
                while len(self._InstaPowerStroke) > POWER_AVG_STROKES:
                    self._InstaPowerStroke.pop(0)
                if len(self._InstaPowerStroke) == POWER_AVG_STROKES:
                    self.AvgInstaPower = int(sum(self._InstaPowerStroke) / len(self._InstaPowerStroke))
                    self.WRValues.update({'watts': self.AvgInstaPower})


    def get_WRValues(self):
        #logger.debug("getWRValues starting lock")
        with self._wr_lock:
            #logger.debug("getWRValues lock started")                
            if self.rowerreset:
                #logger.debug("getWRValues handling rowerreset")
                values = deepcopy(self.WRValues_rst)
            elif self.PaddleTurning:
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
                self.BLEvalues = values
                self.ANTvalues = values
            logger.debug(f"CueBLEANT got values to append to dqueues from S4: {values}")
            ble_out_q.append(values)
            ant_out_q.append(values)

def s4_data_task(in_q, ble_out_q, ant_out_q, hrm: HeartRateMonitor):
    logger.debug("s4_data_task: Initialising Rower class")
    S4 = Rower()
    logger.debug("s4_data_task: Opening Rower class")
    S4.open()
    # Control will not return until a connection has been succesfully opened
    # This means the thread will stay alive, but the code below and the loop
    # which polls the S4 will not be executed unecessarily while an S4 is not
    # connected
    
    S4.reset_request()
    logger.debug("s4_data_task: Initialising DataLogger")

    WRtoBLEANT = DataLogger(S4)
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

            logger.debug("Calling CueBLEANT")
            WRtoBLEANT.CueBLEANT(ble_out_q, ant_out_q, hrm)
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
#             #print("Lastcheck {0}".format(WRtoBLEANT.Lastcheckforpulse))
#             #print("last pulse {0}".format(WRtoBLEANT.PulseEventTime))
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