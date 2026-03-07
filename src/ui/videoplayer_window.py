"""
OFS_VideoplayerWindow  --  Python port of OFS_VideoplayerWindow.h / .cpp

Renders the mpv frame texture via imgui.image().
Supports zoom/pan, VR mode (side-by-side left/right), fullscreen toggle.
No Qt.  All rendering via Dear ImGui + PyOpenGL.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from imgui_bundle import imgui, ImVec2, ImVec4
from imgui_bundle import icons_fontawesome_6 as fa
ImTextureRef = imgui.ImTextureRef

from src.core.video_player import OFS_Videoplayer

# -- Video mode (mirrors OFS_VideoplayerWindow::VideoMode) -----------------
class VideoMode:
    FULL    = 0   # full frame
    LEFT    = 1   # left half (VR side-by-side)
    RIGHT   = 2   # right half
    TOP     = 3   # top half (VR over-under)
    BOTTOM  = 4   # bottom half
    VR      = 5   # equirect / 3D (basic support)


class OFS_VideoplayerWindow:
    """
    Dear ImGui panel that draws the video frame.
    Mirrors C++ OFS_VideoplayerWindow.
    """

    WindowId = "Video###VIDEOPLAYER"

    def __init__(self) -> None:
        self.video_mode: int = VideoMode.FULL

        # Zoom / pan state
        self._zoom: float     = 1.0
        self._offset: ImVec2  = ImVec2(0.0, 0.0)
        self._drag_start: Optional[ImVec2] = None
        self._drag_offset_start: Optional[ImVec2] = None

        # Context-menu visibility
        self._ctx_open: bool = False

        # #15 lockedPosition  --  prevent pan/zoom changes when True
        self.locked_position: bool = False

        # Size of the video area last frame
        self._last_video_size: ImVec2 = ImVec2(0, 0)

    # ----------------------------------------------------------------------

    def reset_translation_and_zoom(self) -> None:
        self._zoom   = 1.0
        self._offset = ImVec2(0.0, 0.0)

    # ----------------------------------------------------------------------

    def Draw(self, player: OFS_Videoplayer, draw_video: bool = True,
             timeline_mgr=None) -> None:
        """
        Called inside the dockable window (begin/end handled by hello_imgui).
        `draw_video` mirrors OFS draw_video flag.
        `timeline_mgr` if provided, video is hidden when transport is outside
        all video clips.  Also resolves which player to display from the pool.
        """
        avail = imgui.get_content_region_avail()
        if avail.x <= 0 or avail.y <= 0:
            return

        # Resolve the active player from the pool (the video track under
        # the transport cursor).  Falls back to the `player` argument.
        active_player = player
        in_any_video = True
        if timeline_mgr is not None:
            pos = timeline_mgr.transport.position
            vtracks = timeline_mgr.timeline.VideoTracks()
            if vtracks:
                in_any_video = any(vt.ContainsGlobal(pos) for _l, vt in vtracks)
            pool_player = timeline_mgr.ActivePlayer(pos)
            if pool_player is not None:
                active_player = pool_player

        if not draw_video or not active_player.VideoLoaded() or not in_any_video:
            # Show placeholder when no video
            cx = imgui.get_cursor_screen_pos().x + avail.x * 0.5
            cy = imgui.get_cursor_screen_pos().y + avail.y * 0.5
            imgui.set_cursor_screen_pos(ImVec2(cx - 80, cy))
            imgui.text_disabled("No video loaded")
            return

        # Compute draw area preserving aspect ratio
        vid_w = active_player.VideoWidth()
        vid_h = active_player.VideoHeight()
        if vid_w <= 0 or vid_h <= 0:
            vid_w, vid_h = 1280, 720

        draw_w, draw_h, uv0, uv1 = self._compute_uvs(avail, vid_w, vid_h)
        self._last_video_size = ImVec2(draw_w, draw_h)

        tex = active_player.FrameTexture
        if not tex:
            return

        # Draw image (origin_upper_left for flip_y already handled by mpv)
        cursor = imgui.get_cursor_screen_pos()

        # Apply pan offset
        cx = cursor.x + (avail.x - draw_w) * 0.5 + self._offset.x
        cy = cursor.y + (avail.y - draw_h) * 0.5 + self._offset.y

        dl = imgui.get_window_draw_list()
        dl.add_image(
            ImTextureRef(tex),
            ImVec2(cx, cy),
            ImVec2(cx + draw_w, cy + draw_h),
            uv0,
            uv1,
        )

        # Invisible interaction area
        imgui.set_cursor_screen_pos(ImVec2(cx, cy))
        imgui.invisible_button("##videoarea", ImVec2(draw_w, draw_h),
                               imgui.ButtonFlags_.mouse_button_right |
                               imgui.ButtonFlags_.mouse_button_left)

        self._handle_interaction(active_player, cx, cy, draw_w, draw_h)
        self._handle_context_menu(active_player)

    # ----------------------------------------------------------------------
    # UV computation  --  handles all VideoModes
    # ----------------------------------------------------------------------

    def _compute_uvs(
        self, avail: ImVec2, vid_w: int, vid_h: int
    ) -> Tuple[float, float, ImVec2, ImVec2]:
        """Return (draw_w, draw_h, uv0, uv1) respecting video_mode and zoom."""

        # Source UV rect based on VideoMode
        if self.video_mode == VideoMode.LEFT:
            uv0 = ImVec2(0.0,  0.0)
            uv1 = ImVec2(0.5,  1.0)
            src_aspect = (vid_w * 0.5) / vid_h
        elif self.video_mode == VideoMode.RIGHT:
            uv0 = ImVec2(0.5,  0.0)
            uv1 = ImVec2(1.0,  1.0)
            src_aspect = (vid_w * 0.5) / vid_h
        elif self.video_mode == VideoMode.TOP:
            uv0 = ImVec2(0.0,  0.0)
            uv1 = ImVec2(1.0,  0.5)
            src_aspect = vid_w / (vid_h * 0.5)
        elif self.video_mode == VideoMode.BOTTOM:
            uv0 = ImVec2(0.0,  0.5)
            uv1 = ImVec2(1.0,  1.0)
            src_aspect = vid_w / (vid_h * 0.5)
        else:
            # FULL or VR
            uv0 = ImVec2(0.0, 0.0)
            uv1 = ImVec2(1.0, 1.0)
            src_aspect = vid_w / vid_h if vid_h else 1.0

        # Fit into avail preserving aspect
        if avail.x / avail.y > src_aspect:
            draw_h = avail.y * self._zoom
            draw_w = draw_h * src_aspect
        else:
            draw_w = avail.x * self._zoom
            draw_h = draw_w / src_aspect if src_aspect else draw_w

        return draw_w, draw_h, uv0, uv1

    # ----------------------------------------------------------------------
    # Interaction
    # ----------------------------------------------------------------------

    def _handle_interaction(
        self, player: OFS_Videoplayer,
        cx: float, cy: float, draw_w: float, draw_h: float
    ) -> None:
        io = imgui.get_io()

        # Double-click -> toggle play
        if imgui.is_item_hovered():
            if imgui.is_mouse_double_clicked(0):
                player.TogglePlay()

            # Scroll wheel -> zoom (Ctrl = fine)  --  guarded by locked_position
            wheel = io.mouse_wheel
            if wheel != 0.0 and not self.locked_position:
                factor = 0.05 if not io.key_ctrl else 0.01
                self._zoom = max(0.1, min(8.0, self._zoom + wheel * factor))

        # Left drag -> pan  --  guarded by locked_position
        if imgui.is_item_active() and imgui.is_mouse_dragging(0, 2.0) and not self.locked_position:
            if self._drag_start is None:
                self._drag_start       = ImVec2(io.mouse_pos.x, io.mouse_pos.y)
                self._drag_offset_start = ImVec2(self._offset.x, self._offset.y)
            else:
                dx = io.mouse_pos.x - self._drag_start.x
                dy = io.mouse_pos.y - self._drag_start.y
                self._offset = ImVec2(
                    self._drag_offset_start.x + dx,
                    self._drag_offset_start.y + dy,
                )
        else:
            self._drag_start = None

    def _handle_context_menu(self, player: OFS_Videoplayer) -> None:
        if imgui.begin_popup_context_item("##vidctx"):
            imgui.text_disabled("Video mode")
            imgui.separator()
            modes = [
                (VideoMode.FULL,   "Full"),
                (VideoMode.LEFT,   "Left half (VR)"),
                (VideoMode.RIGHT,  "Right half (VR)"),
                (VideoMode.TOP,    "Top half"),
                (VideoMode.BOTTOM, "Bottom half"),
            ]
            for m, label in modes:
                if imgui.menu_item(label, "", self.video_mode == m)[0]:
                    self.video_mode = m
            imgui.separator()
            if imgui.menu_item("Reset zoom/pan", "", False)[0]:
                self.reset_translation_and_zoom()
            imgui.separator()
            _, self.locked_position = imgui.menu_item(
                "Lock pan/zoom", "", self.locked_position)
            if self.locked_position:
                imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(1.0, 0.8, 0.2, 1.0))
                imgui.text_disabled("Pan/zoom locked")
                imgui.pop_style_color()
            imgui.end_popup()
