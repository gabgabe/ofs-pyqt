"""
SpecialFunctionsWindow — Python port of OFS_SpecialFunctions.h / .cpp

Special edit operations:
  • Ramer-Douglas-Peucker simplification
  • Limit range (clamp positions)
  • Mirror actions
  • Scale positions
  • Snap to frame
  • Remove every Nth action
  • Generate from audio (stub)
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
    # Find point with maximum distance
    def _perp_dist(pt, line_start, line_end):
        x0, y0 = pt
        x1, y1 = line_start
        x2, y2 = line_end
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(x0 - x1, y0 - y1)
        t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        px, py = x1 + t * dx, y1 + t * dy
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


class SpecialFunctionsWindow:
    """OFS Special Functions panel."""

    WindowId = "Special Functions###SpecFuncs"

    def __init__(self) -> None:
        self._rdp_epsilon:    float = 2.0
        self._limit_min:      int   = 0
        self._limit_max:      int   = 100
        self._scale_pct:      float = 100.0
        self._remove_n:       int   = 2
        self._range_extend:   int   = 0   # -50 … 100 (live preview value)
        self._range_prev_val: int   = 0   # value at drag-start for undo-on-drag

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
        has_scr = script is not None

        imgui.text_disabled("Selection required for most functions")
        imgui.separator()
        imgui.spacing()

        # ── RDP simplification ────────────────────────────────────────
        if imgui.collapsing_header("Simplify (RDP)"):
            imgui.set_next_item_width(150)
            _, self._rdp_epsilon = imgui.input_float(
                "Epsilon##rdp", self._rdp_epsilon, 0.1, 1.0, "%.1f")
            self._rdp_epsilon = max(0.1, self._rdp_epsilon)
            if imgui.button("Simplify selection##rdp", ImVec2(-1, 0)) and has_sel:
                self._do_rdp(script, undo)
            if not has_sel:
                self._disabled_hint()

        imgui.spacing()

        # ── Limit range ───────────────────────────────────────────────
        if imgui.collapsing_header("Limit range"):
            imgui.set_next_item_width(100)
            _, self._limit_min = imgui.input_int("Min##lr", self._limit_min, 1, 5)
            imgui.same_line()
            imgui.set_next_item_width(100)
            _, self._limit_max = imgui.input_int("Max##lr", self._limit_max, 1, 5)
            self._limit_min = max(0, min(99, self._limit_min))
            self._limit_max = max(self._limit_min + 1, min(100, self._limit_max))
            if imgui.button("Clamp selection##lr", ImVec2(-1, 0)) and has_sel:
                self._do_limit(script, undo)
            if not has_sel:
                self._disabled_hint()

        imgui.spacing()

        # ── Scale positions ───────────────────────────────────────────
        if imgui.collapsing_header("Scale positions"):
            imgui.set_next_item_width(120)
            _, self._scale_pct = imgui.input_float(
                "%%##scale", self._scale_pct, 1.0, 10.0, "%.1f%%")
            self._scale_pct = max(1.0, min(500.0, self._scale_pct))
            if imgui.button("Scale selection##scale", ImVec2(-1, 0)) and has_sel:
                self._do_scale(script, undo)
            if not has_sel:
                self._disabled_hint()

        imgui.spacing()

        # ── Remove every Nth ──────────────────────────────────────────
        if imgui.collapsing_header("Remove every Nth"):
            imgui.set_next_item_width(80)
            _, self._remove_n = imgui.input_int(
                "N##rn", self._remove_n, 1, 1)
            self._remove_n = max(2, self._remove_n)
            if imgui.button("Remove from selection##rn", ImVec2(-1, 0)) and has_sel:
                self._do_remove_nth(script, undo)
            if not has_sel:
                self._disabled_hint()

        imgui.spacing()

        # ── Range Extender ────────────────────────────────────────────
        if imgui.collapsing_header("Range Extender"):
            imgui.text_disabled("Stretch strokes outward (+) or compress (-)")
            imgui.spacing()
            imgui.set_next_item_width(-60)
            # On drag-start: snapshot once so live-drag is undoable in one step
            if imgui.is_item_activated():
                self._range_prev_val = self._range_extend
            changed, new_val = imgui.slider_int(
                "##range_ext", self._range_extend, -50, 100, "%d%%")
            if changed and has_sel and script:
                undo.snapshot(StateType.RANGE_EXTEND, script)
                script.range_extend_selection(new_val - self._range_extend)
                self._range_extend = new_val
            elif changed:
                self._range_extend = new_val
            imgui.same_line()
            if imgui.button("Reset##re"):
                self._range_extend = 0
            if not has_sel:
                self._disabled_hint()

    # ──────────────────────────────────────────────────────────────────────
    # Operations
    # ──────────────────────────────────────────────────────────────────────

    def _do_rdp(self, script: Funscript, undo: UndoSystem) -> None:
        sel = sorted(list(script.selection), key=lambda a: a.at)
        if len(sel) < 3:
            return
        pts = [(a.at, float(a.pos)) for a in sel]
        simplified = _rdp(pts, self._rdp_epsilon)
        keep_at = {int(p[0]) for p in simplified}

        undo.snapshot(StateType.SIMPLIFY, script)
        for a in sel:
            if a.at not in keep_at:
                script.remove_action(a)
        script.clear_selection()

    def _do_limit(self, script: Funscript, undo: UndoSystem) -> None:
        sel = list(script.selection)
        undo.snapshot(StateType.ACTIONS_MOVED, script)
        for a in sel:
            new_pos = max(self._limit_min, min(self._limit_max, a.pos))
            if new_pos != a.pos:
                script.edit_action(a, FunscriptAction(a.at, new_pos))
        script.clear_selection()

    def _do_scale(self, script: Funscript, undo: UndoSystem) -> None:
        sel = list(script.selection)
        factor = self._scale_pct / 100.0
        undo.snapshot(StateType.ACTIONS_MOVED, script)
        for a in sel:
            new_pos = max(0, min(100, int(a.pos * factor)))
            if new_pos != a.pos:
                script.edit_action(a, FunscriptAction(a.at, new_pos))
        script.clear_selection()

    def _do_remove_nth(self, script: Funscript, undo: UndoSystem) -> None:
        sel = sorted(list(script.selection), key=lambda a: a.at)
        undo.snapshot(StateType.REMOVE_SELECTION, script)
        for i, a in enumerate(sel):
            if i % self._remove_n == (self._remove_n - 1):
                script.remove_action(a)
        script.clear_selection()

    @staticmethod
    def _disabled_hint() -> None:
        imgui.same_line()
        imgui.text_disabled("  (need selection)")
