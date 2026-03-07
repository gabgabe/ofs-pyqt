"""
UIColors  --  centralised colour table for the entire application.

Every hardcoded colour in the UI is catalogued here as a named field with
sensible defaults that match the original OFS look.  Preferences can
serialise / deserialise the whole table to JSON and the "Colors" tab
exposes colour-pickers for every entry.

Usage
=====
Rendering code reads ``app.colors.<name>`` (a 4-tuple of RGBA floats 0-1).
Module-level ``_col32()`` calls in *script_timeline.py* are replaced at
runtime by reading from the shared ``UIColors`` instance each frame.
"""

from __future__ import annotations

import json
import copy
from dataclasses import dataclass, field, fields
from typing import Dict, List, Tuple

# Type alias for an RGBA colour (0-1 floats)
RGBA = Tuple[float, float, float, float]


def _rgba(r: float, g: float, b: float, a: float = 1.0) -> List[float]:
    """Convenience  --  returns a mutable list (needed for JSON round-trip)."""
    return [r, g, b, a]


# -----------------------------------------------------------------------------
# Category helpers  --  purely for the preferences tab grouping
# -----------------------------------------------------------------------------

# (field_name, display_label) tuples grouped by category.
# The preferences tab iterates these.

CATEGORY_TIMELINE_BG = "Timeline Background"
CATEGORY_ACTIONS = "Actions & Lines"
CATEGORY_PLAYHEAD = "Playhead & Selection"
CATEGORY_TRACKS = "Track Gradients & Borders"
CATEGORY_SPEED_LINES = "Speed-Based Line Colours"
CATEGORY_OVERLAYS = "Overlays (Waveform, Sync, MaxSpeed)"
CATEGORY_GUIDES = "Guides & Grid"
CATEGORY_DAW = "DAW Mode"
CATEGORY_HEATMAP = "Heatmap"
CATEGORY_SIMULATOR = "Simulator"
CATEGORY_PROGRESS_BAR = "Progress Bar"

COLOR_CATEGORIES: List[tuple] = [
    # (category_name, [(field_name, display_label), ...])
    (CATEGORY_TIMELINE_BG, [
        ("timeline_bg",              "Background"),
    ]),
    (CATEGORY_ACTIONS, [
        ("action_dot",               "Normal dot"),
        ("action_dot_selected",      "Selected dot inner"),
        ("action_dot_selected_ring", "Selected dot ring"),
        ("action_line",              "Connecting line"),
        ("action_line_selected",     "Selected segment line"),
        ("action_line_border",       "Line border (outline)"),
        ("inactive_track_dot",       "Inactive track dot"),
        ("inactive_track_line",      "Inactive track line"),
    ]),
    (CATEGORY_PLAYHEAD, [
        ("playhead",                 "Playhead"),
        ("playhead_shadow",          "Playhead shadow"),
        ("selection_rect",           "Selection box fill"),
        ("selection_rect_border",    "Selection box border"),
    ]),
    (CATEGORY_TRACKS, [
        ("active_track_top",         "Active track gradient (top)"),
        ("active_track_bottom",      "Active track gradient (bottom)"),
        ("inactive_track_top",       "Inactive track gradient (top)"),
        ("inactive_track_bottom",    "Inactive track gradient (bottom)"),
        ("track_hover_highlight",    "Track hover highlight"),
        ("track_border_active",      "Active track border"),
        ("track_border_selected",    "Has-selection border"),
        ("track_border_default",     "Default track border"),
        ("track_title_active",       "Track title (active)"),
        ("track_title_inactive",     "Track title (inactive)"),
    ]),
    (CATEGORY_SPEED_LINES, [
        ("speed_high",               "High speed (>400 u/s)"),
        ("speed_mid",                "Mid speed (150-400 u/s)"),
        ("speed_low",                "Low speed (<150 u/s)"),
    ]),
    (CATEGORY_OVERLAYS, [
        ("sync_line",                "Sync line"),
        ("max_speed_highlight",      "Max-speed highlight"),
        ("waveform_tint",            "Waveform tint"),
    ]),
    (CATEGORY_GUIDES, [
        ("height_guide",             "Height guides (0/25/50/75/100%)"),
        ("frame_tick",               "Frame tick lines"),
        ("tempo_subdivision",        "Tempo subdivision lines"),
        ("tempo_measure_label",      "Tempo measure labels"),
        ("seconds_label",            "Visible-seconds label"),
        ("daw_grid_line",            "DAW clip grid lines"),
    ]),
    (CATEGORY_DAW, [
        ("daw_bg",                   "Background"),
        ("daw_layer_alt",            "Alternating layer row"),
        ("daw_layer_border",         "Layer separator"),
        ("daw_cursor",               "Playhead"),
        ("daw_ruler_bg",             "Ruler background"),
        ("daw_ruler_tick",           "Ruler tick marks"),
        ("daw_ruler_text",           "Ruler labels"),
        ("daw_clip_border",          "Clip border"),
        ("daw_muted_overlay",        "Muted overlay"),
        ("daw_label_bg",             "Label panel background"),
        ("daw_label_text",           "Label text"),
        ("daw_label_muted",          "Label text (muted)"),
        ("daw_locked_overlay",       "Locked overlay tint"),
        ("daw_zoom_label",           "Zoom indicator"),
        ("daw_scrollbar",            "Scrollbar indicator"),
        ("daw_trigger_marker",       "Trigger marker"),
    ]),
    (CATEGORY_HEATMAP, [
        ("heatmap_cold",             "Zero speed (cold)"),
        ("heatmap_warm",             "Mid speed (warm)"),
        ("heatmap_hot",              "Max speed (hot)"),
    ]),
    (CATEGORY_SIMULATOR, [
        ("sim_text",                 "Position text"),
        ("sim_border",               "Bar border"),
        ("sim_front",                "Front fill"),
        ("sim_back",                 "Back fill"),
        ("sim_indicator",            "Prev/next indicator"),
        ("sim_extra_lines",          "Height ticks"),
    ]),
    (CATEGORY_PROGRESS_BAR, [
        ("progress_bg",              "Unfilled background"),
        ("progress_fill",            "Fill"),
        ("progress_cursor",          "Cursor line"),
        ("progress_cursor_shadow",   "Cursor shadow"),
        ("progress_hover",           "Hover position line"),
    ]),
]


class UIColors:
    """Central colour table.  Every colour is stored as ``[R, G, B, A]`` (0-1 floats)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Restore all colours to factory defaults."""
        # -- Timeline Background ------------------------------------------
        self.timeline_bg:               List[float] = _rgba(0.10, 0.10, 0.10, 1.00)

        # -- Actions & Lines ----------------------------------------------
        self.action_dot:                List[float] = _rgba(0.30, 0.70, 0.30, 1.00)
        self.action_dot_selected:       List[float] = _rgba(0.02, 0.99, 0.01, 1.00)
        self.action_dot_selected_ring:  List[float] = _rgba(1.00, 1.00, 1.00, 0.95)
        self.action_line:               List[float] = _rgba(0.30, 0.70, 0.30, 0.50)
        self.action_line_selected:      List[float] = _rgba(0.10, 1.00, 0.10, 0.95)
        self.action_line_border:        List[float] = _rgba(0.00, 0.00, 0.00, 1.00)
        self.inactive_track_dot:        List[float] = _rgba(0.50, 0.50, 0.50, 0.60)
        self.inactive_track_line:       List[float] = _rgba(0.50, 0.50, 0.50, 0.30)

        # -- Playhead & Selection -----------------------------------------
        self.playhead:                  List[float] = _rgba(1.00, 1.00, 1.00, 1.00)
        self.playhead_shadow:           List[float] = _rgba(0.00, 0.00, 0.00, 0.50)
        self.selection_rect:            List[float] = _rgba(0.01, 0.99, 0.81, 0.39)
        self.selection_rect_border:     List[float] = _rgba(0.01, 0.99, 0.81, 0.90)

        # -- Track Gradients & Borders ------------------------------------
        self.active_track_top:          List[float] = _rgba(60/255, 0, 60/255, 1.0)
        self.active_track_bottom:       List[float] = _rgba(24/255, 0, 24/255, 1.0)
        self.inactive_track_top:        List[float] = _rgba(0, 0, 50/255, 1.0)
        self.inactive_track_bottom:     List[float] = _rgba(0, 0, 20/255, 1.0)
        self.track_hover_highlight:     List[float] = _rgba(1.0, 1.0, 1.0, 10/255)
        self.track_border_active:       List[float] = _rgba(0, 180/255, 0, 1.0)
        self.track_border_selected:     List[float] = _rgba(0.37, 0.44, 0.74, 1.0)
        self.track_border_default:      List[float] = _rgba(1.0, 1.0, 1.0, 1.0)
        self.track_title_active:        List[float] = _rgba(0.8, 0.8, 0.8, 0.7)
        self.track_title_inactive:      List[float] = _rgba(0.8, 0.8, 0.8, 0.4)

        # -- Speed-Based Line Colours -------------------------------------
        self.speed_high:                List[float] = _rgba(0.89, 0.26, 0.20, 1.00)
        self.speed_mid:                 List[float] = _rgba(0.91, 0.84, 0.35, 1.00)
        self.speed_low:                 List[float] = _rgba(0.97, 0.40, 0.22, 1.00)

        # -- Overlays ----------------------------------------------------
        self.sync_line:                 List[float] = _rgba(1.0, 0.2, 0.2, 0.8)
        self.max_speed_highlight:       List[float] = _rgba(0.89, 0.10, 0.10, 0.55)
        self.waveform_tint:             List[float] = _rgba(227/255, 66/255, 52/255, 0.42)

        # -- Guides & Grid -----------------------------------------------
        self.height_guide:              List[float] = _rgba(0.30, 0.30, 0.30, 0.50)
        self.frame_tick:                List[float] = _rgba(80/255, 80/255, 80/255, 1.0)
        self.tempo_subdivision:         List[float] = _rgba(1.0, 1.0, 1.0, 0.60)
        self.tempo_measure_label:       List[float] = _rgba(0.9, 0.9, 0.9, 0.8)
        self.seconds_label:             List[float] = _rgba(0.7, 0.7, 0.7, 1.0)
        self.daw_grid_line:             List[float] = _rgba(0.40, 0.40, 0.40, 0.35)
        # -- DAW Mode ----------------------------------------------------
        self.daw_bg:                    List[float] = _rgba(0.08, 0.08, 0.08, 1.00)
        self.daw_layer_alt:             List[float] = _rgba(0.12, 0.12, 0.12, 1.00)
        self.daw_layer_border:          List[float] = _rgba(0.25, 0.25, 0.25, 0.60)
        self.daw_cursor:                List[float] = _rgba(1.00, 0.30, 0.15, 0.95)
        self.daw_ruler_bg:              List[float] = _rgba(0.14, 0.14, 0.14, 1.00)
        self.daw_ruler_tick:            List[float] = _rgba(0.55, 0.55, 0.55, 0.70)
        self.daw_ruler_text:            List[float] = _rgba(0.70, 0.70, 0.70, 0.90)
        self.daw_clip_border:           List[float] = _rgba(1.00, 1.00, 1.00, 0.45)
        self.daw_muted_overlay:         List[float] = _rgba(0.00, 0.00, 0.00, 0.50)
        self.daw_label_bg:              List[float] = _rgba(0.16, 0.16, 0.16, 1.00)
        self.daw_label_text:            List[float] = _rgba(0.85, 0.85, 0.85, 1.00)
        self.daw_label_muted:           List[float] = _rgba(0.55, 0.35, 0.35, 1.00)
        self.daw_locked_overlay:        List[float] = _rgba(0.15, 0.12, 0.0, 0.25)
        self.daw_zoom_label:            List[float] = _rgba(0.5, 0.5, 0.5, 0.8)
        self.daw_scrollbar:             List[float] = _rgba(1.0, 1.0, 1.0, 0.25)
        self.daw_trigger_marker:        List[float] = _rgba(1.0, 0.8, 0.2, 0.9)

        # -- Heatmap -----------------------------------------------------
        self.heatmap_cold:              List[float] = _rgba(0x11/255, 0x11/255, 0xFF/255, 1.0)
        self.heatmap_warm:              List[float] = _rgba(0x11/255, 0xFF/255, 0x11/255, 1.0)
        self.heatmap_hot:               List[float] = _rgba(0xFF/255, 0x44/255, 0x11/255, 1.0)

        # -- Simulator ---------------------------------------------------
        self.sim_text:                  List[float] = _rgba(1.0, 1.0, 1.0, 1.0)
        self.sim_border:                List[float] = _rgba(0.8, 0.8, 0.8, 1.0)
        self.sim_front:                 List[float] = _rgba(0.18, 0.80, 0.18, 1.0)
        self.sim_back:                  List[float] = _rgba(0.10, 0.10, 0.10, 1.0)
        self.sim_indicator:             List[float] = _rgba(0.95, 0.75, 0.10, 1.0)
        self.sim_extra_lines:           List[float] = _rgba(0.50, 0.50, 0.50, 0.60)

        # -- Progress Bar ------------------------------------------------
        self.progress_bg:               List[float] = _rgba(0x50/255, 0x50/255, 0x50/255, 1.0)
        self.progress_fill:             List[float] = _rgba(0xAA/255, 0x5F/255, 0x2D/255, 0xBB/255)
        self.progress_cursor:           List[float] = _rgba(1.0, 1.0, 1.0, 1.0)
        self.progress_cursor_shadow:    List[float] = _rgba(0.0, 0.0, 0.0, 1.0)
        self.progress_hover:            List[float] = _rgba(1.0, 1.0, 1.0, 0x88/255)

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def c(self, name: str) -> Tuple[float, float, float, float]:
        """Return colour *name* as an immutable (R, G, B, A) tuple."""
        v = getattr(self, name)
        return (v[0], v[1], v[2], v[3])

    @staticmethod
    def _all_color_fields() -> List[str]:
        """Return names of all colour fields (everything that is a list of 4 floats)."""
        names = []
        for cat_name, entries in COLOR_CATEGORIES:
            for field_name, _label in entries:
                names.append(field_name)
        return names

    # ---------------------------------------------------------------------
    # Serialisation
    # ---------------------------------------------------------------------

    def to_dict(self) -> Dict[str, List[float]]:
        """Serialise all colours to a JSON-friendly dict."""
        out = {}
        for name in self._all_color_fields():
            val = getattr(self, name, None)
            if val is not None:
                out[name] = list(val)
        return out

    def from_dict(self, d: Dict[str, List[float]]) -> None:
        """Restore colours from a dict (e.g. loaded from JSON)."""
        for name in self._all_color_fields():
            if name in d:
                v = d[name]
                if isinstance(v, list) and len(v) >= 3:
                    while len(v) < 4:
                        v.append(1.0)
                    setattr(self, name, [float(x) for x in v[:4]])

    def clone(self) -> "UIColors":
        """Return a deep copy."""
        c = UIColors()
        c.from_dict(self.to_dict())
        return c
