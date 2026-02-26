"""Funscript data model — Python port of OFS ``Funscript/Funscript.h`` and ``Funscript/Funscript.cpp``.

Mirrors the core OFS funscript data structures and editing operations including
action arrays (``FunscriptArray``), selection management, spline interpolation
(``FunscriptSpline``), heatmap generation, and undo-ready mutations.

See also: ``FunscriptAction.h``, ``FunscriptSpline.h``, ``FunscriptHeatmap.h``.
"""

import json
import math
import bisect
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from .undo_system import FunscriptUndoSystem, FunscriptData as _FunscriptData

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

@dataclass(order=True)
class FunscriptAction:
    """Single action point (time in ms + position 0–100). Mirrors ``FunscriptAction`` in ``FunscriptAction.h``."""

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
    """Script metadata fields. Mirrors ``Funscript::Metadata`` in ``Funscript.h``."""

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
# Funscript Bookmark (from .funscript metadata.bookmarks[])
# ---------------------------------------------------------------------------

@dataclass
class FunscriptBookmark:
    """A bookmark entry from the .funscript file's metadata section."""
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
    """Sorted array of ``FunscriptAction`` with binary-search operations.

    Mirrors ``FunscriptArray`` (a ``vector_set<FunscriptAction>``) from
    ``FunscriptAction.h`` and the array helpers in ``Funscript.h``.
    """

    def __init__(self, actions: Optional[List["FunscriptAction"]] = None):
        self._actions: List[FunscriptAction] = []
        if actions:
            for a in actions:
                self.Add(a)

    # ---- mutation ----

    def Add(self, action: FunscriptAction) -> None:
        """Insert maintaining sort order; replace if same timestamp. Mirrors ``FunscriptArray::emplace``."""
        idx = bisect.bisect_left([a.at for a in self._actions], action.at)
        if idx < len(self._actions) and self._actions[idx].at == action.at:
            self._actions[idx] = action
        else:
            self._actions.insert(idx, action)

    def RemoveAction(self, action: FunscriptAction) -> bool:
        """Remove an action by value. Mirrors ``Funscript::RemoveAction``."""
        idx = bisect.bisect_left([a.at for a in self._actions], action.at)
        if idx < len(self._actions) and self._actions[idx].at == action.at:
            del self._actions[idx]
            return True
        return False

    def RemoveAtTime(self, at: int) -> bool:
        """Remove the action at exact timestamp *at* (ms)."""
        idx = bisect.bisect_left([a.at for a in self._actions], at)
        if idx < len(self._actions) and self._actions[idx].at == at:
            del self._actions[idx]
            return True
        return False

    def RemoveActionsInInterval(self, start_s: float, end_s: float) -> int:
        """Remove all actions in [*start_s*, *end_s*]. Mirrors ``Funscript::RemoveActionsInInterval``."""
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        before = len(self._actions)
        self._actions = [a for a in self._actions if a.at < start_ms or a.at > end_ms]
        return before - len(self._actions)

    def Clear(self):
        """Remove all actions. Mirrors ``FunscriptArray::clear``."""
        self._actions.clear()

    # ---- lookup ----

    def GetAtTime(self, time_s: float, tolerance_s: float = 0.0) -> Optional[FunscriptAction]:
        """Get action at *time_s* ± *tolerance_s*. Mirrors ``Funscript::getActionAtTime``."""
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

    def GetClosestAction(self, time_s: float) -> Optional[FunscriptAction]:
        """Get the action closest to *time_s*. Mirrors ``Funscript::GetClosestAction``."""
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

    def GetClosestActionSelection(self, time_s: float,
                                      selection: "FunscriptActionArray") -> Optional[FunscriptAction]:
        """Get closest selected action to *time_s*. Mirrors ``Funscript::GetClosestActionSelection``."""
        if not selection._actions:
            return None
        at = time_s * 1000
        return min(selection._actions, key=lambda a: abs(a.at - at))

    def GetPreviousActionBehind(self, time_s: float) -> Optional[FunscriptAction]:
        """Get last action strictly before *time_s*. Mirrors ``Funscript::getPreviousActionBehind``."""
        at = time_s * 1000
        times = [a.at for a in self._actions]
        idx = bisect.bisect_left(times, at) - 1
        if idx >= 0:
            return self._actions[idx]
        return None

    def GetNextActionAhead(self, time_s: float) -> Optional[FunscriptAction]:
        """Get first action strictly after *time_s*. Mirrors ``Funscript::getNextActionAhead``."""
        at = time_s * 1000
        times = [a.at for a in self._actions]
        idx = bisect.bisect_right(times, at)
        if idx < len(self._actions):
            return self._actions[idx]
        return None

    def GetActionsInRange(self, start_ms: int, end_ms: int) -> List[FunscriptAction]:
        """Return actions in [*start_ms*, *end_ms*]. Mirrors ``Funscript::GetSelection``."""
        times = [a.at for a in self._actions]
        lo = bisect.bisect_left(times, start_ms)
        hi = bisect.bisect_right(times, end_ms)
        return self._actions[lo:hi]

    def LowerBound(self, at_ms: int) -> int:
        """Index of first action ≥ *at_ms*. Mirrors ``FunscriptArray::lower_bound``."""
        return bisect.bisect_left([a.at for a in self._actions], at_ms)

    def Interpolate(self, at_ms: float) -> float:
        """Linear interpolation of position at *at_ms*. Mirrors ``Funscript::GetPositionAtTime``."""
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

    def InterpolateSpline(self, at_ms: float) -> float:
        """Catmull-Rom spline interpolation of position at *at_ms*.

        Mirrors ``FunscriptSpline::catmul_rom_spline_alt`` from ``FunscriptSpline.h``.
        Returns value in 0–100 range.
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

    def GetLastStroke(self, before_time_s: float) -> List[FunscriptAction]:
        """Get last complete stroke before *time_s*. Mirrors ``Funscript::GetLastStroke``."""
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

    def ToList(self) -> List[Dict[str, int]]:
        """Serialize actions to a list of ``{at, pos}`` dicts for JSON export."""
        return [{"at": a.at, "pos": a.pos} for a in self._actions]

    @classmethod
    def FromList(cls, data: List[Dict[str, Any]]) -> "FunscriptActionArray":
        """Deserialize from a list of ``{at, pos}`` dicts (JSON import)."""
        arr = cls()
        for item in data:
            arr.Add(FunscriptAction(at=int(item["at"]), pos=int(item["pos"])))
        return arr

    def Copy(self) -> "FunscriptActionArray":
        """Return a deep copy of this action array."""
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
    """Complete funscript document.

    Full port of the ``Funscript`` class from ``Funscript.h`` / ``Funscript.cpp``
    including action editing, selection management, and undo support.
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
        self.bookmarks: List[FunscriptBookmark] = []
        self.unsaved_edits: bool = False
        self._edit_time = None

        # Per-script undo system — set up lazily to avoid circular imports
        self.undo_system: Optional["FunscriptUndoSystem"] = None
        # Callback list for actions-changed notifications (Qt-independent)
        self._actions_changed_callbacks: List = []

    # ============================================================
    # Title management
    # ============================================================

    def SetTitle(self, new_title: str) -> None:
        """Change the script title. Dispatches ``FunscriptNameChangedEvent``."""
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
    def Load(cls, path: str) -> "Funscript":
        """Load a ``.funscript`` JSON file from disk. Mirrors ``Funscript::Deserialize``."""
        fs = cls(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for action in data.get("actions", []):
                fs.actions.Add(FunscriptAction(
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
                fs.bookmarks.append(FunscriptBookmark(
                    name=bm.get("name", ""),
                    start_time=cls._parse_time(bm.get("time", "0:00")),
                ))

            log.info(f"Loaded funscript: {path} ({len(fs.actions)} actions)")
        except Exception as e:
            log.error(f"Failed to load funscript {path}: {e}")
        return fs

    def Save(self, path: Optional[str] = None) -> bool:
        """Write the funscript to disk as JSON. Mirrors ``Funscript::Serialize``."""
        save_path = path or self._path
        if not save_path:
            return False
        try:
            data = {
                "version": "1.0",
                "inverted": False,
                "range": 100,
                "actions": self.actions.ToList(),
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
                        {"name": bm.name, "time": self._format_time(bm.start_time)}
                        for bm in self.bookmarks
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

    def AddAction(self, action: FunscriptAction) -> None:
        """Add a new action point. Mirrors ``Funscript::AddAction``."""
        self.actions.Add(action)
        self._mark_edited()

    def AddEditAction(self, action: FunscriptAction, tolerance_s: float = 0.0) -> None:
        """Add or replace action within tolerance. Mirrors ``Funscript::AddEditAction``."""
        existing = self.actions.GetAtTime(action.at_s, tolerance_s)
        if existing:
            self.actions.RemoveAction(existing)
            if existing.pos != action.pos:
                self.actions.Add(action)
        else:
            self.actions.Add(action)
        self._mark_edited()

    def EditAction(self, old: FunscriptAction, new: FunscriptAction) -> None:
        """Replace one action with another. Mirrors ``Funscript::EditAction``."""
        self.actions.RemoveAction(old)
        self.actions.Add(new)
        self.selection.RemoveAction(old)
        self.selection.Add(new)
        self._mark_edited()

    def RemoveAction(self, action: FunscriptAction) -> bool:
        """Remove a single action. Mirrors ``Funscript::RemoveAction``."""
        result = self.actions.RemoveAction(action)
        self.selection.RemoveAction(action)
        if result:
            self._mark_edited()
        return result

    def RemoveSelectedActions(self) -> int:
        """Remove all currently selected actions. Mirrors ``Funscript::RemoveSelectedActions``."""
        count = 0
        for a in list(self.selection):
            if self.actions.RemoveAction(a):
                count += 1
        self.selection.Clear()
        if count:
            self._mark_edited()
        return count

    def RemoveActionsInInterval(self, start_s: float, end_s: float) -> int:
        """Remove all actions in a time interval. Mirrors ``Funscript::RemoveActionsInInterval``."""
        count = self.actions.RemoveActionsInInterval(start_s, end_s)
        if count:
            self._mark_edited()
        return count

    # ============================================================
    # Selection
    # ============================================================

    def SelectAction(self, action: FunscriptAction) -> None:
        """Mark an action as selected. Mirrors ``Funscript::SelectAction``."""
        self.selection.Add(FunscriptAction(action.at, action.pos))

    def DeselectAction(self, action: FunscriptAction) -> None:
        """Remove an action from the selection. Mirrors ``Funscript::DeselectAction``."""
        self.selection.RemoveAction(action)

    def SelectAll(self) -> None:
        """Select every action in the script. Mirrors ``Funscript::SelectAll``."""
        self.selection.Clear()
        for a in self.actions:
            self.selection.Add(FunscriptAction(a.at, a.pos))

    def ClearSelection(self) -> None:
        """Deselect all actions. Mirrors ``Funscript::ClearSelection``."""
        self.selection.Clear()

    def SelectTime(self, start_s: float, end_s: float) -> None:
        """Select all actions in a time range. Mirrors ``Funscript::SelectTime``."""
        self.selection.Clear()
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        for a in self.actions.GetActionsInRange(start_ms, end_ms):
            self.selection.Add(FunscriptAction(a.at, a.pos))

    def SelectRect(self, start_s: float, end_s: float,
                   min_pos: int, max_pos: int) -> None:
        """Select actions within a time range AND value (pos) range."""
        self.selection.Clear()
        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)
        for a in self.actions.GetActionsInRange(start_ms, end_ms):
            if min_pos <= a.pos <= max_pos:
                self.selection.Add(FunscriptAction(a.at, a.pos))

    def HasSelection(self) -> bool:
        """Return whether any actions are selected. Mirrors ``Funscript::HasSelection``."""
        return len(self.selection) > 0

    def SelectionSize(self) -> int:
        """Return the number of selected actions. Mirrors ``Funscript::SelectionSize``."""
        return len(self.selection)

    def SelectTopActions(self) -> None:
        """Keep local maxima in selection. Mirrors ``Funscript::SelectTopActions``.

        Deselects the two lowest-pos actions from every consecutive triplet.
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
                new_sel.Add(FunscriptAction(a.at, a.pos))
        self.selection = new_sel

    def SelectBottomActions(self) -> None:
        """Keep local minima in selection. Mirrors ``Funscript::SelectBottomActions``.

        Deselects the two highest-pos actions from every consecutive triplet.
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
                new_sel.Add(FunscriptAction(a.at, a.pos))
        self.selection = new_sel

    def SelectMiddleActions(self) -> None:
        """Keep actions that are neither tops nor bottoms. Mirrors ``Funscript::SelectMidActions``."""
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        # Discover top-point timestamps
        saved = self.selection.Copy()
        self.SelectTopActions()
        top_times = {a.at for a in self.selection}
        # Discover bottom-point timestamps
        self.selection = saved.Copy()
        self.SelectBottomActions()
        bottom_times = {a.at for a in self.selection}
        # Keep only mid points (neither top nor bottom)
        self.selection = saved.Copy()
        new_sel = FunscriptActionArray()
        for a in sel:
            if a.at not in top_times and a.at not in bottom_times:
                new_sel.Add(FunscriptAction(a.at, a.pos))
        self.selection = new_sel

    # ============================================================
    # Move / Transform selected
    # ============================================================

    def MoveSelectionPosition(self, delta: int) -> None:
        """Shift selected actions by *delta* position units. Mirrors ``Funscript::MoveSelectionPosition``."""
        new_sel = []
        for a in list(self.selection):
            new_pos = max(0, min(100, a.pos + delta))
            new_a = FunscriptAction(a.at, new_pos)
            self.actions.RemoveAction(a)
            self.actions.Add(new_a)
            new_sel.append(new_a)
        self.selection.Clear()
        for a in new_sel:
            self.selection.Add(a)
        self._mark_edited()

    def MoveSelectionTime(self, delta_s: float, frame_time_s: float = 0.0) -> None:
        """Shift selected actions by *delta_s* seconds. Mirrors ``Funscript::MoveSelectionTime``."""
        delta_ms = int(delta_s * 1000)
        moved = []
        for a in list(self.selection):
            self.actions.RemoveAction(a)
            new_a = FunscriptAction(max(0, a.at + delta_ms), a.pos)
            moved.append(new_a)
        self.selection.Clear()
        for a in moved:
            self.actions.Add(a)
            self.selection.Add(a)
        self._mark_edited()

    def EqualizeSelection(self) -> None:
        """Space selected actions evenly in time. Mirrors ``Funscript::EqualizeSelection``."""
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        start, end = sel[0], sel[-1]
        total_time = end.at - start.at
        step = total_time / (len(sel) - 1)
        for i, old in enumerate(sel):
            new_at = int(start.at + i * step)
            new_a = FunscriptAction(new_at, old.pos)
            self.actions.RemoveAction(old)
            self.actions.Add(new_a)
            self.selection.RemoveAction(old)
            self.selection.Add(new_a)
        self._mark_edited()

    def InvertSelection(self) -> None:
        """Flip selected actions (pos → 100 − pos). Mirrors ``Funscript::InvertSelection``."""
        new_sel = []
        for a in list(self.selection):
            new_a = FunscriptAction(a.at, 100 - a.pos)
            self.actions.RemoveAction(a)
            self.actions.Add(new_a)
            new_sel.append(new_a)
        self.selection.Clear()
        for a in new_sel:
            self.selection.Add(a)
        self._mark_edited()

    # ============================================================
    # Lookups (proxy to array)
    # ============================================================

    def GetActionAtTime(self, time_s: float, tolerance_s: float = 0.0) -> Optional[FunscriptAction]:
        """Get action at *time_s* ± *tolerance_s*. Mirrors ``Funscript::GetActionAtTime``."""
        return self.actions.GetAtTime(time_s, tolerance_s)

    def GetClosestAction(self, time_s: float) -> Optional[FunscriptAction]:
        """Get the action closest to *time_s*. Mirrors ``Funscript::GetClosestAction``."""
        return self.actions.GetClosestAction(time_s)

    def GetClosestActionSelection(self, time_s: float) -> Optional[FunscriptAction]:
        """Get closest selected action to *time_s*. Mirrors ``Funscript::GetClosestActionSelection``."""
        return self.actions.GetClosestActionSelection(time_s, self.selection)

    def GetPreviousActionBehind(self, time_s: float) -> Optional[FunscriptAction]:
        """Get last action strictly before *time_s*. Mirrors ``Funscript::GetPreviousActionBehind``."""
        return self.actions.GetPreviousActionBehind(time_s)

    def GetNextActionAhead(self, time_s: float) -> Optional[FunscriptAction]:
        """Get first action strictly after *time_s*. Mirrors ``Funscript::GetNextActionAhead``."""
        return self.actions.GetNextActionAhead(time_s)

    def GetLastStroke(self, before_time_s: float) -> List[FunscriptAction]:
        """Get last complete stroke before *time_s*. Mirrors ``Funscript::GetLastStroke``."""
        return self.actions.GetLastStroke(before_time_s)

    def GetPositionAtTime(self, time_s: float) -> float:
        """Return linear-interpolated position at time_s as float in [0.0, 1.0].

        Mirrors OFS Funscript::GetPositionAtTime() which returns a 0-1 range
        (position / 100.0) used by the simulator and scripting overlay.
        """
        return self.actions.Interpolate(time_s * 1000.0) / 100.0

    def AddMultipleActions(self, new_actions: List[FunscriptAction]) -> None:
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

    def SpeedAt(self, at_ms: float) -> float:
        """Compute instantaneous speed (pos-units/s) at *at_ms*. Used by ``FunscriptHeatmap``."""
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

    def GenerateHeatmapData(self, width: int, duration_ms: float) -> List[float]:
        """Generate per-pixel speed data for heatmap rendering. Mirrors ``FunscriptHeatmap``."""
        MAX_SPEED = 400.0
        if duration_ms <= 0 or len(self.actions) < 2:
            return [0.0] * width
        return [
            min(self.SpeedAt((x / width) * duration_ms), MAX_SPEED)
            for x in range(width)
        ]

    # ============================================================
    # Special functions
    # ============================================================

    def RangeExtendSelection(self, range_extend: int) -> None:
        """Stroke-aware range extension. Mirrors ``Funscript::RangeExtendSelection``.

        Args:
            range_extend: Value in -50…100. Positive pushes highs higher and lows
                lower; negative compresses toward each stroke's centre.
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
        self.ClearSelection()
        new_positions = self._compute_range_extend(selected, range_extend)
        for old_a, new_pos in zip(selected, new_positions):
            self.actions.RemoveAction(old_a)
            new_a = FunscriptAction(old_a.at, new_pos)
            self.actions.Add(new_a)
            self.selection.Add(FunscriptAction(new_a.at, new_a.pos))
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

    def RdpSimplifySelection(self, epsilon: float) -> None:
        """Ramer-Douglas-Peucker simplification of selected actions. Mirrors OFS RDP algorithm."""
        sel = sorted(self.selection, key=lambda a: a.at)
        if len(sel) < 3:
            return
        kept = self._rdp(sel, epsilon)
        kept_set = {(a.at, a.pos) for a in kept}
        for a in sel:
            if (a.at, a.pos) not in kept_set:
                self.actions.RemoveAction(a)
                self.selection.RemoveAction(a)
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

    def InitUndoSystem(self) -> None:
        """Attach a ``FunscriptUndoSystem`` to this script (call once after creation)."""
        from .undo_system import FunscriptUndoSystem
        self.undo_system = FunscriptUndoSystem(self)

    def Rollback(self, data: "_FunscriptData") -> None:
        """Restore script data from an undo snapshot. Mirrors ``Funscript::Rollback``."""
        self.actions.Clear()
        for a in data.actions:
            self.actions.Add(FunscriptAction(a.at, a.pos))
        self.selection.Clear()
        for a in data.selection:
            self.selection.Add(FunscriptAction(a.at, a.pos))
        self._notify_actions_changed()

    def ConnectActionsChanged(self, callback) -> None:
        """Register a callback to be called whenever actions change."""
        if callback not in self._actions_changed_callbacks:
            self._actions_changed_callbacks.append(callback)

    def DisconnectActionsChanged(self, callback) -> None:
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
    def FindRelatedScripts(root_path: str) -> List[str]:
        """Find multi-axis companion scripts sharing the same stem."""
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

