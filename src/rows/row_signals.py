import logging

from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)

class RowingState(Enum):
    IDLE = auto()
    ROWING = auto()

class WorkoutPhase(Enum):
    JUST_ROW = auto()
    WORK = auto()
    REST = auto()

@dataclass
class RowSignal:
    timestamp: float

@dataclass
class StrokeStarted(RowSignal):
    pass

@dataclass
class SpeedChanged(RowSignal):
    speed: float

@dataclass
class RowingStateChanged(RowSignal):
    new_state: RowingState

@dataclass
class IntervalStarted(RowSignal):
    interval_index: int
    phase: WorkoutPhase

@dataclass
class IntervalEnded(RowSignal):
    interval_index: int

@dataclass
class WorkoutCompleted(RowSignal):
    pass

@dataclass
class ResetDetected(RowSignal):
    pass

@dataclass
class ZoneChanged(RowSignal):
    zone: int | None