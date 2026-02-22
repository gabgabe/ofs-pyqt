"""
ScriptTimeline — Python port of ScriptTimeline.h / ScriptTimeline.cpp

Custom ImGui DrawList rendering:
  • Action dots (filled circles + connecting lines)
  • Selection rectangle (Ctrl+drag)
  • Click to seek
  • Left-click on action → select / move
  • Multi-track display (one lane per loaded funscript)
  • Waveform-style background heat gradient (optional)
  • Middle mouse drag → scroll timeline
  • Scroll wheel → zoom timeline
"""

from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript, FunscriptAction
from src.core.events       import EV, OFS_Events
from src.core.tempo        import BEAT_MULTIPLES, BEAT_COLORS_RGBA


def _col32(r: float, g: float, b: float, a: float = 1.0) -> int:
    """Pack floats (0‥1) into Dear ImGui IM_COL32 ABGR integer — no context needed."""
    return (int(a * 255) << 24) | (int(b * 255) << 16) | (int(g * 255) << 8) | int(r * 255)


# ── Colours ───────────────────────────────────────────────────────────────
COL_TIMELINE_BG     = _col32(0.10, 0.10, 0.10, 1.00)
COL_CURSOR          = _col32(1.00, 1.00, 1.00, 0.90)
COL_ACTION          = _col32(0.30, 0.70, 0.30, 1.00)
COL_ACTION_SEL      = _col32(0.02, 0.99, 0.01, 1.00)  # Green for selected (OFS: 11,252,3)
COL_ACTION_LINE     = _col32(0.30, 0.70, 0.30, 0.50)
COL_SEL_RECT        = _col32(0.01, 0.99, 0.81, 0.39)  # Cyan (OFS: 3,252,207,100)
COL_SEL_RECT_BORDER = _col32(0.01, 0.99, 0.81, 0.90)
COL_INACTIVE_TRACK  = _col32(0.50, 0.50, 0.50, 0.60)
COL_INACTIVE_LINE   = _col32(0.50, 0.50, 0.50, 0.30)
COL_CURSOR_SHADOW   = _col32(0.00, 0.00, 0.00, 0.50)

# Speed-based line colors (OFS: High=red, Mid=yellow, Low=orange)
COL_HIGH_SPEED      = _col32(0.89, 0.26, 0.20, 1.00)  # IM_COL32(0xE3, 0x42, 0x34)
COL_MID_SPEED       = _col32(0.91, 0.84, 0.35, 1.00)  # IM_COL32(0xE8, 0xD7, 0x5A)
COL_LOW_SPEED       = _col32(0.97, 0.40, 0.22, 1.00)  # IM_COL32(0xF7, 0x65, 0x38)

# Height guide lines
COL_HEIGHT_GUIDE    = _col32(0.30, 0.30, 0.30, 0.50)

DOT_RADIUS          = 4.0
DOT_RADIUS_SEL      = 5.5
LINE_THICKNESS      = 3.0
MAX_DOT_RADIUS      = 7.0

# Default visible time window (seconds)
DEFAULT_VISIBLE_SECS = 5.0

# ── Tempo overlay beat colors — built from shared BEAT_COLORS_RGBA ────────────
_TEMPO_BEAT_COLORS = [_col32(*c) for c in BEAT_COLORS_RGBA]


class ScriptTimeline:
    """
    One horizontal timeline that can show multiple funscript tracks.
    Mirrors C++ ScriptTimeline.
    """

    WindowId = "Timeline###ScriptTimeline"

    def __init__(self) -> None:
        # Viewport
        self._visible_secs: float        = DEFAULT_VISIBLE_SECS
        self._target_visible_secs: float = DEFAULT_VISIBLE_SECS  # OFS: nextVisibleTime
        self._prev_visible_secs: float   = DEFAULT_VISIBLE_SECS  # OFS: previousVisibleTime
        self._zoom_time: float           = 0.0                   # monotonic sec of last zoom
        self._scroll_offset: float = 0.0  # seconds offset (for non-following mode)

        # Cached draw_map (list of enabled script indices) — rebuilt each Show()
        self._draw_map: List[int] = []

        # Selection state (mirrors OFS: IsSelecting, absSel1, relSel2)
        self._is_selecting: bool = False
        self._abs_sel1: float = 0.0       # absolute time at selection start
        self._rel_sel2: float = 0.0       # 0..1 relative canvas position of sel end

        # Action drag state (mirrors OFS: IsMovingIdx)
        self._drag_action_ref: Optional[FunscriptAction] = None
        self._drag_script_idx: int = 0
        self._drag_started: bool = False  # True after first move-event fired

        # Context menu: which track was right-clicked
        self._ctx_track_idx: int = 0

        # Playhead scrub drag (clicking/dragging the top ruler zone)
        self._scrubbing: bool = False
        self._scrub_was_paused: bool = True

        # Follow playback cursor
        self.follow_cursor: bool = True

        # Waveform overlay (set externally by app; loaded async)
        self.waveform = None          # WaveformData | None
        self.show_waveform: bool = False

        # Rendering options (mirrors OFS BaseOverlay)
        self.show_action_lines: bool = True
        self.show_action_points: bool = True
        self.spline_mode: bool = False  # False=linear, True=spline

        # #7 SyncLineEnable — draw a coloured vertical line at the current time
        # in addition to the white playhead (useful for recording sync)
        self.sync_line_enable: bool = False
        self.sync_line_color: tuple = (1.0, 0.2, 0.2, 0.8)  # RGBA 0-1

        # #6 MaxSpeedHighlight — overlay red highlight for very-fast segments
        self.show_max_speed_highlight: bool = True
        self.max_speed_color: tuple = (0.89, 0.10, 0.10, 0.55)  # RGBA 0-1
        self.max_speed_threshold: float = 500.0  # units/s

        # #3 ScaleAudio — amplitude multiplier for waveform drawing
        self.waveform_scale: float = 1.0

        # #4 WaveformColor tint (RGBA 0-1)
        self.waveform_color: tuple = (227/255, 66/255, 52/255, 0.42)

        # ── Overlay mode params (synced from ScriptingMode each frame) ────
        # 0=FRAME, 1=TEMPO, 2=EMPTY
        self.overlay_mode: int   = 0
        # Frame overlay
        self.overlay_fps: float  = 30.0   # effective fps (after possible override)
        # Tempo overlay
        self.overlay_bpm: float              = 120.0
        self.overlay_tempo_offset_s: float   = 0.0
        self.overlay_tempo_measure_idx: int  = 0
        # Cached window rect
        self._win_pos: ImVec2 = ImVec2(0, 0)
        self._win_size: ImVec2 = ImVec2(0, 0)

    # ──────────────────────────────────────────────────────────────────────

    def Init(self) -> None:
        """Initialise the timeline. Mirrors ``ScriptTimeline::Init``."""
        pass

    def Update(self) -> None:
        """Animate visible-time zoom towards target (OFS: easeOutExpo lerp, 150 ms)."""
        elapsed = _time.monotonic() - self._zoom_time
        t = min(1.0, elapsed / 0.15)  # 150 ms transition
        # easeOutExpo: x>=1 → 1, else 1 - 2^(-10x)
        t_eased = 1.0 if t >= 1.0 else 1.0 - (2.0 ** (-10.0 * t))
        self._visible_secs = (
            self._prev_visible_secs
            + (self._target_visible_secs - self._prev_visible_secs) * t_eased
        )

    # ──────────────────────────────────────────────────────────────────────
    # Main render
    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player:     OFS_Videoplayer,
        scripts:    List[Funscript],
        active_idx: int,
    ) -> None:
        """
        Called inside the dockable window (begin/end handled by hello_imgui).
        Mirrors OFS ShowScriptPositions() closely.
        """
        avail = imgui.get_content_region_avail()
        if avail.x <= 4 or avail.y <= 4:
            return

        io      = imgui.get_io()
        mouse   = io.mouse_pos
        duration = player.Duration() if player.VideoLoaded() else 0.0
        current  = player.CurrentTime() if player.VideoLoaded() else 0.0

        # Build ordered list of enabled script indices (draw map)
        draw_map: List[int] = [i for i, s in enumerate(scripts) if s and s.enabled]
        self._draw_map = draw_map  # cache for use in _handle_interaction
        n_tracks = max(1, len(draw_map))
        self._track_h = avail.y / n_tracks

        dl      = imgui.get_window_draw_list()
        win_pos = imgui.get_cursor_screen_pos()
        self._win_pos  = win_pos
        self._win_size = avail

        # Compute visible time range (centred on playhead in follow mode)
        if self.follow_cursor and player.VideoLoaded():
            half    = self._visible_secs * 0.5
            t_start = current - half
            t_end   = current + half
        else:
            t_start = self._scroll_offset
            t_end   = self._scroll_offset + self._visible_secs

        # ── Hovered track (computed BEFORE drawing so _draw_track can use it) ──
        is_win_hovered = imgui.is_window_hovered()
        hovered_script_idx = -1
        if is_win_hovered and self._track_h > 0:
            draw_slot = int((mouse.y - win_pos.y) / self._track_h)
            draw_slot = max(0, min(n_tracks - 1, draw_slot))
            if draw_slot < len(draw_map):
                hovered_script_idx = draw_map[draw_slot]

        # ── Global timeline background ─────────────────────────────────────────
        dl.add_rect_filled(
            win_pos,
            ImVec2(win_pos.x + avail.x, win_pos.y + avail.y),
            COL_TIMELINE_BG,
        )

        # ── Draw each enabled track ────────────────────────────────────────────
        for draw_slot, script_idx in enumerate(draw_map):
            script    = scripts[script_idx]
            track_y   = win_pos.y + draw_slot * self._track_h
            is_active  = (script_idx == active_idx)
            is_hovered = (script_idx == hovered_script_idx)

            self._draw_track(
                dl, script, script_idx, is_active, is_hovered,
                win_pos.x, track_y, avail.x, self._track_h,
                t_start, t_end, duration,
            )

            # ── Playhead per track: triangle marker + thick vertical line ──
            if player.VideoLoaded() and duration > 0:
                cx = self._time_to_x(current, win_pos.x, avail.x, t_start, t_end)
                fs = imgui.get_font_size()
                dl.add_triangle_filled(
                    ImVec2(cx - fs,       track_y),
                    ImVec2(cx + fs,       track_y),
                    ImVec2(cx,            track_y + fs / 1.5),
                    _col32(1.0, 1.0, 1.0, 1.0),
                )
                dl.add_line(
                    ImVec2(cx - 0.5, track_y),
                    ImVec2(cx - 0.5, track_y + self._track_h - 1.0),
                    _col32(1.0, 1.0, 1.0, 1.0), 4.0,
                )

            # ── SyncLine — optional coloured vertical line at current time ───
            if self.sync_line_enable and player.VideoLoaded() and duration > 0:
                cx_s = self._time_to_x(current, win_pos.x, avail.x, t_start, t_end)
                sl_col = _col32(*self.sync_line_color)
                dl.add_line(
                    ImVec2(cx_s, track_y),
                    ImVec2(cx_s, track_y + self._track_h),
                    sl_col, 2.5,
                )

            # ── Selection box — only on active track (OFS behaviour) ──────────
            if self._is_selecting and is_active:
                vt = t_end - t_start
                rel_sel1 = ((self._abs_sel1 - t_start) / vt) if vt > 0 else 0.0
                x1 = win_pos.x + avail.x * rel_sel1
                x2 = win_pos.x + avail.x * self._rel_sel2
                mn_x, mx_x = min(x1, x2), max(x1, x2)
                dl.add_rect_filled(
                    ImVec2(mn_x, track_y),
                    ImVec2(mx_x, track_y + self._track_h),
                    COL_SEL_RECT,
                )
                dl.add_line(ImVec2(x1, track_y), ImVec2(x1, track_y + self._track_h),
                            COL_SEL_RECT_BORDER, 3.0)
                dl.add_line(ImVec2(x2, track_y), ImVec2(x2, track_y + self._track_h),
                            COL_SEL_RECT_BORDER, 3.0)

        # ── "X.XX seconds" zoom indicator ─────────────────────────────────────
        if scripts:
            self._draw_seconds_label(dl, win_pos.x, win_pos.y, avail.y, True)

        # ── Single interaction button covering full timeline area ──────────────
        imgui.set_cursor_screen_pos(win_pos)
        imgui.invisible_button(
            "##timeline", avail,
            imgui.ButtonFlags_.mouse_button_left   |
            imgui.ButtonFlags_.mouse_button_middle |
            imgui.ButtonFlags_.mouse_button_right,
        )
        self._handle_interaction(
            player, scripts, active_idx, hovered_script_idx, draw_map,
            win_pos, avail, t_start, t_end, duration,
        )

        # ── Right-click context menu ───────────────────────────────────────────
        if imgui.begin_popup_context_item("##tlctx"):
            ctx_i      = self._ctx_track_idx
            ctx_script = scripts[ctx_i] if 0 <= ctx_i < len(scripts) else None

            _, self.follow_cursor = imgui.menu_item(
                "Follow playback cursor", "", self.follow_cursor)
            imgui.separator()

            if imgui.begin_menu("Rendering"):
                _, self.show_action_lines  = imgui.menu_item(
                    "Show action lines",  "", self.show_action_lines)
                _, self.show_action_points = imgui.menu_item(
                    "Show action points", "", self.show_action_points)
                _, self.spline_mode        = imgui.menu_item(
                    "Spline mode",        "", self.spline_mode)
                imgui.separator()
                _, self.sync_line_enable   = imgui.menu_item(
                    "Sync line",          "", self.sync_line_enable)
                _, self.show_max_speed_highlight = imgui.menu_item(
                    "Highlight max speed", "", self.show_max_speed_highlight)
                imgui.end_menu()

            if imgui.begin_menu("Scripts"):
                n_enabled = sum(1 for s in scripts if s and s.enabled)
                for j, s in enumerate(scripts):
                    if not s:
                        continue
                    name    = s.title or f"Script {j}"
                    changed, new_val = imgui.menu_item(name, "", s.enabled)
                    if changed:
                        # Don't allow disabling the last enabled track
                        if not new_val and n_enabled <= 1:
                            pass
                        else:
                            s.enabled = new_val
                            n_enabled += (1 if new_val else -1)
                            if not new_val and j == active_idx:
                                # Auto-switch to first remaining enabled track
                                for k, sc in enumerate(scripts):
                                    if sc and sc.enabled:
                                        EV.dispatch(
                                            OFS_Events.CHANGE_ACTIVE_SCRIPT, idx=k)
                                        break
                imgui.end_menu()
            imgui.end_popup()

    # ──────────────────────────────────────────────────────────────────────
    # Track drawing
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_speed_color(action_curr: FunscriptAction, action_prev: FunscriptAction) -> int:
        """Calculate speed-based color (OFS getActionLineColor)."""
        dt = (action_curr.at - action_prev.at) / 1000.0
        if dt <= 0:
            return COL_MID_SPEED
        speed = abs(action_curr.pos - action_prev.pos) / dt  # units/sec
        # OFS thresholds: >400 = high, 150-400 = mid, <150 = low
        if speed > 400:
            return COL_HIGH_SPEED
        elif speed > 150:
            return COL_MID_SPEED
        else:
            return COL_LOW_SPEED

    def _draw_height_lines(self, dl, x: float, y: float, w: float, h: float) -> None:
        """Draw horizontal guide lines at 0%, 25%, 50%, 75%, 100%."""
        for pct in [0, 25, 50, 75, 100]:
            line_y = y + h - (pct / 100.0) * h
            dl.add_line(
                ImVec2(x, line_y), ImVec2(x + w, line_y),
                COL_HEIGHT_GUIDE, 1.0
            )

    def _draw_frame_overlay_grid(
        self, dl,
        x: float, y: float, w: float, h: float,
        t_start: float, t_end: float,
        fps: float,
    ) -> None:
        """Draw vertical frame-tick lines on a track (mirrors OFS FrameOverlay).

        Two passes:
          1. Thin grey lines every frame (fade in as user zooms in).
          2. Thicker lines every round(fps * 0.1) frames (time dividers).
        """
        visible_time = t_end - t_start
        if visible_time <= 0 or fps <= 0:
            return
        frame_time = 1.0 / fps

        # ── 1. Per-frame tick lines ───────────────────────────────────────
        MAX_VISIBLE = 400.0
        visible_frames = visible_time / frame_time
        if visible_frames < MAX_VISIBLE * 0.75:
            alpha = int(255 * (1.0 - visible_frames / MAX_VISIBLE))
            col = _col32(80 / 255, 80 / 255, 80 / 255, alpha / 255)
            offset = -math.fmod(t_start, frame_time)
            line_count = int(visible_frames) + 2
            for i in range(line_count):
                rx = ((offset + i * frame_time) / visible_time) * w
                if -3 < rx < w + 3:
                    px = x + rx
                    dl.add_line(ImVec2(px, y), ImVec2(px, y + h), col, 1.0)

        # ── 2. Time divider lines (every N frames) ────────────────────────
        MAX_DIVIDERS = 150.0
        n_frames_div = max(1, round(fps * 0.1))
        time_interval = n_frames_div * frame_time
        visible_intervals = visible_time / time_interval if time_interval > 0 else 999.0
        if visible_intervals < MAX_DIVIDERS * 0.8:
            alpha = int(255 * (1.0 - visible_intervals / MAX_DIVIDERS))
            col2 = _col32(80 / 255, 80 / 255, 80 / 255, alpha / 255)
            offset2 = -math.fmod(t_start, time_interval)
            line_count2 = int(visible_intervals) + 2
            for i in range(line_count2):
                rx = ((offset2 + i * time_interval) / visible_time) * w
                if -3 < rx < w + 3:
                    px = x + rx
                    dl.add_line(ImVec2(px, y), ImVec2(px, y + h), col2, 3.0)

    def _draw_tempo_overlay_grid(
        self, dl,
        x: float, y: float, w: float, h: float,
        t_start: float, t_end: float,
        bpm: float, beat_offset_s: float, measure_idx: int,
    ) -> None:
        """Draw BPM-grid beat lines on a track (mirrors OFS TempoOverlay)."""
        visible_time = t_end - t_start
        if visible_time <= 0 or bpm <= 0:
            return
        beat_time = (60.0 / bpm) * BEAT_MULTIPLES[measure_idx]
        if beat_time <= 0:
            return

        beat_color = _TEMPO_BEAT_COLORS[measure_idx]
        white_60   = _col32(1.0, 1.0, 1.0, 0.60)

        visible_beats = int(visible_time / beat_time)
        invisible_prev_beats = int(t_start / beat_time) if beat_time > 0 else 0
        offset = -math.fmod(t_start, beat_time) + beat_offset_s
        line_count = visible_beats + 2

        # "thing" = subdivisions per whole measure at this measure_idx
        thing = max(1, int(round(1.0 / (BEAT_MULTIPLES[measure_idx] / 4.0))))

        for i in range(-int(beat_offset_s / beat_time), line_count):
            beat_idx = invisible_prev_beats + i
            is_whole = (beat_idx % thing == 0)
            rx = ((offset + i * beat_time) / visible_time) * w
            if -5 < rx < w + 5:
                px = x + rx
                col  = beat_color if is_whole else white_60
                thk  = 5.0 if is_whole else 3.0
                dl.add_line(ImVec2(px, y), ImVec2(px, y + h), col, thk)
                # Draw measure number for whole-measure lines
                if is_whole:
                    measure_num = beat_idx // thing if thing > 0 else beat_idx
                    dl.add_text(
                        ImVec2(px + 3, y + 2),
                        _col32(0.9, 0.9, 0.9, 0.8),
                        str(measure_num),
                    )


    def _draw_seconds_label(self, dl, x: float, y: float, h: float, is_last_track: bool) -> None:
        """Draw 'X.XX seconds' label at bottom left (only on last track)."""
        if not is_last_track:
            return
        label = f"{self._visible_secs:.2f} seconds"
        text_size = imgui.calc_text_size(label)
        dl.add_text(
            ImVec2(x + 4, y + h - text_size.y - 4),
            _col32(0.7, 0.7, 0.7, 1.0),
            label
        )

    def _draw_track(
        self, dl,
        script: Funscript,
        track_idx: int,
        is_active: bool,
        is_hovered: bool,
        x: float, y: float, w: float, h: float,
        t_start: float, t_end: float,
        duration: float,
    ) -> None:
        # ── OFS-style gradient background ─────────────────────────────────
        # Active:   purple top  (60,0,60)  → darker bottom (24,0,24)
        # Inactive: dark-blue top (0,0,50) → darker bottom (0,0,20)
        if is_active:
            col_top    = _col32(60/255,  0,       60/255,  1.0)
            col_bottom = _col32(24/255,  0,       24/255,  1.0)
        else:
            col_top    = _col32(0,       0,       50/255,  1.0)
            col_bottom = _col32(0,       0,       20/255,  1.0)
        dl.add_rect_filled_multi_color(
            ImVec2(x, y), ImVec2(x + w, y + h),
            col_top, col_top, col_bottom, col_bottom,
        )

        # ── Hover highlight (OFS: IM_COL32(255,255,255,10)) ───────────────
        if is_hovered:
            dl.add_rect_filled(
                ImVec2(x, y), ImVec2(x + w, y + h),
                _col32(1.0, 1.0, 1.0, 10 / 255),
            )

        # ── Per-track clip rect ────────────────────────────────────────────
        dl.push_clip_rect(
            ImVec2(x - 3, y - 3), ImVec2(x + w + 3, y + h + 3), True
        )

        # Draw height guide lines (0%, 25%, 50%, 75%, 100%)
        self._draw_height_lines(dl, x, y, w, h)

        # ── Overlay grid (Frame or Tempo) ─────────────────────────────────
        if self.overlay_mode == 0:   # FRAME
            self._draw_frame_overlay_grid(
                dl, x, y, w, h, t_start, t_end, self.overlay_fps)
        elif self.overlay_mode == 1:  # TEMPO
            self._draw_tempo_overlay_grid(
                dl, x, y, w, h, t_start, t_end,
                self.overlay_bpm, self.overlay_tempo_offset_s,
                self.overlay_tempo_measure_idx)

        # Track title (small label)
        title = script.title or f"Script {track_idx}"
        dl.add_text(
            ImVec2(x + 4, y + 2),
            _col32(0.8, 0.8, 0.8, 0.7 if is_active else 0.4),
            title[:20],
        )

        # ── Waveform overlay (behind action lines) ────────────────────────
        if self.show_waveform and self.waveform is not None and self.waveform.ready:
            _WV_H_SCALE = 0.72      # max fraction of track height used by wave
            wv_col = _col32(*self.waveform_color)
            cy = y + h * 0.5        # centre line of track
            n_cols = max(1, int(w))
            t_range = t_end - t_start
            if t_range > 0:
                inv_cols = t_range / n_cols
                col = 0
                while col < n_cols:
                    t0 = t_start + col * inv_cols
                    t1 = t0 + inv_cols * 2          # 2-px chunks
                    amp = self.waveform.get_max_in_range(t0, t1)
                    if amp > 0.01:
                        half_h = amp * min(2.0, max(0.05, self.waveform_scale)) * h * _WV_H_SCALE * 0.5
                        dl.add_rect_filled(
                            ImVec2(x + col, cy - half_h),
                            ImVec2(x + col + 2, cy + half_h),
                            wv_col,
                        )
                    col += 2

        # Find visible actions (dots only — strictly within the viewport)
        actions = script.actions.GetActionsInRange(
            int(t_start * 1000), int(t_end * 1000)
        )

        # For line drawing we also need the action immediately before t_start
        # and the action immediately after t_end so that lines crossing the
        # viewport boundary are rendered correctly (fixes missing-line bug).
        prev_edge = script.actions.GetPreviousActionBehind(t_start)
        next_edge = script.actions.GetNextActionAhead(t_end)
        line_actions = (
            ([prev_edge] if prev_edge is not None else [])
            + list(actions)
            + ([next_edge] if next_edge is not None else [])
        )

        # ── Draw connecting lines (with speed-based coloring) ────────────
        if self.show_action_lines and len(line_actions) > 1:
            if self.spline_mode and len(line_actions) >= 2:
                # Spline: subdivide each segment into N steps for smooth curve
                SUBDIVS = 8
                prev_action = None
                for a in line_actions:
                    if prev_action is not None:
                        seg_t0 = prev_action.at / 1000.0
                        seg_t1 = a.at / 1000.0
                        if is_active:
                            col_line = self._get_speed_color(a, prev_action)
                        else:
                            col_line = COL_INACTIVE_LINE
                        pts = []
                        for j in range(SUBDIVS + 1):
                            frac   = j / SUBDIVS
                            at_ms  = prev_action.at + (a.at - prev_action.at) * frac
                            pos    = script.actions.InterpolateSpline(at_ms)
                            px     = self._time_to_x(at_ms / 1000.0, x, w, t_start, t_end)
                            py     = self._pos_to_y(pos, y, h)
                            pts.append(ImVec2(px, py))
                        for k in range(len(pts) - 1):
                            dl.add_line(pts[k], pts[k+1], _col32(0, 0, 0, 1.0), 7.0)
                            dl.add_line(pts[k], pts[k+1], col_line, LINE_THICKNESS)
                    prev_action = a
            else:
                prev_action = None
                for a in line_actions:
                    if prev_action is not None:
                        p1 = ImVec2(
                            self._time_to_x(prev_action.at / 1000.0, x, w, t_start, t_end),
                            self._pos_to_y(prev_action.pos, y, h)
                        )
                        p2 = ImVec2(
                            self._time_to_x(a.at / 1000.0, x, w, t_start, t_end),
                            self._pos_to_y(a.pos, y, h)
                        )
                        # Black border for depth
                        dl.add_line(p1, p2, _col32(0, 0, 0, 1.0), 7.0)
                        # Speed-based color
                        if is_active:
                            col_line = self._get_speed_color(a, prev_action)
                        else:
                            col_line = COL_INACTIVE_LINE
                        dl.add_line(p1, p2, col_line, LINE_THICKNESS)

                        # Highlight selected segments
                        if is_active and (prev_action in script.selection) and (a in script.selection):
                            dl.add_line(p1, p2, COL_SEL_RECT_BORDER, LINE_THICKNESS)
                    prev_action = a

        # ── Draw action points (with dynamic size based on zoom) ─────────
        if self.show_action_points:
            # Dynamic size: zoom in → bigger dots
            opacity = min(1.0, 20.0 / max(1.0, self._visible_secs))
            opacity = opacity * opacity  # easing
            if opacity >= 0.25:
                point_size = DOT_RADIUS + (MAX_DOT_RADIUS - DOT_RADIUS) * opacity
                opacity_int = int(255 * opacity)
                
                for a in actions:
                    ax = self._time_to_x(a.at / 1000.0, x, w, t_start, t_end)
                    ay = self._pos_to_y(a.pos, y, h)
                    sc = ImVec2(ax, ay)
                    
                    selected = is_active and (a in script.selection)
                    
                    # Black border
                    dl.add_circle_filled(sc, point_size, _col32(0, 0, 0, opacity), 4)
                    # Inner circle
                    if selected:
                        dl.add_circle_filled(sc, point_size * 0.7, COL_ACTION_SEL, 4)
                    else:
                        col_inner = COL_ACTION if is_active else COL_INACTIVE_TRACK
                        dl.add_circle_filled(sc, point_size * 0.7, col_inner, 4)
        # ── MaxSpeedHighlight — red overlay on very-fast segments ───────────────
        if self.show_max_speed_highlight and is_active:
            ms_col = _col32(*self.max_speed_color)
            for a1, a2 in zip(list(line_actions), list(line_actions)[1:]):
                dt = (a2.at - a1.at) / 1000.0
                if dt <= 0:
                    continue
                speed = abs(a2.pos - a1.pos) / dt
                if speed >= self.max_speed_threshold:
                    x1m = self._time_to_x(a1.at / 1000.0, x, w, t_start, t_end)
                    x2m = self._time_to_x(a2.at / 1000.0, x, w, t_start, t_end)
                    dl.add_rect_filled(
                        ImVec2(x1m, y), ImVec2(x2m, y + h), ms_col)
        # ── Pop clip rect before drawing border ───────────────────────────
        dl.pop_clip_rect()

        # ── Per-track border (OFS: green=active, slider-grab=has-sel, white=default)
        if is_active:
            border_col = _col32(0,       180/255, 0,       1.0)  # OFS: (0,180,0)
        elif script.HasSelection():
            border_col = _col32(0.37,    0.44,    0.74,    1.0)  # ImGuiCol_SliderGrabActive
        else:
            border_col = _col32(1.0,     1.0,     1.0,     1.0)  # white
        dl.add_rect(
            ImVec2(x - 2,     y - 2),
            ImVec2(x + w + 2, y + h + 2),
            border_col, 0.0, 0, 1.0,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Interaction handling
    # ──────────────────────────────────────────────────────────────────────

    def _handle_interaction(
        self,
        player:             OFS_Videoplayer,
        scripts:            List[Funscript],
        active_idx:         int,
        hovered_script_idx: int,
        draw_map:           List[int],
        win_pos:  ImVec2, avail: ImVec2,
        t_start:  float,  t_end: float, duration: float,
    ) -> None:
        io             = imgui.get_io()
        mouse          = io.mouse_pos
        is_item_hovered = imgui.is_item_hovered()
        is_item_active  = imgui.is_item_active()

        active_script = scripts[active_idx] if 0 <= active_idx < len(scripts) else None

        # ── Scroll wheel → zoom (OFS: mouseScroll, scrollPercent=0.10) ────────
        if is_item_hovered and io.mouse_wheel != 0.0:
            factor = 1.0 + 0.10 * (-io.mouse_wheel)
            self._prev_visible_secs   = self._visible_secs
            self._target_visible_secs = max(
                0.5, min(300.0, self._target_visible_secs * factor))
            self._zoom_time = _time.monotonic()

        # ── Playhead scrub: click/drag on the top triangle ruler zone ─────────
        RULER_H = imgui.get_font_size() * 1.5
        in_ruler = (win_pos.y <= mouse.y <= win_pos.y + RULER_H)

        if is_item_hovered and in_ruler and imgui.is_mouse_clicked(0):
            self._scrubbing = True
            self._scrub_was_paused = player.IsPaused()
            if not player.IsPaused():
                player.SetPaused(True)

        if self._scrubbing:
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)
            if is_item_active and imgui.is_mouse_down(0):
                seek_t = self._x_to_time(mouse.x, win_pos.x, avail.x, t_start, t_end)
                seek_t = max(0.0, min(duration, seek_t))
                if player.VideoLoaded():
                    player.SetPositionExact(seek_t)
                    if player.IsPaused():
                        player.Update(0.0)
            if imgui.is_mouse_released(0):
                self._scrubbing = False
                if not self._scrub_was_paused:
                    player.SetPaused(False)

        # ── Mouse cursor: Hand when hovering over an action dot ────────────────
        if is_item_hovered and not self._is_selecting and self._drag_action_ref is None and not self._scrubbing:
            hit_cur, _, _ = self._find_action_at_mouse(
                mouse, win_pos, avail, scripts, active_idx, draw_map, t_start, t_end
            )
            if hit_cur is not None:
                imgui.set_mouse_cursor(imgui.MouseCursor_.hand)

        # ── Middle drag → pan timeline (non-follow) ────────────────────────────
        if is_item_active and imgui.is_mouse_dragging(2, 1.0):
            secs_per_px = (t_end - t_start) / avail.x if avail.x > 0 else 0
            self._scroll_offset = max(
                0.0, self._scroll_offset - io.mouse_delta.x * secs_per_px
            )
            self.follow_cursor = False

        # ── Middle double-click → clear active script selection ────────────────
        if is_item_hovered and imgui.is_mouse_double_clicked(2) and active_script:
            active_script.ClearSelection()

        # ── Store right-clicked track for context menu ─────────────────────────
        if imgui.is_mouse_clicked(1) and is_item_hovered:
            self._ctx_track_idx = (
                hovered_script_idx if hovered_script_idx >= 0 else active_idx
            )

        # ── Selection auto-scroll (OFS: handleSelectionScrolling, margin=3%) ───
        if self._is_selecting:
            margin      = 0.03
            scroll_spd  = 80.0
            if self._rel_sel2 < margin or self._rel_sel2 > (1.0 - margin):
                rel_seek = (
                    -(margin - self._rel_sel2)
                    if self._rel_sel2 < margin
                    else self._rel_sel2 - (1.0 - margin)
                )
                rel_seek *= io.delta_time * scroll_spd
                seek_t = max(0.0, t_start + self._visible_secs * 0.5
                             + self._visible_secs * rel_seek)
                if player.VideoLoaded():
                    player.SetPositionExact(seek_t)
                    if player.IsPaused():
                        player.Update(0.0)

        # ── Finalise selection on mouse release (OFS: IsMouseReleased check) ───
        if self._is_selecting and imgui.is_mouse_released(0):
            self._is_selecting = False
            if active_script:
                vt       = t_end - t_start
                rel1     = (self._abs_sel1 - t_start) / vt if vt > 0 else 0.0
                mn_rel   = min(rel1, self._rel_sel2)
                mx_rel   = max(rel1, self._rel_sel2)
                start_t  = t_start + vt * mn_rel
                end_t    = t_start + vt * mx_rel
                if (end_t - start_t) > 0.008:   # OFS 8 ms threshold
                    if not io.key_ctrl:          # Ctrl = add to existing selection
                        active_script.ClearSelection()
                    active_script.SelectTime(start_t, end_t)

        # ── Clean up drag state when button released ───────────────────────────
        if not is_item_active and not self._is_selecting:
            self._drag_action_ref = None
            self._drag_started    = False
            return

        if not is_item_active:
            return

        # ── Per-frame helpers ──────────────────────────────────────────────────
        click_time   = self._x_to_time(mouse.x, win_pos.x, avail.x, t_start, t_end)
        click_time   = max(0.0, min(duration, click_time))
        # Modifier: Shift = add/move action (mirrors OFS ImGuiMod_Shift)
        shift_held   = io.key_shift

        # ── handleTimelineClicks (mirrors OFS exactly) ─────────────────────────
        # Skip if scrubbing — playhead drag already consumed the click
        if self._scrubbing:
            return

        if imgui.is_mouse_clicked(0):
            # Priority 1: action hit-test — OFS only checks the active script
            hit_action, hit_script, hit_idx = self._find_action_at_mouse(
                mouse, win_pos, avail, scripts, active_idx, draw_map, t_start, t_end
            )

            if shift_held:
                if hit_action is not None:
                    # Shift+click on dot → begin drag
                    hit_script.ClearSelection()
                    hit_script.SelectAction(hit_action)
                    self._drag_action_ref = hit_action
                    self._drag_script_idx = hit_idx
                    self._drag_started    = False
                else:
                    # Shift+click on empty → create action at cursor
                    ty      = self._get_track_y(scripts, draw_map, active_idx, win_pos.y)
                    pos     = self._y_to_pos(mouse.y, ty, self._track_h)
                    new_act = FunscriptAction(int(click_time * 1000),
                                             max(0, min(100, pos)))
                    if active_script:
                        EV.dispatch(OFS_Events.ACTION_SHOULD_CREATE,
                                    action=new_act, script=active_script)

            elif hit_action is not None:
                # Plain click on action dot → seek / select
                EV.dispatch(OFS_Events.ACTION_CLICKED,
                            action=hit_action, script=hit_script)
                self._drag_action_ref = None

            elif imgui.is_mouse_double_clicked(0):
                # Double-click on empty → seek (OFS priority 3)
                if player.VideoLoaded():
                    player.SetPositionExact(click_time)
                    if player.IsPaused():
                        player.Update(0.0)

            elif hovered_script_idx >= 0 and hovered_script_idx != active_idx:
                # Click on a different track → switch active (OFS priority 5)
                EV.dispatch(OFS_Events.CHANGE_ACTIVE_SCRIPT,
                            idx=hovered_script_idx)

            else:
                # Plain left click on empty space of active track → begin selection
                rel1               = ((mouse.x - win_pos.x) / avail.x
                                      if avail.x > 0 else 0.0)
                self._abs_sel1     = t_start + (t_end - t_start) * rel1
                self._rel_sel2     = rel1
                self._is_selecting = True
                self._drag_action_ref = None

        # ── Drag on action dot → move ──────────────────────────────────────────
        if self._drag_action_ref is not None and imgui.is_mouse_dragging(0, 4.0):
            drag_script = (
                scripts[self._drag_script_idx]
                if 0 <= self._drag_script_idx < len(scripts) else None
            )
            if drag_script:
                ty      = self._get_track_y(
                    scripts, draw_map, self._drag_script_idx, win_pos.y)
                new_pos = self._y_to_pos(mouse.y, ty, self._track_h)
                moved   = FunscriptAction(int(click_time * 1000),
                                         max(0, min(100, new_pos)))
                if not self._drag_started:
                    EV.dispatch(OFS_Events.ACTION_SHOULD_MOVE,
                                action=moved, script=drag_script, move_started=True)
                    self._drag_started = True
                else:
                    EV.dispatch(OFS_Events.ACTION_SHOULD_MOVE,
                                action=moved, script=drag_script, move_started=False)
            return  # don't start selection while dragging dot

        # ── Update selection rel_sel2 during drag (OFS: handleTimelineHover) ───
        if self._is_selecting and imgui.is_mouse_dragging(0, 0.0):
            self._rel_sel2 = max(0.0, min(1.0,
                (mouse.x - win_pos.x) / avail.x if avail.x > 0 else 0.0
            ))

    # ──────────────────────────────────────────────────────────────────────
    # Track geometry helpers
    # ──────────────────────────────────────────────────────────────────────

    def _get_track_y(
        self,
        scripts:    List[Funscript],
        draw_map:   List[int],
        script_idx: int,
        win_top:    float,
    ) -> float:
        """Return the top-Y pixel of the given script's track lane."""
        for draw_slot, idx in enumerate(draw_map):
            if idx == script_idx:
                return win_top + draw_slot * self._track_h
        return win_top

    # ──────────────────────────────────────────────────────────────────────
    # Action hit-testing
    # ──────────────────────────────────────────────────────────────────────

    def _find_action_at_mouse(
        self,
        mouse:      ImVec2,
        win_pos:    ImVec2,
        avail:      ImVec2,
        scripts:    List[Funscript],
        active_idx: int,
        draw_map:   List[int],
        t_start:    float,
        t_end:      float,
    ) -> "tuple[Optional[FunscriptAction], Optional[Funscript], int]":
        """Return (action, script, track_idx) of the dot nearest the cursor.
        Mirrors OFS: only checks the active script (OFS: ctx.activeScriptIdx == ctx.drawingScriptIdx).
        Only attempts when points would be visible (opacity >= 0.25 threshold).
        Returns (None, None, -1) if no hit.
        """
        # OFS: BaseOverlay::PointSize >= 4 threshold (skip when zoomed too far out)
        opacity = min(1.0, 20.0 / max(1.0, self._visible_secs)) ** 2
        if opacity < 0.25:
            return (None, None, -1)

        if not (0 <= active_idx < len(scripts)):
            return (None, None, -1)
        script = scripts[active_idx]
        if not script:
            return (None, None, -1)

        # Find the draw slot Y for the active script
        track_y = self._get_track_y(scripts, draw_map, active_idx, win_pos.y)

        HIT_R     = DOT_RADIUS + 5.0
        best_dist = HIT_R
        best      = (None, None, -1)

        if not (track_y - HIT_R <= mouse.y <= track_y + self._track_h + HIT_R):
            return (None, None, -1)

        PAD = (HIT_R / avail.x * (t_end - t_start)) if avail.x > 0 else 0.0
        for a in script.actions.GetActionsInRange(
            int((t_start - PAD) * 1000), int((t_end + PAD) * 1000)
        ):
            ax = self._time_to_x(a.at / 1000.0, win_pos.x, avail.x, t_start, t_end)
            ay = self._pos_to_y(a.pos, track_y, self._track_h)
            d  = math.hypot(mouse.x - ax, mouse.y - ay)
            if d < best_dist:
                best_dist = d
                best      = (a, script, active_idx)
        return best

    # ──────────────────────────────────────────────────────────────────────
    # Coordinate helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _time_to_x(
        t: float, x_origin: float, width: float,
        t_start: float, t_end: float
    ) -> float:
        if t_end <= t_start:
            return x_origin
        return x_origin + (t - t_start) / (t_end - t_start) * width

    @staticmethod
    def _x_to_time(
        x: float, x_origin: float, width: float,
        t_start: float, t_end: float
    ) -> float:
        if width <= 0:
            return t_start
        return t_start + (x - x_origin) / width * (t_end - t_start)

    @staticmethod
    def _pos_to_y(pos: int, y_origin: float, height: float) -> float:
        """pos 0..100 → y (0=bottom, 100=top)."""
        return y_origin + height - (pos / 100.0) * height

    @staticmethod
    def _y_to_pos(y: float, y_origin: float, height: float) -> int:
        """Reverse of _pos_to_y."""
        if height <= 0:
            return 50
        return int(max(0, min(100, (1.0 - (y - y_origin) / height) * 100)))
