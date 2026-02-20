"""
OFS_VideoplayerControls — Python port of OFS_VideoplayerControls.h / .cpp

Two panels:
  DrawControls(player)   — play/pause, frame step, speed, mute, chapter nav
  DrawTimeline(player, script) — seek bar + heatmap gradient strip

Heatmap generation mirrors OFS_ScriptPositionsOverlay gradient.
"""

from __future__ import annotations

import math
from typing import List, Optional

from imgui_bundle import imgui, ImVec2, ImVec4
from imgui_bundle import icons_fontawesome_6 as fa

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript, FunscriptAction

# ── Heatmap colours (mirrors OFS gradient) ────────────────────────────────
_HEATMAP_COLD  = (0x11/255, 0x11/255, 0xFF/255, 1.0)   # deep blue — 0 speed
_HEATMAP_WARM  = (0x11/255, 0xFF/255, 0x11/255, 1.0)   # green
_HEATMAP_HOT   = (0xFF/255, 0x44/255, 0x11/255, 1.0)   # orange-red — max speed
_HEATMAP_TRANS = (0x00/255, 0x00/255, 0x00/255, 0.0)   # transparent (no content)

HEATMAP_SEGMENTS = 256


def _lerp_colour(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


def _speed_colour(norm_speed: float):
    """Map 0‥1 speed to RGBA. Mirrors OFS_ScriptPositionsOverlay."""
    norm_speed = max(0.0, min(1.0, norm_speed))
    if norm_speed < 0.5:
        return _lerp_colour(_HEATMAP_COLD, _HEATMAP_WARM, norm_speed * 2.0)
    else:
        return _lerp_colour(_HEATMAP_WARM, _HEATMAP_HOT, (norm_speed - 0.5) * 2.0)


def _rgba_to_u32(r, g, b, a) -> int:
    ri = int(r * 255) & 0xFF
    gi = int(g * 255) & 0xFF
    bi = int(b * 255) & 0xFF
    ai = int(a * 255) & 0xFF
    return ri | (gi << 8) | (bi << 16) | (ai << 24)


# ── OFS speed normalisation constants ─────────────────────────────────────
# OFS caps speed at ~500 units/s before normalising
MAX_SPEED_UNITS_S = 500.0


class OFS_VideoplayerControls:
    """
    Mirrors C++ OFS_VideoplayerControls.
    """

    TimeId    = "Progress###Timeline"
    ControlId = "Controls###Controls"

    def __init__(self) -> None:
        self._heatmap_colours: List[int] = []   # list of u32 colours, len=HEATMAP_SEGMENTS
        self._heatmap_tex: Optional[int] = None  # GL texture id (if uploaded)
        self._heatmap_dirty: bool = False
        self._heatmap_duration: float = 0.0

        self._prev_paused: Optional[bool] = None
        self._chapter_tooltip: str = ""
        self._drag_was_paused: bool = True   # for seek-pause-resume

    # ──────────────────────────────────────────────────────────────────────

    def Init(self, player: OFS_Videoplayer) -> None:
        pass  # GL texture upload deferred to first use

    # ──────────────────────────────────────────────────────────────────────
    # Heatmap update (called by app when gradient flag set)
    # ──────────────────────────────────────────────────────────────────────

    def UpdateHeatmap(
        self,
        duration: float,
        actions: List[FunscriptAction],
    ) -> None:
        """Pre-compute per-segment colours from action speed data."""
        if duration <= 0.0:
            return
        self._heatmap_duration = duration
        seg_dur = duration / HEATMAP_SEGMENTS
        colours: List[int] = []

        for i in range(HEATMAP_SEGMENTS):
            t_start = i       * seg_dur
            t_end   = (i + 1) * seg_dur

            # Find actions in this segment (ms-based)
            seg_actions = [
                a for a in actions
                if t_start <= a.at / 1000.0 < t_end
            ]

            if len(seg_actions) < 2:
                # Check for single crossing action
                before = [a for a in actions if a.at / 1000.0 < t_start]
                after  = [a for a in actions if a.at / 1000.0 >= t_end]
                if before and after:
                    a0 = before[-1]
                    a1 = after[0]
                    dt = (a1.at - a0.at) / 1000.0
                    if dt > 0:
                        speed = abs(a1.pos - a0.pos) / dt
                        norm  = min(1.0, speed / MAX_SPEED_UNITS_S)
                        colours.append(_rgba_to_u32(*_speed_colour(norm)))
                        continue
                colours.append(0x00000000)  # transparent
                continue

            # Average speed across segment
            total_speed = 0.0
            for j in range(1, len(seg_actions)):
                dt = (seg_actions[j].at - seg_actions[j-1].at) / 1000.0
                if dt > 0:
                    total_speed += abs(seg_actions[j].pos - seg_actions[j-1].pos) / dt
            avg = total_speed / (len(seg_actions) - 1)
            norm = min(1.0, avg / MAX_SPEED_UNITS_S)
            colours.append(_rgba_to_u32(*_speed_colour(norm)))

        self._heatmap_colours = colours
        self._heatmap_dirty   = True

    # ──────────────────────────────────────────────────────────────────────
    # DrawControls — play/pause bar
    # ──────────────────────────────────────────────────────────────────────

    def DrawControls(self, player: OFS_Videoplayer) -> None:
        if not player.VideoLoaded():
            imgui.text_disabled("No video")
            return

        # ── Row 1: playback buttons ────────────────────────────────────
        button_h = imgui.get_frame_height()
        small    = ImVec2(button_h, button_h)

        # prev-frame
        if imgui.button(fa.ICON_FA_BACKWARD_STEP, small):
            player.PreviousFrame()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Previous frame  [←]")
        imgui.same_line()

        # play/pause
        play_icon = fa.ICON_FA_PAUSE if not player.IsPaused() else fa.ICON_FA_PLAY
        if imgui.button(play_icon, small):
            player.TogglePlay()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Play / Pause  [Space]")
        imgui.same_line()

        # next-frame
        if imgui.button(fa.ICON_FA_FORWARD_STEP, small):
            player.NextFrame()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Next frame  [→]")

        imgui.same_line(spacing=8)

        # ── ±3 s seek buttons ──────────────────────────────────────────
        if imgui.button(fa.ICON_FA_BACKWARD + " 3s##sk_back", ImVec2(0, button_h)):
            player.SeekRelative(-3.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Seek −3 seconds  [Shift+←]")
        imgui.same_line(spacing=2)
        if imgui.button("3s " + fa.ICON_FA_FORWARD + "##sk_fwd", ImVec2(0, button_h)):
            player.SeekRelative(3.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Seek +3 seconds  [Shift+→]")

        imgui.same_line(spacing=8)

        # mute
        mute_icon = fa.ICON_FA_VOLUME_XMARK if player.Volume() == 0 else fa.ICON_FA_VOLUME_HIGH
        if imgui.button(mute_icon, small):
            if player.Volume() == 0:
                player.Unmute()
            else:
                player.Mute()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Mute / Unmute")
        imgui.same_line(spacing=4)

        # volume slider
        avail = imgui.get_content_region_avail().x
        imgui.set_next_item_width(max(40, min(60, avail * 0.15)))
        vol = player.Volume()
        changed, new_vol = imgui.slider_float("##vol", vol, 0.0, 100.0, "%.0f%%")
        if changed:
            player.SetVolume(new_vol)

        imgui.same_line(spacing=8)

        # speed input
        imgui.set_next_item_width(max(50, min(70, avail * 0.15)))
        speed = player.CurrentSpeed()
        changed_s, new_speed = imgui.input_float("##spd", speed, 0.0, 0.0, "%.2f×")
        if changed_s:
            player.SetSpeed(max(0.05, min(5.0, new_speed)))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Playback speed  (scroll to change)")

        imgui.same_line(spacing=2)

        # speed preset buttons: 1×  -10%  +10%
        spd_w = ImVec2(max(28, button_h * 1.6), button_h)
        if imgui.button("1" + fa.ICON_FA_XMARK + "##sp1", spd_w):
            player.SetSpeed(1.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Reset speed to 1×")
        imgui.same_line(spacing=2)
        if imgui.button("-10%%##spm", spd_w):
            player.SetSpeed(max(0.05, player.CurrentSpeed() * 0.9))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Decrease speed by 10%")
        imgui.same_line(spacing=2)
        if imgui.button("+10%%##spp", spd_w):
            player.SetSpeed(min(5.0, player.CurrentSpeed() * 1.1))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Increase speed by 10%")

    # ──────────────────────────────────────────────────────────────────────
    # DrawTimeline — custom heatmap + seek bar with chapter/bookmark overlay
    # ──────────────────────────────────────────────────────────────────────

    def DrawTimeline(
        self,
        player: OFS_Videoplayer,
        script:  Optional[Funscript],
        chapter_mgr=None,   # ChapterManagerWindow | None
    ) -> None:
        if not player.VideoLoaded():
            imgui.text_disabled("No video")
            return

        duration = player.Duration()
        current  = player.CurrentTime()
        if duration <= 0.0:
            return

        avail  = imgui.get_content_region_avail()
        dl     = imgui.get_window_draw_list()
        origin = imgui.get_cursor_screen_pos()

        W  = max(1.0, avail.x)
        BAR_H   = 22.0          # main timeline bar height
        CHAP_H  = BAR_H * 0.28  # chapter strip height (top of bar)
        BM_R    = 4.0           # bookmark circle radius
        pct     = current / duration if duration > 0 else 0.0
        ox, oy  = origin.x, origin.y

        # 1 ── Background (grey unfilled portion) ──────────────────────
        dl.add_rect_filled(
            ImVec2(ox,            oy),
            ImVec2(ox + W,        oy + BAR_H),
            0xFF505050,
        )

        # 2 ── Progress fill (highlight up to cursor) ──────────────────
        fill_x = ox + W * pct
        dl.add_rect_filled(
            ImVec2(ox,            oy),
            ImVec2(fill_x,        oy + BAR_H),
            0xBB2D5FAA,
        )

        # 3 ── Heatmap overlay ──────────────────────────────────────────
        if self._heatmap_colours:
            n     = len(self._heatmap_colours)
            seg_w = W / n
            for i, col in enumerate(self._heatmap_colours):
                if col == 0:
                    continue
                x0 = ox + i * seg_w
                x1 = ox + (i + 1) * seg_w
                dl.add_rect_filled(ImVec2(x0, oy), ImVec2(x1, oy + BAR_H), col)

        # 4 ── Chapters (top strip) ────────────────────────────────────
        if chapter_mgr and chapter_mgr._chapters:
            for ch in chapter_mgr._chapters:
                ch_x0 = ox + (ch.start / duration) * W
                ch_x1 = ox + (ch.end   / duration) * W
                if ch_x1 - ch_x0 < 1.0:
                    continue
                cr, cg, cb = ch.color[0], ch.color[1], ch.color[2]
                ch_col = self._rgba_to_u32(cr, cg, cb, 0.85)
                dl.add_rect_filled(
                    ImVec2(ch_x0, oy),
                    ImVec2(ch_x1, oy + CHAP_H),
                    ch_col, 2.0,
                )
                # Active-chapter border
                if ch.start <= current <= ch.end:
                    dl.add_rect(
                        ImVec2(ch_x0, oy),
                        ImVec2(ch_x1, oy + CHAP_H),
                        0xFFFFFFFF, 2.0, 0, 1.5,
                    )
                # Label if it fits
                if ch.name:
                    ts = imgui.calc_text_size(ch.name)
                    cw = ch_x1 - ch_x0
                    if ts.x + 4 <= cw:
                        dl.add_text(
                            ImVec2(ch_x0 + (cw - ts.x) * 0.5,
                                   oy + (CHAP_H - ts.y) * 0.5),
                            0xFFFFFFFF, ch.name,
                        )

        # 5 ── Bookmarks (small circles at bottom) ─────────────────────
        if chapter_mgr and chapter_mgr._bookmarks:
            for bm in chapter_mgr._bookmarks:
                bm_x = ox + (bm.time / duration) * W
                dl.add_circle_filled(
                    ImVec2(bm_x, oy + BAR_H - BM_R - 1), BM_R,
                    0xFFFFFFFF, 8,
                )

        # 6 ── Cursor line (white + dark shadow) ───────────────────────
        cx = ox + W * pct
        dl.add_line(ImVec2(cx, oy - 1), ImVec2(cx, oy + BAR_H + 1), 0xFF000000, 3.0)
        dl.add_line(ImVec2(cx, oy - 1), ImVec2(cx, oy + BAR_H + 1), 0xFFFFFFFF, 1.5)

        # 7 ── Invisible button for interaction ────────────────────────
        imgui.set_cursor_screen_pos(ImVec2(ox, oy))
        imgui.invisible_button("##timeline_bar", ImVec2(W, BAR_H))

        if imgui.is_item_activated():
            self._drag_was_paused = player.IsPaused()
            if not player.IsPaused():
                player.SetPaused(True)

        if imgui.is_item_active() and imgui.is_mouse_down(0):
            mx    = imgui.get_mouse_pos().x
            rel   = max(0.0, min(1.0, (mx - ox) / W))
            player.SetPositionExact(rel * duration)
            if player.IsPaused():
                player.Update(0.0)

        if imgui.is_item_deactivated():
            if not self._drag_was_paused:
                player.SetPaused(False)

        # 8 ── Hover effects ───────────────────────────────────────────
        if imgui.is_item_hovered():
            mouse = imgui.get_mouse_pos()
            rel   = (mouse.x - ox) / W
            hover_t = max(0.0, min(duration, rel * duration))
            # Vertical hover line
            dl.add_line(
                ImVec2(mouse.x, oy),
                ImVec2(mouse.x, oy + BAR_H),
                0x88FFFFFF, 1.0,
            )
            # Tooltip: time + delta
            delta  = hover_t - current
            sign   = "+" if delta >= 0 else ""
            imgui.set_tooltip(
                f"{self._format_time(hover_t, duration)}  ({sign}{self._format_delta(abs(delta))})"
            )

        # 9 ── Chapter context menus ───────────────────────────────────
        if chapter_mgr and chapter_mgr._chapters:
            if imgui.is_item_hovered() and imgui.is_mouse_clicked(1):
                mouse    = imgui.get_mouse_pos()
                click_t  = ((mouse.x - ox) / W) * duration
                for i, ch in enumerate(chapter_mgr._chapters):
                    if ch.start <= click_t <= ch.end:
                        imgui.open_popup(f"##ch_ctx_tl_{i}")

            for i, ch in enumerate(chapter_mgr._chapters):
                if imgui.begin_popup(f"##ch_ctx_tl_{i}"):
                    imgui.text_disabled(ch.name or f"Chapter {i+1}")
                    imgui.separator()
                    if imgui.menu_item("Seek to start")[0]:
                        player.SetPositionExact(ch.start)
                    if imgui.menu_item("Seek to end")[0]:
                        player.SetPositionExact(ch.end)
                    imgui.end_popup()

        # 10 ── Time label below bar ───────────────────────────────────
        imgui.dummy(ImVec2(1, 2))
        imgui.text_disabled(self._format_time(current, duration))

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _rgba_to_u32(r: float, g: float, b: float, a: float = 1.0) -> int:
        ri = int(r * 255) & 0xFF
        gi = int(g * 255) & 0xFF
        bi = int(b * 255) & 0xFF
        ai = int(a * 255) & 0xFF
        return ri | (gi << 8) | (bi << 16) | (ai << 24)

    @staticmethod
    def _format_time(t: float, duration: float) -> str:
        def _ts(s: float) -> str:
            s   = max(0.0, s)
            h   = int(s) // 3600
            m   = (int(s) % 3600) // 60
            sec = s % 60
            if h:
                return f"{h:02d}:{m:02d}:{sec:05.2f}"
            return f"{m:02d}:{sec:05.2f}"
        return f"{_ts(t)} / {_ts(duration)}"

    @staticmethod
    def _format_delta(dt: float) -> str:
        """Format a time delta as  mm:ss.xx (no total)."""
        dt  = max(0.0, dt)
        m   = int(dt) // 60
        sec = dt % 60
        return f"{m:02d}:{sec:05.2f}"
