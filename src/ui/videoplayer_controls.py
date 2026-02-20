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
        small = ImVec2(button_h, button_h)

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
        avail = imgui.get_content_region_avail().x - 60
        imgui.set_next_item_width(min(60, avail * 0.4))
        vol = player.Volume()
        changed, new_vol = imgui.slider_float("##vol", vol, 0.0, 100.0, "%.0f%%")
        if changed:
            player.SetVolume(new_vol)

        imgui.same_line(spacing=8)

        # speed
        imgui.set_next_item_width(min(70, avail * 0.4))
        speed = player.CurrentSpeed()
        changed_s, new_speed = imgui.input_float("##spd", speed, 0.1, 0.25, "%.2f×")
        if changed_s:
            player.SetSpeed(max(0.05, min(5.0, new_speed)))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Playback speed\n[-/+ on numpad]")

    # ──────────────────────────────────────────────────────────────────────
    # DrawTimeline — heatmap + seek bar
    # ──────────────────────────────────────────────────────────────────────

    def DrawTimeline(
        self,
        player: OFS_Videoplayer,
        script:  Optional[Funscript],
    ) -> None:
        if not player.VideoLoaded():
            imgui.text_disabled("No video")
            return

        duration = player.Duration()
        current  = player.CurrentTime()
        if duration <= 0.0:
            return

        avail = imgui.get_content_region_avail()
        bar_h   = 12.0
        seek_h  = imgui.get_frame_height()
        total_h = bar_h + seek_h + 4

        dl = imgui.get_window_draw_list()
        origin = imgui.get_cursor_screen_pos()

        # ── Heatmap strip ─────────────────────────────────────────────────
        if self._heatmap_colours:
            seg_w = avail.x / len(self._heatmap_colours)
            for i, col in enumerate(self._heatmap_colours):
                if col == 0:
                    continue
                x0 = origin.x + i       * seg_w
                x1 = origin.x + (i + 1) * seg_w
                y0 = origin.y
                y1 = origin.y + bar_h
                dl.add_rect_filled(ImVec2(x0, y0), ImVec2(x1, y1), col)
        else:
            dl.add_rect_filled(
                origin,
                ImVec2(origin.x + avail.x, origin.y + bar_h),
                imgui.get_color_u32(ImVec4(0.15, 0.15, 0.15, 1.0))
            )

        # Chapter / bookmark markers
        # (project chapters drawn by chapter manager via event)

        imgui.dummy(ImVec2(avail.x, bar_h))

        # ── Seek slider ────────────────────────────────────────────────────
        imgui.set_next_item_width(avail.x)
        pos_pct = current / duration if duration > 0 else 0.0
        changed, new_pct = imgui.slider_float(
            "##seek", pos_pct, 0.0, 1.0,
            format=self._format_time(current, duration),
            flags=imgui.SliderFlags_.no_input,
        )
        if changed:
            player.SetPositionExact(new_pct * duration)
            if player.IsPaused():
                # Render one frame to update display while paused
                player.Update(0.0)

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_time(t: float, duration: float) -> str:
        def _ts(s):
            h = int(s) // 3600
            m = (int(s) % 3600) // 60
            sec = s % 60
            if h:
                return f"{h:02d}:{m:02d}:{sec:05.2f}"
            return f"{m:02d}:{sec:05.2f}"
        return f"{_ts(t)} / {_ts(duration)}"
