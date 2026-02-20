"""
ScriptingMode — Python port of OFS_ScriptingMode.h / OFS_ScriptingMode.cpp

Scripting modes mirror OFS exactly:
  NORMAL      — point editing (single-click adds/moves action)
  RECORDING   — continuous recording while playing
  DYNAMIC     — dynamic scripting mode (OFS extension)

Exposed methods called by app:
  Init(player, undo)
  Show(player)
  Update()
  add_edit_action(action) — called by keybinding numeric keys
  PreviousFrame() / NextFrame()
  LogicalFrameTime() — seconds per "step" for current mode
  SteppingIntervalForward(t) / SteppingIntervalBackward(t)
  Undo() / Redo()
"""

from __future__ import annotations

import time
from enum import IntEnum
from typing import Optional

from imgui_bundle import imgui, ImVec2, ImVec4
from imgui_bundle import icons_fontawesome_6 as fa

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript, FunscriptAction
from src.core.undo_system  import UndoSystem, StateType


class ScriptingModeEnum(IntEnum):
    NORMAL      = 0
    RECORDING   = 1
    ALTERNATING = 2
    DYNAMIC     = 3


class ScriptingMode:
    """Python port of OFS_ScriptingMode."""

    WindowId = "Scripting###ScriptingMode"

    def __init__(self) -> None:
        self.mode: ScriptingModeEnum = ScriptingModeEnum.NORMAL

        # Normal mode settings
        self._frame_step: bool    = True   # step by frame vs fixed time
        self._fixed_step: float   = 0.033  # seconds when frame_step=False
        self._snap_to_frame: bool = True

        # Recording mode
        self._recording: bool = False

        # Alternating mode state
        self._alt_next_inverted:    bool = False  # False=top/original, True=bottom/inverted
        self._alt_fixed_range:      bool = False  # use fixedBottom/fixedTop
        self._alt_context_sensitive:bool = False  # derive from previous action
        self._alt_fixed_bottom:     int  = 0
        self._alt_fixed_top:        int  = 100

        # Frame step speed multiplier
        self._step_size: int = 1

        # Action insert delay offset (OFS: state.actionInsertDelayMs)
        self._action_delay_ms: int = 0

        self._player: Optional[OFS_Videoplayer] = None
        self._undo:   Optional[UndoSystem]      = None
        self._script: Optional[Funscript]       = None

        # Funscript reference (set by app via active_funscript)
        self._active_getter = lambda: None

    # ──────────────────────────────────────────────────────────────────────

    def Init(self, player: OFS_Videoplayer, undo: UndoSystem) -> None:
        self._player = player
        self._undo   = undo

    def SetActiveGetter(self, fn) -> None:
        self._active_getter = fn

    def _active(self) -> Optional[Funscript]:
        return self._active_getter()

    # ──────────────────────────────────────────────────────────────────────
    # Frame helpers
    # ──────────────────────────────────────────────────────────────────────

    def LogicalFrameTime(self) -> float:
        """Seconds per single step."""
        if not self._player or not self._player.VideoLoaded():
            return 1.0 / 30.0
        return self._player.FrameTime() * self._step_size

    def SteppingIntervalForward(self, t: float) -> float:
        return self.LogicalFrameTime()

    def SteppingIntervalBackward(self, t: float) -> float:
        return -self.LogicalFrameTime()

    def PreviousFrame(self) -> None:
        if self._player:
            self._player.SeekFrames(-self._step_size)

    def NextFrame(self) -> None:
        if self._player:
            self._player.SeekFrames(self._step_size)

    # ──────────────────────────────────────────────────────────────────────
    # Action editing
    # ──────────────────────────────────────────────────────────────────────

    def add_edit_action(self, action: FunscriptAction) -> None:
        """Add or edit action at the action's timestamp."""
        s = self._active()
        if not s or not self._player:
            return
        ft = self.LogicalFrameTime()

        # Apply offset when playing (mirrors OFS ScriptingMode::AddEditAction)
        if not self._player.IsPaused() and self._action_delay_ms != 0:
            action = FunscriptAction(
                action.at + self._action_delay_ms, action.pos
            )

        # Alternating mode: override position
        if self.mode == ScriptingModeEnum.ALTERNATING:
            action = self._apply_alternating(s, action)

        existing = s.get_action_at_time(action.at / 1000.0, ft)
        if existing:
            if existing.pos != action.pos:
                s.edit_action(existing, FunscriptAction(existing.at, action.pos))
        else:
            s.add_action(action)

        # Toggle alternating state (unless context-sensitive)
        if self.mode == ScriptingModeEnum.ALTERNATING and not self._alt_context_sensitive:
            self._alt_next_inverted = not self._alt_next_inverted

        # Auto-advance in normal / alternating modes
        if self.mode in (ScriptingModeEnum.NORMAL, ScriptingModeEnum.ALTERNATING):
            self._player.SeekFrames(self._step_size)

    def _apply_alternating(self, script: "Funscript", action: FunscriptAction) -> FunscriptAction:
        """Compute the overridden position for AlternatingMode."""
        pos = action.pos
        if self._alt_context_sensitive:
            behind = script.actions.get_previous_action_behind(action.at / 1000.0 - 0.001)
            if behind:
                if behind.pos <= 50 and pos <= 50:
                    pos = 100 - pos   # push to top
                elif behind.pos > 50 and pos > 50:
                    pos = 100 - pos   # push to bottom
        elif self._alt_fixed_range:
            pos = self._alt_fixed_bottom if self._alt_next_inverted else self._alt_fixed_top
        else:
            if self._alt_next_inverted:
                pos = 100 - pos
        return FunscriptAction(action.at, max(0, min(100, pos)))

    def Undo(self) -> None:
        if self.mode == ScriptingModeEnum.ALTERNATING and not self._alt_context_sensitive:
            self._alt_next_inverted = not self._alt_next_inverted

    def Redo(self) -> None:
        if self.mode == ScriptingModeEnum.ALTERNATING and not self._alt_context_sensitive:
            self._alt_next_inverted = not self._alt_next_inverted

    # ──────────────────────────────────────────────────────────────────────
    # Update
    # ──────────────────────────────────────────────────────────────────────

    def Update(self) -> None:
        if self.mode == ScriptingModeEnum.RECORDING:
            self._update_recording()

    def _update_recording(self) -> None:
        s = self._active()
        if not s or not self._player:
            return
        if not self._recording or self._player.IsPaused():
            return
        # OFS records mouse Y position as action
        io = imgui.get_io()
        # Normalise mouse Y in window to 0..100
        # (Stubbed: real impl maps mouse to funscript position)

    # ──────────────────────────────────────────────────────────────────────
    # Show
    # ──────────────────────────────────────────────────────────────────────

    def Show(self, player: OFS_Videoplayer) -> None:
        self._player = player
        imgui.text("Scripting mode")
        imgui.separator()

        # Mode selector
        modes = ["Normal", "Recording", "Alternating", "Dynamic"]
        cur = int(self.mode)
        imgui.set_next_item_width(-1)
        changed, new_mode = imgui.combo("##mode", cur, modes)
        if changed:
            self.mode = ScriptingModeEnum(new_mode)

        imgui.spacing()

        if self.mode == ScriptingModeEnum.NORMAL:
            self._show_normal()
        elif self.mode == ScriptingModeEnum.RECORDING:
            self._show_recording()
        elif self.mode == ScriptingModeEnum.ALTERNATING:
            self._show_alternating()

    def _show_normal(self) -> None:
        imgui.text_disabled("Normal mode")
        imgui.spacing()
        _, self._snap_to_frame = imgui.checkbox("Snap to frame", self._snap_to_frame)
        imgui.set_next_item_width(80)
        changed, val = imgui.input_int("Step size", self._step_size, 1, 1)
        if changed:
            self._step_size = max(1, min(60, val))
        imgui.spacing()
        imgui.separator()
        imgui.spacing()
        imgui.set_next_item_width(-1)
        changed2, delay = imgui.drag_int(
            "Offset ms##delay", self._action_delay_ms, 1.0, -500, 500)
        if changed2:
            self._action_delay_ms = max(-500, min(500, delay))
        if imgui.is_item_hovered():
            imgui.begin_tooltip()
            imgui.text("Offset in milliseconds applied to actions\n"
                       "when inserting while the video is playing.")
            imgui.end_tooltip()

    def _show_recording(self) -> None:
        col = ImVec4(0.9, 0.2, 0.2, 1.0) if self._recording else ImVec4(0.2, 0.7, 0.2, 1.0)
        imgui.push_style_color(imgui.Col_.button, col)
        label = fa.ICON_FA_STOP + " Stop" if self._recording else fa.ICON_FA_CIRCLE + " Record"
        if imgui.button(label, ImVec2(-1, 0)):
            self._recording = not self._recording
        imgui.pop_style_color()

    def _show_alternating(self) -> None:
        # Status hint
        if self._alt_context_sensitive:
            imgui.text_disabled("Context-sensitive: auto top/bottom")
        elif self._alt_fixed_range:
            next_val = self._alt_fixed_bottom if self._alt_next_inverted else self._alt_fixed_top
            imgui.text_disabled(f"Next point at: {next_val}")
        else:
            state = "inverted (bottom)" if self._alt_next_inverted else "normal (top)"
            imgui.text_disabled(f"Next point: {state}")

        imgui.spacing()
        _, self._alt_fixed_range = imgui.checkbox("Fixed range##alt", self._alt_fixed_range)
        _, self._alt_context_sensitive = imgui.checkbox(
            "Context sensitive##alt", self._alt_context_sensitive)
        imgui.same_line()
        imgui.text_disabled("(?)")
        if imgui.is_item_hovered():
            imgui.begin_tooltip()
            imgui.text("Automatically alternate based on the previous action's position.")
            imgui.end_tooltip()

        if self._alt_fixed_range:
            avail = imgui.get_content_region_avail().x
            imgui.set_next_item_width(avail * 0.45)
            _, self._alt_fixed_bottom = imgui.input_int(
                "##altbot", self._alt_fixed_bottom, 1, 10)
            imgui.same_line()
            imgui.set_next_item_width(avail * 0.45)
            _, self._alt_fixed_top = imgui.input_int(
                "##alttop", self._alt_fixed_top, 1, 10)
            # Keep bottom < top
            self._alt_fixed_bottom = max(0, min(99, self._alt_fixed_bottom))
            self._alt_fixed_top    = max(self._alt_fixed_bottom + 1, min(100, self._alt_fixed_top))

        imgui.spacing()
        _, self._snap_to_frame = imgui.checkbox("Snap to frame##alt", self._snap_to_frame)
        imgui.set_next_item_width(80)
        changed, val = imgui.input_int("Step size##alt", self._step_size, 1, 1)
        if changed:
            self._step_size = max(1, min(60, val))
