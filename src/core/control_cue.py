"""
ControlCue  --  point-in-time command markers on the timeline.

Control cues are instantaneous events (no duration) placed on a
CONTROL_CUE track.  When the playhead crosses a cue's timestamp the
associated command is executed once.  They sit conceptually between
chapters and tracks  --  think of them as "command bookmarks".

Supported cue types
-------------------
* **PARAMETER**  --  write a register / value to a device
  (e.g. MK-312 mode change, TCode aux command).
* **OSC_COMMAND**  --  send an arbitrary OSC message.
* **WS_MESSAGE**  --  send a JSON payload over a WS output.
* **MODE_CHANGE**  --  change the operational mode of a backend.

Each cue is unique: copy-paste duplicates all fields but assigns a
fresh ``cue_id``.

Persistence
-----------
Cues are stored per-project in ``project._extra_state["control_cues"]``
and on each ``ControlCueTrackData`` payload inside a Track.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Cue type
# ---------------------------------------------------------------------------

class CueType(IntEnum):
    """Kind of command carried by a control cue."""
    PARAMETER   = 0   # device register/value write
    OSC_COMMAND = 1   # arbitrary OSC message
    WS_MESSAGE  = 2   # JSON payload over WS output
    MODE_CHANGE = 3   # backend operational mode switch


# Human-readable labels (for UI)
CUE_TYPE_LABELS: Dict[CueType, str] = {
    CueType.PARAMETER:   "Parameter",
    CueType.OSC_COMMAND: "OSC Command",
    CueType.WS_MESSAGE:  "WS Message",
    CueType.MODE_CHANGE: "Mode Change",
}

# Default colours per type (RGBA 0-1)
CUE_TYPE_COLORS: Dict[CueType, Tuple[float, float, float, float]] = {
    CueType.PARAMETER:   (0.20, 0.70, 1.00, 0.90),   # blue
    CueType.OSC_COMMAND: (0.90, 0.55, 0.10, 0.90),   # orange
    CueType.WS_MESSAGE:  (0.10, 0.85, 0.55, 0.90),   # green
    CueType.MODE_CHANGE: (0.85, 0.25, 0.65, 0.90),   # magenta
}


# ---------------------------------------------------------------------------
# ControlCue
# ---------------------------------------------------------------------------

@dataclass
class ControlCue:
    """A single point-in-time control command.

    Fields
    ------
    cue_id : str
        Unique identifier (auto-generated).  Copy-paste always creates
        a fresh id.
    name : str
        User-visible label shown on the timeline marker.
    cue_type : CueType
        Determines which execution path the cue engine takes.
    time : float
        Track-local time in seconds (relative to the track offset).
    color : tuple
        RGBA 0-1 for the marker.  Defaults per ``cue_type``.
    params : dict
        Type-specific payload:

        **PARAMETER**::
            {"device_instance_id": "mk312_0",
             "address": 0x4078, "value": 5}

        **OSC_COMMAND**::
            {"path": "/my/command", "args": [1.0, "hello"]}

        **WS_MESSAGE**::
            {"ws_instance_id": "wso_abc",
             "payload": {"type": "set_mode", "mode": "pulse"}}

        **MODE_CHANGE**::
            {"device_instance_id": "mk312_0",
             "mode": "intense"}

    notes : str
        Free-form user notes (shown in the edit popup).
    """

    cue_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "Cue"
    cue_type: CueType = CueType.PARAMETER
    time: float = 0.0
    color: Tuple[float, float, float, float] = (0.20, 0.70, 1.00, 0.90)
    params: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    # -- Serialisation -------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "cue_id": self.cue_id,
            "name": self.name,
            "cue_type": int(self.cue_type),
            "time": self.time,
            "color": list(self.color),
            "params": self.params,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ControlCue":
        return cls(
            cue_id=d.get("cue_id", uuid.uuid4().hex[:12]),
            name=d.get("name", "Cue"),
            cue_type=CueType(d.get("cue_type", 0)),
            time=float(d.get("time", 0.0)),
            color=tuple(d.get("color", [0.20, 0.70, 1.00, 0.90])),
            params=d.get("params", {}),
            notes=d.get("notes", ""),
        )

    # -- Copy helper ---------------------------------------------------

    def duplicate(self, time_offset: float = 0.0) -> "ControlCue":
        """Return a deep copy with a fresh ``cue_id``.

        *time_offset* is added to ``self.time`` for the new cue.
        """
        return ControlCue(
            cue_id=uuid.uuid4().hex[:12],     # always unique
            name=self.name,
            cue_type=self.cue_type,
            time=self.time + time_offset,
            color=self.color,
            params=dict(self.params),
            notes=self.notes,
        )


# ---------------------------------------------------------------------------
# ControlCueTrackData  --  payload for TrackType.CONTROL_CUE
# ---------------------------------------------------------------------------

@dataclass
class ControlCueTrackData:
    """Collection of control cues inside a track."""
    cues: List[ControlCue] = field(default_factory=list)

    # -- Query helpers -------------------------------------------------

    def cues_in_range(self, t_start: float, t_end: float) -> List[ControlCue]:
        """Return cues with ``time`` in [t_start, t_end)."""
        return [c for c in self.cues if t_start <= c.time < t_end]

    def cue_at(self, t: float, tolerance: float = 0.05) -> Optional[ControlCue]:
        """Return the cue closest to *t* within *tolerance*, or None."""
        best: Optional[ControlCue] = None
        best_dist = tolerance
        for c in self.cues:
            dist = abs(c.time - t)
            if dist < best_dist:
                best = c
                best_dist = dist
        return best

    def add_cue(self, cue: ControlCue) -> None:
        """Insert a cue, keeping the list sorted by time."""
        self.cues.append(cue)
        self.cues.sort(key=lambda c: c.time)

    def remove_cue(self, cue_id: str) -> Optional[ControlCue]:
        """Remove and return a cue by id."""
        for i, c in enumerate(self.cues):
            if c.cue_id == cue_id:
                return self.cues.pop(i)
        return None

    # -- Serialisation -------------------------------------------------

    def to_dict(self) -> dict:
        return {"cues": [c.to_dict() for c in self.cues]}

    @classmethod
    def from_dict(cls, d: dict) -> "ControlCueTrackData":
        cues = [ControlCue.from_dict(cd) for cd in d.get("cues", [])]
        return cls(cues=cues)
