"""
TrackInfoWindow — Inspector panel for the selected DAW track.

Shows and allows editing of:
* Track name
* Start time (offset on the global timeline)
* Duration (effective clip length)
* End time  (offset + duration)
* For VIDEO tracks: trim in / trim out (media-local in/out points)

Editing start/end/duration keeps the other fields in sync:
  • Changing start  → shifts the clip, duration stays.
  • Changing end    → adjusts duration.
  • Changing duration → adjusts end.
  • Changing trim in/out → adjusts duration (and visual clip).
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from imgui_bundle import imgui, ImVec2

from src.core.events import EV, OFS_Events
from src.core.timeline import Track, TrackType

if TYPE_CHECKING:
    from src.core.timeline_manager import TimelineManager

log = logging.getLogger(__name__)


def _fmt_mmss(t: float) -> str:
    """Format seconds as ``MM:SS.mmm``."""
    m = int(t) // 60
    s = t - m * 60
    return f"{m:02d}:{s:06.3f}"


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

        # Start (offset)
        imgui.text("Start")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        ch, new_start = imgui.input_float("##trk_start", trk.offset, 0.1, 1.0, "%.3f s")
        if ch and imgui.is_item_deactivated_after_edit():
            trk.offset = max(0.0, new_start)
            changed = True

        # Duration
        imgui.text("Duration")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        ch, new_dur = imgui.input_float("##trk_dur", trk.duration, 0.1, 1.0, "%.3f s")
        if ch and imgui.is_item_deactivated_after_edit():
            new_dur = max(0.001, new_dur)
            trk.duration = new_dur
            # Sync trim_out for VIDEO tracks
            if trk.track_type == TrackType.VIDEO:
                trk.trim_out = trk.trim_in + new_dur
                md = trk.media_duration if trk.media_duration > 0 else new_dur
                if trk.trim_out > md:
                    trk.trim_out = md
                    trk.duration = trk.trim_out - trk.trim_in
            changed = True

        # End (read-write — adjusts duration)
        end_t = trk.offset + trk.duration
        imgui.text("End")
        imgui.same_line(100)
        imgui.set_next_item_width(field_w)
        ch, new_end = imgui.input_float("##trk_end", end_t, 0.1, 1.0, "%.3f s")
        if ch and imgui.is_item_deactivated_after_edit():
            new_dur = max(0.001, new_end - trk.offset)
            trk.duration = new_dur
            if trk.track_type == TrackType.VIDEO:
                trk.trim_out = trk.trim_in + new_dur
                md = trk.media_duration if trk.media_duration > 0 else new_dur
                if trk.trim_out > md:
                    trk.trim_out = md
                    trk.duration = trk.trim_out - trk.trim_in
            changed = True

        # ── VIDEO-specific trim fields ─────────────────────────────────
        if trk.track_type == TrackType.VIDEO:
            imgui.spacing()
            imgui.separator()
            imgui.text("Media Trim")
            imgui.spacing()

            md = trk.media_duration if trk.media_duration > 0 else trk.duration

            # Media duration (read-only)
            imgui.text("Source")
            imgui.same_line(100)
            imgui.text(f"{_fmt_mmss(md)}  ({md:.3f} s)")

            # Trim In
            imgui.text("Trim In")
            imgui.same_line(100)
            imgui.set_next_item_width(field_w)
            ch, new_in = imgui.input_float("##trk_trim_in", trk.trim_in, 0.1, 1.0, "%.3f s")
            if ch and imgui.is_item_deactivated_after_edit():
                new_in = max(0.0, min(new_in, trk.trim_out - 0.001))
                trk.trim_in = new_in
                trk.duration = trk.trim_out - trk.trim_in
                changed = True

            # Trim Out
            imgui.text("Trim Out")
            imgui.same_line(100)
            imgui.set_next_item_width(field_w)
            ch, new_out = imgui.input_float("##trk_trim_out", trk.trim_out, 0.1, 1.0, "%.3f s")
            if ch and imgui.is_item_deactivated_after_edit():
                new_out = max(trk.trim_in + 0.001, min(new_out, md))
                trk.trim_out = new_out
                trk.duration = trk.trim_out - trk.trim_in
                changed = True

            # ── Quick trim buttons ─────────────────────────────────────
            imgui.spacing()
            if imgui.button("Reset Trim##reset_trim"):
                trk.trim_in = 0.0
                trk.trim_out = md
                trk.duration = md
                changed = True
            imgui.same_line()
            if imgui.button("Trim to Cursor##trim_cursor"):
                # Set trim_in to the current transport position (media-local)
                tp_pos = timeline_mgr.transport.position
                media_t = trk.GlobalToMedia(tp_pos)
                media_t = max(0.0, min(media_t, md - 0.001))
                if media_t < trk.trim_out:
                    trk.trim_in = media_t
                    trk.duration = trk.trim_out - trk.trim_in
                    changed = True

        # ── Colour ─────────────────────────────────────────────────────
        imgui.spacing()
        imgui.separator()
        imgui.text("Colour")
        imgui.same_line(100)
        r, g, b, a = trk.color[:4]
        ch, (r, g, b) = imgui.color_edit3("##trk_col", (r, g, b))
        if ch:
            trk.color = (r, g, b, a)
            changed = True

        if changed:
            EV.dispatch(OFS_Events.TIMELINE_LAYOUT_CHANGED)
