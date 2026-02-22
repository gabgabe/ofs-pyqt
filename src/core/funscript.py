"""
Funscript Data Model - Complete port of OFS Funscript.h / Funscript.cpp

Handles loading, saving, editing, selection, undo-ready operations,
interpolation, heatmap data, and multitrack support.
"""

import json
import math
import bisect
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple, TYPE_CHECKING
from pathlib import Path

try:
    from PySide6.QtCore import QObject, Signal
    _HAS_QT = True
except ImportError:
    _HAS_QT = False

if TYPE_CHECKING:
    from .undo_system import FunscriptUndoSystem, FunscriptData as _FunscriptData

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

@dataclass(order=True)
class FunscriptAction:
    """Single action point: time in ms + position 0-100."""
    at: int   # milliseconds
    pos: int  # 0-100

    def __post_init__(self):
        self.at = int(self.at)
        self.pos = max(0, min(100, int(self.pos)))

    @property
    def at_s(self) -> float:
        return self.at / 1000.0

    def __eq__(self, other):
        if isinstance(other, FunscriptAction):
            return self.at == other.at and self.pos == other.pos
        return NotImplemented

    def __hash__(self):
        return hash((self.at, self.pos))


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

@dataclass
class FunscriptMetadata:
    type: str = "basic"
    title: str = ""
    creator: str = ""
    script_url: str = ""
    video_url: str = ""
    tags: List[str] = field(default_factory=list)
    performers: List[str] = field(default_factory=list)
    description: str = ""
    license: str = ""
    notes: str = ""
    duration: int = 0  # ms


# ---------------------------------------------------------------------------
# Chapter / Bookmark
# ---------------------------------------------------------------------------

@dataclass
class Chapter:
    name: str = ""
    start_time: float = 0.0   # seconds
    end_time: float = 0.0     # seconds (0 = bookmark)

    @property
    def is_bookmark(self) -> bool:
        return self.end_time <= self.start_time


# ---------------------------------------------------------------------------
# Action Array (sorted, with efficient lookup)
# ---------------------------------------------------------------------------

class FunscriptActionArray:
    """
    Sorted array of FunscriptActions with binary-search operations.
    Mirrors OFS FunscriptArray semantics.
    """

    def __init__(self, actions: Optional[List["FunscriptAction"]] = None):
        self._actions: List[FunscriptAction] = []
        if actions:
            for a in actions:
                self.add(a)

    # ---- mutation ----

    def add(self, action: FunscriptAction) -> None:
        """Insert maintaining sort order; replace if same time."""
        idx = bisect.bisect_left([a.at for a in self._actions], action.at)
        if idx < len(self._actions) and self._actions[idx].at == action.at:
            self._actions[idx] = action
        else:
            self._actions.insert(idx, action)

    def remove_action(self, action: FunscriptAction) -> bool:
        idx = bisect.bisect_left([a.at for a in self._actions], action.at)
        if idx < len(self._actions) and self._actions[idx].at == action.at:
            del self._actions[idx]
            return True
        return False

    def remove_at_time(self, at: int) -> bool:
        idx = bisect.bisect_left([a.at for a in self._actions], at)
        if idx < len(self._actions) and self._actions[idx].at == at:
            del self._actions[idx]
            return True
        return False

    def remove_actions_in_interval(self, start_s: float, end_s: float) -> int:
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        before = len(self._actions)
        self._actions = [a for a in self._actions if a.at < start_ms or a.at > end_ms]
        return before - len(self._actions)

    def clear(self):
        self._actions.clear()

    # ---- lookup ----

    def get_at_time(self, time_s: float, tolerance_s: float = 0.0) -> Optional[FunscriptAction]:
        """Get action exactly at time_s or within tolerance_s."""
        at = int(time_s * 1000)
        tol = int(tolerance_s * 1000)
        times = [a.at for a in self._actions]
        idx = bisect.bisect_left(times, at)
        best = None
        best_dist = tol + 1
        for check_idx in [idx - 1, idx]:
            if 0 <= check_idx < len(self._actions):
                dist = abs(self._actions[check_idx].at - at)
                if dist <= tol and dist < best_dist:
                    best_dist = dist
                    best = self._actions[check_idx]
        return best

    def get_closest_action(self, time_s: float) -> Optional[FunscriptAction]:
        """Get the action closest to time_s."""
        if not self._actions:
            return None
        at = time_s * 1000
        times = [a.at for a in self._actions]
        idx = bisect.bisect_left(times, at)
        candidates = []
        if idx < len(self._actions):
            candidates.append(self._actions[idx])
        if idx > 0:
            candidates.append(self._actions[idx - 1])
        return min(candidates, key=lambda a: abs(a.at - at))

    def get_closest_action_selection(self, time_s: float,
                                      selection: "FunscriptActionArray") -> Optional[FunscriptAction]:
        """Get closest selected action to time_s."""
        if not selection._actions:
            return None
        at = time_s * 1000
        return min(selection._actions, key=lambda a: abs(a.at - at))

    def get_previous_action_behind(self, time_s: float) -> Optional[FunscriptAction]:
        """Get last action strictly before time_s (OFS GetPreviousActionBehind)."""
        at = time_s * 1000
        times = [a.at for a in self._actions]
        idx = bisect.bisect_left(times, at) - 1
        if idx >= 0:
            return self._actions[idx]
        return None

    def get_next_action_ahead(self, time_s: float) -> Optional[FunscriptAction]:
        """Get first action strictly after time_s (OFS GetNextActionAhead)."""
        at = time_s * 1000
        times = [a.at for a in self._actions]
        idx = bisect.bisect_right(times, at)
        if idx < len(self._actions):
            return self._actions[idx]
        return None

    def get_actions_in_range(self, start_ms: int, end_ms: int) -> List[FunscriptAction]:
        times = [a.at for a in self._actions]
        lo = bisect.bisect_left(times, start_ms)
        hi = bisect.bisect_right(times, end_ms)
        return self._actions[lo:hi]

    def lower_bound(self, at_ms: int) -> int:
        """Index of first action >= at_ms."""
        return bisect.bisect_left([a.at for a in self._actions], at_ms)

    def interpolate(self, at_ms: float) -> float:
        """Linear interpolation of position at at_ms."""
        if not self._actions:
            return 50.0
        times = [a.at for a in self._actions]
        idx = bisect.bisect_right(times, at_ms)
        if idx == 0:
            return float(self._actions[0].pos)
        if idx >= len(self._actions):
            return float(self._actions[-1].pos)
        a, b = self._actions[idx - 1], self._actions[idx]
        if b.at == a.at:
            return float(b.pos)
        t = (at_ms - a.at) / (b.at - a.at)
        return a.pos + t * (b.pos - a.pos)

    def interpolate_spline(self, at_ms: float) -> float:
        """Catmull-Rom spline interpolation of position at at_ms.

        Mirrors FunscriptSpline::catmul_rom_spline_alt() from OFS.
        Returns value in 0-100 range (float).
        """
        acts = self._actions
        n = len(acts)
        if n == 0:
            return 50.0
        if n == 1:
            return float(acts[0].pos)

        times = [a.at for a in acts]
        # find i1: index of last action <= at_ms
        idx = bisect.bisect_right(times, at_ms) - 1
        idx = max(0, min(n - 2, idx))

        i0 = max(0, idx - 1)
        i1 = idx
        i2 = min(n - 1, idx + 1)
        i3 = min(n - 1, idx + 2)

        p1, p2 = acts[i1], acts[i2]

        # If equal positions, no spline needed
        if p1.pos == p2.pos:
            return float(p1.pos)

        dt = p2.at - p1.at
        if dt <= 0:
            return float(p2.pos)

        # t in [0, 1]
        t = (at_ms - p1.at) / dt
        t = max(0.0, min(1.0, t))

        # Catmull-Rom using 0-1 normalised positions
        v0 = acts[i0].pos / 100.0
        v1 = acts[i1].pos / 100.0
        v2 = acts[i2].pos / 100.0
        v3 = acts[i3].pos / 100.0

        # glm::catmullRom formula
        t2, t3 = t * t, t * t * t
        result = 0.5 * (
            (2.0 * v1)
            + (-v0 + v2) * t
            + (2.0 * v0 - 5.0 * v1 + 4.0 * v2 - v3) * t2
            + (-v0 + 3.0 * v1 - 3.0 * v2 + v3) * t3
        )
        return max(0.0, min(100.0, result * 100.0))

    # ---- helpers ----

    def get_last_stroke(self, before_time_s: float) -> List[FunscriptAction]:
        """Get last complete stroke before time_s (OFS GetLastStroke)."""
        at = before_time_s * 1000
        times = [a.at for a in self._actions]
        idx = bisect.bisect_left(times, at) - 1
        if idx < 1:
            return []
        stroke: List[FunscriptAction] = []
        direction = None
        i = idx
        while i >= 0:
            if not stroke:
                stroke.append(self._actions[i])
                i -= 1
                continue
            curr = self._actions[i]
            prev = stroke[-1]
            d = prev.pos - curr.pos
            if direction is None:
                direction = 1 if d > 0 else -1
            elif (d > 0 and direction < 0) or (d < 0 and direction > 0):
                break
            stroke.append(curr)
            i -= 1
        stroke.reverse()
        return stroke

    # ---- serialization ----

    def to_list(self) -> List[Dict[str, int]]:
        return [{"at": a.at, "pos": a.pos} for a in self._actions]

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> "FunscriptActionArray":
        arr = cls()
        for item in data:
            arr.add(FunscriptAction(at=int(item["at"]), pos=int(item["pos"])))
        return arr

    def copy(self) -> "FunscriptActionArray":
        new = FunscriptActionArray()
        new._actions = [FunscriptAction(a.at, a.pos) for a in self._actions]
        return new

    # ---- dunder ----

    def __len__(self) -> int:
        return len(self._actions)

    def __iter__(self):
        return iter(self._actions)

    def __getitem__(self, index):
        return self._actions[index]

    def __bool__(self):
        return bool(self._actions)


# ---------------------------------------------------------------------------
# Main Funscript class
# ---------------------------------------------------------------------------

class Funscript:
    """
    Complete funscript document.
    Full port of OFS Funscript class with all editing operations.
    """

    EXTENSION = ".funscript"

    AXIS_NAMES = ["twist", "pitch", "roll", "surge", "sway", "forward",
                  "backward", "left", "right", "up", "down",
                  "clockwise", "counterclockwise", "squeeze", "valve",
                  "vibrate", "pump", "suction"]

    def __init__(self, path: str = ""):
        self._path: str = path
        self.title: str = Path(path).stem if path else "Untitled"
        self.relative_path: str = ""
        self.enabled: bool = True

        self.actions = FunscriptActionArray()
        self.selection = FunscriptActionArray()
        self.metadata = FunscriptMetadata()
        self.chapters: List[Chapter] = []
        self.unsaved_edits: bool = False
        self._edit_time = None

        # Per-script undo system — set up lazily to avoid circular imports
        self.undo_system: Optional["FunscriptUndoSystem"] = None
        # Callback list for actions-changed notifications (Qt-independent)
        self._actions_changed_callbacks: List = []

    # ============================================================
    # Title management
    # ============================================================

    def set_title(self, new_title: str) -> None:
        """Change the script title and dispatch FUNSCRIPT_NAME_CHANGED."""
        if new_title == self.title:
            return
        old_title = self.title
        self.title = new_title
        try:
            from .events import EV, OFS_Events
            EV.dispatch(OFS_Events.FUNSCRIPT_NAME_CHANGED,
                        script=self, old_title=old_title, new_title=new_title)
        except Exception:
            pass

    # ============================================================
    # I/O
    # ============================================================

    @classmethod
    def load(cls, path: str) -> "Funscript":
        fs = cls(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for action in data.get("actions", []):
                fs.actions.add(FunscriptAction(
                    at=int(action.get("at", 0)),
                    pos=int(action.get("pos", 0))
                ))

            meta = data.get("metadata", {})
            fs.metadata = FunscriptMetadata(
                type=meta.get("type", "basic"),
                title=meta.get("title", ""),
                creator=meta.get("creator", ""),
                script_url=meta.get("script_url", ""),
                video_url=meta.get("video_url", ""),
                tags=meta.get("tags", []),
                performers=meta.get("performers", []),
                description=meta.get("description", ""),
                license=meta.get("license", ""),
                notes=meta.get("notes", ""),
                duration=meta.get("duration", 0),
            )
            fs.title = fs.metadata.title or Path(path).stem

            for bm in meta.get("bookmarks", []):
                fs.chapters.append(Chapter(
                    name=bm.get("name", ""),
                    start_time=cls._parse_time(bm.get("time", "0:00")),
                ))

            log.info(f"Loaded funscript: {path} ({len(fs.actions)} actions)")
        except Exception as e:
            log.error(f"Failed to load funscript {path}: {e}")
        return fs

    def save(self, path: Optional[str] = None) -> bool:
        save_path = path or self._path
        if not save_path:
            return False
        try:
            data = {
                "version": "1.0",
                "inverted": False,
                "range": 100,
                "actions": self.actions.to_list(),
                "metadata": {
                    "type": self.metadata.type,
                    "title": self.metadata.title,
                    "creator": self.metadata.creator,
                    "script_url": self.metadata.script_url,
                    "video_url": self.metadata.video_url,
                    "tags": self.metadata.tags,
                    "performers": self.metadata.performers,
                    "description": self.metadata.description,
                    "license": self.metadata.license,
                    "notes": self.metadata.notes,
                    "duration": self.metadata.duration,
                    "bookmarks": [
                        {"name": ch.name, "time": self._format_time(ch.start_time)}
                        for ch in self.chapters
                    ]
                }
            }
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._path = save_path
            self.unsaved_edits = False
            log.info(f"Saved funscript: {save_path}")
            return True
        except Exception as e:
            log.error(f"Failed to save {save_path}: {e}")
            return False

    # ============================================================
    # Basic editing
    # ============================================================

    def add_action(self, action: FunscriptAction) -> None:
        self.actions.add(action)
        self._mark_edited()

    def add_edit_action(self, action: FunscriptAction, tolerance_s: float = 0.0) -> None:
        """Add or replace action within tolerance (OFS AddEditAction)."""
        existing = self.actions.get_at_time(action.at_s, tolerance_s)
        if existing:
            self.actions.remove_action(existing)
            if existing.pos != action.pos:
                self.actions.add(action)
        else:
            self.actions.add(action)
        self._mark_edited()

    def edit_action(self, old: FunscriptAction, new: FunscriptAction) -> None:
        """Replace one action with another (OFS EditAction)."""
        self.actions.remove_action(old)
        self.actions.add(new)
        self.selection.remove_action(old)
        self.selection.add(new)
        self._mark_edited()

    def remove_action(self, action: FunscriptAction) -> bool:
        result = self.actions.remove_action(action)
        self.selection.remove_action(action)
        if result:
            self._mark_edited()
        return result

    def remove_selected_actions(self) -> int:
        count = 0
        for a in list(self.selection):
            if self.actions.remove_action(a):
                count += 1
        self.selection.clear()
        if count:
            self._mark_edited()
        return count

    def remove_actions_in_interval(self, start_s: float, end_s: float) -> int:
        count = self.actions.remove_actions_in_interval(start_s, end_s)
        if count:
            self._mark_edited()
        return count

    # ============================================================
    # Selection
    # ============================================================

    def select_action(self, action: FunscriptAction) -> None:
        self.selection.add(FunscriptAction(action.at, action.pos))

    def deselect_action(self, action: FunscriptAction) -> None:
        self.selection.remove_action(action)

    def select_all(self) -> None:
        self.selection.clear()
        for a in self.actions:
            self.selection.add(FunscriptAction(a.at, a.pos))

    def clear_selection(self) -> None:
        self.selection.clear()

    def select_time(self, start_s: float, end_s: float) -> None:
        self.selection.clear()
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        for a in self.actions.get_actions_in_range(start_ms, end_ms):
            self.selection.add(FunscriptAction(a.at, a.pos))

    def has_selection(self) -> bool:
        return len(self.selection) > 0

    def selection_size(self) -> int:
        return len(self.selection)

    def select_top_actions(self) -> None:
        """
        Keep local maxima — deselects the two lowest-pos actions from every
        consecutive triplet.  Exact port of OFS Funscript::SelectTopActions.
        """
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        to_deselect: set = set()
        for i in range(1, len(sel) - 1):
            prev, curr, nxt = sel[i - 1], sel[i], sel[i + 1]
            # min1 = smaller-pos between prev and current
            min1 = prev if prev.pos < curr.pos else curr
            # min2 = smaller-pos between min1 and next
            min2 = min1 if min1.pos < nxt.pos else nxt
            to_deselect.add(min1.at)
            if min1.at != min2.at:
                to_deselect.add(min2.at)
        new_sel = FunscriptActionArray()
        for a in sel:
            if a.at not in to_deselect:
                new_sel.add(FunscriptAction(a.at, a.pos))
        self.selection = new_sel

    def select_bottom_actions(self) -> None:
        """
        Keep local minima — deselects the two highest-pos actions from every
        consecutive triplet.  Exact port of OFS Funscript::SelectBottomActions.
        """
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        to_deselect: set = set()
        for i in range(1, len(sel) - 1):
            prev, curr, nxt = sel[i - 1], sel[i], sel[i + 1]
            # max1 = larger-pos between prev and current
            max1 = prev if prev.pos > curr.pos else curr
            # max2 = larger-pos between max1 and next
            max2 = max1 if max1.pos > nxt.pos else nxt
            to_deselect.add(max1.at)
            if max1.at != max2.at:
                to_deselect.add(max2.at)
        new_sel = FunscriptActionArray()
        for a in sel:
            if a.at not in to_deselect:
                new_sel.add(FunscriptAction(a.at, a.pos))
        self.selection = new_sel

    def select_middle_actions(self) -> None:
        """
        Keep actions that are neither tops nor bottoms.
        Exact port of OFS Funscript::SelectMidActions.
        """
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        # Discover top-point timestamps
        saved = self.selection.copy()
        self.select_top_actions()
        top_times = {a.at for a in self.selection}
        # Discover bottom-point timestamps
        self.selection = saved.copy()
        self.select_bottom_actions()
        bottom_times = {a.at for a in self.selection}
        # Keep only mid points (neither top nor bottom)
        self.selection = saved.copy()
        new_sel = FunscriptActionArray()
        for a in sel:
            if a.at not in top_times and a.at not in bottom_times:
                new_sel.add(FunscriptAction(a.at, a.pos))
        self.selection = new_sel

    # ============================================================
    # Move / Transform selected
    # ============================================================

    def move_selection_position(self, delta: int) -> None:
        new_sel = []
        for a in list(self.selection):
            new_pos = max(0, min(100, a.pos + delta))
            new_a = FunscriptAction(a.at, new_pos)
            self.actions.remove_action(a)
            self.actions.add(new_a)
            new_sel.append(new_a)
        self.selection.clear()
        for a in new_sel:
            self.selection.add(a)
        self._mark_edited()

    def move_selection_time(self, delta_s: float, frame_time_s: float = 0.0) -> None:
        delta_ms = int(delta_s * 1000)
        moved = []
        for a in list(self.selection):
            self.actions.remove_action(a)
            new_a = FunscriptAction(max(0, a.at + delta_ms), a.pos)
            moved.append(new_a)
        self.selection.clear()
        for a in moved:
            self.actions.add(a)
            self.selection.add(a)
        self._mark_edited()

    def equalize_selection(self) -> None:
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        start, end = sel[0], sel[-1]
        total_time = end.at - start.at
        step = total_time / (len(sel) - 1)
        for i, old in enumerate(sel):
            new_at = int(start.at + i * step)
            new_a = FunscriptAction(new_at, old.pos)
            self.actions.remove_action(old)
            self.actions.add(new_a)
            self.selection.remove_action(old)
            self.selection.add(new_a)
        self._mark_edited()

    def invert_selection(self) -> None:
        new_sel = []
        for a in list(self.selection):
            new_a = FunscriptAction(a.at, 100 - a.pos)
            self.actions.remove_action(a)
            self.actions.add(new_a)
            new_sel.append(new_a)
        self.selection.clear()
        for a in new_sel:
            self.selection.add(a)
        self._mark_edited()

    # ============================================================
    # Lookups (proxy to array)
    # ============================================================

    def get_action_at_time(self, time_s: float, tolerance_s: float = 0.0) -> Optional[FunscriptAction]:
        return self.actions.get_at_time(time_s, tolerance_s)

    def get_closest_action(self, time_s: float) -> Optional[FunscriptAction]:
        return self.actions.get_closest_action(time_s)

    def get_closest_action_selection(self, time_s: float) -> Optional[FunscriptAction]:
        return self.actions.get_closest_action_selection(time_s, self.selection)

    def get_previous_action_behind(self, time_s: float) -> Optional[FunscriptAction]:
        return self.actions.get_previous_action_behind(time_s)

    def get_next_action_ahead(self, time_s: float) -> Optional[FunscriptAction]:
        return self.actions.get_next_action_ahead(time_s)

    def get_last_stroke(self, before_time_s: float) -> List[FunscriptAction]:
        return self.actions.get_last_stroke(before_time_s)

    def get_position_at_time(self, time_s: float) -> float:
        """Return linear-interpolated position at time_s as float in [0.0, 1.0].

        Mirrors OFS Funscript::GetPositionAtTime() which returns a 0-1 range
        (position / 100.0) used by the simulator and scripting overlay.
        """
        return self.actions.interpolate(time_s * 1000.0) / 100.0

    def add_multiple_actions(self, new_actions: List[FunscriptAction]) -> None:
        """Batch-insert a list of actions efficiently (single sort pass).

        Mirrors OFS Funscript::AddMultipleActions — avoids O(n²) repeated
        bisect insertions when adding many points at once (e.g. from recording
        or paste operations).
        """
        merged = {a.at: a for a in self.actions._actions}
        for a in new_actions:
            merged[a.at] = a
        self.actions._actions = sorted(merged.values(), key=lambda a: a.at)

    # ============================================================
    # Speed / Heatmap
    # ============================================================

    def speed_at(self, at_ms: float) -> float:
        if len(self.actions) < 2:
            return 0.0
        times = [a.at for a in self.actions]
        idx = bisect.bisect_right(times, at_ms)
        idx = max(1, min(idx, len(self.actions) - 1))
        prev = self.actions[idx - 1]
        curr = self.actions[idx]
        dt = (curr.at - prev.at) / 1000.0
        if dt <= 0:
            return 0.0
        return abs(curr.pos - prev.pos) / dt

    def generate_heatmap_data(self, width: int, duration_ms: float) -> List[float]:
        MAX_SPEED = 400.0
        if duration_ms <= 0 or len(self.actions) < 2:
            return [0.0] * width
        return [
            min(self.speed_at((x / width) * duration_ms), MAX_SPEED)
            for x in range(width)
        ]

    # ============================================================
    # Special functions
    # ============================================================

    def range_extend_selection(self, range_extend: int) -> None:
        """
        Stroke-aware range extension.  Exact port of OFS RangeExtendSelection.

        range_extend : int  (-50 … 100)
            Positive values push highs higher and lows lower.
            Negative values compress the range toward each stroke's centre.
        """
        if range_extend == 0:
            return
        sel_set = {(a.at, a.pos) for a in self.selection}
        if not sel_set:
            return
        # Collect selected actions in data.Actions order (sorted by time)
        selected = [a for a in self.actions if (a.at, a.pos) in sel_set]
        if not selected:
            return
        self.clear_selection()
        new_positions = self._compute_range_extend(selected, range_extend)
        for old_a, new_pos in zip(selected, new_positions):
            self.actions.remove_action(old_a)
            self.actions.add(FunscriptAction(old_a.at, new_pos))
        self._mark_edited()

    @staticmethod
    def _compute_range_extend(actions: List["FunscriptAction"], range_extend: int) -> List[int]:
        """
        OFS stroke-aware StretchPosition algorithm.
        Mirrors the ExtendRange lambda inside Funscript::RangeExtendSelection.
        """
        n = len(actions)
        if n == 0:
            return []

        def stretch(pos: int, lowest: int, highest: int, ext: int) -> int:
            if highest == lowest:
                return pos
            new_high = max(0, min(100, highest + ext))
            new_low  = max(0, min(100, lowest  - ext))
            rel      = (pos - lowest) / (highest - lowest)
            return max(0, min(100, int(rel * (new_high - new_low) + new_low)))

        positions        = [a.pos for a in actions]
        last_extreme_idx = 0
        last_val         = positions[0]
        last_extreme_val = last_val
        lowest           = last_val
        highest          = last_val

        NONE, UP, DOWN = 0, 1, -1
        stroke_dir = NONE

        for index in range(n):
            pos = positions[index]

            if stroke_dir == NONE:
                if pos < last_extreme_val:
                    stroke_dir = DOWN
                elif pos > last_extreme_val:
                    stroke_dir = UP
            else:
                is_turn = (
                    (pos < last_val and stroke_dir == UP) or
                    (pos > last_val and stroke_dir == DOWN)
                )
                is_last = (index == n - 1)

                if is_turn or is_last:
                    # Stretch middle actions of the finished stroke
                    for i in range(last_extreme_idx + 1, index):
                        positions[i] = stretch(
                            positions[i], lowest, highest, range_extend
                        )
                    if index > 0:
                        # The previous action is the new extreme reference
                        last_extreme_val = positions[index - 1]
                        last_extreme_idx = index - 1
                        highest          = last_extreme_val
                        lowest           = last_extreme_val
                        stroke_dir       = DOWN if stroke_dir == UP else UP

            last_val = pos
            if pos > highest:
                highest = pos
            if pos < lowest:
                lowest = pos

        return positions

    def rdp_simplify_selection(self, epsilon: float) -> None:
        """Ramer-Douglas-Peucker simplification (OFS RamerDouglasPeucker)."""
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        kept = self._rdp(sel, epsilon)
        kept_set = {(a.at, a.pos) for a in kept}
        for a in sel:
            if (a.at, a.pos) not in kept_set:
                self.actions.remove_action(a)
                self.selection.remove_action(a)
        self._mark_edited()

    @staticmethod
    def _rdp(points: List[FunscriptAction], epsilon: float) -> List[FunscriptAction]:
        if len(points) < 3:
            return points

        def perp_dist(point, start, end):
            if start.at == end.at:
                return abs(point.pos - start.pos)
            dx, dy = end.at - start.at, end.pos - start.pos
            return abs(dy * point.at - dx * point.pos + end.at * start.pos
                       - end.pos * start.at) / math.sqrt(dx * dx + dy * dy)

        max_d, max_idx = 0.0, 0
        for i in range(1, len(points) - 1):
            d = perp_dist(points[i], points[0], points[-1])
            if d > max_d:
                max_d, max_idx = d, i
        if max_d > epsilon:
            left = Funscript._rdp(points[:max_idx + 1], epsilon)
            right = Funscript._rdp(points[max_idx:], epsilon)
            return left[:-1] + right
        return [points[0], points[-1]]

    # ============================================================
    # Undo support
    # ============================================================

    def init_undo_system(self) -> None:
        """Attach a FunscriptUndoSystem to this script (call once after creation)."""
        from .undo_system import FunscriptUndoSystem
        self.undo_system = FunscriptUndoSystem(self)

    def rollback(self, data: "_FunscriptData") -> None:
        """
        Restore script data from a snapshot (called by FunscriptUndoSystem).
        Mirrors OFS Funscript::Rollback.
        """
        self.actions.clear()
        for a in data.actions:
            self.actions.add(FunscriptAction(a.at, a.pos))
        self.selection.clear()
        for a in data.selection:
            self.selection.add(FunscriptAction(a.at, a.pos))
        self._notify_actions_changed()

    def connect_actions_changed(self, callback) -> None:
        """Register a callback to be called whenever actions change."""
        if callback not in self._actions_changed_callbacks:
            self._actions_changed_callbacks.append(callback)

    def disconnect_actions_changed(self, callback) -> None:
        """Unregister an actions-changed callback."""
        try:
            self._actions_changed_callbacks.remove(callback)
        except ValueError:
            pass

    def _notify_actions_changed(self) -> None:
        """Fire all registered actions-changed callbacks."""
        for cb in list(self._actions_changed_callbacks):
            try:
                cb(self)
            except Exception as e:
                log.warning(f"actions_changed callback error: {e}")

    # ============================================================
    # Helpers
    # ============================================================

    def _mark_edited(self):
        from datetime import datetime
        self.unsaved_edits = True
        self._edit_time = datetime.now()
        self._notify_actions_changed()

    @staticmethod
    def _parse_time(time_str: str) -> float:
        parts = time_str.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except (ValueError, IndexError):
            pass
        return 0.0

    @staticmethod
    def _format_time(seconds: float) -> str:
        m = int(seconds) // 60
        s = seconds - m * 60
        return f"{m}:{s:05.2f}"

    @staticmethod
    def find_related_scripts(root_path: str) -> List[str]:
        root = Path(root_path)
        parent = root.parent
        stem = root.stem
        related = []
        for f in parent.glob(f"{stem}.*{Funscript.EXTENSION}"):
            if str(f) != root_path:
                related.append(str(f))
        return sorted(related)

    def __repr__(self):
        return f"Funscript('{self.title}', {len(self.actions)} actions)"

