"""
TrackInfoWindow  --  Inspector panel for the selected DAW track.

Shows and allows editing of:
* Track name
* Start time (offset on the global timeline)   --  moves clip
* Duration (effective clip length on timeline)  --  trims end for VIDEO tracks
* End time  (offset + duration)                 --  moves clip end
* For VIDEO tracks: source duration, trim in / trim out
* For CONTROL_CUE tracks: cue list, selected cue editor with typed params

Logic for VIDEO tracks:
  * Start (+/-)   -> shifts the clip (offset); duration & trim stay.
  * End (+/-)     -> shifts the clip end (offset changes, duration stays).
  * Duration (+/-)-> adjusts how much of the video is shown by trimming
                    the tail (trim_out).  Clamped to [trim_in+0.001 .. media_duration].
  * Trim In (+/-) -> cuts the head of the media; duration shrinks.
  * Trim Out (+/-)-> cuts the tail of the media; duration shrinks.
  * "Trim In -> Cursor" sets trim_in to cursor position in media-local time.
  * "Trim Out -> Cursor" sets trim_out to cursor position in media-local time.
  * "Reset Trim" restores full source range.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.events import EV, OFS_Events
from src.core.timeline import Track, TrackType
from src.core.control_cue import (
    ControlCue, ControlCueTrackData, CueType,
    CUE_TYPE_LABELS, CUE_TYPE_COLORS,
)

if TYPE_CHECKING:
    from src.core.timeline_manager import TimelineManager
    from src.core.device_manager import DeviceManager
    from src.core.routing_matrix import RoutingMatrix

log = logging.getLogger(__name__)

# -- MK-312 register catalogue ------------------------------------------
# (name, address, reg_type, min, max, description)
#   reg_type: "int" -> slider 0-max, "bool" -> checkbox, "mode" -> mode combo,
#            "bitmask" -> raw int (shown as hex)

_MK312_REGISTERS: List[Tuple[str, int, str, int, int, str]] = [
    # -- Channel A / B intensity ------------------------------------
    ("A Level (intensity)",     0x4064, "int",  0, 255, "Channel A output level"),
    ("B Level (intensity)",     0x4065, "int",  0, 255, "Channel B output level"),
    ("Multi-Adjust",            0x420D, "int",  0, 255, "Multi-adjust knob value"),
    # -- Mode -------------------------------------------------------
    ("Current Mode",            0x407B, "mode", 0, 255, "Operating mode register"),
    ("Top Mode",                0x41F3, "mode", 0, 255, "Highest selectable mode"),
    ("Split Mode A",            0x41F5, "mode", 0, 255, "Split: channel A mode"),
    ("Split Mode B",            0x41F6, "mode", 0, 255, "Split: channel B mode"),
    ("Favourite Mode",          0x41F7, "mode", 0, 255, "Favourite mode shortcut"),
    # -- Power / System ---------------------------------------------
    ("Power Level",             0x41F4, "int",  0,   2, "0=Low  1=Normal  2=High"),
    ("ADC Disable Flags",       0x400F, "bitmask", 0, 255, "Bit 0 = disable ADC"),
    ("Output Flags",            0x4083, "bitmask", 0, 255, "Mute / phase / mono flags"),
    ("Debug Enable",            0x4207, "bool", 0,   1, "Enable debug output"),
    # -- Channel A: Gate --------------------------------------------
    ("A Gate Value",            0x4090, "int",  0, 255, "Ch.A gate current value"),
    ("A Gate On Time",          0x4098, "int",  0, 255, "Ch.A gate on time"),
    ("A Gate Off Time",         0x4099, "int",  0, 255, "Ch.A gate off time"),
    ("A Gate Select",           0x409A, "bitmask", 0, 255, "Ch.A gate source"),
    # -- Channel A: Ramp --------------------------------------------
    ("A Ramp Value",            0x409C, "int",  0, 255, "Ch.A ramp current"),
    ("A Ramp Min",              0x409D, "int",  0, 255, "Ch.A ramp minimum"),
    ("A Ramp Max",              0x409E, "int",  0, 255, "Ch.A ramp maximum"),
    ("A Ramp Rate",             0x409F, "int",  0, 255, "Ch.A ramp rate"),
    ("A Ramp Step",             0x40A0, "int",  0, 255, "Ch.A ramp step size"),
    ("A Ramp @ Min Action",     0x40A1, "int",  0, 255, "Ch.A action at ramp min"),
    ("A Ramp @ Max Action",     0x40A2, "int",  0, 255, "Ch.A action at ramp max"),
    ("A Ramp Select",           0x40A3, "bitmask", 0, 255, "Ch.A ramp source"),
    # -- Channel A: Intensity ---------------------------------------
    ("A Intensity Value",       0x40A5, "int",  0, 255, "Ch.A intensity current"),
    ("A Intensity Min",         0x40A6, "int",  0, 255, "Ch.A intensity minimum"),
    ("A Intensity Max",         0x40A7, "int",  0, 255, "Ch.A intensity maximum"),
    ("A Intensity Rate",        0x40A8, "int",  0, 255, "Ch.A intensity rate"),
    ("A Intensity Step",        0x40A9, "int",  0, 255, "Ch.A intensity step"),
    ("A Intensity @ Min",       0x40AA, "int",  0, 255, "Ch.A action at int min"),
    ("A Intensity @ Max",       0x40AB, "int",  0, 255, "Ch.A action at int max"),
    ("A Intensity Select",      0x40AC, "bitmask", 0, 255, "Ch.A intensity source"),
    # -- Channel A: Frequency ---------------------------------------
    ("A Freq Value",            0x40AE, "int",  0, 255, "Ch.A frequency current"),
    ("A Freq Min",              0x40AF, "int",  0, 255, "Ch.A frequency minimum"),
    ("A Freq Max",              0x40B0, "int",  0, 255, "Ch.A frequency maximum"),
    ("A Freq Rate",             0x40B1, "int",  0, 255, "Ch.A frequency rate"),
    ("A Freq Step",             0x40B2, "int",  0, 255, "Ch.A frequency step"),
    ("A Freq @ Min",            0x40B3, "int",  0, 255, "Ch.A action at freq min"),
    ("A Freq @ Max",            0x40B4, "int",  0, 255, "Ch.A action at freq max"),
    ("A Freq Select",           0x40B5, "bitmask", 0, 255, "Ch.A frequency source"),
    # -- Channel A: Width -------------------------------------------
    ("A Width Value",           0x40B7, "int",  0, 255, "Ch.A width current"),
    ("A Width Min",             0x40B8, "int",  0, 255, "Ch.A width minimum"),
    ("A Width Max",             0x40B9, "int",  0, 255, "Ch.A width maximum"),
    ("A Width Rate",            0x40BA, "int",  0, 255, "Ch.A width rate"),
    ("A Width Step",            0x40BB, "int",  0, 255, "Ch.A width step"),
    ("A Width @ Min",           0x40BC, "int",  0, 255, "Ch.A action at width min"),
    ("A Width @ Max",           0x40BD, "int",  0, 255, "Ch.A action at width max"),
    ("A Width Select",          0x40BE, "bitmask", 0, 255, "Ch.A width source"),
    # -- Channel B: Gate --------------------------------------------
    ("B Gate Value",            0x4190, "int",  0, 255, "Ch.B gate current value"),
    ("B Gate On Time",          0x4198, "int",  0, 255, "Ch.B gate on time"),
    ("B Gate Off Time",         0x4199, "int",  0, 255, "Ch.B gate off time"),
    ("B Gate Select",           0x419A, "bitmask", 0, 255, "Ch.B gate source"),
    # -- Channel B: Ramp --------------------------------------------
    ("B Ramp Value",            0x419C, "int",  0, 255, "Ch.B ramp current"),
    ("B Ramp Min",              0x419D, "int",  0, 255, "Ch.B ramp minimum"),
    ("B Ramp Max",              0x419E, "int",  0, 255, "Ch.B ramp maximum"),
    ("B Ramp Rate",             0x419F, "int",  0, 255, "Ch.B ramp rate"),
    ("B Ramp Step",             0x41A0, "int",  0, 255, "Ch.B ramp step size"),
    ("B Ramp @ Min Action",     0x41A1, "int",  0, 255, "Ch.B action at ramp min"),
    ("B Ramp @ Max Action",     0x41A2, "int",  0, 255, "Ch.B action at ramp max"),
    ("B Ramp Select",           0x41A3, "bitmask", 0, 255, "Ch.B ramp source"),
    # -- Channel B: Intensity ---------------------------------------
    ("B Intensity Value",       0x41A5, "int",  0, 255, "Ch.B intensity current"),
    ("B Intensity Min",         0x41A6, "int",  0, 255, "Ch.B intensity minimum"),
    ("B Intensity Max",         0x41A7, "int",  0, 255, "Ch.B intensity maximum"),
    ("B Intensity Rate",        0x41A8, "int",  0, 255, "Ch.B intensity rate"),
    ("B Intensity Step",        0x41A9, "int",  0, 255, "Ch.B intensity step"),
    ("B Intensity @ Min",       0x41AA, "int",  0, 255, "Ch.B action at int min"),
    ("B Intensity @ Max",       0x41AB, "int",  0, 255, "Ch.B action at int max"),
    ("B Intensity Select",      0x41AC, "bitmask", 0, 255, "Ch.B intensity source"),
    # -- Channel B: Frequency ---------------------------------------
    ("B Freq Value",            0x41AE, "int",  0, 255, "Ch.B frequency current"),
    ("B Freq Min",              0x41AF, "int",  0, 255, "Ch.B frequency minimum"),
    ("B Freq Max",              0x41B0, "int",  0, 255, "Ch.B frequency maximum"),
    ("B Freq Rate",             0x41B1, "int",  0, 255, "Ch.B frequency rate"),
    ("B Freq Step",             0x41B2, "int",  0, 255, "Ch.B frequency step"),
    ("B Freq @ Min",            0x41B3, "int",  0, 255, "Ch.B action at freq min"),
    ("B Freq @ Max",            0x41B4, "int",  0, 255, "Ch.B action at freq max"),
    ("B Freq Select",           0x41B5, "bitmask", 0, 255, "Ch.B frequency source"),
    # -- Channel B: Width -------------------------------------------
    ("B Width Value",           0x41B7, "int",  0, 255, "Ch.B width current"),
    ("B Width Min",             0x41B8, "int",  0, 255, "Ch.B width minimum"),
    ("B Width Max",             0x41B9, "int",  0, 255, "Ch.B width maximum"),
    ("B Width Rate",            0x41BA, "int",  0, 255, "Ch.B width rate"),
    ("B Width Step",            0x41BB, "int",  0, 255, "Ch.B width step"),
    ("B Width @ Min",           0x41BC, "int",  0, 255, "Ch.B action at width min"),
    ("B Width @ Max",           0x41BD, "int",  0, 255, "Ch.B action at width max"),
    ("B Width Select",          0x41BE, "bitmask", 0, 255, "Ch.B width source"),
    # -- Advanced panel ---------------------------------------------
    ("Adv: Ramp Level",         0x41F8, "int",  0, 255, "Advanced: ramp level"),
    ("Adv: Ramp Time",          0x41F9, "int",  0, 255, "Advanced: ramp time"),
    ("Adv: Depth",              0x41FA, "int",  0, 255, "Advanced: depth"),
    ("Adv: Tempo",              0x41FB, "int",  0, 255, "Advanced: tempo"),
    ("Adv: Frequency",          0x41FC, "int",  0, 255, "Advanced: frequency"),
    ("Adv: Effect",             0x41FD, "int",  0, 255, "Advanced: effect"),
    ("Adv: Width",              0x41FE, "int",  0, 255, "Advanced: width"),
    ("Adv: Pace",               0x41FF, "int",  0, 255, "Advanced: pace"),
    # -- Misc / System ----------------------------------------------
    ("Multi-Adjust Offset",     0x4061, "int",  0, 255, "Multi-adjust offset"),
    ("MA Min Value",            0x4086, "int",  0, 255, "MA knob minimum"),
    ("MA Max Value",            0x4087, "int",  0, 255, "MA knob maximum"),
    ("Command Reg 1",           0x4070, "int",  0, 255, "Command register 1"),
    ("Command Reg 2",           0x4071, "int",  0, 255, "Command register 2"),
    ("Menu Item",               0x4078, "int",  0, 255, "Currently displayed menu item"),
    ("LCD Write Param",         0x4180, "int",  0, 255, "LCD write parameter"),
    ("Cmd Param 1",             0x4182, "int",  0, 255, "Command parameter 1"),
    ("Cmd Param 2",             0x4183, "int",  0, 255, "Command parameter 2"),
    # -- Custom (raw hex) -------------------------------------------
    ("Custom (raw address)",    0x0000, "raw",  0, 255, "Enter any hex address manually"),
]

# Fast lookup: address -> index in _MK312_REGISTERS
_MK312_REG_BY_ADDR: Dict[int, int] = {
    entry[1]: i for i, entry in enumerate(_MK312_REGISTERS)
}
# Labels for the combo (cached once)
_MK312_REG_LABELS: List[str] = [
    f"{name}  (0x{addr:04X})" for name, addr, *_ in _MK312_REGISTERS
]

# MK-312 operating modes
_MK312_MODES: List[Tuple[str, int]] = [
    ("Waves",    0x76),
    ("Stroke",   0x77),
    ("Climb",    0x78),
    ("Combo",    0x79),
    ("Intense",  0x7A),
    ("Rhythm",   0x7B),
    ("Audio 1",  0x7C),
    ("Audio 2",  0x7D),
    ("Audio 3",  0x7E),
    ("Split",    0x7F),
    ("Random 1", 0x80),
    ("Random 2", 0x81),
    ("Toggle",   0x82),
    ("Orgasm",   0x83),
    ("Torment",  0x84),
    ("Phase 1",  0x85),
    ("Phase 2",  0x86),
    ("Phase 3",  0x87),
    ("User 1",   0x88),
    ("User 2",   0x89),
    ("User 3",   0x8A),
    ("User 4",   0x8B),
    ("User 5",   0x8C),
    ("User 6",   0x8D),
    ("User 7",   0x8E),
]
_MK312_MODE_LABELS: List[str] = [
    f"{name}  (0x{val:02X})" for name, val in _MK312_MODES
]
_MK312_MODE_BY_VAL: Dict[int, int] = {
    val: i for i, (_, val) in enumerate(_MK312_MODES)
}

# Colour palette  --  same swatches as the Add Track wizard
_TRACK_PALETTE = [
    (0.55, 0.27, 0.68, 1.0),  # purple
    (0.27, 0.55, 0.68, 1.0),  # teal
    (0.68, 0.55, 0.27, 1.0),  # amber
    (0.27, 0.68, 0.40, 1.0),  # green
    (0.68, 0.27, 0.40, 1.0),  # rose
    (0.40, 0.68, 0.27, 1.0),  # lime
    (0.85, 0.35, 0.20, 1.0),  # orange
    (0.20, 0.40, 0.85, 1.0),  # blue
    (0.85, 0.20, 0.55, 1.0),  # magenta
    (0.20, 0.75, 0.75, 1.0),  # cyan
    (0.90, 0.75, 0.15, 1.0),  # gold
    (0.50, 0.50, 0.50, 1.0),  # grey
]


def _fmt_mmss(t: float) -> str:
    """Format seconds as ``MM:SS.mmm``."""
    m = int(t) // 60
    s = t - m * 60
    return f"{m:02d}:{s:06.3f}"


# -- Float-field helper ------------------------------------------------
# imgui.input_float returns True on every value change (including +/-
# button clicks).  We commit immediately so the step buttons work.

def _field_float(label: str, value: float, step: float = 0.1,
                 fmt: str = "%.3f s", min_v: float = 0.0,
                 max_v: float = 0.0) -> tuple[bool, float]:
    """Render an input_float and return (changed, new_value).

    Commits on every change so +/- step buttons take effect instantly.
    If *max_v* > *min_v*, clamps the result into [min_v, max_v].
    Otherwise only clamps to >= min_v.
    """
    ch, nv = imgui.input_float(label, value, step, step * 10.0, fmt)
    if ch:
        if max_v > min_v:
            nv = max(min_v, min(nv, max_v))
        else:
            nv = max(min_v, nv)
        return True, nv
    return False, value


class TrackInfoWindow:
    """Track inspector panel drawn inside a dockable window."""

    WindowId = "Track Info###TrackInfo"

    def __init__(self) -> None:
        self._selected_track_id: Optional[str] = None

        # -- Control-cue editing state ---------------------------------
        self._sel_cue_id: Optional[str] = None   # currently selected cue
        self._cue_edit_name: str = ""
        self._cue_edit_type: int = 0
        self._cue_edit_time: float = 0.0
        self._cue_edit_color: List[float] = [0.2, 0.7, 1.0, 0.9]
        self._cue_edit_notes: str = ""
        # Type-specific param fields
        self._cue_p_device_id: str = ""       # PARAMETER / MODE_CHANGE
        self._cue_p_reg_idx: int = 0           # PARAMETER: index into _MK312_REGISTERS
        self._cue_p_reg_filter: str = ""       # PARAMETER: register search filter text
        self._cue_p_raw_addr: str = ""         # PARAMETER: raw hex addr (for "Custom")
        self._cue_p_int_value: int = 0         # PARAMETER: integer value
        self._cue_p_bool_value: bool = False   # PARAMETER: boolean value
        self._cue_p_mode_idx: int = 0          # PARAMETER+MODE_CHANGE: mode combo idx
        # Multi-parameter entries: list of dicts:
        #   {"reg_idx": int, "raw_addr": str, "int_value": int,
        #    "bool_value": bool, "mode_idx": int}
        self._cue_p_entries: List[Dict[str, Any]] = []
        self._cue_p_osc_path: str = ""        # OSC_COMMAND
        self._cue_p_osc_args: str = ""        # OSC_COMMAND (JSON array)
        self._cue_p_ws_id: str = ""           # WS_MESSAGE
        self._cue_p_ws_payload: str = ""      # WS_MESSAGE (JSON)
        self._cue_p_mode: str = ""            # MODE_CHANGE (legacy)

    # -- Public API ----------------------------------------------------

    def SelectTrack(self, track_id: Optional[str]) -> None:
        """Set which track is inspected (called from DAW interaction)."""
        self._selected_track_id = track_id

    # -- Draw ----------------------------------------------------------

    def Show(self, timeline_mgr: "TimelineManager",
             device_mgr: Optional["DeviceManager"] = None,
             routing: Optional["RoutingMatrix"] = None) -> None:
        """Render the Track Info contents (called inside a docked window)."""
        tl = timeline_mgr.timeline

        # Resolve selected track
        trk: Optional[Track] = None
        if self._selected_track_id:
            result = tl.FindTrack(self._selected_track_id)
            if result:
                _layer, trk = result

        if trk is None:
            imgui.text_disabled("No track selected")
            imgui.separator()
            imgui.text_disabled("Click on a track in the DAW timeline to inspect it.")
            return

        changed = False
        is_video = trk.track_type == TrackType.VIDEO

        # -- Track name -------------------------------------------------
        imgui.text("Track")
        imgui.same_line()
        imgui.set_next_item_width(-1)
        ch, new_name = imgui.input_text("##trk_name", trk.name, 64)
        if ch:
            trk.name = new_name
            changed = True

        imgui.separator()

        # -- Type badge -------------------------------------------------
        type_labels = {
            TrackType.VIDEO: "VIDEO",
            TrackType.FUNSCRIPT: "FUNSCRIPT",
            TrackType.TRIGGER: "TRIGGER",
            TrackType.CONTROL_CUE: "CONTROL CUE",
        }
        imgui.text(f"Type: {type_labels.get(trk.track_type, '?')}")
        imgui.spacing()

        is_cue = trk.track_type == TrackType.CONTROL_CUE

        # -- Time fields ------------------------------------------------
        col_w = imgui.get_content_region_avail().x
        field_w = max(80.0, col_w - 100.0)

        # For VIDEO tracks we need the source duration to clamp everything
        md = trk.media_duration if (is_video and trk.media_duration > 0) else 0.0

        # -- Start (offset) ---------------------------------------------
        # +/- moves the clip on the timeline; duration stays.
        imgui.text("Start")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        ch, nv = _field_float("##trk_start", trk.offset, 0.1)
        if ch:
            trk.offset = max(0.0, nv)
            changed = True

        # -- Duration -----------------------------------------------
        # For VIDEO: changing duration trims the tail (adjusts trim_out).
        imgui.text("Duration")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        max_dur = (md - trk.trim_in) if (is_video and md > 0) else 0.0
        ch, nv = _field_float("##trk_dur", trk.duration, 0.1,
                              min_v=0.001, max_v=max_dur if max_dur > 0 else 0.0)
        if ch:
            nv = max(0.001, nv)
            if is_video and md > 0:
                nv = min(nv, md - trk.trim_in)
                trk.trim_out = trk.trim_in + nv
            trk.duration = nv
            changed = True

        # -- End (offset + duration) ------------------------------------
        # +/- moves the clip end; that shifts offset while keeping duration.
        end_t = trk.offset + trk.duration
        imgui.text("End")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        ch, nv = _field_float("##trk_end", end_t, 0.1)
        if ch:
            new_end = max(trk.duration, nv)  # end can't be < duration (offset>=0)
            trk.offset = max(0.0, new_end - trk.duration)
            changed = True

        # -- VIDEO-specific trim fields ---------------------------------
        if is_video and md > 0:
            imgui.spacing()
            imgui.separator()
            imgui.text("Media Trim")
            imgui.spacing()

            # Source duration (read-only)
            imgui.text("Source")
            imgui.same_line(100)
            imgui.text(f"{_fmt_mmss(md)}  ({md:.3f} s)")

            # Trim In
            imgui.text("Trim In")
            imgui.same_line(100)
            imgui.set_next_item_width(field_w)
            ch, nv = _field_float("##trk_trim_in", trk.trim_in, 0.1,
                                  min_v=0.0, max_v=trk.trim_out - 0.001)
            if ch:
                trk.trim_in = nv
                trk.duration = trk.trim_out - trk.trim_in
                changed = True

            # Trim Out
            imgui.text("Trim Out")
            imgui.same_line(100)
            imgui.set_next_item_width(field_w)
            ch, nv = _field_float("##trk_trim_out", trk.trim_out, 0.1,
                                  min_v=trk.trim_in + 0.001, max_v=md)
            if ch:
                trk.trim_out = nv
                trk.duration = trk.trim_out - trk.trim_in
                changed = True

            # -- Quick trim buttons -------------------------------------
            imgui.spacing()
            if imgui.button("Reset Trim"):
                trk.trim_in = 0.0
                trk.trim_out = md
                trk.duration = md
                changed = True

            imgui.same_line()
            if imgui.button("Trim In \u2192 Cursor"):
                tp_pos = timeline_mgr.transport.position
                media_t = trk.GlobalToMedia(tp_pos)
                media_t = max(0.0, min(media_t, trk.trim_out - 0.001))
                trk.trim_in = media_t
                trk.duration = trk.trim_out - trk.trim_in
                changed = True

            imgui.same_line()
            if imgui.button("Trim Out \u2192 Cursor"):
                tp_pos = timeline_mgr.transport.position
                media_t = trk.GlobalToMedia(tp_pos)
                media_t = max(trk.trim_in + 0.001, min(media_t, md))
                trk.trim_out = media_t
                trk.duration = trk.trim_out - trk.trim_in
                changed = True

        # -- Control Cue inspector --------------------------------------
        if is_cue and trk.control_cue_data:
            self._draw_cue_section(trk, timeline_mgr, device_mgr, routing, field_w)

        # -- Colour -----------------------------------------------------
        imgui.spacing()
        imgui.separator()
        imgui.text("Colour")
        imgui.same_line(100)
        r, g, b, a = trk.color[:4]

        # Colour button  --  clicking opens a popup with picker + palette
        if imgui.color_button("##trk_col_btn", ImVec4(r, g, b, 1.0),
                              imgui.ColorEditFlags_.no_tooltip, ImVec2(26, 26)):
            imgui.open_popup("##trk_color_popup")

        if imgui.begin_popup("##trk_color_popup"):
            # Colour picker
            ch, (r, g, b) = imgui.color_picker3(
                "##trk_picker", (r, g, b),
                imgui.ColorEditFlags_.no_side_preview
                | imgui.ColorEditFlags_.no_small_preview)
            if ch:
                trk.color = (r, g, b, a)
                changed = True

            # -- Palette swatches inside the popup ----------------------
            imgui.spacing()
            imgui.separator()
            imgui.text("Palette")
            COLS_PER_ROW = 6
            for i, c in enumerate(_TRACK_PALETTE):
                if i % COLS_PER_ROW != 0:
                    imgui.same_line()
                pr, pg, pb, pa = c
                is_match = (abs(r - pr) < 0.02 and abs(g - pg) < 0.02
                            and abs(b - pb) < 0.02)
                if is_match:
                    imgui.push_style_color(imgui.Col_.button, ImVec4(pr, pg, pb, pa))
                    imgui.push_style_color(imgui.Col_.button_hovered, ImVec4(pr, pg, pb, pa))
                    imgui.push_style_color(imgui.Col_.button_active, ImVec4(pr, pg, pb, pa))
                    imgui.push_style_color(imgui.Col_.border, ImVec4(1.0, 1.0, 1.0, 1.0))
                    imgui.push_style_var(imgui.StyleVar_.frame_border_size, 2.0)
                else:
                    imgui.push_style_color(imgui.Col_.button, ImVec4(pr, pg, pb, pa))
                    imgui.push_style_color(imgui.Col_.button_hovered,
                                           ImVec4(min(1, pr + 0.15), min(1, pg + 0.15),
                                                  min(1, pb + 0.15), pa))
                    imgui.push_style_color(imgui.Col_.button_active, ImVec4(pr, pg, pb, pa))
                if imgui.button(f"##ti_pal{i}", ImVec2(28, 28)):
                    trk.color = (pr, pg, pb, a)
                    r, g, b = pr, pg, pb
                    changed = True
                if is_match:
                    imgui.pop_style_var()
                    imgui.pop_style_color(4)
                else:
                    imgui.pop_style_color(3)
            imgui.end_popup()

        if changed:
            EV.dispatch(OFS_Events.TIMELINE_LAYOUT_CHANGED)

    # -- Control-cue helpers -------------------------------------------

    def _load_cue_into_editor(self, cue: ControlCue) -> None:
        """Copy a cue's fields into the editor state variables."""
        self._sel_cue_id = cue.cue_id
        self._cue_edit_name = cue.name
        self._cue_edit_type = int(cue.cue_type)
        self._cue_edit_time = cue.time
        self._cue_edit_color = list(cue.color)
        self._cue_edit_notes = cue.notes
        p = cue.params
        ct = cue.cue_type
        if ct == CueType.PARAMETER:
            self._cue_p_device_id = p.get("device_instance_id", "")
            # Load multi-entry list
            entries_raw = p.get("entries", [])
            if entries_raw:
                self._cue_p_entries = []
                for e in entries_raw:
                    self._cue_p_entries.append(
                        self._addr_val_to_entry(
                            int(e.get("address", 0)),
                            int(e.get("value", 0))))
            else:
                # Legacy single-entry -> convert to entries list
                addr = int(p.get("address", 0))
                val = int(p.get("value", 0))
                self._cue_p_entries = [self._addr_val_to_entry(addr, val)]
            # Keep first entry mirrored to the single-field variables for compat
            if self._cue_p_entries:
                e0 = self._cue_p_entries[0]
                self._cue_p_reg_idx = e0.get("reg_idx", 0)
                self._cue_p_raw_addr = e0.get("raw_addr", "")
                self._cue_p_int_value = e0.get("int_value", 0)
                self._cue_p_bool_value = e0.get("bool_value", False)
                self._cue_p_mode_idx = e0.get("mode_idx", 0)
        elif ct == CueType.OSC_COMMAND:
            self._cue_p_osc_path = p.get("path", "")
            self._cue_p_osc_args = json.dumps(p.get("args", []))
        elif ct == CueType.WS_MESSAGE:
            self._cue_p_ws_id = p.get("ws_instance_id", "")
            self._cue_p_ws_payload = json.dumps(p.get("payload", {}), indent=2)
        elif ct == CueType.MODE_CHANGE:
            self._cue_p_device_id = p.get("device_instance_id", "")
            mode_val = p.get("mode", 0)
            try:
                mode_int = int(mode_val)
            except (ValueError, TypeError):
                mode_int = 0
            self._cue_p_mode_idx = _MK312_MODE_BY_VAL.get(mode_int, 0)
            self._cue_p_mode = str(mode_val)

    @staticmethod
    def _addr_val_to_entry(addr: int, val: int) -> Dict[str, Any]:
        """Convert an (address, value) pair to an editor entry dict."""
        reg_idx = _MK312_REG_BY_ADDR.get(addr, len(_MK312_REGISTERS) - 1)
        _name, _a, rtype, _mn, _mx, _desc = _MK312_REGISTERS[reg_idx]
        raw_addr = f"0x{addr:04X}" if rtype == "raw" else ""
        bool_value = bool(val) if rtype == "bool" else False
        mode_idx = _MK312_MODE_BY_VAL.get(val, 0) if rtype == "mode" else 0
        return {
            "reg_idx": reg_idx,
            "raw_addr": raw_addr,
            "int_value": val,
            "bool_value": bool_value,
            "mode_idx": mode_idx,
            "filter": "",  # search filter for this entry's combo
        }

    @staticmethod
    def _entry_to_addr_val(entry: Dict[str, Any]) -> Tuple[int, int]:
        """Convert an editor entry dict back to (address, value)."""
        reg_idx = entry.get("reg_idx", 0)
        _name, reg_addr, rtype, _mn, _mx, _desc = _MK312_REGISTERS[reg_idx]
        if rtype == "raw":
            try:
                addr = int(entry.get("raw_addr", "0"), 0)
            except (ValueError, TypeError):
                addr = 0
        else:
            addr = reg_addr
        if rtype == "bool":
            val = 1 if entry.get("bool_value", False) else 0
        elif rtype == "mode":
            midx = entry.get("mode_idx", 0)
            if 0 <= midx < len(_MK312_MODES):
                val = _MK312_MODES[midx][1]
            else:
                val = entry.get("int_value", 0)
        else:
            val = entry.get("int_value", 0)
        return addr, val

    def _save_editor_to_cue(self, cue: ControlCue) -> None:
        """Write editor state back into a cue object."""
        cue.name = self._cue_edit_name
        cue.cue_type = CueType(self._cue_edit_type)
        cue.time = max(0.0, self._cue_edit_time)
        cue.color = tuple(self._cue_edit_color)
        cue.notes = self._cue_edit_notes

        ct = cue.cue_type
        if ct == CueType.PARAMETER:
            # Build entries list from multi-entry editor
            entries = []
            for entry in self._cue_p_entries:
                addr, val = self._entry_to_addr_val(entry)
                entries.append({"address": addr, "value": val})
            if entries:
                # Also keep legacy single-entry fields for backward compat
                cue.params = {
                    "device_instance_id": self._cue_p_device_id,
                    "address": entries[0]["address"],
                    "value": entries[0]["value"],
                    "entries": entries,
                }
            else:
                cue.params = {"device_instance_id": self._cue_p_device_id}
        elif ct == CueType.OSC_COMMAND:
            try:
                args = json.loads(self._cue_p_osc_args)
            except json.JSONDecodeError:
                args = []
            cue.params = {"path": self._cue_p_osc_path, "args": args}
        elif ct == CueType.WS_MESSAGE:
            try:
                payload = json.loads(self._cue_p_ws_payload)
            except json.JSONDecodeError:
                payload = {}
            cue.params = {
                "ws_instance_id": self._cue_p_ws_id,
                "payload": payload,
            }
        elif ct == CueType.MODE_CHANGE:
            if 0 <= self._cue_p_mode_idx < len(_MK312_MODES):
                mode_val = _MK312_MODES[self._cue_p_mode_idx][1]
            else:
                mode_val = 0
            cue.params = {
                "device_instance_id": self._cue_p_device_id,
                "mode": mode_val,
            }

    def _test_fire_cue(self, cue: ControlCue,
                       timeline_mgr: "TimelineManager") -> None:
        """Immediately fire a cue via the CueEngine (bypass playhead)."""
        engine = timeline_mgr.cue_engine
        log.info(f"[TrackInfo] TEST FIRE cue '{cue.name}' "
                 f"type={cue.cue_type.name}  params={cue.params}")
        engine._execute(cue)

    def _get_device_list(
        self,
        device_mgr: Optional["DeviceManager"],
        routing: Optional["RoutingMatrix"],
    ) -> List[Tuple[str, str]]:
        """Return (instance_id, label) list of all known device instances."""
        items: List[Tuple[str, str]] = []
        if routing:
            for did, inst in routing.devices.items():
                items.append((did, inst.name or did))
        elif device_mgr:
            for did, be in device_mgr._backends.items():
                items.append((did, be.name or did))
        return sorted(items, key=lambda x: x[1])

    def _get_ws_output_list(
        self,
        device_mgr: Optional["DeviceManager"],
        routing: Optional["RoutingMatrix"],
    ) -> List[Tuple[str, str]]:
        """Return (ws_instance_id, label) list of WS outputs."""
        items: List[Tuple[str, str]] = []
        if routing:
            for wid, inst in routing.ws_outputs.items():
                items.append((wid, getattr(inst, "name", wid)))
        elif device_mgr:
            for wid, be in device_mgr._ws_outs.items():
                items.append((wid, be.name or wid))
        return sorted(items, key=lambda x: x[1])

    # -- Main cue section drawn inside Show() --------------------------

    def _draw_cue_section(
        self,
        trk: Track,
        timeline_mgr: "TimelineManager",
        device_mgr: Optional["DeviceManager"],
        routing: Optional["RoutingMatrix"],
        field_w: float,
    ) -> None:
        """Draw the control-cue list + editor for a CONTROL_CUE track."""
        cue_data: ControlCueTrackData = trk.control_cue_data
        if not cue_data:
            return

        imgui.spacing()
        imgui.separator()
        imgui.text_colored(ImVec4(0.5, 0.8, 1.0, 1.0), "Control Cues")
        imgui.spacing()

        # -- Cue list table ---------------------------------------------
        n_cues = len(cue_data.cues)
        imgui.text(f"{n_cues} cue{'s' if n_cues != 1 else ''} on this track")

        list_h = min(150.0, max(60.0, n_cues * 22.0 + 4))
        imgui.begin_child("##cue_list", ImVec2(-1, list_h), child_flags=imgui.ChildFlags_.borders)
        for cue in cue_data.cues:
            cr, cg, cb, ca = cue.color[:4]
            is_sel = (cue.cue_id == self._sel_cue_id)

            # Colour dot
            dl = imgui.get_window_draw_list()
            cur = imgui.get_cursor_screen_pos()
            dot_col = imgui.get_color_u32(ImVec4(cr, cg, cb, ca))
            dl.add_circle_filled(ImVec2(cur.x + 6, cur.y + 9), 4.0, dot_col)
            imgui.dummy(ImVec2(14, 0))
            imgui.same_line()

            # Selectable row
            label = f"{_fmt_mmss(cue.time)}  {cue.name}##cue_{cue.cue_id}"
            clicked, _ = imgui.selectable(label, is_sel,
                                          imgui.SelectableFlags_.none,
                                          ImVec2(0, 18))
            if clicked:
                self._load_cue_into_editor(cue)
        imgui.end_child()

        # -- Add cue button ---------------------------------------------
        if imgui.button("+ Add Cue##ti_add_cue"):
            pos = timeline_mgr.transport.position
            # Convert global position to track-local time
            local_t = max(0.0, pos - trk.offset)
            new_cue = ControlCue(
                name="New Cue",
                cue_type=CueType.PARAMETER,
                time=local_t,
                color=CUE_TYPE_COLORS[CueType.PARAMETER],
            )
            cue_data.add_cue(new_cue)
            self._load_cue_into_editor(new_cue)
            EV.dispatch(OFS_Events.TIMELINE_LAYOUT_CHANGED)

        # -- Selected cue editor ----------------------------------------
        sel_cue: Optional[ControlCue] = None
        if self._sel_cue_id:
            for c in cue_data.cues:
                if c.cue_id == self._sel_cue_id:
                    sel_cue = c
                    break
            if sel_cue is None:
                self._sel_cue_id = None

        if sel_cue is None:
            imgui.spacing()
            imgui.text_disabled("Select a cue above to edit it.")
            return

        imgui.spacing()
        imgui.separator()
        imgui.text_colored(ImVec4(0.9, 0.8, 0.3, 1.0), "Edit Cue")
        imgui.spacing()

        dirty = False

        # Name
        imgui.text("Name")
        imgui.same_line(70)
        imgui.set_next_item_width(-1)
        ch, self._cue_edit_name = imgui.input_text(
            "##ti_cue_name", self._cue_edit_name)
        if ch:
            dirty = True

        # Type combo
        type_labels_list = [CUE_TYPE_LABELS[CueType(i)]
                            for i in range(len(CueType))]
        imgui.text("Type")
        imgui.same_line(70)
        imgui.set_next_item_width(-1)
        ch_type, self._cue_edit_type = imgui.combo(
            "##ti_cue_type", self._cue_edit_type, type_labels_list)
        if ch_type:
            # Auto-update colour when type changes
            ct = CueType(self._cue_edit_type)
            self._cue_edit_color = list(CUE_TYPE_COLORS.get(
                ct, (0.5, 0.5, 0.5, 0.9)))
            # Clear type-specific fields
            self._cue_p_device_id = ""
            self._cue_p_reg_idx = 0
            self._cue_p_raw_addr = ""
            self._cue_p_int_value = 0
            self._cue_p_bool_value = False
            self._cue_p_mode_idx = 0
            self._cue_p_osc_path = ""
            self._cue_p_osc_args = "[]"
            self._cue_p_ws_id = ""
            self._cue_p_ws_payload = "{}"
            self._cue_p_mode = ""
            dirty = True

        # Time
        imgui.text("Time")
        imgui.same_line(70)
        imgui.set_next_item_width(field_w)
        ch_t, self._cue_edit_time = imgui.input_float(
            "##ti_cue_time", self._cue_edit_time, 0.01, 0.1, "%.3f s")
        if ch_t:
            dirty = True

        # Color
        imgui.text("Color")
        imgui.same_line(70)
        ch_col, self._cue_edit_color = imgui.color_edit4(
            "##ti_cue_col", self._cue_edit_color,
            imgui.ColorEditFlags_.no_inputs)
        if ch_col:
            dirty = True

        # -- Type-specific parameters -----------------------------------
        imgui.spacing()
        imgui.separator()
        ct = CueType(self._cue_edit_type)
        imgui.text_colored(ImVec4(0.6, 0.8, 0.6, 1.0),
                           f"Parameters - {CUE_TYPE_LABELS[ct]}")
        imgui.spacing()

        if ct == CueType.PARAMETER:
            dirty |= self._draw_param_fields_parameter(device_mgr, routing)
        elif ct == CueType.OSC_COMMAND:
            dirty |= self._draw_param_fields_osc()
        elif ct == CueType.WS_MESSAGE:
            dirty |= self._draw_param_fields_ws(device_mgr, routing)
        elif ct == CueType.MODE_CHANGE:
            dirty |= self._draw_param_fields_mode(device_mgr, routing)

        # Notes
        imgui.spacing()
        imgui.text("Notes")
        ch_n, self._cue_edit_notes = imgui.input_text_multiline(
            "##ti_cue_notes", self._cue_edit_notes,
            ImVec2(-1, 45))
        if ch_n:
            dirty = True

        # -- Apply / Test / Delete buttons ------------------------------
        imgui.spacing()
        if imgui.button("Apply##ti_cue_apply", ImVec2(70, 0)):
            self._save_editor_to_cue(sel_cue)
            cue_data.cues.sort(key=lambda c: c.time)
            EV.dispatch(OFS_Events.TIMELINE_LAYOUT_CHANGED)

        imgui.same_line()
        if imgui.button("Dup##ti_cue_dup", ImVec2(50, 0)):
            new_c = sel_cue.duplicate(time_offset=0.5)
            cue_data.add_cue(new_c)
            self._load_cue_into_editor(new_c)
            EV.dispatch(OFS_Events.TIMELINE_LAYOUT_CHANGED)

        imgui.same_line()
        imgui.push_style_color(imgui.Col_.button, ImVec4(0.15, 0.45, 0.65, 1.0))
        imgui.push_style_color(imgui.Col_.button_hovered, ImVec4(0.20, 0.55, 0.80, 1.0))
        if imgui.button("> Test##ti_cue_test", ImVec2(70, 0)):
            # Save current editor state first, then fire via CueEngine
            self._save_editor_to_cue(sel_cue)
            self._test_fire_cue(sel_cue, timeline_mgr)
        imgui.pop_style_color(2)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Fire this cue NOW (sends to device)")

        imgui.same_line()
        imgui.push_style_color(imgui.Col_.button, ImVec4(0.6, 0.15, 0.15, 1.0))
        imgui.push_style_color(imgui.Col_.button_hovered, ImVec4(0.8, 0.2, 0.2, 1.0))
        if imgui.button("Del##ti_cue_del", ImVec2(50, 0)):
            cue_data.remove_cue(sel_cue.cue_id)
            self._sel_cue_id = None
            EV.dispatch(OFS_Events.TIMELINE_LAYOUT_CHANGED)
        imgui.pop_style_color(2)

    # -- Type-specific param editors -----------------------------------

    def _draw_param_fields_parameter(
        self,
        device_mgr: Optional["DeviceManager"],
        routing: Optional["RoutingMatrix"],
    ) -> bool:
        """Fields for PARAMETER cue: device combo + multi-entry list.

        Each entry has its own searchable register dropdown and a
        type-appropriate value widget.  An [+ Add] button appends
        entries; each entry has an [x] remove button.
        """
        dirty = False
        devices = self._get_device_list(device_mgr, routing)

        # -- Device combo (shared across all entries) -------------------
        imgui.text("Device")
        imgui.same_line(80)
        imgui.set_next_item_width(-1)
        current_label = self._cue_p_device_id or "-- select --"
        for did, dlabel in devices:
            if did == self._cue_p_device_id:
                current_label = dlabel
                break
        if imgui.begin_combo("##ti_cp_dev", current_label):
            if imgui.selectable("-- none --", self._cue_p_device_id == "")[0]:
                self._cue_p_device_id = ""
                dirty = True
            for did, dlabel in devices:
                sel, _ = imgui.selectable(
                    f"{dlabel}##d_{did}",
                    self._cue_p_device_id == did)
                if sel:
                    self._cue_p_device_id = did
                    dirty = True
            imgui.end_combo()

        imgui.spacing()
        imgui.separator()

        # Ensure at least one entry exists
        if not self._cue_p_entries:
            self._cue_p_entries = [self._addr_val_to_entry(0, 0)]

        # -- Draw each parameter entry ----------------------------------
        remove_idx: Optional[int] = None
        for ei, entry in enumerate(self._cue_p_entries):
            imgui.push_id(f"pe_{ei}")

            # Header line: "#N  [Register combo ..............]  [x]"
            n_entries = len(self._cue_p_entries)
            if n_entries > 1:
                imgui.text(f"#{ei + 1}")
                imgui.same_line(30)
            else:
                imgui.text("Reg")
                imgui.same_line(30)

            # -- Searchable register combo ------------------------------
            reg_idx = entry.get("reg_idx", 0)
            filt = entry.get("filter", "")
            preview = _MK312_REG_LABELS[reg_idx] if 0 <= reg_idx < len(_MK312_REG_LABELS) else "--"
            btn_w = 26 if n_entries > 1 else 0
            imgui.set_next_item_width(imgui.get_content_region_avail().x - btn_w)
            ch_reg = False
            if imgui.begin_combo(f"##reg", preview):
                if imgui.is_window_appearing():
                    imgui.set_keyboard_focus_here()
                    entry["filter"] = ""
                    filt = ""
                _fch, filt = imgui.input_text_with_hint(
                    "##rf", "Search registers\u2026", filt)
                entry["filter"] = filt
                imgui.separator()
                filt_lower = filt.lower()
                for ri, label in enumerate(_MK312_REG_LABELS):
                    if filt_lower and filt_lower not in label.lower():
                        continue
                    is_sel = (ri == reg_idx)
                    sel, _ = imgui.selectable(f"{label}##r_{ri}", is_sel)
                    if is_sel and imgui.is_window_appearing():
                        imgui.set_item_default_focus()
                    if sel:
                        entry["reg_idx"] = ri
                        entry["int_value"] = 0
                        entry["bool_value"] = False
                        entry["mode_idx"] = 0
                        entry["raw_addr"] = ""
                        ch_reg = True
                imgui.end_combo()
            if ch_reg:
                dirty = True

            # Show register description tooltip
            _name, reg_addr, rtype, reg_min, reg_max, desc = _MK312_REGISTERS[entry.get("reg_idx", 0)]
            if imgui.is_item_hovered():
                imgui.set_tooltip(desc)

            # -- Remove button -----------------------------------------
            if n_entries > 1:
                imgui.same_line()
                imgui.push_style_color(imgui.Col_.button.value, ImVec4(0.6, 0.15, 0.15, 0.9))
                imgui.push_style_color(imgui.Col_.button_hovered.value, ImVec4(0.8, 0.2, 0.2, 1.0))
                if imgui.button("x##del", ImVec2(22, 0)):
                    remove_idx = ei
                imgui.pop_style_color(2)

            # -- Custom raw address (only for "raw" type) ---------------
            if rtype == "raw":
                imgui.text("Addr")
                imgui.same_line(30)
                imgui.set_next_item_width(-1)
                ch, entry["raw_addr"] = imgui.input_text(
                    "##radr", entry.get("raw_addr", ""))
                if ch:
                    dirty = True
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Hex address, e.g. 0x4064")

            # -- Value input  --  type-specific ----------------------------
            if rtype == "bool":
                imgui.text("Val")
                imgui.same_line(30)
                ch, entry["bool_value"] = imgui.checkbox(
                    "##bv", entry.get("bool_value", False))
                if ch:
                    dirty = True
                imgui.same_line()
                imgui.text_disabled("ON" if entry.get("bool_value") else "OFF")

            elif rtype == "mode":
                imgui.text("Mode")
                imgui.same_line(30)
                imgui.set_next_item_width(-1)
                ch, entry["mode_idx"] = imgui.combo(
                    "##mv", entry.get("mode_idx", 0), _MK312_MODE_LABELS)
                if ch:
                    dirty = True

            elif rtype == "bitmask":
                imgui.text("Val")
                imgui.same_line(30)
                imgui.set_next_item_width(80)
                iv = entry.get("int_value", 0)
                ch, iv = imgui.input_int("##bmv", iv, 1, 16)
                if ch:
                    iv = max(reg_min, min(reg_max, iv))
                    entry["int_value"] = iv
                    dirty = True
                imgui.same_line()
                imgui.text_disabled(f"0x{iv:02X}")

            else:
                imgui.text("Val")
                imgui.same_line(30)
                imgui.set_next_item_width(-1)
                iv = entry.get("int_value", 0)
                if reg_max <= 10:
                    ch, iv = imgui.input_int("##iv", iv, 1, 1)
                else:
                    ch, iv = imgui.slider_int("##iv", iv, reg_min, reg_max, "%d")
                if ch:
                    iv = max(reg_min, min(reg_max, iv))
                    entry["int_value"] = iv
                    dirty = True

            # Show address info
            if rtype != "raw":
                disp_val = ""
                if rtype == "bool":
                    disp_val = "ON" if entry.get("bool_value") else "OFF"
                elif rtype == "mode":
                    midx = entry.get("mode_idx", 0)
                    if 0 <= midx < len(_MK312_MODE_LABELS):
                        disp_val = _MK312_MODE_LABELS[midx]
                else:
                    disp_val = str(entry.get("int_value", 0))
                imgui.text_disabled(f"  -> 0x{reg_addr:04X} = {disp_val}")

            imgui.pop_id()

            # Thin separator between entries (not after last)
            if ei < len(self._cue_p_entries) - 1:
                imgui.spacing()
                imgui.separator()

        # -- Handle removal ---------------------------------------------
        if remove_idx is not None and 0 <= remove_idx < len(self._cue_p_entries):
            self._cue_p_entries.pop(remove_idx)
            dirty = True

        # -- Add Parameter button ---------------------------------------
        imgui.spacing()
        imgui.push_style_color(imgui.Col_.button.value, ImVec4(0.2, 0.45, 0.2, 0.9))
        imgui.push_style_color(imgui.Col_.button_hovered.value, ImVec4(0.25, 0.6, 0.25, 1.0))
        if imgui.button("+ Add Parameter", ImVec2(-1, 0)):
            self._cue_p_entries.append(self._addr_val_to_entry(0, 0))
            dirty = True
        imgui.pop_style_color(2)

        # Keep legacy single-field variables in sync with first entry
        if self._cue_p_entries:
            e0 = self._cue_p_entries[0]
            self._cue_p_reg_idx = e0.get("reg_idx", 0)
            self._cue_p_raw_addr = e0.get("raw_addr", "")
            self._cue_p_int_value = e0.get("int_value", 0)
            self._cue_p_bool_value = e0.get("bool_value", False)
            self._cue_p_mode_idx = e0.get("mode_idx", 0)

        return dirty

    def _draw_param_fields_osc(self) -> bool:
        """Fields for OSC_COMMAND cue: path, args."""
        dirty = False

        imgui.text("Path")
        imgui.same_line(80)
        imgui.set_next_item_width(-1)
        ch, self._cue_p_osc_path = imgui.input_text(
            "##ti_cp_opath", self._cue_p_osc_path)
        if ch:
            dirty = True
        if imgui.is_item_hovered():
            imgui.set_tooltip("OSC address, e.g. /my/command")

        imgui.text("Args")
        imgui.same_line(80)
        imgui.set_next_item_width(-1)
        ch, self._cue_p_osc_args = imgui.input_text(
            "##ti_cp_oargs", self._cue_p_osc_args)
        if ch:
            dirty = True
        if imgui.is_item_hovered():
            imgui.set_tooltip("JSON array, e.g. [1.0, \"hello\"]")

        # Validation hint
        try:
            parsed = json.loads(self._cue_p_osc_args)
            if not isinstance(parsed, list):
                imgui.text_colored(ImVec4(1.0, 0.5, 0.2, 1.0),
                                   "[!] Must be a JSON array")
        except json.JSONDecodeError:
            imgui.text_colored(ImVec4(1.0, 0.3, 0.3, 1.0),
                               "[!] Invalid JSON")

        return dirty

    def _draw_param_fields_ws(
        self,
        device_mgr: Optional["DeviceManager"],
        routing: Optional["RoutingMatrix"],
    ) -> bool:
        """Fields for WS_MESSAGE cue: ws output, payload."""
        dirty = False
        ws_list = self._get_ws_output_list(device_mgr, routing)

        # WS output combo
        imgui.text("WS Out")
        imgui.same_line(80)
        imgui.set_next_item_width(-1)
        current_label = self._cue_p_ws_id or "-- select --"
        for wid, wlabel in ws_list:
            if wid == self._cue_p_ws_id:
                current_label = wlabel
                break
        if imgui.begin_combo("##ti_cp_ws", current_label):
            if imgui.selectable("-- none --", self._cue_p_ws_id == "")[0]:
                self._cue_p_ws_id = ""
                dirty = True
            for wid, wlabel in ws_list:
                sel, _ = imgui.selectable(
                    f"{wlabel}##w_{wid}",
                    self._cue_p_ws_id == wid)
                if sel:
                    self._cue_p_ws_id = wid
                    dirty = True
            imgui.end_combo()

        # Payload (JSON)
        imgui.text("Payload")
        ch, self._cue_p_ws_payload = imgui.input_text_multiline(
            "##ti_cp_wpl", self._cue_p_ws_payload,
            ImVec2(-1, 60))
        if ch:
            dirty = True

        # Validation
        try:
            json.loads(self._cue_p_ws_payload)
        except json.JSONDecodeError:
            imgui.text_colored(ImVec4(1.0, 0.3, 0.3, 1.0),
                               "[!] Invalid JSON")

        return dirty

    def _draw_param_fields_mode(
        self,
        device_mgr: Optional["DeviceManager"],
        routing: Optional["RoutingMatrix"],
    ) -> bool:
        """Fields for MODE_CHANGE cue: device, mode dropdown."""
        dirty = False
        devices = self._get_device_list(device_mgr, routing)

        # -- Device combo -----------------------------------------------
        imgui.text("Device")
        imgui.same_line(80)
        imgui.set_next_item_width(-1)
        current_label = self._cue_p_device_id or "-- select --"
        for did, dlabel in devices:
            if did == self._cue_p_device_id:
                current_label = dlabel
                break
        if imgui.begin_combo("##ti_cm_dev", current_label):
            if imgui.selectable("-- none --", self._cue_p_device_id == "")[0]:
                self._cue_p_device_id = ""
                dirty = True
            for did, dlabel in devices:
                sel, _ = imgui.selectable(
                    f"{dlabel}##md_{did}",
                    self._cue_p_device_id == did)
                if sel:
                    self._cue_p_device_id = did
                    dirty = True
            imgui.end_combo()

        # -- Mode combo -------------------------------------------------
        imgui.text("Mode")
        imgui.same_line(80)
        imgui.set_next_item_width(-1)
        ch, self._cue_p_mode_idx = imgui.combo(
            "##ti_cm_mode", self._cue_p_mode_idx, _MK312_MODE_LABELS)
        if ch:
            dirty = True

        # Show hex value
        if 0 <= self._cue_p_mode_idx < len(_MK312_MODES):
            mode_name, mode_val = _MK312_MODES[self._cue_p_mode_idx]
            imgui.text_disabled(f"-> writes 0x{mode_val:02X} to 0x407B")

        return dirty
