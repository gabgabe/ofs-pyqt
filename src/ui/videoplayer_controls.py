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

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.ui.ui_colors import UIColors

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
        self._drag_was_paused: bool = True   # for seek-pause-resume

        # Shared colour table (set via set_colors)
        self._ui_colors: Optional["UIColors"] = None

        # Optional transport controller — when set, play/pause/seek/speed go
        # through the TimelineManager instead of calling the player directly.
        self._timeline_mgr = None  # TimelineManager | None

        # Selected track id — mirrors track_info selection.
        # When set, the progress bar shows the track's range; otherwise the
        # full timeline range (or video duration if no timeline manager).
        self._selected_track_id: Optional[str] = None

    # ──────────────────────────────────────────────────────────────────────

    def Init(self, player: OFS_Videoplayer) -> None:
        pass  # GL texture upload deferred to first use

    def SetTimelineManager(self, mgr) -> None:
        """Wire the transport controller for DAW-mode routing."""
        self._timeline_mgr = mgr

    def set_colors(self, colors: "UIColors") -> None:
        """Wire the shared colour table."""
        self._ui_colors = colors

    def SetSelectedTrackId(self, track_id: Optional[str]) -> None:
        """Set the selected track for progress-bar range mapping."""
        self._selected_track_id = track_id

    def _effective_range(self) -> tuple:
        """Return (start, end, current) for the progress bar.

        * If a track is selected → (track.offset, track.end, transport_pos)
        * Else if timeline_mgr → (earliest_track_start, latest_track_end, transport_pos)
        * Fallback → (0, player.Duration(), player.CurrentTime())
        """
        mgr = self._timeline_mgr
        if mgr is not None:
            pos = mgr.transport.position
            tl = mgr.timeline
            # Try selected track first
            if self._selected_track_id:
                result = tl.FindTrack(self._selected_track_id)
                if result:
                    _lay, trk = result
                    return (trk.offset, trk.end, pos)
            # No track selected → span from earliest track start to latest track end
            all_tracks = tl.AllTracks()
            if all_tracks:
                t_min = min(t.offset for _l, t in all_tracks)
                t_max = max(t.end    for _l, t in all_tracks)
                if t_max > t_min:
                    return (t_min, t_max, pos)
        return None  # caller will fallback to player

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

        # Use UIColors for heatmap gradient if available
        global _HEATMAP_COLD, _HEATMAP_WARM, _HEATMAP_HOT
        if self._ui_colors is not None:
            _HEATMAP_COLD = tuple(self._ui_colors.heatmap_cold)
            _HEATMAP_WARM = tuple(self._ui_colors.heatmap_warm)
            _HEATMAP_HOT  = tuple(self._ui_colors.heatmap_hot)

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

    def _has_content(self) -> bool:
        """True if a video is loaded OR the timeline has any tracks."""
        mgr = self._timeline_mgr
        if mgr is not None and mgr.timeline.layers:
            return True
        return False

    def DrawControls(self, player: OFS_Videoplayer) -> None:
        has_video = player.VideoLoaded()
        if not has_video and not self._has_content():
            imgui.text_disabled("No video")
            return

        mgr = self._timeline_mgr  # may be None

        # ── Row 1: playback buttons ────────────────────────────────────
        button_h = imgui.get_frame_height()
        small    = ImVec2(button_h, button_h)

        # prev-frame
        if has_video or mgr:
            if imgui.button(fa.ICON_FA_BACKWARD_STEP, small):
                if mgr:
                    mgr.StepFrames(-1)
                else:
                    player.PreviousFrame()
            if imgui.is_item_hovered():
                imgui.set_tooltip("Previous frame  [←]")
            imgui.same_line()

        # play/pause — route through transport when available
        is_playing = (not mgr.IsPlaying()) if mgr else player.IsPaused()
        play_icon = fa.ICON_FA_PAUSE if not is_playing else fa.ICON_FA_PLAY
        if imgui.button(play_icon, small):
            if mgr:
                mgr.TogglePlay()
            else:
                player.TogglePlay()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Play / Pause  [Space]")
        imgui.same_line()

        # next-frame
        if has_video or mgr:
            if imgui.button(fa.ICON_FA_FORWARD_STEP, small):
                if mgr:
                    mgr.StepFrames(1)
                else:
                    player.NextFrame()
            if imgui.is_item_hovered():
                imgui.set_tooltip("Next frame  [→]")

        imgui.same_line(spacing=8)

        # ── ±3 s seek buttons ──────────────────────────────────────────
        if imgui.button(fa.ICON_FA_BACKWARD + " 3s##sk_back", ImVec2(0, button_h)):
            if mgr:
                mgr.SeekRelative(-3.0)
            else:
                player.SeekRelative(-3.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Seek −3 seconds  [Shift+←]")
        imgui.same_line(spacing=2)
        if imgui.button("3s " + fa.ICON_FA_FORWARD + "##sk_fwd", ImVec2(0, button_h)):
            if mgr:
                mgr.SeekRelative(3.0)
            else:
                player.SeekRelative(3.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Seek +3 seconds  [Shift+→]")

        imgui.same_line(spacing=8)

        # mute / volume (only relevant when a video is loaded)
        if has_video:
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
            avail = imgui.get_content_region_avail().x
            imgui.set_next_item_width(max(40, min(60, avail * 0.15)))
            vol = player.Volume()
            changed, new_vol = imgui.slider_float("##vol", vol, 0.0, 100.0, "%.0f%%")
            if changed:
                player.SetVolume(new_vol)

            imgui.same_line(spacing=8)
        else:
            avail = imgui.get_content_region_avail().x

        # speed input — route through transport when available
        imgui.set_next_item_width(max(50, min(70, avail * 0.15)))
        speed = mgr.transport.speed if mgr else player.CurrentSpeed()
        changed_s, new_speed = imgui.input_float("##spd", speed, 0.0, 0.0, "%.2f×")
        if changed_s:
            new_speed = max(0.05, min(5.0, new_speed))
            if mgr:
                mgr.SetSpeed(new_speed)
            else:
                player.SetSpeed(new_speed)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Playback speed  (scroll to change)")

        imgui.same_line(spacing=2)

        # speed preset buttons: 1×  -10%  +10%
        spd_w = ImVec2(max(28, button_h * 1.6), button_h)
        if imgui.button("1" + fa.ICON_FA_XMARK + "##sp1", spd_w):
            if mgr:
                mgr.SetSpeed(1.0)
            else:
                player.SetSpeed(1.0)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Reset speed to 1×")
        imgui.same_line(spacing=2)
        if imgui.button("-10%%##spm", spd_w):
            if mgr:
                mgr.SetSpeed(max(0.05, mgr.transport.speed * 0.9))
            else:
                player.SetSpeed(max(0.05, player.CurrentSpeed() * 0.9))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Decrease speed by 10%")
        imgui.same_line(spacing=2)
        if imgui.button("+10%%##spp", spd_w):
            if mgr:
                mgr.SetSpeed(min(5.0, mgr.transport.speed * 1.1))
            else:
                player.SetSpeed(min(5.0, player.CurrentSpeed() * 1.1))
        if imgui.is_item_hovered():
            imgui.set_tooltip("Increase speed by 10%")

        # Actual measured speed — show when it diverges from requested speed
        if has_video:
            actual = player.ActualSpeed() if hasattr(player, "ActualSpeed") else speed
            if abs(actual - speed) > 0.02 and not player.IsPaused():
                imgui.same_line(spacing=6)
                imgui.text_disabled(f"~{actual:.2f}\u00d7")

        # ── Buffering indicator (Omakase pattern) ─────────────────────
        if mgr and mgr.IsBuffering():
            imgui.same_line(spacing=8)
            # Animated dots
            import time as _t
            n_dots = int(_t.monotonic() * 3) % 4
            imgui.text_colored(ImVec4(1.0, 0.7, 0.2, 1.0),
                               "Buffering" + "." * n_dots)
        elif has_video and player.IsBuffering() and not player.IsPaused():
            imgui.same_line(spacing=8)
            import time as _t
            n_dots = int(_t.monotonic() * 3) % 4
            imgui.text_colored(ImVec4(1.0, 0.7, 0.2, 1.0),
                               "Buffering" + "." * n_dots)

    # ──────────────────────────────────────────────────────────────────────
    # DrawTimeline — custom heatmap + seek bar with chapter/bookmark overlay
    # ──────────────────────────────────────────────────────────────────────

    def DrawTimeline(
        self,
        player: OFS_Videoplayer,
        script:  Optional[Funscript],
        chapter_mgr=None,   # ChapterManagerWindow | None
        always_show_bookmark_labels: bool = False,
        thumbnail_mgr=None,  # VideoThumbnailManager | None
    ) -> None:
        if not player.VideoLoaded() and not self._has_content():
            imgui.text_disabled("No video")
            return

        # Determine effective range for the progress bar
        eff = self._effective_range()
        if eff is not None:
            bar_start, bar_end, current = eff
        else:
            bar_start = 0.0
            # Prefer timeline duration for funscript-only projects
            mgr = self._timeline_mgr
            tl_dur = mgr.Duration() if mgr else 0.0
            bar_end = tl_dur if tl_dur > 0 else player.Duration()
            current = mgr.CurrentTime() if mgr else player.CurrentTime()
        duration = bar_end - bar_start
        if duration <= 0.0:
            return

        avail  = imgui.get_content_region_avail()
        dl     = imgui.get_window_draw_list()
        origin = imgui.get_cursor_screen_pos()

        W  = max(1.0, avail.x)
        BAR_H   = 22.0          # main timeline bar height
        CHAP_H  = BAR_H * 0.28  # chapter strip height (top of bar)
        BM_R    = 4.0           # bookmark circle radius
        pct     = max(0.0, min(1.0, (current - bar_start) / duration)) if duration > 0 else 0.0
        ox, oy  = origin.x, origin.y

        # 1 ── Background (grey unfilled portion) ──────────────────────
        _c = self._ui_colors
        col_bg      = _rgba_to_u32(*_c.progress_bg)      if _c else 0xFF505050
        col_fill    = _rgba_to_u32(*_c.progress_fill)     if _c else 0xBB2D5FAA
        col_cursor  = _rgba_to_u32(*_c.progress_cursor)   if _c else 0xFFFFFFFF
        col_shadow  = _rgba_to_u32(*_c.progress_cursor_shadow) if _c else 0xFF000000
        col_hover   = _rgba_to_u32(*_c.progress_hover)    if _c else 0x88FFFFFF

        dl.add_rect_filled(
            ImVec2(ox,            oy),
            ImVec2(ox + W,        oy + BAR_H),
            col_bg,
        )

        # 2 ── Progress fill (highlight up to cursor) ──────────────────
        fill_x = ox + W * pct
        dl.add_rect_filled(
            ImVec2(ox,            oy),
            ImVec2(fill_x,        oy + BAR_H),
            col_fill,
        )

        # 3 ── Heatmap overlay ──────────────────────────────────────────
        if self._heatmap_colours:
            n     = len(self._heatmap_colours)
            seg_w = W / n
            for i, col in enumerate(self._heatmap_colours):
                if col == 0:
                    continue
                x0 = ox + i * seg_w
                x1 = ox + (i + 1) * seg_w
                dl.add_rect_filled(ImVec2(x0, oy), ImVec2(x1, oy + BAR_H), col)

        # 4 ── Chapters (top strip) ────────────────────────────────────
        if chapter_mgr and chapter_mgr._chapters:
            for ch in chapter_mgr._chapters:
                ch_x0 = ox + ((ch.start - bar_start) / duration) * W
                ch_x1 = ox + ((ch.end   - bar_start) / duration) * W
                if ch_x1 - ch_x0 < 1.0:
                    continue
                cr, cg, cb = ch.color[0], ch.color[1], ch.color[2]
                ch_col = self._rgba_to_u32(cr, cg, cb, 0.85)
                dl.add_rect_filled(
                    ImVec2(ch_x0, oy),
                    ImVec2(ch_x1, oy + CHAP_H),
                    ch_col, 2.0,
                )
                # Active-chapter border
                if ch.start <= current <= ch.end:
                    dl.add_rect(
                        ImVec2(ch_x0, oy),
                        ImVec2(ch_x1, oy + CHAP_H),
                        0xFFFFFFFF, 2.0, 0, 1.5,
                    )
                # Label if it fits
                if ch.name:
                    ts = imgui.calc_text_size(ch.name)
                    cw = ch_x1 - ch_x0
                    if ts.x + 4 <= cw:
                        dl.add_text(
                            ImVec2(ch_x0 + (cw - ts.x) * 0.5,
                                   oy + (CHAP_H - ts.y) * 0.5),
                            0xFFFFFFFF, ch.name,
                        )

        # 5 ── Bookmarks (small circles at bottom) ─────────────────────
        if chapter_mgr and chapter_mgr._bookmarks:
            for bm in chapter_mgr._bookmarks:
                bm_x = ox + ((bm.time - bar_start) / duration) * W
                dl.add_circle_filled(
                    ImVec2(bm_x, oy + BAR_H - BM_R - 1), BM_R,
                    0xFFFFFFFF, 8,
                )
                if always_show_bookmark_labels and bm.name:
                    ts = imgui.calc_text_size(bm.name)
                    dl.add_text(
                        ImVec2(bm_x - ts.x * 0.5,
                               oy + BAR_H - BM_R * 2 - ts.y - 2),
                        0xFFFFFFFF, bm.name,
                    )

        # 6 ── Cursor line (white + dark shadow) ───────────────────────
        cx = ox + W * pct
        dl.add_line(ImVec2(cx, oy - 1), ImVec2(cx, oy + BAR_H + 1), col_shadow, 3.0)
        dl.add_line(ImVec2(cx, oy - 1), ImVec2(cx, oy + BAR_H + 1), col_cursor, 1.5)

        # 7 ── Invisible button for interaction ────────────────────────
        imgui.set_cursor_screen_pos(ImVec2(ox, oy))
        imgui.invisible_button("##timeline_bar", ImVec2(W, BAR_H))

        if imgui.is_item_activated():
            if self._timeline_mgr:
                self._drag_was_paused = not self._timeline_mgr.IsPlaying()
                if self._timeline_mgr.IsPlaying():
                    self._timeline_mgr.transport.Pause()
            else:
                self._drag_was_paused = player.IsPaused()
                if not player.IsPaused():
                    player.SetPaused(True)

        if imgui.is_item_active() and imgui.is_mouse_down(0):
            mx    = imgui.get_mouse_pos().x
            rel   = max(0.0, min(1.0, (mx - ox) / W))
            seek_t = bar_start + rel * duration
            if self._timeline_mgr:
                self._timeline_mgr.Seek(seek_t)
            else:
                player.SetPositionExact(seek_t)
                if player.IsPaused():
                    player.Update(0.0)

        if imgui.is_item_deactivated():
            if not self._drag_was_paused:
                if self._timeline_mgr:
                    self._timeline_mgr.transport.Play()
                else:
                    player.SetPaused(False)

        # 8 ── Hover effects ───────────────────────────────────────────
        if imgui.is_item_hovered():
            mouse = imgui.get_mouse_pos()
            rel   = (mouse.x - ox) / W
            hover_t = max(bar_start, min(bar_end, bar_start + rel * duration))

            # Request thumbnail for the hover position
            if thumbnail_mgr is not None:
                thumbnail_mgr.RequestFrame(player.VideoPath(), hover_t)

            # Vertical hover line
            dl.add_line(
                ImVec2(mouse.x, oy),
                ImVec2(mouse.x, oy + BAR_H),
                col_hover, 1.0,
            )

            # Tooltip: thumbnail image (if available) + time label
            delta  = hover_t - current
            sign   = "+" if delta >= 0 else ""
            time_str = (
                f"{self._format_time(hover_t, bar_end)}"
                f"  ({sign}{self._format_delta(abs(delta))})"
            )
            if thumbnail_mgr is not None and thumbnail_mgr.ready:
                imgui.begin_tooltip()
                thumb_w = thumbnail_mgr.width  * 0.6
                thumb_h = thumbnail_mgr.height * 0.6
                imgui.image(
                    imgui.ImTextureRef(thumbnail_mgr.texture),
                    ImVec2(thumb_w, thumb_h),
                )
                imgui.text_disabled(time_str)
                imgui.end_tooltip()
            else:
                imgui.set_tooltip(time_str)

        # 9 ── Chapter context menus ───────────────────────────────────
        if chapter_mgr and chapter_mgr._chapters:
            if imgui.is_item_hovered() and imgui.is_mouse_clicked(1):
                mouse    = imgui.get_mouse_pos()
                click_t  = bar_start + ((mouse.x - ox) / W) * duration
                for i, ch in enumerate(chapter_mgr._chapters):
                    if ch.start <= click_t <= ch.end:
                        imgui.open_popup(f"##ch_ctx_tl_{i}")

            for i, ch in enumerate(chapter_mgr._chapters):
                if imgui.begin_popup(f"##ch_ctx_tl_{i}"):
                    imgui.text_disabled(ch.name or f"Chapter {i+1}")
                    imgui.separator()
                    if imgui.menu_item("Seek to start", "", False)[0]:
                        player.SetPositionExact(ch.start)
                    if imgui.menu_item("Seek to end", "", False)[0]:
                        player.SetPositionExact(ch.end)
                    imgui.end_popup()

        # 10 ── Time label below bar ───────────────────────────────────
        imgui.dummy(ImVec2(1, 2))
        imgui.text_disabled(self._format_time(current, bar_end))

    # ──────────────────────────────────────────────────────────────────────
    # Heatmap bitmap export
    # ──────────────────────────────────────────────────────────────────────

    def RenderHeatmapToBytes(
        self,
        width: int,
        height: int,
        chapters=None,
        chapter_height: int = 0,
    ) -> Optional[bytes]:
        """Return raw RGBA bytes for a heatmap image of (width × total_height).

        Parameters
        ----------
        width           Output image width in pixels.
        height          Height of the heatmap band in pixels.
        chapters        Optional list of Chapter objects to draw above the heatmap.
        chapter_height  Height in pixels of the chapter overlay strip (drawn on
                        top; image total height = height + chapter_height).

        Returns None if no heatmap data is available.

        Mirrors OFS playerControls.RenderHeatmapToBitmap / ...WithChapters.
        """
        if not self._heatmap_colours:
            return None

        total_h = height + chapter_height
        # RGBA pixel buffer initialised to black-transparent
        pixels = bytearray(width * total_h * 4)

        def _put(x: int, y: int, r: int, g: int, b: int, a: int = 255) -> None:
            if 0 <= x < width and 0 <= y < total_h:
                off = (y * width + x) * 4
                pixels[off]     = r
                pixels[off + 1] = g
                pixels[off + 2] = b
                pixels[off + 3] = a

        n = len(self._heatmap_colours)

        # ── Heatmap band ──────────────────────────────────────────────────
        for px in range(width):
            seg_idx = int(px / width * n)
            seg_idx = min(seg_idx, n - 1)
            u32 = self._heatmap_colours[seg_idx]
            r   = (u32      ) & 0xFF
            g   = (u32 >>  8) & 0xFF
            b   = (u32 >> 16) & 0xFF
            a   = (u32 >> 24) & 0xFF
            # Draw into heatmap rows (below any chapter strip)
            y0 = chapter_height
            for py in range(y0, y0 + height):
                _put(px, py, r, g, b, a)

        # ── Chapter strip (top) ───────────────────────────────────────────
        if chapters and chapter_height > 0 and self._heatmap_duration > 0:
            for ch in chapters:
                if not hasattr(ch, 'start_time') or not hasattr(ch, 'end_time'):
                    continue
                x0 = int(ch.start_time / self._heatmap_duration * width)
                x1 = int(ch.end_time   / self._heatmap_duration * width)
                col = getattr(ch, 'color', (0.4, 0.6, 1.0, 1.0))
                cr  = int(col[0] * 255)
                cg  = int(col[1] * 255)
                cb  = int(col[2] * 255)
                for px in range(max(0, x0), min(width, x1)):
                    for py in range(chapter_height):
                        _put(px, py, cr, cg, cb, 255)

        return bytes(pixels)

    def SaveHeatmapPng(
        self,
        path: str,
        width: int = 1280,
        height: int = 100,
        chapters=None,
    ) -> bool:
        """Save heatmap to a PNG file.  Requires Pillow (PIL).

        Mirrors OFS saveHeatmap(path, width, height, withChapters).

        Parameters
        ----------
        path        Output .png file path.
        width       Image width in pixels (default 1280).
        height      Heatmap band height in pixels (default 100).
        chapters    If provided, an additional chapter strip of `height` pixels
                    is added on top (total image = width × 2*height).
        """
        chapter_height = height if chapters else 0
        raw = self.RenderHeatmapToBytes(width, height,
                                           chapters=chapters,
                                           chapter_height=chapter_height)
        if raw is None:
            return False
        try:
            from PIL import Image  # type: ignore
            total_h = height + chapter_height
            img = Image.frombytes("RGBA", (width, total_h), raw)
            img.save(path)
            return True
        except ImportError:
            # Fall back to writing a raw PPM-ish file as a basic alternative
            import struct, zlib
            total_h = height + chapter_height
            # Build PNG manually (minimal, no Pillow needed)
            def _png_chunk(name: bytes, data: bytes) -> bytes:
                crc = zlib.crc32(name + data) & 0xFFFFFFFF
                return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

            # Convert RGBA to RGB (PNG RGBA)
            header = struct.pack(">8sBBIBBBBH",
                b"\x89PNG\r\n\x1a\n"[1:], 0, 0, 0, 0, 0, 0, 0, 0)  # placeholder
            ihdr_data = struct.pack(">IIBBBBB", width, total_h, 8, 2, 0, 0, 0)
            # Actually just use a simple approach via struct
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr = _png_chunk(b"IHDR",
                              struct.pack(">IIBBBBB", width, total_h, 8, 6, 0, 0, 0))
            # Filter + compress pixel data (RGBA)
            raw_rows = b""
            for y in range(total_h):
                raw_rows += b"\x00"  # filter byte = None
                raw_rows += raw[y * width * 4 : (y + 1) * width * 4]
            compressed = zlib.compress(raw_rows, 9)
            idat = _png_chunk(b"IDAT", compressed)
            iend = _png_chunk(b"IEND", b"")
            with open(path, "wb") as f:
                f.write(sig + ihdr + idat + iend)
            return True
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"SaveHeatmapPng: {exc}")
            return False

    # ──────────────────────────────────────────────────────────────────────
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _rgba_to_u32(r: float, g: float, b: float, a: float = 1.0) -> int:
        ri = int(r * 255) & 0xFF
        gi = int(g * 255) & 0xFF
        bi = int(b * 255) & 0xFF
        ai = int(a * 255) & 0xFF
        return ri | (gi << 8) | (bi << 16) | (ai << 24)

    @staticmethod
    def _format_time(t: float, duration: float) -> str:
        def _ts(s: float) -> str:
            s   = max(0.0, s)
            h   = int(s) // 3600
            m   = (int(s) % 3600) // 60
            sec = s % 60
            if h:
                return f"{h:02d}:{m:02d}:{sec:05.2f}"
            return f"{m:02d}:{sec:05.2f}"
        return f"{_ts(t)} / {_ts(duration)}"

    @staticmethod
    def _format_delta(dt: float) -> str:
        """Format a time delta as  mm:ss.xx (no total)."""
        dt  = max(0.0, dt)
        m   = int(dt) // 60
        sec = dt % 60
        return f"{m:02d}:{sec:05.2f}"
