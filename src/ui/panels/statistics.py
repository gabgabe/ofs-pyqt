"""
StatisticsWindow — Python port of OFS_Statistics.h / OFS_Statistics.cpp

Displays per-funscript statistics:
  • Total / selected action count
  • Average / max speed
  • Average / max position
  • Actions per minute
  • Selection duration
"""

from __future__ import annotations

import math
from typing import Optional, List

from imgui_bundle import imgui, ImVec2

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript, FunscriptAction


def _compute_stats(actions: List[FunscriptAction]):
    """Return dict of statistics for a list of actions."""
    n = len(actions)
    if n == 0:
        return {"count": 0}

    positions = [a.pos for a in actions]
    avg_pos = sum(positions) / n
    max_pos = max(positions)
    min_pos = min(positions)

    speeds = []
    for i in range(1, n):
        dt = (actions[i].at - actions[i - 1].at) / 1000.0
        if dt > 0:
            speeds.append(abs(actions[i].pos - actions[i - 1].pos) / dt)

    avg_speed    = sum(speeds) / len(speeds) if speeds else 0.0
    max_speed    = max(speeds) if speeds else 0.0
    sorted_sp    = sorted(speeds)
    mid          = len(sorted_sp) // 2
    if len(sorted_sp) == 0:
        median_speed = 0.0
    elif len(sorted_sp) % 2 == 1:
        median_speed = sorted_sp[mid]
    else:
        median_speed = (sorted_sp[mid - 1] + sorted_sp[mid]) / 2.0

    total_dur = (actions[-1].at - actions[0].at) / 1000.0 if n >= 2 else 0.0
    apm = (n / total_dur * 60.0) if total_dur > 0 else 0.0

    return {
        "count":        n,
        "avg_pos":      avg_pos,
        "max_pos":      max_pos,
        "min_pos":      min_pos,
        "avg_speed":    avg_speed,
        "median_speed": median_speed,
        "max_speed":    max_speed,
        "duration":     total_dur,
        "apm":          apm,
    }


class StatisticsWindow:
    """OFS Statistics panel."""

    WindowId = "Statistics###Statistics"

    def __init__(self) -> None:
        self._stats_all: dict = {}
        self._stats_sel: dict = {}
        self._last_hash: int  = 0

    @staticmethod
    def _script_hash(script: "Funscript") -> int:
        """Fast hash that changes whenever the script's content or selection changes."""
        n_all = len(list(script.actions))
        n_sel = script.selection_size()
        # XOR with the sum of all positions so adding/moving a point invalidates cache
        pos_sum = sum(a.pos for a in script.actions)
        return hash((id(script), n_all, n_sel, pos_sum))

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player: OFS_Videoplayer,
        script: Optional[Funscript],
    ) -> None:
        if script is None:
            imgui.text_disabled("No script loaded")
            return

        current_time = player.CurrentTime()  # seconds

        # ── Real-time stats at cursor (mirrors OFS ShowStatisticsWindow) ──
        front = script.get_action_at_time(current_time, 0.001)
        if front is not None:
            behind = script.get_previous_action_behind(front.at / 1000.0)
        else:
            behind = script.get_previous_action_behind(current_time)
            front  = script.get_next_action_ahead(current_time)

        if behind is not None:
            interval_ms = (current_time - behind.at / 1000.0) * 1000.0
            imgui.text(f"Interval:  {interval_ms:.2f} ms")
            if front is not None:
                duration_s = (front.at - behind.at) / 1000.0
                delta_pos  = front.pos - behind.pos
                speed      = abs(delta_pos) / duration_s if duration_s > 0 else 0.0
                direction  = "\u2191" if delta_pos > 0 else ("\u2193" if delta_pos < 0 else "\u2014")
                imgui.text(f"Speed:     {speed:.2f} u/s")
                imgui.text(f"Duration:  {(duration_s * 1000.0):.2f} ms")
                imgui.text(f"{behind.pos} \u2192 {front.pos} = {abs(delta_pos)} {direction}")
        imgui.separator()

        # Recompute when script content or selection changes
        h = self._script_hash(script)
        if h != self._last_hash or not self._stats_all:
            self._stats_all = _compute_stats(list(script.actions))
            self._stats_sel = _compute_stats(sorted(
                list(script.selection), key=lambda a: a.at))
            self._last_hash = h

        imgui.text("Script statistics")
        imgui.separator()
        self._table("All actions",       self._stats_all)
        imgui.spacing()
        self._table("Selected actions",  self._stats_sel)

    @staticmethod
    def _table(header: str, s: dict) -> None:
        if not s or s.get("count", 0) == 0:
            imgui.text_disabled(f"{header}: (none)")
            return

        imgui.text(header)
        if imgui.begin_table(f"##st_{header}", 2,
                             imgui.TableFlags_.borders_inner_v |
                             imgui.TableFlags_.row_bg |
                             imgui.TableFlags_.sizing_stretch_prop):
            imgui.table_setup_column("Property", imgui.TableColumnFlags_.width_stretch)
            imgui.table_setup_column("Value",    imgui.TableColumnFlags_.width_stretch)
            imgui.table_headers_row()

            def _row(k, v):
                imgui.table_next_row()
                imgui.table_set_column_index(0); imgui.text_unformatted(k)
                imgui.table_set_column_index(1); imgui.text_unformatted(str(v))

            _row("Actions",       s["count"])
            _row("Avg position",  f"{s['avg_pos']:.1f}")
            _row("Max position",  s["max_pos"])
            _row("Min position",  s["min_pos"])
            _row("Avg speed",    f"{s['avg_speed']:.1f} u/s")
            _row("Median speed", f"{s.get('median_speed', 0.0):.1f} u/s")
            _row("Max speed",    f"{s['max_speed']:.1f} u/s")
            _row("Duration",      f"{s['duration']:.2f} s")
            _row("Actions/min",   f"{s['apm']:.1f}")
            imgui.end_table()
