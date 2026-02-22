"""
OFS Event System — Python port of OFS_EventSystem.h / OFS_Event.h

Replaces Qt signals everywhere. Simple callable-based event bus.
Mirrors OFS EV::Queue().appendListener() / EV::Enqueue<T>() / EV::Process().

Usage:
    from src.core.events import EV

    # Register listener
    EV.listen("VideoLoaded", lambda path: print(f"Loaded: {path}"))

    # Enqueue event (deferred — processed next EV.process() call)
    EV.enqueue("VideoLoaded", path="/some/video.mp4")

    # Direct dispatch (immediate, synchronous)
    EV.dispatch("VideoLoaded", path="/some/video.mp4")

    # Process queued events (call once per frame)
    EV.process()
"""

from __future__ import annotations

from collections import deque, defaultdict
from typing import Callable, Dict, Any, List

# ---------------------------------------------------------------------------
# Event type constants (mirror OFS event names)
# ---------------------------------------------------------------------------

class OFS_Events:
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

    # Drag-and-drop
    DROP_FILE             = "DropFile"


# ---------------------------------------------------------------------------
# EventSystem — the bus
# ---------------------------------------------------------------------------

class EventSystem:
    """
    Thread-safe event bus.

    All EV.enqueue() calls are deferred and processed on the next EV.process()
    call, which must be called from the main thread (just like OFS EV::Process()).

    EV.dispatch() is immediate / synchronous — use for same-frame reactions.
    """

    _instance: "EventSystem | None" = None

    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)
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


# Singleton — mirrors OFS EV namespace
EV = EventSystem.get()
