"""
TrackInfoWindow — Inspector panel for the selected DAW track.

Shows and allows editing of:
* Track name
* Start time (offset on the global timeline)  — moves clip
* Duration (effective clip length on timeline) — trims end for VIDEO tracks
* End time  (offset + duration)                — moves clip end
* For VIDEO tracks: source duration, trim in / trim out

Logic for VIDEO tracks:
  • Start (+/-)   → shifts the clip (offset); duration & trim stay.
  • End (+/-)     → shifts the clip end (offset changes, duration stays).
  • Duration (+/-)→ adjusts how much of the video is shown by trimming
                    the tail (trim_out).  Clamped to [trim_in+0.001 .. media_duration].
  • Trim In (+/-) → cuts the head of the media; duration shrinks.
  • Trim Out (+/-)→ cuts the tail of the media; duration shrinks.
  • "Trim In → Cursor" sets trim_in to cursor position in media-local time.
  • "Trim Out → Cursor" sets trim_out to cursor position in media-local time.
  • "Reset Trim" restores full source range.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.events import EV, OFS_Events
from src.core.timeline import Track, TrackType

if TYPE_CHECKING:
    from src.core.timeline_manager import TimelineManager

log = logging.getLogger(__name__)

# Colour palette — same swatches as the Add Track wizard
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


# ── Float-field helper ────────────────────────────────────────────────
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

    # ── Public API ────────────────────────────────────────────────────

    def SelectTrack(self, track_id: Optional[str]) -> None:
        """Set which track is inspected (called from DAW interaction)."""
        self._selected_track_id = track_id

    # ── Draw ──────────────────────────────────────────────────────────

    def Show(self, timeline_mgr: "TimelineManager") -> None:
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

        # ── Track name ─────────────────────────────────────────────────
        imgui.text("Track")
        imgui.same_line()
        imgui.set_next_item_width(-1)
        ch, new_name = imgui.input_text("##trk_name", trk.name, 64)
        if ch:
            trk.name = new_name
            changed = True

        imgui.separator()

        # ── Type badge ─────────────────────────────────────────────────
        type_labels = {
            TrackType.VIDEO: "VIDEO",
            TrackType.FUNSCRIPT: "FUNSCRIPT",
            TrackType.TRIGGER: "TRIGGER",
        }
        imgui.text(f"Type: {type_labels.get(trk.track_type, '?')}")
        imgui.spacing()

        # ── Time fields ────────────────────────────────────────────────
        col_w = imgui.get_content_region_avail().x
        field_w = max(80.0, col_w - 100.0)

        # For VIDEO tracks we need the source duration to clamp everything
        md = trk.media_duration if (is_video and trk.media_duration > 0) else 0.0

        # ── Start (offset) ─────────────────────────────────────────────
        # +/- moves the clip on the timeline; duration stays.
        imgui.text("Start")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        ch, nv = _field_float("##trk_start", trk.offset, 0.1)
        if ch:
            trk.offset = max(0.0, nv)
            changed = True

        # ── Duration ───────────────────────────────────────────────────
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

        # ── End (offset + duration) ────────────────────────────────────
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

        # ── VIDEO-specific trim fields ─────────────────────────────────
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

            # ── Quick trim buttons ─────────────────────────────────────
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

        # ── Colour ─────────────────────────────────────────────────────
        imgui.spacing()
        imgui.separator()
        imgui.text("Colour")
        imgui.same_line(100)
        r, g, b, a = trk.color[:4]

        # Colour button — clicking opens a popup with picker + palette
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

            # ── Palette swatches inside the popup ──────────────────────
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
