"""Editing-command methods extracted from OpenFunscripter.

Mirrors editing operations from ``OpenFunscripter.cpp`` (Copy, Paste, Cut,
Equalize, Invert, Isolate, RepeatStroke, Undo, Redo, etc.).

Mixin class — must be listed **before** the main class in the MRO so that
``super()`` chains correctly, but in practice the methods here only call
``self.<attr>`` so MRO order does not matter.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.core.funscript   import Funscript, FunscriptAction
from src.core.undo_system import StateType
from src.ui.app_state     import OFS_Status

if TYPE_CHECKING:
    from src.ui.app import OpenFunscripter

log = logging.getLogger(__name__)


class EditingCommandsMixin:
    """Editing operations extracted from *OpenFunscripter*.

    Every method uses ``self: "OpenFunscripter"`` annotations so that
    IDE autocompletion / type-checking still works.
    """

    # ──────────────────────────────────────────────────────────────────────
    # Editing operations (mirrors OFS methods)
    # ──────────────────────────────────────────────────────────────────────

    def _active(self: "OpenFunscripter") -> Optional[Funscript]:
        return self.project.active_script

    def _funscript_time(self: "OpenFunscripter") -> float:
        """Current time in funscript-local coordinates (seconds).

        Uses the transport position converted via the active track's offset
        when a timeline manager is present; falls back to player time.
        """
        mgr = getattr(self, 'timeline_mgr', None)
        if mgr is not None:
            global_t = mgr.transport.position
            trk = mgr.TrackForFunscript(self.project.active_idx)
            if trk is not None:
                return trk.GlobalToLocal(global_t)
            return global_t
        return self.player.CurrentTime()

    def AddEditAction(self: "OpenFunscripter", pos: int) -> None:
        """Insert or edit an action at the current time. Mirrors ``OpenFunscripter::AddEditAction``."""
        s = self._active()
        if not s:
            return
        at_ms = int(self._funscript_time() * 1000)
        self.undo_system.Snapshot(StateType.ADD_EDIT_ACTIONS, s)
        self.scripting.AddEditAction(FunscriptAction(at_ms, pos))

    def RemoveAction(self: "OpenFunscripter") -> None:
        """Remove the selected or closest action. Mirrors ``OpenFunscripter::RemoveAction``."""
        s = self._active()
        if not s:
            return
        if s.HasSelection():
            self.undo_system.Snapshot(StateType.REMOVE_SELECTION, s)
            s.RemoveSelectedActions()
        else:
            closest = s.GetClosestAction(self._funscript_time())
            if closest:
                self.undo_system.Snapshot(StateType.REMOVE_ACTION, s)
                s.RemoveAction(closest)

    def CutSelection(self: "OpenFunscripter") -> None:
        """Copy then remove the selection. Mirrors ``OpenFunscripter::CutSelection``."""
        s = self._active()
        if s and s.HasSelection():
            self.CopySelection()
            self.undo_system.Snapshot(StateType.CUT_SELECTION, s)
            s.RemoveSelectedActions()

    def CopySelection(self: "OpenFunscripter") -> None:
        """Copy the selected actions to the clipboard. Mirrors ``OpenFunscripter::CopySelection``."""
        s = self._active()
        if s and s.HasSelection():
            self.copied_selection = sorted(s.selection, key=lambda a: a.at)

    def PasteSelection(self: "OpenFunscripter") -> None:
        """Paste copied actions relative to the current time. Mirrors ``OpenFunscripter::PasteSelection``."""
        s = self._active()
        if not s or not self.copied_selection:
            return
        self.undo_system.Snapshot(StateType.PASTE_COPIED_ACTIONS, s)
        cur_t = self._funscript_time()
        t0 = cur_t * 1000
        offset = t0 - self.copied_selection[0].at
        dur = (self.copied_selection[-1].at - self.copied_selection[0].at) / 1000.0
        s.RemoveActionsInInterval(
            cur_t - 0.0005,
            cur_t + dur + 0.0005
        )
        for a in self.copied_selection:
            s.AddAction(FunscriptAction(a.at + int(offset), a.pos))
        last = self.copied_selection[-1]
        self.player.SetPositionExact((last.at + int(offset)) / 1000.0)

    def PasteExact(self: "OpenFunscripter") -> None:
        """Paste copied actions at their original timestamps. Mirrors ``OpenFunscripter::PasteExact``."""
        s = self._active()
        if not s or not self.copied_selection:
            return
        self.undo_system.Snapshot(StateType.PASTE_COPIED_ACTIONS, s)
        if len(self.copied_selection) >= 2:
            s.RemoveActionsInInterval(
                self.copied_selection[0].at / 1000.0,
                self.copied_selection[-1].at / 1000.0
            )
        for a in self.copied_selection:
            s.AddAction(a)

    def EqualizeSelection(self: "OpenFunscripter") -> None:
        """Equalize spacing of selected actions. Mirrors ``OpenFunscripter::EqualizeSelection``."""
        s = self._active()
        if not s:
            return
        if not s.HasSelection():
            closest = s.GetClosestAction(self._funscript_time())
            if closest:
                behind = s.GetPreviousActionBehind(closest.at / 1000.0)
                ahead  = s.GetNextActionAhead(closest.at / 1000.0)
                if behind and ahead:
                    self.undo_system.Snapshot(StateType.EQUALIZE_ACTIONS, s)
                    s.SelectAction(behind); s.SelectAction(closest); s.SelectAction(ahead)
                    s.EqualizeSelection()
                    s.ClearSelection()
        elif len(list(s.selection)) >= 3:
            self.undo_system.Snapshot(StateType.EQUALIZE_ACTIONS, s)
            s.EqualizeSelection()

    def InvertSelection(self: "OpenFunscripter") -> None:
        """Invert positions of selected actions (100−pos). Mirrors ``OpenFunscripter::InvertSelection``."""
        s = self._active()
        if not s:
            return
        if not s.HasSelection():
            closest = s.GetClosestAction(self._funscript_time())
            if closest:
                self.undo_system.Snapshot(StateType.INVERT_ACTIONS, s)
                s.SelectAction(closest); s.InvertSelection(); s.ClearSelection()
        elif len(list(s.selection)) >= 3:
            self.undo_system.Snapshot(StateType.INVERT_ACTIONS, s)
            s.InvertSelection()

    def IsolateAction(self: "OpenFunscripter") -> None:
        """Remove the neighbours of the closest action. Mirrors ``OpenFunscripter::IsolateAction``."""
        s = self._active()
        if not s:
            return
        closest = s.GetClosestAction(self._funscript_time())
        if not closest:
            return
        self.undo_system.Snapshot(StateType.ISOLATE_ACTION, s)
        prev = s.GetPreviousActionBehind(closest.at / 1000.0 - 0.001)
        nxt  = s.GetNextActionAhead(closest.at / 1000.0 + 0.001)
        if prev:
            s.RemoveAction(prev)
        if nxt:
            s.RemoveAction(nxt)

    def RepeatLastStroke(self: "OpenFunscripter") -> None:
        """Repeat the last stroke pattern at the current time. Mirrors ``OpenFunscripter::RepeatStroke``."""
        s = self._active()
        if not s:
            return
        cur_t = self._funscript_time()
        stroke = s.GetLastStroke(cur_t)
        if len(stroke) < 2:
            return
        offset = cur_t * 1000 - stroke[-1].at
        self.undo_system.Snapshot(StateType.REPEAT_STROKE, s)
        on_action = s.GetActionAtTime(cur_t,
                                         self.scripting.LogicalFrameTime())
        start = len(stroke) - 2 if on_action else len(stroke) - 1
        for i in range(start, -1, -1):
            s.AddAction(FunscriptAction(stroke[i].at + int(offset), stroke[i].pos))
        self.player.SetPositionExact((stroke[0].at + int(offset)) / 1000.0)

    def _select_top_points(self: "OpenFunscripter") -> None:
        s = self._active()
        if s and s.HasSelection():
            self.undo_system.Snapshot(StateType.TOP_POINTS_ONLY, s)
            s.SelectTopActions()

    def _select_middle_points(self: "OpenFunscripter") -> None:
        s = self._active()
        if s and s.HasSelection():
            self.undo_system.Snapshot(StateType.MID_POINTS_ONLY, s)
            s.SelectMiddleActions()

    def _select_bottom_points(self: "OpenFunscripter") -> None:
        s = self._active()
        if s and s.HasSelection():
            self.undo_system.Snapshot(StateType.BOTTOM_POINTS_ONLY, s)
            s.SelectBottomActions()

    # ──────────────────────────────────────────────────────────────────────
    # Undo / Redo
    # ──────────────────────────────────────────────────────────────────────

    def Undo(self: "OpenFunscripter") -> None:
        """Undo the last edit. Mirrors ``OpenFunscripter::Undo``."""
        if self.undo_system.Undo():
            self.scripting.Undo()
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def Redo(self: "OpenFunscripter") -> None:
        """Redo the last undone edit. Mirrors ``OpenFunscripter::Redo``."""
        if self.undo_system.Redo():
            self.scripting.Redo()
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    # ──────────────────────────────────────────────────────────────────────
    # Heatmap / move-action helpers
    # ──────────────────────────────────────────────────────────────────────

    def SaveHeatmap(self: "OpenFunscripter", path: str, width: int = 1280,
                     height: int = 100, with_chapters: bool = False) -> None:
        """Export the heatmap to a PNG file.

        Mirrors OFS saveHeatmap(path, width, height, withChapters).
        with_chapters=True adds a chapter colour strip above the heatmap
        (total height = 2×height).
        """
        chapters = None
        if with_chapters:
            chapters = self.chapter_mgr.chapters if hasattr(self.chapter_mgr, "chapters") else []
        ok = self.player_controls.SaveHeatmapPng(path, width, height, chapters)
        if ok:
            log.info(f"Heatmap saved to {path}")
        else:
            self._alert("Save heatmap", "Failed to save heatmap (no data or Pillow missing).")

    def _save_heatmap_dialog(self: "OpenFunscripter", with_chapters: bool = False) -> None:
        """Open a save-file dialog then call SaveHeatmap()."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            s = self._active()
            default_name = (s.title if s else "heatmap") + "_Heatmap.png"
            default = str(Path(self._prefpath()) / default_name)
            result = pfd.save_file("Save heatmap", default,
                                   filters=["PNG image", "*.png"]).result()
            if result:
                self.SaveHeatmap(result, with_chapters=with_chapters)
        except ImportError:
            pass

    def _move_action_to_current(self: "OpenFunscripter") -> None:
        s = self._active()
        if not s:
            return
        cur_t = self._funscript_time()
        c = s.GetClosestAction(cur_t)
        if c:
            self.undo_system.Snapshot(StateType.MOVE_ACTION_TO_CURRENT_POS, s)
            s.EditAction(c, FunscriptAction(
                int(cur_t * 1000), c.pos))
