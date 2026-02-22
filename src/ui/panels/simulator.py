"""
SimulatorWindow — Full port of OFS_ScriptSimulator.h / OFS_ScriptSimulator.cpp

Draws an oriented bar (P1 → P2) on the foreground draw list that floats on
top of all other windows, showing the current funscript position.

Matches OFS features:
  • Draggable P1 / P2 endpoints (hand cursor) + centre-drag (move cursor)
  • Lock checkbox  ·  Center / Invert / Load / Save config buttons
  • Collapsing configuration: 6 colour editors, Width/BorderWidth/LineWidth/
    Opacity sliders, ExtraLinesCount, feature-toggle checkboxes, vanilla mode,
    Reset to defaults
  • Height tick marks at 10 % intervals
  • Prev/next action indicators + numeric position labels
  • Centre position text
  • Vanilla mode: read-only VSliderFloat fallback
  • Config persistence  (~/.ofs-pyqt/sim_config.json)
  • Mouse-to-position mapping (MouseOnSimulator flag)
"""

from __future__ import annotations

import json
import math
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript

log = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".ofs-pyqt" / "sim_config.json"

# ── Helpers ───────────────────────────────────────────────────────────────

def _dist2(a: Tuple, b: Tuple) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return math.sqrt(dx * dx + dy * dy)

def _norm2(p: Tuple) -> Tuple:
    mag = _dist2((0.0, 0.0), p)
    if mag < 1e-6:
        return (0.0, 1.0)
    return (p[0] / mag, p[1] / mag)

def _perp2(d: Tuple) -> Tuple:
    """90° CCW rotation."""
    return (-d[1], d[0])

def _add2(a: Tuple, b: Tuple) -> Tuple:
    return (a[0] + b[0], a[1] + b[1])

def _sub2(a: Tuple, b: Tuple) -> Tuple:
    return (a[0] - b[0], a[1] - b[1])

def _mul2(a: Tuple, s: float) -> Tuple:
    return (a[0] * s, a[1] * s)

def _iv2(p: Tuple) -> ImVec2:
    return ImVec2(p[0], p[1])

def _col_u32(c: List[float], opacity: float = 1.0) -> int:
    """(r,g,b,a) floats → ABGR u32 with opacity applied to alpha."""
    r, g, b, a = c[0], c[1], c[2], c[3] if len(c) > 3 else 1.0
    final_a = min(1.0, a * opacity)
    return (
        (int(final_a * 255) << 24)
        | (int(b * 255) << 16)
        | (int(g * 255) << 8)
        | int(r * 255)
    )


# ── Default state ─────────────────────────────────────────────────────────

_DEFAULT_STATE: dict = {
    "width":             30.0,
    "border_width":      2.0,
    "line_width":        2.0,
    "global_opacity":    0.9,
    "extra_line_width":  1.5,
    "extra_lines_count": 0,
    "col_text":          [1.0, 1.0, 1.0, 1.0],
    "col_border":        [0.8, 0.8, 0.8, 1.0],
    "col_front":         [0.18, 0.80, 0.18, 1.0],
    "col_back":          [0.10, 0.10, 0.10, 1.0],
    "col_indicator":     [0.95, 0.75, 0.10, 1.0],
    "col_extra_lines":   [0.50, 0.50, 0.50, 0.60],
    "enable_height_lines": True,
    "enable_indicators":   True,
    "enable_position":     True,
    "locked_position":     False,
}


class SimulatorWindow:
    """OFS Simulator panel — visual position indicator.

    Mirrors ``OFS_ScriptSimulator`` (OFS_ScriptSimulator.h / .cpp).
    """

    WindowId = "Simulator###Simulator"

    def __init__(self) -> None:
        # Geometry (absolute screen positions; initialised on first Show())
        self._p1: List[float] = [0.0, 0.0]
        self._p2: List[float] = [0.0, 0.0]
        self._initialized: bool = False

        # Appearance
        self._width:             float = _DEFAULT_STATE["width"]
        self._border_width:      float = _DEFAULT_STATE["border_width"]
        self._line_width:        float = _DEFAULT_STATE["line_width"]
        self._global_opacity:    float = _DEFAULT_STATE["global_opacity"]
        self._extra_line_width:  float = _DEFAULT_STATE["extra_line_width"]
        self._extra_lines_count: int   = _DEFAULT_STATE["extra_lines_count"]

        # Colours  (r, g, b, a) in 0‥1
        self._col_text:        List[float] = list(_DEFAULT_STATE["col_text"])
        self._col_border:      List[float] = list(_DEFAULT_STATE["col_border"])
        self._col_front:       List[float] = list(_DEFAULT_STATE["col_front"])
        self._col_back:        List[float] = list(_DEFAULT_STATE["col_back"])
        self._col_indicator:   List[float] = list(_DEFAULT_STATE["col_indicator"])
        self._col_extra_lines: List[float] = list(_DEFAULT_STATE["col_extra_lines"])

        # Feature toggles
        self._enable_height_lines: bool = _DEFAULT_STATE["enable_height_lines"]
        self._enable_indicators:   bool = _DEFAULT_STATE["enable_indicators"]
        self._enable_position:     bool = _DEFAULT_STATE["enable_position"]
        self._locked_position:     bool = _DEFAULT_STATE["locked_position"]
        self._vanilla_mode:        bool = False
        self._spline_mode:         bool = False   # Use Catmull-Rom spline interpolation

        # Dragging state
        self._dragging: Optional[str]  = None   # 'p1' | 'p2' | 'both' | None
        self._drag_start_p1: List[float] = [0.0, 0.0]
        self._drag_start_p2: List[float] = [0.0, 0.0]

        # Mouse mapping
        self.mouse_value:      float = 0.0   # 0‥1 mapped position
        self.mouse_on_sim:     bool  = False

        self._load_config()

    # ──────────────────────────────────────────────────────────────────────
    # Config persistence
    # ──────────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if not _CONFIG_PATH.exists():
            return
        try:
            with open(_CONFIG_PATH) as f:
                d = json.load(f)
            for k, v in d.items():
                if hasattr(self, f"_{k}"):
                    setattr(self, f"_{k}", v)
        except Exception as e:
            log.warning(f"Could not load sim config: {e}")

    def _save_config(self) -> None:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        keys = [
            "width", "border_width", "line_width", "global_opacity",
            "extra_line_width", "extra_lines_count",
            "col_text", "col_border", "col_front", "col_back",
            "col_indicator", "col_extra_lines",
            "enable_height_lines", "enable_indicators",
            "enable_position", "locked_position",
        ]
        d = {k: getattr(self, f"_{k}") for k in keys}
        try:
            with open(_CONFIG_PATH, "w") as f:
                json.dump(d, f, indent=2)
        except Exception as e:
            log.warning(f"Could not save sim config: {e}")

    def _reset_to_defaults(self) -> None:
        for k, v in _DEFAULT_STATE.items():
            setattr(self, f"_{k}", list(v) if isinstance(v, list) else v)

    def _center_simulator(self) -> None:
        vp = imgui.get_main_viewport()
        cx = vp.pos.x + vp.size.x * 0.5
        cy = vp.pos.y + vp.size.y * 0.5
        default_len = max(self._width, min(self._width * 3.0, 1000.0))
        self._p1 = [cx - self._width * 0.5, cy - default_len * 0.5]
        self._p2 = [cx - self._width * 0.5, cy + default_len * 0.5]

    # ──────────────────────────────────────────────────────────────────────
    # Public Show entry-point (called from dockable window)
    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player: OFS_Videoplayer,
        script: Optional[Funscript],
    ) -> None:
        """Render controls + draw bar via foreground draw list. Mirrors ``OFS_ScriptSimulator::ShowSimulator``."""
        if not self._initialized:
            self._center_simulator()
            self._initialized = True

        # ── Vanilla mode: simple read-only VSlider ─────────────────────
        if self._vanilla_mode:
            pos = self._get_position(player, script)
            avail = imgui.get_content_region_avail()
            imgui.begin_disabled(True)
            imgui.v_slider_float("##vsim", avail, pos, 0.0, 100.0, "%.0f")
            imgui.end_disabled()
            # Draw bar overlay as usual too so vanilla toggle is obvious
            self._draw_bar(player, script)
            return

        # ── Controls UI ────────────────────────────────────────────────
        self._draw_controls()

        # ── Draggable bar (foreground draw list) ───────────────────────
        if not imgui.is_popup_open("", imgui.PopupFlags_.any_popup):
            self._handle_drag()

        self._draw_bar(player, script)

    # ──────────────────────────────────────────────────────────────────────
    # UI Controls
    # ──────────────────────────────────────────────────────────────────────

    def _draw_controls(self) -> None:
        fh = imgui.get_frame_height()
        half = (imgui.get_content_region_avail().x - imgui.get_style().item_spacing.x) * 0.5

        # Lock checkbox
        _, self._locked_position = imgui.checkbox(
            "Lock" + (" 🔒" if self._locked_position else " 🔓"),
            self._locked_position,
        )

        # Center / Invert
        if imgui.button("Center", ImVec2(half, 0)):
            self._center_simulator()
        imgui.same_line()
        if imgui.button("Invert", ImVec2(-1, 0)):
            self._p1, self._p2 = list(self._p2), list(self._p1)

        # Load / Save config
        if imgui.button("Load config", ImVec2(half, 0)):
            self._load_config()
        imgui.same_line()
        if imgui.button("Save config", ImVec2(-1, 0)):
            self._save_config()

        # Configuration collapsing section
        if imgui.collapsing_header("Configuration"):
            self._draw_config_section()

    def _draw_config_section(self) -> None:
        w = 180

        def _color(label: str, attr: str) -> None:
            col = getattr(self, attr)
            changed, new_col = imgui.color_edit4(label, col)
            if changed:
                setattr(self, attr, list(new_col))

        _color("Text colour",        "_col_text")
        _color("Border colour",      "_col_border")
        _color("Front colour",       "_col_front")
        _color("Back colour",        "_col_back")
        _color("Indicator colour",   "_col_indicator")
        _color("Extra lines colour", "_col_extra_lines")
        imgui.spacing()

        imgui.set_next_item_width(w)
        c, v = imgui.drag_float("Width##sw", self._width, 0.5, 1.0, 1000.0)
        if c: self._width = max(1.0, min(1000.0, v))

        imgui.set_next_item_width(w)
        c, v = imgui.drag_float("Border width##sbw", self._border_width, 0.5, 0.0, 1000.0)
        if c: self._border_width = max(0.0, min(1000.0, v))

        imgui.set_next_item_width(w)
        c, v = imgui.drag_float("Line width##slw", self._line_width, 0.5, 0.5, 100.0)
        if c: self._line_width = max(0.5, v)

        imgui.set_next_item_width(w)
        c, v = imgui.slider_float("Opacity##sop", self._global_opacity, 0.0, 1.0)
        if c: self._global_opacity = max(0.0, min(1.0, v))

        imgui.set_next_item_width(w)
        c, v = imgui.drag_float("Extra line width##selw", self._extra_line_width, 0.5, 0.5, 1000.0)
        if c: self._extra_line_width = max(0.5, min(1000.0, v))

        imgui.set_next_item_width(80)
        c, v = imgui.input_int("Extra lines##selc", self._extra_lines_count, 1, 2)
        if c: self._extra_lines_count = max(0, min(10, v))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Number of extra tick lines above/below 0-100 range")
        imgui.spacing()

        _, self._enable_indicators   = imgui.checkbox("Indicators",    self._enable_indicators)
        imgui.same_line()
        _, self._enable_height_lines = imgui.checkbox("Height lines",  self._enable_height_lines)
        _, self._enable_position     = imgui.checkbox("Show position", self._enable_position)
        _, self._vanilla_mode        = imgui.checkbox("Vanilla mode",  self._vanilla_mode)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Show a simple vertical slider instead")
        _, self._spline_mode         = imgui.checkbox("Spline mode",   self._spline_mode)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Use Catmull-Rom spline interpolation instead of linear")
        imgui.spacing()

        if imgui.button("Reset to defaults##srd", ImVec2(-1, 0)):
            self._reset_to_defaults()

    # ──────────────────────────────────────────────────────────────────────
    # Position calculation
    # ──────────────────────────────────────────────────────────────────────

    def _get_position(self, player: OFS_Videoplayer, script: Optional[Funscript]) -> float:
        if script is None or not player.VideoLoaded():
            return 0.0
        t_ms = player.CurrentTime() * 1000.0
        if self._spline_mode:
            return script.actions.InterpolateSpline(t_ms)
        return script.actions.Interpolate(t_ms)

    # ──────────────────────────────────────────────────────────────────────
    # Drag handling (P1, P2, centre)
    # ──────────────────────────────────────────────────────────────────────

    def _handle_drag(self) -> None:
        if self._locked_position:
            self._dragging = None
            return

        mouse = imgui.get_mouse_pos()
        mx, my = mouse.x, mouse.y

        p1 = tuple(self._p1)
        p2 = tuple(self._p2)
        centre = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)

        d_p1     = _dist2((mx, my), p1)
        d_p2     = _dist2((mx, my), p2)
        d_centre = _dist2((mx, my), centre)
        hw = self._width * 0.5

        near_p1     = d_p1     <= hw
        near_p2     = d_p2     <= hw
        near_centre = d_centre <= hw and not near_p1 and not near_p2

        # Update mouse_value and mouse_on_sim
        if near_p1 or near_p2 or near_centre or self._dragging is not None:
            direction = _norm2(_sub2(p1, p2))
            perp      = _perp2(direction)
            dist      = _dist2(p1, p2)
            if dist > 0:
                # Map mouse onto bar axis
                rel = _sub2((mx, my), p2)
                proj = rel[0] * direction[0] + rel[1] * direction[1]
                self.mouse_value = max(0.0, min(1.0, proj / dist))
                # Bounding box for MouseOnSimulator
                bar_pos  = _mul2(_add2(p1, p2), 0.5)
                pad      = 10.0
                bar_half = dist * 0.5 + pad
                bar_half_w = hw + pad
                self.mouse_on_sim = (
                    abs(proj - dist * 0.5) <= bar_half
                    and abs(rel[0] * perp[0] + rel[1] * perp[1]) <= bar_half_w
                )

        # Show appropriate cursor
        if self._dragging is None:
            if near_p1 or near_p2:
                imgui.set_mouse_cursor(imgui.MouseCursor_.hand)
            elif near_centre:
                imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)

        # Start drag on click (only if no ImGui item is active)
        if imgui.is_mouse_clicked(0) and not imgui.is_any_item_active():
            if near_p1:
                self._dragging = 'p1'
                self._drag_start_p1 = list(self._p1)
            elif near_p2:
                self._dragging = 'p2'
                self._drag_start_p2 = list(self._p2)
            elif near_centre:
                self._dragging = 'both'
                self._drag_start_p1 = list(self._p1)
                self._drag_start_p2 = list(self._p2)

        # Apply drag
        if self._dragging is not None:
            if imgui.is_mouse_down(0):
                delta = imgui.get_mouse_drag_delta(0)
                dx, dy = delta.x, delta.y
                if self._dragging == 'p1':
                    self._p1 = [self._drag_start_p1[0] + dx,
                                self._drag_start_p1[1] + dy]
                elif self._dragging == 'p2':
                    self._p2 = [self._drag_start_p2[0] + dx,
                                self._drag_start_p2[1] + dy]
                else:
                    self._p1 = [self._drag_start_p1[0] + dx,
                                self._drag_start_p1[1] + dy]
                    self._p2 = [self._drag_start_p2[0] + dx,
                                self._drag_start_p2[1] + dy]
            if imgui.is_mouse_released(0):
                self._dragging = None

    # ──────────────────────────────────────────────────────────────────────
    # Draw bar on foreground draw list
    # ──────────────────────────────────────────────────────────────────────

    def _draw_bar(
        self,
        player: OFS_Videoplayer,
        script: Optional[Funscript],
    ) -> None:
        current_pos = self._get_position(player, script)

        fl = imgui.get_foreground_draw_list()
        op = self._global_opacity
        bw = self._border_width
        lw = self._line_width
        w  = self._width

        # Viewport offset (foreground list uses absolute coords)
        vp_off = imgui.get_main_viewport().pos
        off    = (vp_off.x, vp_off.y)

        p1_abs = _add2(off, tuple(self._p1))
        p2_abs = _add2(off, tuple(self._p2))

        direction = _norm2(_sub2(p1_abs, p2_abs))  # from P2 → P1
        perp      = _perp2(direction)

        bar_p1 = _sub2(p1_abs, _mul2(direction, bw * 0.5))
        bar_p2 = _add2(p2_abs, _mul2(direction, bw * 0.5))
        dist   = _dist2(bar_p1, bar_p2)

        if dist < 1.0:
            return

        bar_thick = max(1.0, w - bw + 1.0)
        percent   = max(0.0, min(1.0, current_pos / 100.0))

        # ── Background ─────────────────────────────────────────────────
        fl.add_line(
            _iv2(_add2(bar_p1, _mul2(direction, 1.0))),
            _iv2(_sub2(bar_p2, _mul2(direction, 1.0))),
            _col_u32(self._col_back, op),
            bar_thick,
        )

        # ── Front fill ─────────────────────────────────────────────────
        fl.add_line(
            _iv2(_add2(bar_p2, _mul2(direction, dist * percent))),
            _iv2(bar_p2),
            _col_u32(self._col_front, op),
            bar_thick,
        )

        # ── Border quad ────────────────────────────────────────────────
        if bw > 0.0:
            border_off = _mul2(perp, w * 0.5)
            fl.add_quad(
                _iv2(_sub2(p1_abs, border_off)),
                _iv2(_add2(p1_abs, border_off)),
                _iv2(_add2(p2_abs, border_off)),
                _iv2(_sub2(p2_abs, border_off)),
                _col_u32(self._col_border, op),
                bw,
            )

        # ── Height tick lines (10 % intervals) ─────────────────────────
        if self._enable_height_lines:
            for i in range(1, 10):
                self._draw_tick(fl, bar_p2, direction, perp, dist,
                                i * 10.0, w, bw, op,
                                self._col_extra_lines, lw)

        # ── Extra lines (above/below range) ────────────────────────────
        for i in range(-self._extra_lines_count, 0):
            self._draw_tick(fl, bar_p2, direction, perp, dist,
                            i * 10.0, w, bw, op,
                            self._col_extra_lines, self._extra_line_width)
        for i in range(10, 11 + self._extra_lines_count):
            self._draw_tick(fl, bar_p2, direction, perp, dist,
                            i * 10.0, w, bw, op,
                            self._col_extra_lines, self._extra_line_width)

        # ── Indicators (prev / next action) ────────────────────────────
        if self._enable_indicators and script is not None and player.VideoLoaded():
            t = player.CurrentTime()
            prev_a = script.GetActionAtTime(t, 0.02)
            if prev_a is None:
                prev_a = script.GetPreviousActionBehind(t)
            next_a = script.GetNextActionAhead(t)
            if prev_a is not None and next_a is prev_a:
                next_a = script.GetNextActionAhead(prev_a.at / 1000.0)

            for action in (prev_a, next_a):
                if action is None:
                    continue
                if action.pos <= 0 or action.pos >= 100:
                    continue
                self._draw_indicator(fl, bar_p2, direction, perp, dist,
                                     action.pos, w, bw, op)

        # ── Centre position text ───────────────────────────────────────
        if self._enable_position:
            label = f"{current_pos:.0f}"
            ts    = imgui.calc_text_size(label)
            center_pt = _add2(bar_p2, _mul2(direction, dist * 0.5))
            text_pos  = (center_pt[0] - ts.x * 0.5,
                         center_pt[1] - ts.y * 0.5)
            fl.add_text(_iv2(text_pos), _col_u32(self._col_text, op), label)

    # ──────────────────────────────────────────────────────────────────────
    # Draw helpers
    # ──────────────────────────────────────────────────────────────────────

    def _draw_tick(
        self, fl, bar_p2, direction, perp, dist,
        pos_pct, w, bw, op, col_list, thickness,
    ) -> None:
        centre = _add2(bar_p2, _mul2(direction, dist * pos_pct / 100.0))
        half   = w * 0.5 - bw * 0.5
        fl.add_line(
            _iv2(_sub2(centre, _mul2(perp, half))),
            _iv2(_add2(centre, _mul2(perp, half))),
            _col_u32(col_list, op),
            thickness,
        )

    def _draw_indicator(
        self, fl, bar_p2, direction, perp, dist,
        pos_val, w, bw, op,
    ) -> None:
        centre = _add2(bar_p2, _mul2(direction, dist * pos_val / 100.0))
        half   = w * 0.5 - bw * 0.5
        fl.add_line(
            _iv2(_sub2(centre, _mul2(perp, half))),
            _iv2(_add2(centre, _mul2(perp, half))),
            _col_u32(self._col_indicator, op),
            self._line_width,
        )
        label    = str(int(pos_val))
        ts       = imgui.calc_text_size(label)
        text_pos = (centre[0] - ts.x * 0.5, centre[1] - ts.y * 0.5)
        fl.add_text(_iv2(text_pos), _col_u32(self._col_text, op), label)

