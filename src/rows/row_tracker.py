import logging

from enum import Enum, auto
from typing import Optional
import time

from src.rows.row_signals import (
    RowSignal,
    StrokeStarted,
    SpeedChanged,
    RowingStateChanged,
    IntervalStarted,
    IntervalEnded,
    WorkoutCompleted,
    ResetDetected,
    ZoneChanged,
    RowingState,
    WorkoutPhase,
)

logger = logging.getLogger(__name__)

IDLE_TIMEOUT = 600      # Automatically end a session after this many seconds of idle (i.e. no rowing detected)   

class SessionState(Enum):
    RESET = auto()
    ACTIVE = auto()
    ENDED = auto()


class RowSessionTracker:
    def __init__(self):
        self.session_state: SessionState = SessionState.RESET
        self.rowing_state: RowingState = RowingState.IDLE
        self.current_interval: int | None = None
        self.current_phase: WorkoutPhase | None = None
        self.last_activity_ts: float | None = None
        self.zone: int | None = None

    def process(self, signal: RowSignal):
        """Process a RowSignal and update internal state."""
        self.last_activity_ts = signal.timestamp

        match signal:
            case ResetDetected():
                self._enter_reset_state()

            case StrokeStarted():
                if self.session_state == SessionState.RESET:
                    self._start_session()

            case SpeedChanged(speed=0):
                self.rowing_state = RowingState.IDLE

            case SpeedChanged(speed=_):
                self.rowing_state = RowingState.ROWING

            case RowingStateChanged(new_state=new_state):
                self.rowing_state = new_state

            case IntervalStarted(interval_index=index, phase=phase):
                self.current_interval = index
                self.current_phase = phase

            case IntervalEnded(interval_index=_):
                self.current_phase = None

            case WorkoutCompleted():
                self._end_session()

            case ZoneChanged(zone=zone):
                self.zone = zone

            case _:
                pass  # Unknown or unhandled signal

    def _start_session(self):
        self.session_state = SessionState.ACTIVE
        self.current_interval = None
        self.current_phase = None
        logger.info("Row session started")

    def _end_session(self):
        self.session_state = SessionState.ENDED
        logger.info("Row session ended")

    def _enter_reset_state(self):
        self.session_state = SessionState.RESET
        self.rowing_state = RowingState.IDLE
        self.current_interval = None
        self.current_phase = None
        self.zone = None
        logger.info("Reset state entered")

    def check_for_idle_timeout(self, timeout_secs: int = IDLE_TIMEOUT):
        """Check for idle timeout (e.g., to reset after 10 minutes)."""
        if self.last_activity_ts and time.time() - self.last_activity_ts > timeout_secs:
            logger.info("Idle timeout reached. Ending session and resetting rower")
            self._enter_reset_state()
