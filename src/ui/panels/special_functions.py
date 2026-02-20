"""
SpecialFunctionsWindow — Python port of OFS_SpecialFunctions.h / .cpp

Two functions exposed via a combo selector (OFS style):
  0 — Range Extender
  1 — Simplify (RDP)
"""

from __future__ import annotations

import math
from typing import Optional, List

from imgui_bundle import imgui, ImVec2

from src.core.funscript   import Funscript, FunscriptAction
from src.core.undo_system import UndoSystem, StateType


def _rdp(points: List, epsilon: float) -> List:
    """Ramer-Douglas-Peucker simplification."""
    if len(points) < 3:
        return points

    def _perp_dist(pt, line_start, line_end):
        x0, y0 = pt
        x1, y1 = line_start
        x2, y2 = line_end
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(x0 - x1, y0 - y1)
        t  = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
        t  = max(0.0, min(1.0, t))
        px = x1 + t * dx
        py = y1 + t * dy
        return math.hypot(x0 - px, y0 - py)

    dmax  = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        d = _perp_dist(points[i], points[0], points[-1])
        if d > dmax:
            dmax  = d
            index = i

    if dmax > epsilon:
        r1 = _rdp(points[:index + 1], epsilon)
        r2 = _rdp(points[index:],     epsilon)
        return r1[:-1] + r2
    return [points[0], points[-1]]


# OFS function names shown in the combo
_FUNC_NAMES = ["Range Extender", "Simplify (RDP)"]


class SpecialFunctionsWindow:
    """OFS Special Functions panel."""

    WindowId = "Special Functions###SpecFuncs"

    def __init__(self) -> None:
        self._selected_func:  int   = 0      # index into _FUNC_NAMES
        # RDP
        self._rdp_epsilon:    float = 2.0
        # Range Extender
        self._range_extend:   int   = 0      # live value -50…100
        self._range_drag_active: bool = False  # True while slider is held

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        script:  Optional[Funscript],
        undo:    UndoSystem,
        visible: bool,
    ) -> bool:
        """Returns updated visible flag (False if user clicked the close button)."""
        if not visible:
            return False
        open_flag = True
        opened, open_flag = imgui.begin(
            "Special Functions###SpecFuncs",
            open_flag,
            imgui.WindowFlags_.always_auto_resize,
        )
        if opened:
            self._draw(script, undo)
        imgui.end()
        return open_flag

    def _draw(self, script: Optional[Funscript], undo: UndoSystem) -> None:
        has_sel = bool(script and script.has_selection())

        # ── Function selector combo ───────────────────────────────────
        imgui.set_next_item_width(180)
        ch, new_idx = imgui.combo("##funcsel", self._selected_func, _FUNC_NAMES)
        if ch:
            self._selected_func = new_idx
        imgui.separator()
        imgui.spacing()

        if self._selected_func == 0:
            self._draw_range_extender(script, undo, has_sel)
        else:
            self._draw_rdp(script, undo, has_sel)

    # ──────────────────────────────────────────────────────────────────────
    # Range Extender
    # ──────────────────────────────────────────────────────────────────────

    def _draw_range_extender(
        self,
        script:  Optional[Funscript],
        undo:    UndoSystem,
        has_sel: bool,
    ) -> None:
        imgui.text_disabled("Stretch strokes outward (+) or compress (-)")
        imgui.spacing()

        imgui.set_next_item_width(-60)

        # Detect drag-start: take a snapshot *once* so the whole live-drag
        # collapses into a single undo entry.
        if imgui.is_item_activated():
            if has_sel and script:
                undo.snapshot(StateType.RANGE_EXTEND, script)
            self._range_drag_active = True

        changed, new_val = imgui.slider_int(
            "##range_ext", self._range_extend, -50, 100, "%d%%")

        if imgui.is_item_deactivated():
            self._range_drag_active = False

        if changed and has_sel and script:
            # Undo before re-applying so every tick stays as one undo step
            undo.undo(script)
            undo.snapshot(StateType.RANGE_EXTEND, script)
            script.range_extend_selection(new_val)
            self._range_extend = new_val
        elif changed:
            self._range_extend = new_val

        imgui.same_line()
        if imgui.button("Reset##re"):
            if has_sel and script and self._range_extend != 0:
                undo.snapshot(StateType.RANGE_EXTEND, script)
                script.range_extend_selection(-self._range_extend)
            self._range_extend = 0

        if not has_sel:
            self._disabled_hint()

    # ──────────────────────────────────────────────────────────────────────
    # RDP Simplify
    # ──────────────────────────────────────────────────────────────────────

    def _draw_rdp(
        self,
        script:  Optional[Funscript],
        undo:    UndoSystem,
        has_sel: bool,
    ) -> None:
        imgui.text_disabled("Remove redundant points using Ramer–Douglas–Peucker")
        imgui.spacing()

        imgui.set_next_item_width(150)
        _, self._rdp_epsilon = imgui.input_float(
            "Epsilon##rdp", self._rdp_epsilon, 0.1, 1.0, "%.1f")
        self._rdp_epsilon = max(0.1, self._rdp_epsilon)
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Epsilon is scaled by the average inter-action distance.\n"
                "Larger value = more aggressive simplification.")

        if imgui.button("Simplify selection##rdp", ImVec2(-1, 0)) and has_sel:
            self._do_rdp(script, undo)
        if not has_sel:
            self._disabled_hint()

    # ──────────────────────────────────────────────────────────────────────
    # Operations
    # ──────────────────────────────────────────────────────────────────────

    def _do_rdp(self, script: Funscript, undo: UndoSystem) -> None:
        sel = sorted(list(script.selection), key=lambda a: a.at)
        if len(sel) < 3:
            return

        # Scale epsilon by average inter-action Euclidean distance
        pts = [(a.at, float(a.pos)) for a in sel]
        if len(pts) >= 2:
            distances = [
                math.hypot(pts[j][0] - pts[j-1][0], pts[j][1] - pts[j-1][1])
                for j in range(1, len(pts))
            ]
            avg_dist = sum(distances) / len(distances) if distances else 1.0
        else:
            avg_dist = 1.0

        scaled_eps = self._rdp_epsilon * max(1.0, avg_dist)
        simplified = _rdp(pts, scaled_eps)
        keep_at    = {int(p[0]) for p in simplified}

        undo.snapshot(StateType.SIMPLIFY, script)
        for a in sel:
            if a.at not in keep_at:
                script.remove_action(a)
        script.clear_selection()

    @staticmethod
    def _disabled_hint() -> None:
        imgui.same_line()
        imgui.text_disabled("  (need selection)")
        imgui.same_line()
        imgui.text_disabled("  (need selection)")
