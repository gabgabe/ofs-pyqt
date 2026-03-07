"""
OFS Event System  --  Python port of OFS_EventSystem.h / OFS_Event.h

Replaces Qt signals everywhere. Simple callable-based event bus.
Mirrors OFS EV::Queue().appendListener() / EV::Enqueue<T>() / EV::Process().

Usage:
    from src.core.events import EV

    # Register listener
    EV.listen("VideoLoaded", lambda path: print(f"Loaded: {path}"))

    # Enqueue event (deferred  --  processed next EV.process() call)
    EV.enqueue("VideoLoaded", path="/some/video.mp4")

    # Direct dispatch (immediate, synchronous)
    EV.dispatch("VideoLoaded", path="/some/video.mp4")

    # Process queued events (call once per frame)
    EV.process()
"""

from __future__ import annotations

from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Type

# ---------------------------------------------------------------------------
# Event type constants (mirror OFS event names)
# ---------------------------------------------------------------------------

class OFS_Events:
    """Event name constants mirroring the OFS C++ event identifiers (``OFS_Event.h``)."""

    # Video
    VIDEO_LOADED          = "VideoLoaded"
    DURATION_CHANGE       = "DurationChange"
    TIME_CHANGE           = "TimeChange"
    PLAY_PAUSE_CHANGE     = "PlayPauseChange"
    PLAYBACK_SPEED_CHANGE = "PlaybackSpeedChange"

    # Funscript
    FUNSCRIPT_CHANGED     = "FunscriptActionsChanged"
    FUNSCRIPT_NAME_CHANGED = "FunscriptNameChanged"   # dispatched when title is renamed
    FUNSCRIPT_REMOVED     = "FunscriptRemoved"        # dispatched when a script is removed
    PROJECT_LOADED        = "ProjectLoaded"
    METADATA_CHANGED      = "MetadataChanged"

    # Timeline
    ACTION_SHOULD_CREATE  = "FunscriptActionShouldCreate"
    ACTION_SHOULD_MOVE    = "FunscriptActionShouldMove"
    ACTION_CLICKED        = "FunscriptActionClicked"
    SHOULD_SET_TIME       = "ShouldSetTime"
    SELECT_TIME           = "FunscriptShouldSelectTime"
    CHANGE_ACTIVE_SCRIPT  = "ShouldChangeActiveScript"

    # Chapter
    CHAPTER_STATE_CHANGED = "ChapterStateChanged"
    EXPORT_CLIP           = "ExportClipForChapter"

    # DAW Timeline
    TIMELINE_BUILT        = "TimelineBuilt"
    TIMELINE_PLAY_PAUSE   = "TimelinePlayPause"
    TIMELINE_SEEK         = "TimelineSeek"
    TIMELINE_TRACK_MOVED  = "TimelineTrackMoved"
    TIMELINE_TRACK_ADDED  = "TimelineTrackAdded"
    TIMELINE_TRACK_REMOVED = "TimelineTrackRemoved"
    TIMELINE_LAYER_MUTE   = "TimelineLayerMute"
    TIMELINE_LAYER_ADDED  = "TimelineLayerAdded"       # layer_id=str
    TIMELINE_LAYER_REMOVED = "TimelineLayerRemoved"    # layer_id=str
    TIMELINE_LAYER_RENAMED = "TimelineLayerRenamed"    # layer_id=str, name=str
    TIMELINE_LAYOUT_CHANGED = "TimelineLayoutChanged"
    TIMELINE_TRACK_SELECTED = "TimelineTrackSelected"
    TIMELINE_TRACK_DESELECTED = "TimelineTrackDeselected"
    TIMELINE_ADD_AXIS_REQUEST = "TimelineAddAxisRequest"   # axis=str

    # Drag-and-drop
    DROP_FILE             = "DropFile"


# ---------------------------------------------------------------------------
# Typed Event base & concrete types (Omakase pattern)
# ---------------------------------------------------------------------------
# Each typed event is a frozen dataclass carrying all its payload.
# dispatch_typed(event) / listen_typed(EventClass, cb) provide IDE
# autocomplete and runtime type safety.  The legacy string-based
# dispatch()/listen() system remains fully functional.

@dataclass(frozen=True)
class TypedEvent:
    """Base class for typed events."""
    pass

# -- Video --------------------------------------------------------------
@dataclass(frozen=True)
class VideoLoadedEvent(TypedEvent):
    path: str = ""

@dataclass(frozen=True)
class DurationChangeEvent(TypedEvent):
    duration: float = 0.0

@dataclass(frozen=True)
class TimeChangeEvent(TypedEvent):
    time: float = 0.0

@dataclass(frozen=True)
class PlayPauseChangeEvent(TypedEvent):
    paused: bool = True

@dataclass(frozen=True)
class PlaybackSpeedChangeEvent(TypedEvent):
    speed: float = 1.0

# -- Timeline / Transport ----------------------------------------------
@dataclass(frozen=True)
class TimelineSeekEvent(TypedEvent):
    time: float = 0.0

@dataclass(frozen=True)
class TrackSelectedEvent(TypedEvent):
    track_id: str = ""

@dataclass(frozen=True)
class TrackDeselectedEvent(TypedEvent):
    pass

@dataclass(frozen=True)
class TrackMovedEvent(TypedEvent):
    track_id: str = ""
    new_offset: float = 0.0

@dataclass(frozen=True)
class LayerMuteEvent(TypedEvent):
    layer_id: str = ""
    muted: bool = False

@dataclass(frozen=True)
class LayoutChangedEvent(TypedEvent):
    pass

# -- Buffering ---------------------------------------------------------
@dataclass(frozen=True)
class BufferingEvent(TypedEvent):
    """Fired when a video player enters or exits buffering state."""
    buffering: bool = False
    track_id: str = ""


# ---------------------------------------------------------------------------
# EventSystem  --  the bus
# ---------------------------------------------------------------------------

class EventSystem:
    """
    Callable-based event bus. Mirrors ``OFS::EventSystem`` / ``EV`` namespace.

    All ``EV.enqueue()`` calls are deferred and processed on the next ``EV.process()``
    call, which must be called from the main thread (like ``EV::Process()`` in C++).

    ``EV.dispatch()`` is immediate / synchronous  --  use for same-frame reactions.
    """

    _instance: "EventSystem | None" = None

    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._typed_listeners: Dict[str, List[Callable]] = defaultdict(list)
        self._queue: deque = deque()

    # ------------------------------------------------------------------
    @classmethod
    def get(cls) -> "EventSystem":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    def listen(self, event_type: str, callback: Callable) -> None:
        """Append a listener for *event_type*."""
        self._listeners[event_type].append(callback)

    def unlisten(self, event_type: str, callback: Callable) -> None:
        """Remove a listener."""
        try:
            self._listeners[event_type].remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    def enqueue(self, event_type: str, **kwargs: Any) -> None:
        """Queue an event to be fired on the next process() call."""
        self._queue.append((event_type, kwargs))

    def dispatch(self, event_type: str, **kwargs: Any) -> None:
        """Fire an event immediately (synchronous)."""
        for cb in list(self._listeners.get(event_type, [])):
            cb(**kwargs)

    # ------------------------------------------------------------------
    # Typed event API (Omakase-inspired)
    # ------------------------------------------------------------------

    def listen_typed(self, event_cls: Type["TypedEvent"], callback: Callable) -> None:
        """Register a callback for a typed event class (receives the event object)."""
        self._typed_listeners[event_cls.__name__].append(callback)

    def unlisten_typed(self, event_cls: Type["TypedEvent"], callback: Callable) -> None:
        """Remove a typed-event listener."""
        try:
            self._typed_listeners[event_cls.__name__].remove(callback)
        except ValueError:
            pass

    def dispatch_typed(self, event: "TypedEvent") -> None:
        """Fire a typed event immediately.  All ``listen_typed`` handlers receive
        the event object; legacy ``listen`` handlers are also fired with the
        event's fields as ``**kwargs``."""
        cls_name = type(event).__name__
        # Typed listeners
        for cb in list(self._typed_listeners.get(cls_name, [])):
            try:
                cb(event)
            except Exception as e:
                import traceback
                print(f"[EVENTS] Error in typed handler for '{cls_name}': {e}")
                traceback.print_exc()

    # ------------------------------------------------------------------
    def process(self) -> None:
        """
        Drain the queue and fire all pending events.
        Call exactly once per frame from the main thread.
        """
        while self._queue:
            event_type, kwargs = self._queue.popleft()
            for cb in list(self._listeners.get(event_type, [])):
                try:
                    cb(**kwargs)
                except Exception as e:
                    import traceback
                    print(f"[EVENTS] Error in handler for '{event_type}': {e}")
                    traceback.print_exc()


# Singleton  --  mirrors OFS EV namespace
EV = EventSystem.get()
