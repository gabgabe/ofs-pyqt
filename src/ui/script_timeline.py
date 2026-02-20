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
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript, FunscriptAction
from src.core.events       import EV, OFS_Events


def _col32(r: float, g: float, b: float, a: float = 1.0) -> int:
    """Pack floats (0‥1) into Dear ImGui IM_COL32 ABGR integer — no context needed."""
    return (int(a * 255) << 24) | (int(b * 255) << 16) | (int(g * 255) << 8) | int(r * 255)


# ── Colours ───────────────────────────────────────────────────────────────
COL_TIMELINE_BG     = _col32(0.10, 0.10, 0.10, 1.00)
COL_CURSOR          = _col32(1.00, 1.00, 1.00, 0.90)
COL_ACTION          = _col32(0.30, 0.70, 0.30, 1.00)
COL_ACTION_SEL      = _col32(0.85, 0.60, 0.10, 1.00)
COL_ACTION_LINE     = _col32(0.30, 0.70, 0.30, 0.50)
COL_SEL_RECT        = _col32(0.85, 0.85, 0.20, 0.30)
COL_SEL_RECT_BORDER = _col32(0.85, 0.85, 0.20, 0.70)
COL_INACTIVE_TRACK  = _col32(0.50, 0.50, 0.50, 0.60)
COL_INACTIVE_LINE   = _col32(0.50, 0.50, 0.50, 0.30)
COL_CURSOR_SHADOW   = _col32(0.00, 0.00, 0.00, 0.50)

DOT_RADIUS          = 4.0
DOT_RADIUS_SEL      = 5.5
LINE_THICKNESS      = 1.5

# Default visible time window (seconds)
DEFAULT_VISIBLE_SECS = 5.0


class ScriptTimeline:
    """
    One horizontal timeline that can show multiple funscript tracks.
    Mirrors C++ ScriptTimeline.
    """

    WindowId = "Timeline###ScriptTimeline"

    def __init__(self) -> None:
        # Viewport
        self._visible_secs: float = DEFAULT_VISIBLE_SECS
        self._scroll_offset: float = 0.0  # seconds offset (for non-following mode)

        # Selection rect state
        self._sel_start: Optional[ImVec2] = None
        self._sel_rect_active: bool = False
        self._sel_rect_min: ImVec2 = ImVec2(0, 0)
        self._sel_rect_max: ImVec2 = ImVec2(0, 0)

        # Drag state for action moving
        self._dragging_action: bool = False
        self._drag_action_ref: Optional[FunscriptAction] = None
        self._drag_script_idx: int = 0
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0
        self._drag_started: bool = False  # True after first move-event fired

        # Follow playback cursor
        self.follow_cursor: bool = True

        # Track heights
        self._track_h: float = 0.0   # computed per frame

        # Cached window rect
        self._win_pos: ImVec2 = ImVec2(0, 0)
        self._win_size: ImVec2 = ImVec2(0, 0)

    # ──────────────────────────────────────────────────────────────────────

    def Init(self) -> None:
        pass

    def Update(self) -> None:
        pass

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
        """
        avail = imgui.get_content_region_avail()
        if avail.x <= 4 or avail.y <= 4:
            return

        n_tracks = max(1, len(scripts))
        self._track_h = avail.y / n_tracks
        duration = player.Duration() if player.VideoLoaded() else 0.0
        current  = player.CurrentTime() if player.VideoLoaded() else 0.0

        dl = imgui.get_window_draw_list()
        win_pos = imgui.get_cursor_screen_pos()
        self._win_pos  = win_pos
        self._win_size = avail

        # Compute visible time range
        if self.follow_cursor and player.VideoLoaded():
            half = self._visible_secs * 0.5
            t_start = current - half
            t_end   = current + half
        else:
            t_start = self._scroll_offset
            t_end   = self._scroll_offset + self._visible_secs

        # Background
        dl.add_rect_filled(
            win_pos,
            ImVec2(win_pos.x + avail.x, win_pos.y + avail.y),
            COL_TIMELINE_BG,
        )

        # Tracks
        for i, script in enumerate(scripts):
            if not script:
                continue
            track_y = win_pos.y + i * self._track_h
            is_active = (i == active_idx)
            self._draw_track(
                dl, script, i, is_active,
                win_pos.x, track_y, avail.x, self._track_h,
                t_start, t_end, duration
            )

        # Current-time cursor line
        if player.VideoLoaded() and duration > 0:
            cx = self._time_to_x(current, win_pos.x, avail.x, t_start, t_end)
            dl.add_line(
                ImVec2(cx, win_pos.y),
                ImVec2(cx, win_pos.y + avail.y),
                COL_CURSOR_SHADOW, 3.0,
            )
            dl.add_line(
                ImVec2(cx, win_pos.y),
                ImVec2(cx, win_pos.y + avail.y),
                COL_CURSOR, 1.5,
            )

        # Selection rectangle overlay
        if self._sel_rect_active:
            dl.add_rect_filled(self._sel_rect_min, self._sel_rect_max, COL_SEL_RECT)
            dl.add_rect(self._sel_rect_min, self._sel_rect_max,
                        COL_SEL_RECT_BORDER, 0.0, 0, 1.0)

        # Interaction (invisible overlay)
        imgui.set_cursor_screen_pos(win_pos)
        imgui.invisible_button(
            "##timeline", avail,
            imgui.ButtonFlags_.mouse_button_left  |
            imgui.ButtonFlags_.mouse_button_middle |
            imgui.ButtonFlags_.mouse_button_right,
        )
        self._handle_interaction(
            player, scripts, active_idx,
            win_pos, avail, t_start, t_end, duration
        )

    # ──────────────────────────────────────────────────────────────────────
    # Track drawing
    # ──────────────────────────────────────────────────────────────────────

    def _draw_track(
        self, dl,
        script: Funscript,
        track_idx: int,
        is_active: bool,
        x: float, y: float, w: float, h: float,
        t_start: float, t_end: float,
        duration: float,
    ) -> None:
        # Track separator line
        if track_idx > 0:
            dl.add_line(
                ImVec2(x, y), ImVec2(x + w, y),
                _col32(0.3, 0.3, 0.3, 0.5), 1.0
            )

        # Track title (small label)
        title = script.title or f"Script {track_idx}"
        dl.add_text(
            ImVec2(x + 4, y + 2),
            _col32(0.8, 0.8, 0.8, 0.7 if is_active else 0.4),
            title[:20],
        )

        col_dot  = COL_ACTION      if is_active else COL_INACTIVE_TRACK
        col_line = COL_ACTION_LINE if is_active else COL_INACTIVE_LINE

        # Find visible actions (add small padding so lines are drawn)
        PAD = 2.0 / w * (t_end - t_start)  # 2px in time-units
        actions = script.actions.get_actions_in_range(
            int((t_start - PAD) * 1000), int((t_end + PAD) * 1000)
        )

        prev_screen: Optional[ImVec2] = None

        for a in actions:
            at_s = a.at / 1000.0
            ax   = self._time_to_x(at_s, x, w, t_start, t_end)
            ay   = self._pos_to_y(a.pos, y, h)

            sc = ImVec2(ax, ay)

            # Connecting line from previous action
            if prev_screen is not None:
                dl.add_line(prev_screen, sc, col_line, LINE_THICKNESS)

            # Dot
            selected  = is_active and (a in script.selection)
            col       = COL_ACTION_SEL if selected else col_dot
            radius    = DOT_RADIUS_SEL if selected else DOT_RADIUS
            dl.add_circle_filled(sc, radius, col)

            prev_screen = sc

    # ──────────────────────────────────────────────────────────────────────
    # Interaction handling
    # ──────────────────────────────────────────────────────────────────────

    def _handle_interaction(
        self,
        player: OFS_Videoplayer,
        scripts: List[Funscript],
        active_idx: int,
        win_pos: ImVec2, avail: ImVec2,
        t_start: float, t_end: float, duration: float,
    ) -> None:
        io = imgui.get_io()
        mouse = io.mouse_pos

        is_hovered = imgui.is_item_hovered()
        is_active  = imgui.is_item_active()

        # ── Scroll wheel → zoom ────────────────────────────────────────
        if is_hovered and io.mouse_wheel != 0.0:
            if io.key_ctrl:
                self._visible_secs = max(
                    0.5,
                    min(60.0, self._visible_secs - io.mouse_wheel * 0.5)
                )
            else:
                if not self.follow_cursor:
                    self._scroll_offset = max(
                        0.0,
                        self._scroll_offset - io.mouse_wheel * self._visible_secs * 0.1
                    )

        # ── Middle drag → scroll (non-follow) ─────────────────────────
        if is_active and imgui.is_mouse_dragging(2, 2.0):
            delta_px = io.mouse_delta.x
            secs_per_px = (t_end - t_start) / avail.x if avail.x > 0 else 0
            self._scroll_offset = max(
                0.0,
                self._scroll_offset - delta_px * secs_per_px
            )
            self.follow_cursor = False

        # ── Right-click → context menu ─────────────────────────────────
        if imgui.begin_popup_context_item("##tlctx"):
            _, self.follow_cursor = imgui.menu_item(
                "Follow playback cursor", "", self.follow_cursor)
            imgui.end_popup()

        # ── Release: clean up drag state ───────────────────────────────
        if not is_active:
            self._sel_rect_active = False
            self._sel_start       = None
            self._dragging_action = False
            self._drag_action_ref = None
            self._drag_started    = False
            return

        # ── Per-frame helpers ──────────────────────────────────────────
        click_time = self._x_to_time(mouse.x, win_pos.x, avail.x, t_start, t_end)
        click_time = max(0.0, min(duration, click_time))

        rel_y         = mouse.y - win_pos.y
        track_clicked = int(rel_y / self._track_h) if self._track_h > 0 else 0
        track_clicked = max(0, min(len(scripts) - 1, track_clicked))
        clicked_script = scripts[track_clicked] if scripts else None

        # ── Mouse button just clicked ──────────────────────────────────
        if imgui.is_mouse_clicked(0):
            hit_action, hit_script, hit_idx = self._find_action_at_mouse(
                mouse, win_pos, avail, scripts, t_start, t_end
            )
            if hit_action is not None:
                # Clicked directly on an action dot → select or seek
                EV.dispatch(OFS_Events.ACTION_CLICKED,
                            action=hit_action, script=hit_script)
                # Prepare potential drag of this dot
                self._drag_action_ref = hit_action
                self._drag_script_idx = hit_idx
                self._dragging_action = False
                self._drag_started    = False
            else:
                # Empty-space click
                self._drag_action_ref = None
                if io.key_ctrl:
                    # Ctrl+click → create action at cursor position
                    track_y = win_pos.y + track_clicked * self._track_h
                    pos     = self._y_to_pos(mouse.y, track_y, self._track_h)
                    pos     = max(0, min(100, pos))
                    new_act = FunscriptAction(int(click_time * 1000), pos)
                    if clicked_script:
                        EV.dispatch(OFS_Events.ACTION_SHOULD_CREATE,
                                    action=new_act, script=clicked_script)
                else:
                    # Plain click → seek to position
                    if player.VideoLoaded():
                        player.SetPositionExact(click_time)
                        if player.IsPaused():
                            player.Update(0.0)
                    self._sel_start = None

        # ── Drag on action dot → move action ──────────────────────────
        if self._drag_action_ref is not None and imgui.is_mouse_dragging(0, 4.0):
            drag_script = (
                scripts[self._drag_script_idx]
                if 0 <= self._drag_script_idx < len(scripts)
                else None
            )
            if drag_script:
                track_y = win_pos.y + self._drag_script_idx * self._track_h
                new_pos = self._y_to_pos(mouse.y, track_y, self._track_h)
                new_pos = max(0, min(100, new_pos))
                moved   = FunscriptAction(int(click_time * 1000), new_pos)
                if not self._drag_started:
                    # First frame: fire snapshot event
                    EV.dispatch(OFS_Events.ACTION_SHOULD_MOVE,
                                action=moved, script=drag_script, move_started=True)
                    self._drag_started    = True
                    self._dragging_action = True
                else:
                    EV.dispatch(OFS_Events.ACTION_SHOULD_MOVE,
                                action=moved, script=drag_script, move_started=False)
            return  # skip selection rect while dragging dot

        # ── Ctrl+drag → selection rectangle ───────────────────────────
        if (imgui.is_mouse_clicked(0) and io.key_ctrl
                and self._drag_action_ref is None):
            self._sel_start = ImVec2(mouse.x, mouse.y)

        if (imgui.is_mouse_dragging(0, 4.0) and io.key_ctrl
                and self._sel_start is not None
                and self._drag_action_ref is None):
            self._sel_rect_active = True
            mx, my = mouse.x, mouse.y
            sx, sy = self._sel_start.x, self._sel_start.y
            self._sel_rect_min = ImVec2(min(mx, sx), min(my, sy))
            self._sel_rect_max = ImVec2(max(mx, sx), max(my, sy))
            if clicked_script:
                t_sel_start = self._x_to_time(
                    self._sel_rect_min.x, win_pos.x, avail.x, t_start, t_end)
                t_sel_end   = self._x_to_time(
                    self._sel_rect_max.x, win_pos.x, avail.x, t_start, t_end)
                clicked_script.select_time(t_sel_start, t_sel_end)

        elif (imgui.is_mouse_dragging(0, 4.0) and not io.key_ctrl
              and self._drag_action_ref is None):
            # Plain drag without dot → scrub video
            if player.VideoLoaded():
                player.SetPositionExact(click_time)

    # ──────────────────────────────────────────────────────────────────────
    # Action hit-testing
    # ──────────────────────────────────────────────────────────────────────

    def _find_action_at_mouse(
        self,
        mouse:   ImVec2,
        win_pos: ImVec2,
        avail:   ImVec2,
        scripts: List[Funscript],
        t_start: float,
        t_end:   float,
    ) -> "tuple[Optional[FunscriptAction], Optional[Funscript], int]":
        """Return (action, script, track_idx) of the dot nearest the cursor,
        or (None, None, -1) if none is within the hit radius."""
        HIT_R     = DOT_RADIUS + 5.0  # slightly generous hit area
        best_dist = HIT_R
        best      = (None, None, -1)
        for idx, script in enumerate(scripts):
            if not script:
                continue
            track_y = win_pos.y + idx * self._track_h
            if not (track_y - HIT_R <= mouse.y <= track_y + self._track_h + HIT_R):
                continue
            PAD = (HIT_R / avail.x * (t_end - t_start)) if avail.x > 0 else 0.0
            for a in script.actions.get_actions_in_range(
                int((t_start - PAD) * 1000), int((t_end + PAD) * 1000)
            ):
                ax = self._time_to_x(a.at / 1000.0, win_pos.x, avail.x, t_start, t_end)
                ay = self._pos_to_y(a.pos, track_y, self._track_h)
                d  = math.hypot(mouse.x - ax, mouse.y - ay)
                if d < best_dist:
                    best_dist = d
                    best      = (a, script, idx)
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
