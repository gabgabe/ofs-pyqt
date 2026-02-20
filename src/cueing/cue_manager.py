"""
Cueing System - Bridge between funscript playback and device control.

Adapted from zhappy's cue_manager.py and data_models.py.
Connects funscript position/speed data to device parameters via
the same signal-based architecture used in zhappy.

Supports:
- Static cues (fixed parameter values)
- Dynamic cues (time-varying parameters)
- Funscript cues (position-driven from funscript data)
"""

import logging
import json
import os
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

from PySide6.QtCore import QObject, Signal, QTimer

log = logging.getLogger(__name__)


# === Data Models (from zhappy data_models.py) ===

class CueType(Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    FUNSCRIPT = "funscript"


class CueExecutionMode(Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    FUNSCRIPT = "funscript"


class CueState(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"


class ParameterMode(Enum):
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    MULTIPLY = "multiply"


@dataclass
class ParameterValue:
    """Single parameter value with mode."""
    value: float = 0.0
    mode: ParameterMode = ParameterMode.ABSOLUTE
    min_val: float = 0.0
    max_val: float = 255.0


@dataclass
class CueData:
    """
    Cue data structure - combines zhappy's ParameterCueData, FunscriptData,
    and PlaybackControlData into a unified cue.
    """
    cue_id: str = ""
    name: str = ""
    cue_type: CueType = CueType.STATIC
    state: CueState = CueState.IDLE

    # Timing
    start_time: float = 0.0      # seconds
    duration: float = 1.0        # seconds
    fade_in: float = 0.0         # seconds
    fade_out: float = 0.0        # seconds

    # Parameters (subset of zhappy's full parameter set)
    # Maps parameter name → ParameterValue
    parameters: Dict[str, ParameterValue] = field(default_factory=dict)

    # Funscript binding (for CueType.FUNSCRIPT)
    funscript_track: str = ""     # track name
    funscript_mapping: str = ""   # target parameter name (e.g., "intensity_a")
    funscript_scale_min: float = 0.0
    funscript_scale_max: float = 255.0

    # Metadata
    layer: int = 0
    color: str = "#7c4dff"
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d['cue_type'] = self.cue_type.value
        d['state'] = self.state.value
        # Convert parameter values
        params = {}
        for k, v in self.parameters.items():
            params[k] = {'value': v.value, 'mode': v.mode.value,
                         'min_val': v.min_val, 'max_val': v.max_val}
        d['parameters'] = params
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'CueData':
        cue = cls()
        cue.cue_id = data.get('cue_id', '')
        cue.name = data.get('name', '')
        cue.cue_type = CueType(data.get('cue_type', 'static'))
        cue.start_time = data.get('start_time', 0.0)
        cue.duration = data.get('duration', 1.0)
        cue.fade_in = data.get('fade_in', 0.0)
        cue.fade_out = data.get('fade_out', 0.0)
        cue.funscript_track = data.get('funscript_track', '')
        cue.funscript_mapping = data.get('funscript_mapping', '')
        cue.funscript_scale_min = data.get('funscript_scale_min', 0.0)
        cue.funscript_scale_max = data.get('funscript_scale_max', 255.0)
        cue.layer = data.get('layer', 0)
        cue.color = data.get('color', '#7c4dff')
        cue.notes = data.get('notes', '')

        for k, v in data.get('parameters', {}).items():
            cue.parameters[k] = ParameterValue(
                value=v.get('value', 0.0),
                mode=ParameterMode(v.get('mode', 'absolute')),
                min_val=v.get('min_val', 0.0),
                max_val=v.get('max_val', 255.0)
            )
        return cue


# === Cue Manager (from zhappy cue_manager.py) ===

class CueManager(QObject):
    """
    Centralized cue management - adapted from zhappy's UnifiedCueManager.
    
    Manages cue storage, execution, and signal emission.
    Drives device parameters based on funscript playback position.
    """

    # Signals (same pattern as zhappy)
    cue_stored = Signal(str)        # cue_id
    cue_updated = Signal(str)       # cue_id
    cue_deleted = Signal(str)       # cue_id
    cue_activated = Signal(str)     # cue_id
    cue_deactivated = Signal(str)   # cue_id

    # Device parameter output signals
    parameter_changed = Signal(str, float)  # param_name, value (0-255)
    all_parameters_changed = Signal(dict)   # {param_name: value}

    def __init__(self, parent=None):
        super().__init__(parent)

        self._cues: Dict[str, CueData] = {}
        self._active_cues: Dict[str, CueData] = {}
        self._current_time: float = 0.0  # seconds

        # 60 FPS update timer for dynamic cues (same as zhappy)
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_active_cues)
        self._update_timer.setInterval(16)  # ~60fps

        self._data_dir: str = ""

    # === Storage ===

    def store_cue(self, cue: CueData) -> str:
        """Store a cue and emit signal."""
        if not cue.cue_id:
            import uuid
            cue.cue_id = str(uuid.uuid4())[:8]
        self._cues[cue.cue_id] = cue
        self.cue_stored.emit(cue.cue_id)
        log.info(f"Cue stored: {cue.cue_id} '{cue.name}'")
        return cue.cue_id

    def get_cue(self, cue_id: str) -> Optional[CueData]:
        return self._cues.get(cue_id)

    def delete_cue(self, cue_id: str):
        if cue_id in self._cues:
            del self._cues[cue_id]
            self._active_cues.pop(cue_id, None)
            self.cue_deleted.emit(cue_id)

    def get_all_cues(self) -> List[CueData]:
        return list(self._cues.values())

    # === Execution ===

    def set_time(self, seconds: float):
        """Update current playback time. Called from video player."""
        self._current_time = seconds

    def start(self):
        """Start cue execution timer."""
        self._update_timer.start()

    def stop(self):
        """Stop cue execution timer."""
        self._update_timer.stop()
        # Deactivate all
        for cue_id in list(self._active_cues.keys()):
            self._deactivate_cue(cue_id)

    def _update_active_cues(self):
        """Called at ~60fps to update active cues and emit parameter values."""
        t = self._current_time
        output: Dict[str, float] = {}

        for cue in self._cues.values():
            in_range = cue.start_time <= t <= (cue.start_time + cue.duration)

            if in_range:
                if cue.cue_id not in self._active_cues:
                    self._activate_cue(cue)

                # Calculate parameter values
                elapsed = t - cue.start_time
                fade_factor = self._calc_fade(cue, elapsed)

                for param_name, pv in cue.parameters.items():
                    val = pv.value * fade_factor
                    if pv.mode == ParameterMode.ABSOLUTE:
                        output[param_name] = val
                    elif pv.mode == ParameterMode.RELATIVE:
                        output[param_name] = output.get(param_name, 0) + val
                    elif pv.mode == ParameterMode.MULTIPLY:
                        output[param_name] = output.get(param_name, 1) * val
            else:
                if cue.cue_id in self._active_cues:
                    self._deactivate_cue(cue.cue_id)

        # Emit parameter changes
        if output:
            self.all_parameters_changed.emit(output)
            for name, val in output.items():
                self.parameter_changed.emit(name, val)

    def _calc_fade(self, cue: CueData, elapsed: float) -> float:
        """Calculate fade in/out factor (0-1)."""
        factor = 1.0
        if cue.fade_in > 0 and elapsed < cue.fade_in:
            factor *= elapsed / cue.fade_in
        remaining = cue.duration - elapsed
        if cue.fade_out > 0 and remaining < cue.fade_out:
            factor *= remaining / cue.fade_out
        return max(0.0, min(1.0, factor))

    def _activate_cue(self, cue: CueData):
        cue.state = CueState.ACTIVE
        self._active_cues[cue.cue_id] = cue
        self.cue_activated.emit(cue.cue_id)

    def _deactivate_cue(self, cue_id: str):
        cue = self._active_cues.pop(cue_id, None)
        if cue:
            cue.state = CueState.IDLE
            self.cue_deactivated.emit(cue_id)

    # === Funscript Integration ===

    def create_funscript_cue(self, name: str, track: str,
                              target_param: str,
                              start_time: float = 0.0,
                              duration: float = 0.0,
                              scale_min: float = 0.0,
                              scale_max: float = 255.0) -> CueData:
        """
        Create a cue that maps a funscript track to a device parameter.
        
        This bridges OFS funscript data into zhappy's cueing system.
        """
        cue = CueData(
            name=name,
            cue_type=CueType.FUNSCRIPT,
            funscript_track=track,
            funscript_mapping=target_param,
            funscript_scale_min=scale_min,
            funscript_scale_max=scale_max,
            start_time=start_time,
            duration=duration,
            color="#00b4ff"
        )
        self.store_cue(cue)
        return cue

    # === Persistence (from zhappy pattern) ===

    def save_to_file(self, path: str):
        """Save all cues to JSON file."""
        data = [cue.to_dict() for cue in self._cues.values()]
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        log.info(f"Saved {len(data)} cues to {path}")

    def load_from_file(self, path: str):
        """Load cues from JSON file."""
        if not os.path.exists(path):
            return
        with open(path, 'r') as f:
            data = json.load(f)
        self._cues.clear()
        for item in data:
            cue = CueData.from_dict(item)
            self._cues[cue.cue_id] = cue
        log.info(f"Loaded {len(self._cues)} cues from {path}")
