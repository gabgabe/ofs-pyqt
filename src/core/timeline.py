"""
Global Timeline Model — multi-track, multi-layer DAW-style timeline.

Architecture
============
The timeline is the **global transport authority**.  Its clock starts at 0.0
and grows unbounded.  Every piece of media and data lives on a **Track**
(a clip with a horizontal offset) placed inside a **Layer** (a row that
can be muted / soloed).

Hierarchy::

    Timeline
      ├── Transport          (position, play/pause, speed)
      ├── Layer 0  "Video"
      │     └── Track        (type=VIDEO,  offset=0.0, data → VideoTrackData)
      ├── Layer 1  "main"
      │     └── Track        (type=FUNSCRIPT, offset=0.0, data → FunscriptTrackData)
      ├── Layer 2  "surge"
      │     └── Track        (type=FUNSCRIPT, offset=2.5, data → FunscriptTrackData)
      ├── Layer 3  "triggers"
      │     └── Track        (type=TRIGGER, offset=10.0, data → TriggerTrackData)
      └── …

Key concepts
------------
* **Transport** — the single source of truth for playback position.
  Video players slave to the transport (not the other way round).
* **Track** — a clip that occupies [offset .. offset+duration] on the
  timeline.  It can be dragged horizontally (offset changes).
* **Layer** — a horizontal row.  Multiple tracks can live in the same
  layer (but must not overlap — enforced at insert time).  Each layer
  has a *mute* flag.
* **TrackType** — VIDEO, FUNSCRIPT, TRIGGER (extensible enum).
* **Duration** — for a Funscript track the duration expands
  automatically when new actions are added beyond the current end, with
  a configurable margin so there's always drawing room.  For an imported
  funscript the initial duration equals the last action's timestamp.
  For a video track, duration = video file duration.
"""

from __future__ import annotations

import time as _time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# TrackType
# ---------------------------------------------------------------------------

class TrackType(IntEnum):
    """Extensible track-type enum."""
    VIDEO      = 0
    FUNSCRIPT  = 1
    TRIGGER    = 2      # OSC / HTTP / custom trigger data


# ---------------------------------------------------------------------------
# TransportState
# ---------------------------------------------------------------------------

class TransportState(IntEnum):
    STOPPED = 0
    PLAYING = 1
    PAUSED  = 2


# ---------------------------------------------------------------------------
# Typed track payloads
# ---------------------------------------------------------------------------

@dataclass
class VideoTrackData:
    """Payload attached to a VIDEO track.

    Stores per-track video metadata so that each clip on the timeline
    carries its own media information.
    """
    media_path: str = ""
    fps: float = 30.0
    media_duration: float = 0.0   # seconds (full file duration)
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        return {
            "media_path": self.media_path,
            "fps": self.fps,
            "media_duration": self.media_duration,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoTrackData":
        return cls(
            media_path=d.get("media_path", ""),
            fps=float(d.get("fps", 30.0)),
            media_duration=float(d.get("media_duration", 0.0)),
            width=int(d.get("width", 0)),
            height=int(d.get("height", 0)),
        )


@dataclass
class FunscriptTrackData:
    """Payload attached to a FUNSCRIPT track.

    ``funscript_idx`` indexes into ``OFS_Project.funscripts``.
    """
    funscript_idx: int = 0
    auto_expand_margin: float = 5.0   # seconds of extra room when writing

    def to_dict(self) -> dict:
        return {"funscript_idx": self.funscript_idx,
                "auto_expand_margin": self.auto_expand_margin}

    @classmethod
    def from_dict(cls, d: dict) -> "FunscriptTrackData":
        return cls(funscript_idx=int(d.get("funscript_idx", 0)),
                   auto_expand_margin=float(d.get("auto_expand_margin", 5.0)))


@dataclass
class TriggerEvent:
    """A single trigger event inside a TRIGGER track."""
    time: float = 0.0         # local time (seconds from track start)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"time": self.time, "payload": self.payload}

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerEvent":
        return cls(time=float(d.get("time", 0.0)),
                   payload=d.get("payload", {}))


@dataclass
class TriggerTrackData:
    """Payload attached to a TRIGGER track (OSC / HTTP output events)."""
    events: List[TriggerEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"events": [e.to_dict() for e in self.events]}

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerTrackData":
        evts = [TriggerEvent.from_dict(e) for e in d.get("events", [])]
        return cls(events=evts)


# ---------------------------------------------------------------------------
# Track
# ---------------------------------------------------------------------------

@dataclass
class Track:
    """A single clip on the timeline.

    The track occupies [offset .. offset + duration] in global timeline seconds.

    For VIDEO tracks, *trim_in* / *trim_out* define the media-local
    in-point and out-point (seconds).  The effective clip length shown
    on the timeline is ``trim_out - trim_in``; *duration* is kept in
    sync automatically via :meth:`apply_trim`.
    """
    name: str = ""
    track_type: TrackType = TrackType.FUNSCRIPT
    offset: float = 0.0              # global seconds — horizontal position
    duration: float = 60.0           # length in seconds
    color: Tuple[float, ...] = (0.55, 0.27, 0.68, 1.0)

    # Trim points (media-local seconds).  Used mainly for VIDEO tracks.
    # *media_duration* stores the full untrimmed source duration.
    trim_in: float = 0.0
    trim_out: float = 0.0            # 0 means "not set" → uses *duration*
    media_duration: float = 0.0      # full source duration (0 → not set)

    # Typed payload — exactly one should be set depending on track_type
    video_data: Optional[VideoTrackData] = None
    funscript_data: Optional[FunscriptTrackData] = None
    trigger_data: Optional[TriggerTrackData] = None

    # Unique id (auto-generated)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # ── Computed ──────────────────────────────────────────────────────

    @property
    def end(self) -> float:
        """Global end time of this track."""
        return self.offset + self.duration

    # ── Trim helpers ──────────────────────────────────────────────────

    def ApplyTrim(self, new_in: float, new_out: float) -> None:
        """Set trim in/out and update *duration* accordingly."""
        md = self.media_duration if self.media_duration > 0 else self.duration
        self.trim_in  = max(0.0, min(new_in, md))
        self.trim_out = max(self.trim_in, min(new_out, md))
        self.duration = self.trim_out - self.trim_in

    def GlobalToMedia(self, global_t: float) -> float:
        """Convert global transport time → media-local time (respecting trim_in)."""
        return (global_t - self.offset) + self.trim_in

    # ── Time conversion ───────────────────────────────────────────────

    def GlobalToLocal(self, global_t: float) -> float:
        """Convert global transport time to track-local time."""
        return global_t - self.offset

    def LocalToGlobal(self, local_t: float) -> float:
        """Convert track-local time to global transport time."""
        return local_t + self.offset

    def ContainsGlobal(self, global_t: float) -> bool:
        """True if *global_t* falls within this track's extent."""
        return self.offset <= global_t <= self.end

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "name": self.name,
            "track_type": int(self.track_type),
            "offset": self.offset,
            "duration": self.duration,
            "color": list(self.color),
            "trim_in": self.trim_in,
            "trim_out": self.trim_out,
            "media_duration": self.media_duration,
        }
        if self.video_data:
            d["video_data"] = self.video_data.to_dict()
        if self.funscript_data:
            d["funscript_data"] = self.funscript_data.to_dict()
        if self.trigger_data:
            d["trigger_data"] = self.trigger_data.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        tt = TrackType(d.get("track_type", 1))
        t = cls(
            name=d.get("name", ""),
            track_type=tt,
            offset=float(d.get("offset", 0.0)),
            duration=float(d.get("duration", 60.0)),
            color=tuple(d.get("color", [0.55, 0.27, 0.68, 1.0])),
            trim_in=float(d.get("trim_in", 0.0)),
            trim_out=float(d.get("trim_out", 0.0)),
            media_duration=float(d.get("media_duration", 0.0)),
        )
        t.id = d.get("id", t.id)
        if "video_data" in d:
            t.video_data = VideoTrackData.from_dict(d["video_data"])
        if "funscript_data" in d:
            t.funscript_data = FunscriptTrackData.from_dict(d["funscript_data"])
        if "trigger_data" in d:
            t.trigger_data = TriggerTrackData.from_dict(d["trigger_data"])
        return t


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------

@dataclass
class Layer:
    """A horizontal row in the timeline.  Holds one or more non-overlapping tracks."""
    name: str = "Layer"
    muted: bool = False
    locked: bool = False
    height: float = 60.0              # UI row height in pixels
    tracks: List[Track] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # ── Track management ──────────────────────────────────────────────

    def TrackAt(self, global_t: float) -> Optional[Track]:
        """Return the track occupying *global_t*, or None."""
        for t in self.tracks:
            if t.ContainsGlobal(global_t):
                return t
        return None

    def CanPlace(self, offset: float, duration: float,
                 exclude_id: str = "") -> bool:
        """True if [offset..offset+duration] doesn't overlap any existing track."""
        end = offset + duration
        for t in self.tracks:
            if t.id == exclude_id:
                continue
            if offset < t.end and end > t.offset:
                return False
        return True

    def AddTrack(self, track: Track) -> bool:
        """Add *track* if it doesn't overlap. Returns success."""
        if not self.CanPlace(track.offset, track.duration):
            return False
        self.tracks.append(track)
        return True

    def RemoveTrack(self, track_id: str) -> Optional[Track]:
        """Remove and return the track with *track_id*."""
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                return self.tracks.pop(i)
        return None

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "muted": self.muted,
            "locked": self.locked,
            "height": self.height,
            "tracks": [t.to_dict() for t in self.tracks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        lay = cls(
            name=d.get("name", "Layer"),
            muted=d.get("muted", False),
            locked=d.get("locked", False),
            height=float(d.get("height", 60.0)),
        )
        lay.id = d.get("id", lay.id)
        lay.tracks = [Track.from_dict(td) for td in d.get("tracks", [])]
        return lay


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class Transport:
    """Global transport — the master clock of the timeline.

    Uses ``time.perf_counter()`` for wall-clock advancement so it stays in
    sync regardless of frame rate.
    """

    def __init__(self) -> None:
        self.position: float = 0.0
        self.state: TransportState = TransportState.PAUSED
        self.speed: float = 1.0
        self._last_tick: float = _time.perf_counter()
        self._listeners: List[Callable[[float], None]] = []

    # ── Controls ──────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        return self.state == TransportState.PLAYING

    def Play(self) -> None:
        if self.state != TransportState.PLAYING:
            self.state = TransportState.PLAYING
            self._last_tick = _time.perf_counter()

    def Pause(self) -> None:
        self.state = TransportState.PAUSED

    def Stop(self) -> None:
        self.state = TransportState.STOPPED
        self.position = 0.0

    def TogglePlay(self) -> None:
        if self.is_playing:
            self.Pause()
        else:
            self.Play()

    def Seek(self, t: float) -> None:
        """Jump to absolute position *t* (seconds)."""
        self.position = max(0.0, t)
        self._last_tick = _time.perf_counter()
        self._notify()

    def SeekRelative(self, delta: float) -> None:
        """Shift position by *delta* seconds."""
        self.Seek(self.position + delta)

    # ── Tick (call once per frame) ────────────────────────────────────

    def Tick(self) -> None:
        """Advance the transport position if playing.

        Uses wall-clock delta so the position stays real-time accurate
        even when the frame rate varies.
        """
        now = _time.perf_counter()
        if self.is_playing:
            dt = (now - self._last_tick) * self.speed
            self.position = max(0.0, self.position + dt)
            self._notify()
        self._last_tick = now

    # ── Listener helpers ──────────────────────────────────────────────

    def OnTick(self, cb: Callable[[float], None]) -> None:
        """Register a callback invoked on every tick with the current position."""
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb(self.position)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Timeline — top-level container
# ---------------------------------------------------------------------------

class Timeline:
    """Top-level container: transport + layers."""

    def __init__(self) -> None:
        self.transport: Transport = Transport()
        self.layers: List[Layer] = []

    # ── Duration (dynamic) ────────────────────────────────────────────

    @property
    def duration(self) -> float:
        """Dynamic duration = max end of all tracks across all layers."""
        mx = 0.0
        for lay in self.layers:
            for t in lay.tracks:
                mx = max(mx, t.end)
        return mx

    # ── Layer management ──────────────────────────────────────────────

    def AddLayer(self, name: str = "Layer") -> Layer:
        lay = Layer(name=name)
        self.layers.append(lay)
        return lay

    def RemoveLayer(self, layer_id: str) -> Optional[Layer]:
        for i, lay in enumerate(self.layers):
            if lay.id == layer_id:
                return self.layers.pop(i)
        return None

    def MoveLayer(self, layer_id: str, new_idx: int) -> bool:
        """Reorder a layer to *new_idx*."""
        for i, lay in enumerate(self.layers):
            if lay.id == layer_id:
                self.layers.pop(i)
                new_idx = max(0, min(new_idx, len(self.layers)))
                self.layers.insert(new_idx, lay)
                return True
        return False

    # ── Track queries ─────────────────────────────────────────────────

    def AllTracks(self) -> List[Tuple[Layer, Track]]:
        """Return every (layer, track) pair."""
        result = []
        for lay in self.layers:
            for t in lay.tracks:
                result.append((lay, t))
        return result

    def FindTrack(self, track_id: str) -> Optional[Tuple[Layer, Track]]:
        """Locate a track by id."""
        for lay in self.layers:
            for t in lay.tracks:
                if t.id == track_id:
                    return (lay, t)
        return None

    def FunscriptTracks(self) -> List[Tuple[Layer, Track]]:
        return [(l, t) for l, t in self.AllTracks()
                if t.track_type == TrackType.FUNSCRIPT]

    def VideoTracks(self) -> List[Tuple[Layer, Track]]:
        return [(l, t) for l, t in self.AllTracks()
                if t.track_type == TrackType.VIDEO]

    def ActiveFunscriptTracks(self) -> List[Tuple[Layer, Track]]:
        """Funscript tracks on non-muted layers."""
        return [(l, t) for l, t in self.FunscriptTracks() if not l.muted]

    # ── Funscript track auto-expand ───────────────────────────────────

    def ExpandFunscriptTrack(self, track: Track, local_action_t: float) -> None:
        """If *local_action_t* approaches or exceeds the track end, grow it.

        ``auto_expand_margin`` (from FunscriptTrackData) ensures there's
        always free space ahead of the last written action.
        """
        if track.track_type != TrackType.FUNSCRIPT or not track.funscript_data:
            return
        margin = track.funscript_data.auto_expand_margin
        needed = local_action_t + margin
        if needed > track.duration:
            track.duration = needed

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "transport": {
                "position": self.transport.position,
                "speed": self.transport.speed,
            },
            "layers": [lay.to_dict() for lay in self.layers],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Timeline":
        tl = cls()
        tp = d.get("transport", {})
        tl.transport.position = float(tp.get("position", 0.0))
        tl.transport.speed = float(tp.get("speed", 1.0))
        tl.layers = [Layer.from_dict(ld) for ld in d.get("layers", [])]
        return tl
