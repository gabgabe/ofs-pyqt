"""Keybinding registration mixin — mirrors OFS ``registerBindings`` in OpenFunscripter.cpp.

All default key-chord assignments replicate the C++ ``KeybindingSystem`` setup
found in ``OpenFunscripter::registerBindings``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import imgui

from src.core.funscript import FunscriptAction
from src.core.undo_system import StateType
from src.ui.app_state import OFS_Status

if TYPE_CHECKING:
    from src.ui.app import OpenFunscripter


class KeybindingsMixin:
    """Mixin providing ``_register_bindings()`` — extracted from OpenFunscripter.

    Mirrors keybinding registration in ``OpenFunscripter::registerBindings``
    (OpenFunscripter.cpp).  Groups: Actions, Core, Navigation, Utility,
    Moving, Special, Videoplayer, Chapters.
    """

    def _register_bindings(self: "OpenFunscripter") -> None:
        K  = imgui.Key
        M  = imgui.Key   # mods same namespace in imgui-bundle

        def reg_grp(id_, label):
            self.keys.RegisterGroup(id_, label)

        def reg(id_, fn, label, grp, chords=None, repeat=False):
            self.keys.RegisterAction(id_, fn, label, grp, chords, repeat)

        # ── Actions ───────────────────────────────────────────────────────
        reg_grp("Actions", "Actions")
        reg("remove_action", self.RemoveAction, "Remove action", "Actions",
            [(0, K.delete)])
        for val, key in [(0, K.keypad0),(10,K.keypad1),(20,K.keypad2),(30,K.keypad3),
                         (40,K.keypad4),(50,K.keypad5),(60,K.keypad6),(70,K.keypad7),
                         (80,K.keypad8),(90,K.keypad9),(100,K.keypad_divide)]:
            v = val  # capture
            reg(f"action_{v}", lambda _v=v: self.AddEditAction(_v),
                f"Add action {v}", "Actions", [(0, key)])

        # ── Core ──────────────────────────────────────────────────────────
        reg_grp("Core", "Core")
        reg("save_project",   self.SaveProject,  "Save project",     "Core",
            [(K.mod_ctrl, K.s)])
        reg("quick_export",   self.QuickExport,  "Quick export",     "Core",
            [(K.mod_ctrl | K.mod_shift, K.s)])
        reg("sync_timestamps",
            lambda: self.player.SyncWithPlayerTime(),
            "Sync time with player", "Core", [(0, K.s)])

        def _cycle_fwd():
            scripts = self.project.funscripts
            if not scripts:
                return
            n = len(scripts)
            idx = self.project.active_idx
            for _ in range(n):
                idx = (idx + 1) % n
                if scripts[idx].enabled:
                    break
            self.project.active_idx = idx
            self._update_title()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

        def _cycle_bwd():
            scripts = self.project.funscripts
            if not scripts:
                return
            n = len(scripts)
            idx = self.project.active_idx
            for _ in range(n):
                idx = (idx - 1) % n
                if scripts[idx].enabled:
                    break
            self.project.active_idx = idx
            self._update_title()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

        reg("cycle_loaded_forward_scripts",  _cycle_fwd, "Cycle scripts forward",  "Core", [(0, K.page_down)])
        reg("cycle_loaded_backward_scripts", _cycle_bwd, "Cycle scripts backward", "Core", [(0, K.page_up)])

        # ── Navigation ────────────────────────────────────────────────────
        reg_grp("Navigation", "Navigation")

        def _prev_action():
            s = self._active()
            if s:
                a = s.GetPreviousActionBehind(self.player.CurrentTime() - 0.001)
                if a:
                    self.player.SetPositionExact(a.at / 1000.0)

        def _next_action():
            s = self._active()
            if s:
                a = s.GetNextActionAhead(self.player.CurrentTime() + 0.001)
                if a:
                    self.player.SetPositionExact(a.at / 1000.0)

        reg("prev_action", _prev_action, "Previous action", "Navigation",
            [(0, K.down_arrow, True)], repeat=True)
        reg("next_action", _next_action, "Next action",     "Navigation",
            [(0, K.up_arrow, True)],   repeat=True)

        def _prev_action_multi():
            """Mirrors OFS prev_action_multi: navigate to nearest action BEHIND
            the cursor across ALL loaded scripts (Ctrl+↓)."""
            scripts = self.project.funscripts
            if not scripts:
                return
            current_time = self.player.CurrentTime()
            best_time: float = -1.0
            for s in scripts:
                a = s.GetPreviousActionBehind(current_time - 0.001)
                if a is not None:
                    t = a.at / 1000.0
                    if best_time < 0.0 or abs(current_time - t) < abs(current_time - best_time):
                        best_time = t
            if best_time >= 0.0:
                self.player.SetPositionExact(best_time)

        def _next_action_multi():
            """Mirrors OFS next_action_multi: navigate to nearest action AHEAD
            of the cursor across ALL loaded scripts (Ctrl+↑)."""
            scripts = self.project.funscripts
            if not scripts:
                return
            current_time = self.player.CurrentTime()
            best_time: float = -1.0
            for s in scripts:
                a = s.GetNextActionAhead(current_time + 0.001)
                if a is not None:
                    t = a.at / 1000.0
                    if best_time < 0.0 or abs(current_time - t) < abs(current_time - best_time):
                        best_time = t
            if best_time >= 0.0:
                self.player.SetPositionExact(best_time)

        reg("prev_action_multi", _prev_action_multi,
            "Previous action (all scripts)", "Navigation",
            [(K.mod_ctrl, K.down_arrow, True)], repeat=True)
        reg("next_action_multi", _next_action_multi,
            "Next action (all scripts)", "Navigation",
            [(K.mod_ctrl, K.up_arrow, True)], repeat=True)

        reg("prev_frame",
            lambda: self.scripting.PreviousFrame() if self.player.IsPaused() else None,
            "Previous frame", "Navigation", [(0, K.left_arrow, True)], repeat=True)
        reg("next_frame",
            lambda: self.scripting.NextFrame() if self.player.IsPaused() else None,
            "Next frame", "Navigation", [(0, K.right_arrow, True)], repeat=True)

        def _frame_x3(direction: int) -> None:
            if not self.player.IsPaused():
                return
            key = K.right_arrow if direction > 0 else K.left_arrow
            # Single click → 3 frames; held repeat → 10 frames per step
            frames = 3 if imgui.is_key_pressed(key, repeat=False) else 10
            self.player.SeekFrames(frames * direction * self.scripting._step_size)

        reg("prev_frame_x3", lambda: _frame_x3(-1),
            "Previous frame ×3 / ×10 held", "Navigation",
            [(K.mod_ctrl, K.left_arrow, True)], repeat=True)
        reg("next_frame_x3", lambda: _frame_x3(1),
            "Next frame ×3 / ×10 held", "Navigation",
            [(K.mod_ctrl, K.right_arrow, True)], repeat=True)

        fast_step = self.preferences.fast_step_amount
        reg("fast_step",     lambda: self.player.SeekFrames( fast_step), "Fast step",     "Navigation")
        reg("fast_backstep", lambda: self.player.SeekFrames(-fast_step), "Fast backstep", "Navigation")

        # ── Utility ───────────────────────────────────────────────────────
        reg_grp("Utility", "Utility")
        reg("undo", self.Undo, "Undo", "Utility", [(K.mod_ctrl, K.z, True)], repeat=True)
        reg("redo", self.Redo, "Redo", "Utility", [(K.mod_ctrl, K.y, True)], repeat=True)

        reg("copy",       self.CopySelection,  "Copy",       "Utility", [(K.mod_ctrl, K.c)])
        reg("paste",      self.PasteSelection, "Paste",      "Utility", [(K.mod_ctrl, K.v)])
        reg("paste_exact",self.PasteExact,     "Paste exact","Utility", [(K.mod_ctrl | K.mod_shift, K.v)])
        reg("cut",        self.CutSelection,   "Cut",        "Utility", [(K.mod_ctrl, K.x)])

        reg("select_all",
            lambda: self._active().SelectAll() if self._active() else None,
            "Select all", "Utility", [(K.mod_ctrl, K.a)])
        reg("deselect_all",
            lambda: self._active().ClearSelection() if self._active() else None,
            "Deselect all", "Utility", [(K.mod_ctrl, K.d)])
        reg("select_all_left",
            lambda: self._active().SelectTime(0, self.player.CurrentTime()) if self._active() else None,
            "Select all left",  "Utility", [(K.mod_ctrl | K.mod_alt, K.left_arrow)])
        reg("select_all_right",
            lambda: self._active().SelectTime(self.player.CurrentTime(), self.player.Duration()) if self._active() else None,
            "Select all right", "Utility", [(K.mod_ctrl | K.mod_alt, K.right_arrow)])

        reg("select_top_points",    self._select_top_points,    "Select top points",    "Utility")
        reg("select_middle_points", self._select_middle_points, "Select middle points", "Utility")
        reg("select_bottom_points", self._select_bottom_points, "Select bottom points", "Utility")

        reg("save_frame_as_image",
            lambda: self.player.SaveFrameToImage(self._prefpath("screenshot")),
            "Save frame as image", "Utility", [(0, K.f2)])
        reg("cycle_subtitles",
            lambda: self.player.CycleSubtitles(),
            "Cycle subtitles", "Utility", [(0, K.j)])
        reg("fullscreen_toggle",
            lambda: self._toggle_fullscreen(),
            "Toggle fullscreen", "Utility", [(0, K.f10)])

        # ── Moving ────────────────────────────────────────────────────────
        reg_grp("Moving", "Moving")

        def _move_pos(delta):
            s = self._active()
            if not s:
                return
            if s.HasSelection():
                self.undo_system.Snapshot(StateType.ACTIONS_MOVED, s)
                s.MoveSelectionPosition(delta)
            else:
                c = s.GetClosestAction(self.player.CurrentTime())
                if c:
                    moved = FunscriptAction(c.at, max(0, min(100, c.pos + delta)))
                    self.undo_system.Snapshot(StateType.ACTIONS_MOVED, s)
                    s.EditAction(c, moved)

        def _move_time(forward: bool, snap_video: bool = False):
            s = self._active()
            if not s:
                return
            sel = list(s.selection)
            if sel:
                t = (self.scripting.SteppingIntervalForward(sel[0].at / 1000.0)
                     if forward else
                     self.scripting.SteppingIntervalBackward(sel[0].at / 1000.0))
                self.undo_system.Snapshot(StateType.ACTIONS_MOVED, s)
                s.MoveSelectionTime(t, self.scripting.LogicalFrameTime())
                if snap_video:
                    c = s.GetClosestActionSelection(self.player.CurrentTime())
                    self.player.SetPositionExact(
                        (c.at / 1000.0) if c else (sel[0].at / 1000.0)
                    )
            else:
                c = s.GetClosestAction(self.player.CurrentTime())
                if c:
                    t = (self.scripting.SteppingIntervalForward(c.at / 1000.0)
                         if forward else
                         self.scripting.SteppingIntervalBackward(c.at / 1000.0))
                    moved = FunscriptAction(int(c.at + t * 1000), c.pos)
                    clash = s.GetActionAtTime(moved.at / 1000.0,
                                                 self.scripting.LogicalFrameTime())
                    if (clash is None or
                        (forward and clash.at < moved.at) or
                        (not forward and clash.at > moved.at)):
                        self.undo_system.Snapshot(StateType.ACTIONS_MOVED, s)
                        s.EditAction(c, moved)
                        if snap_video:
                            self.player.SetPositionExact(moved.at / 1000.0)

        reg("move_actions_up_ten",   lambda: _move_pos(10),  "Move up 10",   "Moving")
        reg("move_actions_down_ten", lambda: _move_pos(-10), "Move down 10", "Moving")
        reg("move_actions_up_five",  lambda: _move_pos(5),   "Move up 5",    "Moving")
        reg("move_actions_down_five",lambda: _move_pos(-5),  "Move down 5",  "Moving")
        reg("move_actions_up",       lambda: _move_pos(1),   "Move up 1",    "Moving",
            [(K.mod_shift, K.up_arrow, True)], repeat=True)
        reg("move_actions_down",     lambda: _move_pos(-1),  "Move down 1",  "Moving",
            [(K.mod_shift, K.down_arrow, True)], repeat=True)

        reg("move_actions_left",         lambda: _move_time(False),       "Move left",         "Moving", [(K.mod_shift, K.left_arrow,  True)], repeat=True)
        reg("move_actions_right",        lambda: _move_time(True),        "Move right",        "Moving", [(K.mod_shift, K.right_arrow, True)], repeat=True)
        reg("move_actions_left_snapped", lambda: _move_time(False, True), "Move left (snap)",  "Moving", [(K.mod_ctrl | K.mod_shift, K.left_arrow,  True)], repeat=True)
        reg("move_actions_right_snapped",lambda: _move_time(True,  True), "Move right (snap)", "Moving", [(K.mod_ctrl | K.mod_shift, K.right_arrow, True)], repeat=True)

        reg("move_action_to_current_pos",
            lambda: self._move_action_to_current(),
            "Move action to current pos", "Moving", [(0, K.end)])

        # ── Special ───────────────────────────────────────────────────────
        reg_grp("Special", "Special")
        reg("equalize_actions", self.EqualizeSelection, "Equalize actions", "Special", [(0, K.e)])
        reg("invert_actions",   self.InvertSelection,   "Invert actions",   "Special", [(0, K.i)])
        reg("isolate_action",   self.IsolateAction,     "Isolate action",   "Special", [(0, K.r)])
        reg("repeat_stroke",    self.RepeatLastStroke, "Repeat stroke",    "Special", [(0, K.home)])

        # ── Videoplayer ───────────────────────────────────────────────────
        reg_grp("Videoplayer", "Videoplayer")
        reg("toggle_play",      lambda: self.player.TogglePlay(),    "Toggle play",     "Videoplayer", [(0, K.space)])
        reg("decrement_speed",  lambda: self.player.AddSpeed(-0.1),  "Decrease speed",  "Videoplayer", [(0, K.keypad_subtract)])
        reg("increment_speed",  lambda: self.player.AddSpeed( 0.1),  "Increase speed",  "Videoplayer", [(0, K.keypad_add)])
        reg("goto_start",  lambda: self.player.SetPositionPercent(0.0), "Go to start", "Videoplayer")
        reg("goto_end",    lambda: self.player.SetPositionPercent(1.0), "Go to end",   "Videoplayer")

        # Scroll wheel pseudo-key bindings (no default action; bindable by user)
        reg("scroll_up",   lambda: None, "Scroll wheel up",   "Videoplayer")
        reg("scroll_down", lambda: None, "Scroll wheel down",  "Videoplayer")

        # ── Chapters ──────────────────────────────────────────────────────
        reg_grp("Chapters", "Chapters")
        reg("create_chapter",  lambda: self.chapter_mgr.AddChapter(self.player.CurrentTime(), self.player.Duration()), "Create chapter",  "Chapters")
        reg("create_bookmark", lambda: self.chapter_mgr.AddBookmark(self.player.CurrentTime()), "Create bookmark", "Chapters")
