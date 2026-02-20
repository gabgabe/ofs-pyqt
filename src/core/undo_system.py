"""
Undo/Redo System — Python port of OFS_UndoSystem + FunscriptUndoSystem.

Architecture mirrors OFS exactly:
  - Each Funscript carries its own FunscriptUndoSystem (per-script stacks).
  - The global UndoSystem keeps a stack of UndoContexts; each context
    holds a snapshot-type tag and references to the scripts that changed.
  - On Undo/Redo the global system delegates to each script's per-script
    undo system, which swaps the saved FunscriptData back in.
  - The script's `rollback(data)` method restores the action/selection arrays
    and emits the `actions_changed` signal.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .funscript import Funscript

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StateType — mirrors OFS StateType enum exactly
# ---------------------------------------------------------------------------

class StateType(IntEnum):
    ADD_EDIT_ACTIONS           = 0
    ADD_EDIT_ACTION            = 1
    ADD_ACTION                 = 2

    REMOVE_ACTIONS             = 3
    REMOVE_ACTION              = 4

    MOUSE_MOVE_ACTION          = 5
    ACTIONS_MOVED              = 6

    CUT_SELECTION              = 7
    REMOVE_SELECTION           = 8
    PASTE_COPIED_ACTIONS       = 9

    EQUALIZE_ACTIONS           = 10
    INVERT_ACTIONS             = 11
    ISOLATE_ACTION             = 12

    TOP_POINTS_ONLY            = 13
    MID_POINTS_ONLY            = 14
    BOTTOM_POINTS_ONLY         = 15

    GENERATE_ACTIONS           = 16
    FRAME_ALIGN                = 17  # unused
    RANGE_EXTEND               = 18

    REPEAT_STROKE              = 19

    MOVE_ACTION_TO_CURRENT_POS = 20

    SIMPLIFY                   = 21
    CUSTOM_LUA                 = 22


# Human-readable labels for every StateType (used in the history panel)
_STATE_LABELS: dict[StateType, str] = {
    StateType.ADD_EDIT_ACTIONS:           "Add / Edit Actions",
    StateType.ADD_EDIT_ACTION:            "Add / Edit Action",
    StateType.ADD_ACTION:                 "Add Action",
    StateType.REMOVE_ACTIONS:             "Remove Actions",
    StateType.REMOVE_ACTION:              "Remove Action",
    StateType.MOUSE_MOVE_ACTION:          "Mouse Move Action",
    StateType.ACTIONS_MOVED:              "Actions Moved",
    StateType.CUT_SELECTION:              "Cut Selection",
    StateType.REMOVE_SELECTION:           "Remove Selection",
    StateType.PASTE_COPIED_ACTIONS:       "Paste Selection",
    StateType.EQUALIZE_ACTIONS:           "Equalize",
    StateType.INVERT_ACTIONS:             "Invert",
    StateType.ISOLATE_ACTION:             "Isolate",
    StateType.TOP_POINTS_ONLY:            "Top Points Only",
    StateType.MID_POINTS_ONLY:            "Mid Points Only",
    StateType.BOTTOM_POINTS_ONLY:         "Bottom Points Only",
    StateType.GENERATE_ACTIONS:           "Generate Actions",
    StateType.FRAME_ALIGN:                "Frame Align",
    StateType.RANGE_EXTEND:              "Range Extend",
    StateType.REPEAT_STROKE:             "Repeat Stroke",
    StateType.MOVE_ACTION_TO_CURRENT_POS: "Move to Current Position",
    StateType.SIMPLIFY:                   "Simplify",
    StateType.CUSTOM_LUA:                 "Lua Script",
}


def state_label(t: StateType) -> str:
    return _STATE_LABELS.get(t, str(t))


# ---------------------------------------------------------------------------
# FunscriptData snapshot — mirrors OFS Funscript::FunscriptData
# ---------------------------------------------------------------------------

@dataclass
class FunscriptData:
    """Immutable snapshot of a Funscript's action + selection arrays."""
    actions: list   # list of FunscriptAction (deep copies)
    selection: list  # list of FunscriptAction (deep copies, from selection array)

    @staticmethod
    def capture(script: "Funscript") -> "FunscriptData":
        """Take a snapshot of the script's current data."""
        return FunscriptData(
            actions=[deepcopy(a) for a in script.actions],
            selection=[deepcopy(a) for a in script.selection],
        )


# ---------------------------------------------------------------------------
# ScriptState — per-script undo entry (mirrors OFS ScriptState)
# ---------------------------------------------------------------------------

@dataclass
class ScriptState:
    type: StateType
    data: FunscriptData


# ---------------------------------------------------------------------------
# FunscriptUndoSystem — per-script undo stacks (mirrors OFS FunscriptUndoSystem)
# ---------------------------------------------------------------------------

class FunscriptUndoSystem:
    """
    Attached to each Funscript. Manages per-script undo/redo stacks.
    Snapshot() saves current data; Undo()/Redo() swap data in/out.
    """

    MAX_UNDO = 1000
    MAX_REDO = 100

    def __init__(self, script: "Funscript") -> None:
        self._script = script
        self._undo_stack: List[ScriptState] = []
        self._redo_stack: List[ScriptState] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self, state_type: StateType, clear_redo: bool = True) -> None:
        """Push current script data onto the undo stack."""
        self._undo_stack.append(
            ScriptState(state_type, FunscriptData.capture(self._script))
        )
        # Trim to prevent unbounded memory growth
        if len(self._undo_stack) > self.MAX_UNDO:
            self._undo_stack.pop(0)
        if clear_redo:
            self._clear_redo()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        top = self._undo_stack.pop()
        self._snapshot_redo(top.type)
        self._script.rollback(top.data)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        top = self._redo_stack.pop()
        self.snapshot(top.type, clear_redo=False)
        self._script.rollback(top.data)
        return True

    def match_undo_top(self, state_type: StateType) -> bool:
        return bool(self._undo_stack) and self._undo_stack[-1].type == state_type

    @property
    def undo_empty(self) -> bool:
        return not self._undo_stack

    @property
    def redo_empty(self) -> bool:
        return not self._redo_stack

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot_redo(self, state_type: StateType) -> None:
        self._redo_stack.append(
            ScriptState(state_type, FunscriptData.capture(self._script))
        )
        if len(self._redo_stack) > self.MAX_REDO:
            self._redo_stack.pop(0)

    def _clear_redo(self) -> None:
        self._redo_stack.clear()


# ---------------------------------------------------------------------------
# UndoContext — one entry on the global undo stack (mirrors OFS UndoContext)
# ---------------------------------------------------------------------------

@dataclass
class UndoContext:
    state_type: StateType
    # Weak references are not practical with plain Python objects;
    # we store the script objects directly (they're managed by the Project).
    scripts: List["Funscript"] = field(default_factory=list)

    def description(self) -> str:
        return state_label(self.state_type)


# ---------------------------------------------------------------------------
# UndoSystem — global undo/redo coordinator (mirrors OFS UndoSystem)
# ---------------------------------------------------------------------------

class UndoSystem:
    """
    Application-wide undo/redo system.

    Usage::

        # before mutating any scripts:
        undo_system.snapshot(StateType.ADD_ACTION, [script])

        # undo/redo:
        undo_system.undo()
        undo_system.redo()
    """

    def __init__(self) -> None:
        self._undo_stack: List[UndoContext] = []
        self._redo_stack: List[UndoContext] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(
        self,
        state_type: StateType,
        scripts: "Funscript | List[Funscript]",
        clear_redo: bool = True,
    ) -> None:
        """
        Take a snapshot of *scripts* before a mutating operation.

        Parameters
        ----------
        state_type:
            The type of operation being recorded.
        scripts:
            A single Funscript or a list of Funscripts whose data should be
            captured.
        clear_redo:
            When True (default) the redo stack is cleared — this is the
            expected behaviour after every user-initiated edit.
        """
        if not isinstance(scripts, list):
            scripts = [scripts]

        context = UndoContext(state_type=state_type, scripts=scripts)
        self._undo_stack.append(context)

        if clear_redo:
            self._clear_redo()

        for script in scripts:
            if script.undo_system is not None:
                script.undo_system.snapshot(state_type, clear_redo=clear_redo)

    def undo(self) -> bool:
        """Undo the most recent operation. Returns True if anything changed."""
        if not self._undo_stack:
            return False

        context = self._undo_stack.pop()
        did_something = False

        for script in context.scripts:
            if script.undo_system is not None:
                did_something = script.undo_system.undo() or did_something

        # If nothing actually changed (stale scripts) recurse
        if not did_something and self._undo_stack:
            return self.undo()

        self._redo_stack.append(context)
        return did_something

    def redo(self) -> bool:
        """Redo the most recently undone operation. Returns True if anything changed."""
        if not self._redo_stack:
            return False

        context = self._redo_stack.pop()
        did_something = False

        for script in context.scripts:
            if script.undo_system is not None:
                did_something = script.undo_system.redo() or did_something

        # If nothing actually changed recurse
        if not did_something and self._redo_stack:
            return self.redo()

        self._undo_stack.append(context)
        return did_something

    def match_undo_top(self, state_type: StateType) -> bool:
        """True if the top of the undo stack matches *state_type*."""
        return bool(self._undo_stack) and self._undo_stack[-1].state_type == state_type

    @property
    def undo_empty(self) -> bool:
        return not self._undo_stack

    @property
    def redo_empty(self) -> bool:
        return not self._redo_stack

    @property
    def undo_stack(self) -> List[UndoContext]:
        return self._undo_stack

    @property
    def redo_stack(self) -> List[UndoContext]:
        return self._redo_stack

    def clear(self) -> None:
        """Discard all undo/redo history (e.g. after loading a new project)."""
        self._undo_stack.clear()
        self._redo_stack.clear()

    def jump_to(self, target_idx: int) -> bool:
        """Jump to absolute position *target_idx* in the combined history.

        Index 0 = oldest committed state.
        Index ``len(undo_stack)`` = current (now) position.
        Index ``len(undo_stack) + len(redo_stack)`` = most recently undone state.
        """
        cur_idx = len(self._undo_stack)
        changed = False
        if target_idx < cur_idx:
            for _ in range(cur_idx - target_idx):
                if not self.undo():
                    break
                changed = True
        elif target_idx > cur_idx:
            steps = target_idx - cur_idx
            for _ in range(steps):
                if not self.redo():
                    break
                changed = True
        return changed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_redo(self) -> None:
        self._redo_stack.clear()

    # ------------------------------------------------------------------
    # History data for the UI panel
    # ------------------------------------------------------------------

    def history_items(self) -> list[dict]:
        """
        Returns a list of dicts for display in the undo/redo history panel.

        Each dict has keys:
            ``label``   – human-readable description
            ``count``   – how many consecutive identical entries are collapsed
            ``is_redo`` – True if this entry is on the redo stack
        """
        items: list[dict] = []

        # Redo stack (shown at the top, dimmed)
        prev_type: StateType | None = None
        count = 0
        for ctx in self._redo_stack:
            if ctx.state_type == prev_type:
                count += 1
            else:
                if prev_type is not None:
                    items.append({
                        "label": state_label(prev_type),
                        "count": count,
                        "is_redo": True,
                    })
                prev_type = ctx.state_type
                count = 1
        if prev_type is not None:
            items.append({
                "label": state_label(prev_type),
                "count": count,
                "is_redo": True,
            })

        items.append({"separator": True})

        # Undo stack (most recent at the top)
        prev_type = None
        count = 0
        for ctx in reversed(self._undo_stack):
            if ctx.state_type == prev_type:
                count += 1
            else:
                if prev_type is not None:
                    items.append({
                        "label": state_label(prev_type),
                        "count": count,
                        "is_redo": False,
                    })
                prev_type = ctx.state_type
                count = 1
        if prev_type is not None:
            items.append({
                "label": state_label(prev_type),
                "count": count,
                "is_redo": False,
            })

        return items
