import logging
import re

from src.s4.s4if import (
    S4Event,
    WorkoutMode,
    DistanceMode,
    IntensityMode,
)

logger = logging.getLogger(__name__)

class Workout:
    def __init__(self):
        self._workout_flags: int | None = None
        self.type: str | None = None
        self.intervals_set: bool | None = None  
        self.intervals: int | None = None
        self.units: str | None = None
        self.work_targets: dict[int, int] = {}  # e.g. {1: 300, 2: 500}
        self.rest_durations: dict[int, int] = {}  # e.g. {1: 60, 2: 90}

    def reset(self) -> None:
        self.__init__()

    def update_if_flags_changed(self, flags: int) -> bool:
        '''
        Returns:
            True if the Workout flags have changed
            False if the Workout flags haven't changed
        '''
        
        if self._workout_flags is not None and not WorkoutMode.changed_workout_bits(self._workout_flags, flags):
            # No change in workout flags
            return False
        
        # The S4's workout settings have changed.
        self.reset()

        mode = WorkoutMode(flags)

        if mode.has_workout_set():
            if mode.is_duration():
                self.type = "duration"
                self.units = "secs"
            elif mode.is_distance():
                self.type = "distance"

            self.intervals_set = mode.is_interval()

        else:
            self.type = "just_row"
            self.intervals_set = False

        self._workout_flags = flags
        return True

    def update_from_event(self, evt: S4Event) -> None:
        if evt.value is None:
            return

        if evt.type == "workout_intervals":
            self.workout = max(evt.value - 1, 0)
            return

        if evt.type == "distance1_disp_flags":
            distance_flags = DistanceMode(evt.value)
            selected_unit = DistanceMode.get_single_unit_mode(distance_flags)
            if not selected_unit:
                # No unit selected yet.
                return

            unit_map = {
                DistanceMode.UNITS_METRES: "metres",
                DistanceMode.UNITS_MILES: "miles",
                DistanceMode.UNITS_KM: "km",
                DistanceMode.UNITS_STROKES: "strokes",
            }
            self.units = unit_map.get(selected_unit)
            return

        # Match type like 'workout_work3' or 'workout_rest2'
        match = re.match(r"workout_(work|rest)(\d+)", evt.type)
        if not match:
            return  # Not an interval component

        kind, index = match.group(1), int(match.group(2))

        if kind == "work":
            self.work_targets[index] = evt.value
        elif kind == "rest":
            self.rest_durations[index] = evt.value

    def is_valid(self) -> bool:
        '''Checks whether the components of a workout are coherent. However, it does not 
        go as far as checking or validating the validity of values of the work and rest periods themselves,
        just that there are the right number of them.'''
        if self.type is None or self.units is None:
            return False
        if self.type == "duration" and self.units != "secs":
            logger.warning(f"Duration workout expects units to be seconds, but units are: {self.units}")
            return False
        elif self.type == "distance" and self.units not in ["metres", "strokes", "miles", "km"]:
            return False 

        if self.intervals_set is None:
            if self.intervals is not None:
                logger.warning("Intervals count is set but intervals_set flag is None (unset)")
            else:
                return False  # Neither intervals nor intervals_set is set – configuration incomplete
        if self.intervals_set:
            if self.intervals is None:
                return False    # The interval count has not been captured yet
            if self.intervals == 0:
                logger.warning("An interval workout is selected, but the interval count is set at 0")
                return False
            expected_intervals = (len(self.work_targets) + len(self.rest_durations))
            if expected_intervals > self.intervals:
                logger.warning(f"The interval count reported by the S4 is less than the number of work and rest periods")
                return False
            else:
                return (len(self.work_targets) + len(self.rest_durations)) == self.intervals # Workout is valid if the number of work and rest periods equal the number of expected intervals
        else:
            if self.intervals and self.intervals > 1:
                logger.warning("Non-interval workout has multiple intervals set")
            return len(self.work_targets) == 1
                    
    def as_ordered_lists(self):
        work = [self.work_targets[k] for k in sorted(self.work_targets)]
        rest = [self.rest_durations[k] for k in sorted(self.rest_durations)]
        return work, rest


class Zone:
    def __init__(self):
        self._workout_flags: int | None = None
        self._zone_trigger_flags: int | None = None
        self.type: str | None = None
        self.units: str | None = None
        self.bounds: dict[str, tuple[int | None, int | None]] = {}

    def reset(self) -> None:
        self.__init__()
    
    def _reset_bounds(self) -> None:
        self.bounds = {
            'bpm': (None, None), 
            'mps': (None, None),
            'mph': (None, None), 
            '500m_pace': (None, None), 
            '2km_pace': (None, None), 
            'spm': (None, None),
        }

    def reset_bounds_if_flags_changed(self, flags: int) -> bool:
        '''
        Unlike workout, a user can change the upper or lower bounds of a zone without triggering
        a change in the workout flags. Therefore we use a proxy (typically misc_display_flags) 
        which we know will change whenever the user makes any change to the zone settings.
        Returns:
            True if the flags have changed.
            False if the flags haven't changed.
            False if a zone isn't selected by the workout flags 
        '''
        old_flags = self._zone_trigger_flags
        if old_flags is not None and old_flags == flags:
            # No change in workout flags
            return False
        
        # The S4's workout settings have changed.
        self._zone_trigger_flags = flags

        mode = WorkoutMode(flags)
        zone_type = mode.get_zone_type()
        if zone_type is None:
            # No zone is selected so ignore this change in misc_display_flags
            return False
        
        # The S4 is configured to work within a zone, so this change in misc_display_flags
        # could indicate that the user has chnaged zone bounds. Reset the bounds and tell
        # the caller so that it can take action to refresh the bounds.
        self._reset_bounds
        return True

    def update_type_if_flags_changed(self, flags: int) -> bool:
        '''
        Returns:
            True if the Zone bits of the workout flags have changed
            False if the Zone bits of the workout flags haven't changed
        '''
        if self._workout_flags is not None and not WorkoutMode.changed_zone_bits(self._workout_flags, flags):
            # No change in workout flags
            return False
        
        # The S4's selected zone has changed.
        self._workout_flags = flags

        mode = WorkoutMode(flags)
        zone_type = mode.get_zone_type()
        self.type = zone_type
        self.units = None
        if self.type == "heart_rate":
            self.units = "bpm"
        elif self.type == "stroke_rate":
            self.units = "spm"

        self._reset_bounds()
        return True

    def update_from_event(self, evt: S4Event) -> None:
        if evt.value is None:
            return

        if evt.type == "intensity2_disp_flags":
            intensity_flags = IntensityMode(evt.value)
            selected_unit = IntensityMode.get_single_unit_mode(intensity_flags)
            if not selected_unit:
                # No unit selected yet.
                return

            unit_map = {
                IntensityMode.UNITS_MPS: "mps",
                IntensityMode.UNITS_MPH: "mph",
                IntensityMode.UNITS_SECS_500m: "500m_pace",
                IntensityMode.UNITS_SECS_2KM: "2km_pace",
            }
            self.units = unit_map.get(selected_unit)
            return
        
        label_map = {
            'hr': 'bpm',
            'mps': 'mps',
            'mph': 'mph',
            '500m_pace': '500m_pace',
            '2km_pace': '2km_pace',
            'sr': 'spm',
        }

        match = re.match(r"zone_(int_)?([a-z0-9]+)_(upper|lower)", evt.type)
        if not match:
            return  # Not a zone bound update

        short_label = match.group(2)
        bound_type = match.group(3)
        key = label_map.get(short_label)
        
        if key in self.bounds:
            current_lower, current_upper = self.bounds[key]
            if bound_type == 'lower':
                self.bounds[key] = (evt.value, current_upper)
            else:  # 'upper'
                self.bounds[key] = (current_lower, evt.value)

    def is_valid(self) -> bool:
        if any(x is None for x in [self.type, self.units]):
            return False
        assert self.units is not None

        if self.type == "intensity" and self.units not in ["mps", "mph", "500m_pace", "2km_pace"]:
            logger.debug(f"Zone set as intensity but unexpected units: {self.units}")
            return False

        if any(None in bounds for bounds in self.bounds.values()):
            # At least one Upper or lower bound is not yet set. The s4 monitor stores
            # the upper and lower bounds for all types of zone regardless of which one
            # (if any) is selected, so keep polling to get all of the bounds.
            return False 
        return True