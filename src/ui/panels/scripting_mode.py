"""
ScriptingMode  --  Python port of OFS_ScriptingMode.h / OFS_ScriptingMode.cpp

Scripting modes mirror OFS exactly:
  NORMAL       --  point editing (single-click adds/moves action)
  RECORDING    --  continuous recording while playing
  DYNAMIC      --  dynamic scripting mode (OFS extension)

Exposed methods called by app:
  Init(player, undo)
  Show(player)
  Update()
  AddEditAction(action)  --  called by keybinding numeric keys
  PreviousFrame() / NextFrame()
  LogicalFrameTime()  --  seconds per "step" for current mode
  SteppingIntervalForward(t) / SteppingIntervalBackward(t)
  Undo() / Redo()
"""

from __future__ import annotations

import math
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


# -- Overlay modes (mirrors OFS ScriptingOverlayModes) -------------------------
class OverlayModeEnum(IntEnum):
    FRAME = 0
    TEMPO = 1
    EMPTY = 2


# Beat subdivisions  --  shared from core.tempo
from src.core.tempo import BEAT_MULTIPLES, BEAT_NAMES


def _tempo_beat_time(bpm: float, measure_idx: int) -> float:
    """Seconds per subdivided beat for given BPM and subdivision index."""
    return (60.0 / max(1.0, bpm)) * BEAT_MULTIPLES[measure_idx]


def _get_next_tempo_position(beat_time: float, current_time: float,
                             beat_offset: float) -> float:
    """Next beat boundary strictly after current_time (mirrors OFS GetNextPosition)."""
    beat_idx = math.floor((current_time - beat_offset) / beat_time) + 1.0
    new_pos = beat_idx * beat_time + beat_offset
    if abs(new_pos - current_time) <= 0.001:
        new_pos += beat_time
    return new_pos


def _get_prev_tempo_position(beat_time: float, current_time: float,
                             beat_offset: float) -> float:
    """Previous beat boundary strictly before current_time (mirrors OFS GetPreviousPosition)."""
    beat_idx = math.ceil((current_time - beat_offset) / beat_time) - 1.0
    new_pos = beat_idx * beat_time + beat_offset
    if abs(new_pos - current_time) <= 0.001:
        new_pos -= beat_time
    return new_pos

class ScriptingMode:
    """Python port of ``OFS_ScriptingMode`` (OFS_ScriptingMode.h / .cpp).

    Manages scripting modes (Normal, Recording, Alternating, Dynamic),
    overlay modes (Frame, Tempo, Empty), and frame-stepping logic.
    """

    WindowId = "Scripting###ScriptingMode"

    def __init__(self) -> None:
        self.mode: ScriptingModeEnum = ScriptingModeEnum.NORMAL

        # Normal mode settings
        self._frame_step: bool    = True   # step by frame vs fixed time
        self._fixed_step: float   = 0.033  # seconds when frame_step=False
        self._snap_to_frame: bool = True

        # Recording mode
        self._recording: bool = False
        # 0 = HoldSample (continuous), 1 = FrameByFrame
        self._rec_type: int    = 0
        self._rec_active_pos: float = 50.0   # 0-100, fed externally (e.g. from simulator)
        self._rec_has_pos:    bool  = False   # True when simulator is feeding values
        self._rec_last_at:    float = -1.0    # last recorded time (s) to avoid duplicates
        self._rec_interval_s: float = 1.0 / 60.0  # HoldSample interval (default 60 Hz)

        # Alternating mode state
        self._alt_next_inverted:    bool = False  # False=top/original, True=bottom/inverted
        self._alt_fixed_range:      bool = False  # use fixedBottom/fixedTop
        self._alt_context_sensitive:bool = False  # derive from previous action
        self._alt_fixed_bottom:     int  = 0
        self._alt_fixed_top:        int  = 100

        # Dynamic Injection mode settings (OFS: DynamicInjectionMode)
        self._dyn_target_speed: float = 300.0   # units/s  (MinSpeed=50, MaxSpeed=1000)
        self._dyn_direction_bias: float = 0.0   # -0.9 .. 0.9
        self._dyn_top_bottom: int = 1            # +1 = top, -1 = bottom

        # Frame step speed multiplier
        self._step_size: int = 1

        # Action insert delay offset (OFS: state.actionInsertDelayMs)
        self._action_delay_ms: int = 0

        # -- Overlay mode (mirrors OFS ScriptingOverlayModes) --------------
        self.overlay_mode: OverlayModeEnum = OverlayModeEnum.FRAME
        # Frame overlay settings
        self._frame_fps_override: bool  = False
        self._frame_fps_value:    float = 30.0   # fps to use when override enabled
        # Tempo overlay settings
        self._tempo_bpm:         float = 120.0
        self._tempo_offset_s:    float = 0.0     # beat offset in seconds
        self._tempo_measure_idx: int   = 0       # index into _BEAT_MULTIPLES

        self._player: Optional[OFS_Videoplayer] = None
        self._undo:   Optional[UndoSystem]      = None
        self._script: Optional[Funscript]       = None
        self._timeline_mgr = None  # set via SetTimelineManager()

        # Funscript reference (set by app via active_funscript)
        self._active_getter = lambda: None

    # ----------------------------------------------------------------------

    def Init(self, player: OFS_Videoplayer, undo: UndoSystem) -> None:
        """Wire player and undo references. Mirrors ``OFS_ScriptingMode::Init``."""
        self._player = player
        self._undo   = undo

    def SetActiveGetter(self, fn) -> None:
        """Set the callable that returns the currently active Funscript."""
        self._active_getter = fn

    def SetTimelineManager(self, mgr) -> None:
        """Wire timeline manager for transport-level stepping and timing."""
        self._timeline_mgr = mgr

    def _current_time(self) -> float:
        """Current time in seconds  --  prefers transport position over player."""
        if self._timeline_mgr is not None:
            return self._timeline_mgr.CurrentTime()
        if self._player:
            return self._player.CurrentTime()
        return 0.0

    def _active(self) -> Optional[Funscript]:
        return self._active_getter()

    # ----------------------------------------------------------------------
    # Frame helpers
    # ----------------------------------------------------------------------

    def LogicalFrameTime(self) -> float:
        """Seconds per single step (respects Frame overlay FPS override)."""
        if (self.overlay_mode == OverlayModeEnum.FRAME
                and self._frame_fps_override and self._frame_fps_value > 0):
            return (1.0 / self._frame_fps_value) * self._step_size
        if not self._player or not self._player.VideoLoaded():
            return 1.0 / 30.0
        return self._player.FrameTime() * self._step_size

    def SteppingIntervalForward(self, t: float) -> float:
        """Seconds to advance for one step forward (overlay-aware)."""
        if self.overlay_mode == OverlayModeEnum.TEMPO:
            bt = _tempo_beat_time(self._tempo_bpm, self._tempo_measure_idx)
            return _get_next_tempo_position(bt, t, self._tempo_offset_s) - t
        return self.LogicalFrameTime()

    def SteppingIntervalBackward(self, t: float) -> float:
        """Seconds to rewind for one step backward (overlay-aware)."""
        if self.overlay_mode == OverlayModeEnum.TEMPO:
            bt = _tempo_beat_time(self._tempo_bpm, self._tempo_measure_idx)
            return _get_prev_tempo_position(bt, t, self._tempo_offset_s) - t
        return -self.LogicalFrameTime()

    def PreviousFrame(self) -> None:
        """Step one frame/beat backward. Mirrors ``OFS_ScriptingMode::PreviousFrame``."""
        if not self._player:
            return
        if self.overlay_mode == OverlayModeEnum.TEMPO:
            t = self._player.CurrentTime()
            bt = _tempo_beat_time(self._tempo_bpm, self._tempo_measure_idx)
            self._player.SetPositionExact(
                _get_prev_tempo_position(bt, t, self._tempo_offset_s))
        elif (self.overlay_mode == OverlayModeEnum.FRAME
              and self._frame_fps_override and self._frame_fps_value > 0):
            self._player.SeekRelative(
                -(1.0 / self._frame_fps_value) * self._step_size)
        else:
            self._player.SeekFrames(-self._step_size)

    def NextFrame(self) -> None:
        """Step one frame/beat forward. Mirrors ``OFS_ScriptingMode::NextFrame``."""
        if not self._player:
            return
        if self.overlay_mode == OverlayModeEnum.TEMPO:
            t = self._player.CurrentTime()
            bt = _tempo_beat_time(self._tempo_bpm, self._tempo_measure_idx)
            self._player.SetPositionExact(
                _get_next_tempo_position(bt, t, self._tempo_offset_s))
        elif (self.overlay_mode == OverlayModeEnum.FRAME
              and self._frame_fps_override and self._frame_fps_value > 0):
            self._player.SeekRelative(
                (1.0 / self._frame_fps_value) * self._step_size)
        else:
            self._player.SeekFrames(self._step_size)

    # ----------------------------------------------------------------------
    # Action editing
    # ----------------------------------------------------------------------

    def AddEditAction(self, action: FunscriptAction) -> None:
        """Add or edit action at the action's timestamp. Mirrors ``OFS_ScriptingMode::AddEditAction``."""
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

        # Dynamic injection mode: auto-insert a midpoint action
        if self.mode == ScriptingModeEnum.DYNAMIC:
            t_sec = action.at / 1000.0
            behind = s.actions.GetPreviousActionBehind(t_sec - 0.001)
            if behind is not None:
                dt = t_sec - behind.at / 1000.0
                # midpoint with direction bias
                inject_at_s = (
                    behind.at / 1000.0
                    + dt * 0.5
                    + dt * 0.5 * self._dyn_direction_bias
                )
                inject_dur = inject_at_s - behind.at / 1000.0
                inject_pos = max(
                    0,
                    min(
                        100,
                        int(round(
                            behind.pos
                            + self._dyn_top_bottom
                            * inject_dur
                            * self._dyn_target_speed
                        )),
                    ),
                )
                inject_ms = int(inject_at_s * 1000)
                if behind.at < inject_ms < action.at:
                    s.AddAction(FunscriptAction(inject_ms, inject_pos))

        existing = s.GetActionAtTime(action.at / 1000.0, ft)
        if existing:
            if existing.pos != action.pos:
                s.EditAction(existing, FunscriptAction(existing.at, action.pos))
        else:
            s.AddAction(action)

        # Toggle alternating state (unless context-sensitive)
        if self.mode == ScriptingModeEnum.ALTERNATING and not self._alt_context_sensitive:
            self._alt_next_inverted = not self._alt_next_inverted

        # Auto-advance in normal / alternating modes
        if self.mode in (ScriptingModeEnum.NORMAL, ScriptingModeEnum.ALTERNATING):
            if self._timeline_mgr is not None:
                self._timeline_mgr.StepFrames(self._step_size)
            elif self._player:
                self._player.SeekFrames(self._step_size)

    def _apply_alternating(self, script: "Funscript", action: FunscriptAction) -> FunscriptAction:
        """Compute the overridden position for AlternatingMode."""
        pos = action.pos
        if self._alt_context_sensitive:
            behind = script.actions.GetPreviousActionBehind(action.at / 1000.0 - 0.001)
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

    def SetActivePosition(self, value: float, active: bool) -> None:
        """Feed 0-100 position from an external source (e.g. Simulator).

        Call every frame; set *active=False* when the source is not pointing
        at it.  Mirrors ``OFS_ScriptingMode::SetActivePosition``.
        """
        if active:
            self._rec_active_pos = value
        self._rec_has_pos = active

    def Undo(self) -> None:
        """Revert alternating-mode toggle on undo. Mirrors ``OFS_ScriptingMode::Undo``."""
        if self.mode == ScriptingModeEnum.ALTERNATING and not self._alt_context_sensitive:
            self._alt_next_inverted = not self._alt_next_inverted

    def Redo(self) -> None:
        """Re-apply alternating-mode toggle on redo. Mirrors ``OFS_ScriptingMode::Redo``."""
        if self.mode == ScriptingModeEnum.ALTERNATING and not self._alt_context_sensitive:
            self._alt_next_inverted = not self._alt_next_inverted

    # ----------------------------------------------------------------------
    # Update
    # ----------------------------------------------------------------------

    def Update(self) -> None:
        """Per-frame update (drives recording mode). Mirrors ``OFS_ScriptingMode::Update``."""
        if self.mode == ScriptingModeEnum.RECORDING:
            self._update_recording()

    def _update_recording(self) -> None:
        s = self._active()
        if not s or not self._player:
            return
        if not self._recording or self._player.IsPaused():
            return
        if not self._rec_has_pos:
            return

        t = self._current_time()

        if self._rec_type == 0:  # HoldSample  --  continuous at _rec_interval_s
            if abs(t - self._rec_last_at) < self._rec_interval_s:
                return

        # FrameByFrame: same as HoldSample but interval = 1 frame
        # (both end up here; difference is only in interval)
        at_ms = int(t * 1000) + self._action_delay_ms
        if at_ms <= 0:
            return
        pos = max(0, min(100, int(round(self._rec_active_pos))))
        new_act = FunscriptAction(at_ms, pos)

        existing = s.GetActionAtTime(t, self._player.FrameTime() * 0.5)
        if existing is None:
            if self._undo:
                self._undo.Snapshot(StateType.ADD_ACTION, s)
            s.AddAction(new_act)
        elif existing.pos != pos:
            if self._undo:
                self._undo.Snapshot(StateType.MOVE_ACTION, s)
            s.EditAction(existing, FunscriptAction(existing.at, pos))

        self._rec_last_at = t

    # ----------------------------------------------------------------------
    # Show
    # ----------------------------------------------------------------------

    def Show(self, player: OFS_Videoplayer) -> None:
        """Render the scripting-mode panel. Mirrors ``OFS_ScriptingMode::ShowScriptingMode``."""
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
        elif self.mode == ScriptingModeEnum.DYNAMIC:
            self._show_dynamic()

        # -- Overlay mode --------------------------------------------------
        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        overlays = ["Frame", "Tempo", "Empty"]
        cur_ov = int(self.overlay_mode)
        imgui.set_next_item_width(-1)
        ov_changed, new_ov = imgui.combo("##overlay", cur_ov, overlays)
        if ov_changed:
            self.overlay_mode = OverlayModeEnum(new_ov)
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Timeline overlay:\n"
                "  Frame - vertical frame-tick lines\n"
                "  Tempo - BPM beat grid\n"
                "  Empty - no grid"
            )

        if self.overlay_mode == OverlayModeEnum.FRAME:
            self._show_frame_settings(player)
        elif self.overlay_mode == OverlayModeEnum.TEMPO:
            self._show_tempo_settings()

        # -- Global action offset ms ---------------------------------------
        imgui.spacing()
        imgui.separator()
        imgui.spacing()
        imgui.set_next_item_width(-1)
        changed_d, delay = imgui.drag_int(
            "Offset ms##gdelay", self._action_delay_ms, 1.0, -500, 500)
        if changed_d:
            self._action_delay_ms = max(-500, min(500, delay))
        if imgui.is_item_hovered():
            imgui.begin_tooltip()
            imgui.text("Offset (ms) applied to inserted actions when the video is playing.")
            imgui.end_tooltip()

    def _show_normal(self) -> None:
        imgui.text_disabled("Normal mode")
        imgui.spacing()
        _, self._snap_to_frame = imgui.checkbox("Snap to frame", self._snap_to_frame)
        imgui.set_next_item_width(80)
        changed, val = imgui.input_int("Step size", self._step_size, 1, 1)
        if changed:
            self._step_size = max(1, min(60, val))

    def _show_recording(self) -> None:
        # Record / Stop button
        col = ImVec4(0.9, 0.2, 0.2, 1.0) if self._recording else ImVec4(0.2, 0.7, 0.2, 1.0)
        imgui.push_style_color(imgui.Col_.button, col)
        label = fa.ICON_FA_STOP + " Stop" if self._recording else fa.ICON_FA_CIRCLE + " Record"
        if imgui.button(label, ImVec2(-1, 0)):
            self._recording = not self._recording
            self._rec_last_at = -1.0
        imgui.pop_style_color()

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        # Recording type
        types = ["Hold sample (continuous)", "Frame-by-frame"]
        imgui.set_next_item_width(-1)
        changed, self._rec_type = imgui.combo("##rectype", self._rec_type, types)

        if self._rec_type == 0:  # HoldSample: configurable Hz
            imgui.spacing()
            rate = 1.0 / self._rec_interval_s if self._rec_interval_s > 0 else 60.0
            imgui.set_next_item_width(-1)
            c, rate = imgui.slider_float("##rechz", rate, 10.0, 240.0, "%.0f Hz")
            if c:
                self._rec_interval_s = 1.0 / max(1.0, rate)
        else:  # FrameByFrame: use logical frame time
            if self._player and self._player.VideoLoaded():
                self._rec_interval_s = self._player.FrameTime()

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        # Status indicator
        if self._recording:
            if self._rec_has_pos:
                imgui.push_style_color(imgui.Col_.text, ImVec4(0.3, 1.0, 0.3, 1.0))
                imgui.text(f"Pos: {self._rec_active_pos:.0f}")
            else:
                imgui.push_style_color(imgui.Col_.text, ImVec4(1.0, 0.7, 0.2, 1.0))
                imgui.text("Waiting for position input...")
            imgui.pop_style_color()
            imgui.text_disabled("(Move mouse over Simulator window)")
        else:
            imgui.text_disabled("Drag mouse in the Simulator window while recording.")

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

    def _show_dynamic(self) -> None:
        """DynamicInjectionMode UI  --  mirrors DynamicInjectionMode::DrawModeSettings."""
        imgui.text_disabled("Dynamic Injection")
        imgui.spacing()

        # Target speed slider (MinSpeed=50, MaxSpeed=1000)
        imgui.set_next_item_width(-1)
        c, v = imgui.slider_float(
            "##dynspeed", self._dyn_target_speed,
            50.0, 1000.0, "Target speed: %.0f u/s",
            imgui.SliderFlags_.always_clamp,
        )
        if c:
            self._dyn_target_speed = round(max(50.0, min(1000.0, v)))
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Speed (units/second) used to compute the injected midpoint action."
            )

        # Up/Down bias slider
        imgui.set_next_item_width(-1)
        c, v = imgui.slider_float(
            "##dynbias", self._dyn_direction_bias,
            -0.9, 0.9, "Up/Down bias: %.2f",
            imgui.SliderFlags_.always_clamp,
        )
        if c:
            self._dyn_direction_bias = v
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Shifts the injected midpoint earlier (<0) or later (>0)."
            )

        imgui.spacing()

        # Top / Bottom radio buttons
        avail = imgui.get_content_region_avail().x
        imgui.set_next_item_width(avail * 0.5)
        if imgui.radio_button("Top##dyntop",    self._dyn_top_bottom == 1):
            self._dyn_top_bottom = 1
        imgui.same_line()
        if imgui.radio_button("Bottom##dynbot", self._dyn_top_bottom == -1):
            self._dyn_top_bottom = -1

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        _, self._snap_to_frame = imgui.checkbox("Snap to frame##dyn", self._snap_to_frame)
        imgui.set_next_item_width(80)
        changed, val = imgui.input_int("Step size##dyn", self._step_size, 1, 1)
        if changed:
            self._step_size = max(1, min(60, val))

    # ----------------------------------------------------------------------
    # Overlay settings sub-panels
    # ----------------------------------------------------------------------

    def _show_frame_settings(self, player: OFS_Videoplayer) -> None:
        """Frame overlay settings (OFS FrameOverlay::DrawSettings)."""
        imgui.spacing()
        ch, self._frame_fps_override = imgui.checkbox(
            "FPS override##fov", self._frame_fps_override)
        if ch and self._frame_fps_override and player and player.VideoLoaded():
            self._frame_fps_value = player.Fps()
        if self._frame_fps_override:
            imgui.set_next_item_width(-1)
            c, v = imgui.input_float(
                "##fpsov_val", self._frame_fps_value, 1.0, 10.0, "%.2f fps")
            if c:
                self._frame_fps_value = max(1.0, min(300.0, v))
                if player and player.VideoLoaded():
                    # snap playhead to nearest overridden frame
                    ft = 1.0 / self._frame_fps_value
                    t = self._current_time()
                    snapped = round(t / ft) * ft
                    if self._timeline_mgr is not None:
                        self._timeline_mgr.Seek(snapped)
                    else:
                        player.SetPositionExact(snapped, True)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Override the video FPS for frame-stepping")

    def _show_tempo_settings(self) -> None:
        """Tempo overlay settings (OFS TempoOverlay::DrawSettings)."""
        imgui.spacing()
        # BPM input
        c, v = imgui.input_float("BPM##tmpo", self._tempo_bpm, 1.0, 10.0, "%.2f")
        if c:
            self._tempo_bpm = max(1.0, v)
        # Beat offset drag
        imgui.set_next_item_width(-1)
        c2, v2 = imgui.drag_float(
            "Offset##tmpo_off", self._tempo_offset_s,
            0.001, -10.0, 10.0, "%.3f s",
            imgui.SliderFlags_.always_clamp)
        if c2:
            self._tempo_offset_s = v2
        # Subdivision combo (Snap)
        imgui.set_next_item_width(-1)
        ch3, new_idx = imgui.combo("Snap##tmpo_snap",
                                   self._tempo_measure_idx, BEAT_NAMES)
        if ch3:
            self._tempo_measure_idx = new_idx
        # Interval display
        bt = _tempo_beat_time(self._tempo_bpm, self._tempo_measure_idx)
        imgui.text_disabled(f"Interval: {bt * 1000.0:.2f} ms")
