"""
SimulatorWindow — Python port of OFS_Simulator3D (simplified 2D version).

Draws a visual stroke bar that moves according to the active funscript
position at the current playback time (linear interpolation between actions).
"""

from __future__ import annotations

import math
from typing import Optional

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript


def _interpolate_position(script: Funscript, t_s: float) -> Optional[float]:
    """Return interpolated position (0‥100) at time t_s seconds."""
    actions = list(script.actions.get_actions_in_range(
        int((t_s - 0.5) * 1000), int((t_s + 0.5) * 1000)))
    if not actions:
        return None
    t_ms = t_s * 1000.0
    # Find surrounding pair
    before = [a for a in actions if a.at <= t_ms]
    after  = [a for a in actions if a.at >  t_ms]
    if not before:
        return float(after[0].pos) if after else None
    if not after:
        return float(before[-1].pos)
    a0, a1 = before[-1], after[0]
    span = a1.at - a0.at
    if span <= 0:
        return float(a0.pos)
    t = (t_ms - a0.at) / span
    return a0.pos + (a1.pos - a0.pos) * t


class SimulatorWindow:
    """OFS Simulator panel — visual position indicator."""

    WindowId = "Simulator###Simulator"

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player: OFS_Videoplayer,
        script: Optional[Funscript],
    ) -> None:
        avail = imgui.get_content_region_avail()
        if avail.x < 4 or avail.y < 4:
            return

        dl   = imgui.get_window_draw_list()
        pos  = imgui.get_cursor_screen_pos()

        bar_w = max(20.0, min(40.0, avail.x * 0.3))
        bar_h = avail.y - 8

        bar_x = pos.x + (avail.x - bar_w) * 0.5
        bar_y = pos.y + 4

        # Background track
        dl.add_rect_filled(
            ImVec2(bar_x, bar_y),
            ImVec2(bar_x + bar_w, bar_y + bar_h),
            imgui.get_color_u32(ImVec4(0.15, 0.15, 0.15, 1.0)),
            4.0,
        )
        dl.add_rect(
            ImVec2(bar_x, bar_y),
            ImVec2(bar_x + bar_w, bar_y + bar_h),
            imgui.get_color_u32(ImVec4(0.3, 0.3, 0.3, 1.0)),
            4.0, 0, 1.0,
        )

        # Moving "head"
        raw_pos = 0.0
        if script and player.VideoLoaded():
            v = _interpolate_position(script, player.CurrentTime())
            if v is not None:
                raw_pos = v

        norm = max(0.0, min(1.0, raw_pos / 100.0))
        head_h  = max(12.0, bar_h * 0.12)
        head_y  = bar_y + (1.0 - norm) * (bar_h - head_h)

        # Gradient colour: blue(low) → green(mid) → red(high)
        if norm < 0.5:
            r = 0.0
            g = norm * 2.0
            b = 1.0 - norm * 2.0
        else:
            r = (norm - 0.5) * 2.0
            g = 1.0 - (norm - 0.5) * 2.0
            b = 0.0

        col = imgui.get_color_u32(ImVec4(r, g, b, 0.9))
        dl.add_rect_filled(
            ImVec2(bar_x + 2, head_y),
            ImVec2(bar_x + bar_w - 2, head_y + head_h),
            col,
            3.0,
        )

        # Position label
        imgui.set_cursor_screen_pos(ImVec2(pos.x, bar_y + bar_h + 2))
        imgui.text(f"{raw_pos:.0f}")

        # Leave space
        imgui.dummy(ImVec2(avail.x, 0))
