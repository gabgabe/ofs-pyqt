"""
VideoThumbnailManager  --  secondary mpv instance for timeline hover previews.

A separate mpv render context renders into a small 320x180 FBO.
The caller queries `texture` each frame; if non-zero it is ready to show
as an ImGui image.

Usage::

    mgr = VideoThumbnailManager()
    mgr.Init()                          # call with GL context current
    mgr.SetVideo(path)                  # call when video is opened
    # every frame:
    mgr.Update()                        # renders pending frame if ready
    # on timeline hover:
    mgr.RequestFrame(path, hover_t_s)   # debounced, non-blocking
    # in tooltip:
    if mgr.ready:
        imgui.image(ImTextureRef(mgr.texture), ...)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

THUMB_W = 320
THUMB_H = 180
THUMB_DEBOUNCE_S = 0.08   # 80 ms  --  wait for mouse to settle before seeking

try:
    import mpv as _mpv_module
    _MPV_AVAILABLE = True
except ImportError:
    _MPV_AVAILABLE = False

try:
    from OpenGL import GL as gl
    _GL_AVAILABLE = True
except ImportError:
    _GL_AVAILABLE = False

# Re-use the same proc-address function defined in video_player so both render
# contexts share the same GL symbol resolver.
try:
    from src.core.video_player import _get_proc_address
    _HAS_PROC_ADDR = True
except ImportError:
    _HAS_PROC_ADDR = False


class VideoThumbnailManager:
    """
    Secondary mpv render context for timeline hover thumbnails. Mirrors ``OFS::VideoThumbnailManager``.

    All GL calls happen on the main thread (same context as the primary player).
    mpv property observers run on mpv's internal thread and only set a
    ``threading.Event``, so no GL calls are made from the background thread.
    """

    def __init__(self) -> None:
        self._mpv = None
        self._render_ctx = None

        # GL objects
        self._fbo: int     = 0
        self._texture: int = 0

        # State
        self._current_path: str         = ""
        self._pending_path: Optional[str]  = None
        self._pending_time: Optional[float] = None
        self._last_request_wall: float   = 0.0
        self._ready: bool                = False

        # Fired from mpv's thread when a new frame is available to render
        self._render_pending: threading.Event = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def Init(self) -> bool:
        """
        Create the thumbnail mpv + render context. Mirrors ``VideoThumbnailManager::Init``.

        Must be called while the OpenGL context is current.
        Returns True on success; falls back to no-op on failure.
        """
        if not _MPV_AVAILABLE:
            log.debug("Thumbnails disabled: python-mpv not available")
            return False
        if not _GL_AVAILABLE:
            log.debug("Thumbnails disabled: PyOpenGL not available")
            return False
        if not _HAS_PROC_ADDR:
            log.debug("Thumbnails disabled: proc address function unavailable")
            return False

        try:
            self._mpv = _mpv_module.MPV(vo="libmpv")
            self._mpv["pause"]     = True
            self._mpv["loop-file"] = "inf"
            self._mpv["aid"]       = "no"   # no audio decoding  --  faster seek
            self._mpv["sid"]       = "no"   # no subtitles
        except Exception as exc:
            log.warning("Thumbnail mpv init failed: %s", exc)
            self._mpv = None
            return False

        try:
            self._render_ctx = _mpv_module.MpvRenderContext(
                self._mpv,
                "opengl",
                opengl_init_params={"get_proc_address": _get_proc_address},
                advanced_control=True,
            )
            self._render_ctx.update_cb = lambda: self._render_pending.set()
        except Exception as exc:
            log.warning("Thumbnail render context failed: %s", exc)
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None
            return False

        self._ensure_fbo()
        log.info("VideoThumbnailManager initialised (%dx%d)", THUMB_W, THUMB_H)
        return True

    def Shutdown(self) -> None:
        """Destroy the thumbnail render context and terminate mpv. Mirrors ``VideoThumbnailManager::Shutdown``."""
        if self._render_ctx is not None:
            try:
                self._render_ctx.free()
            except Exception:
                pass
            self._render_ctx = None
        if self._mpv is not None:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None
        self._destroy_fbo()

    # ------------------------------------------------------------------
    # Public API (called from main thread)
    # ------------------------------------------------------------------

    def SetVideo(self, path: str) -> None:
        """Load *path* into the thumbnail player (paused). Mirrors ``VideoThumbnailManager::SetVideo``."""
        if not self._mpv:
            return
        if path == self._current_path:
            return
        self._current_path = path
        self._ready = False
        try:
            self._mpv.play(path)
            self._mpv["pause"] = True
        except Exception as exc:
            log.debug("Thumbnail SetVideo: %s", exc)

    def RequestFrame(self, path: str, time_s: float) -> None:
        """
        Queue a thumbnail at *time_s* in *path*. Mirrors ``VideoThumbnailManager::RequestFrame``.

        Debounced  --  actual seek only happens after ``THUMB_DEBOUNCE_S`` of inactivity.
        """
        self._pending_path = path
        self._pending_time = time_s
        self._last_request_wall = time.monotonic()

    def Update(self) -> None:
        """
        Per-frame update: apply pending seeks and render into the FBO. Mirrors ``VideoThumbnailManager::Update``.

        Must be called every frame from the main thread with GL context current.
        """
        if not self._mpv or not self._render_ctx:
            return

        now = time.monotonic()

        # --- Apply pending seek once debounce expires ---
        if (self._pending_time is not None
                and now - self._last_request_wall >= THUMB_DEBOUNCE_S):
            path = self._pending_path
            t    = self._pending_time
            self._pending_time = None
            self._pending_path = None

            # Load new video if needed
            if path and path != self._current_path:
                self._current_path = path
                self._ready = False
                try:
                    self._mpv.play(path)
                    self._mpv["pause"] = True
                except Exception:
                    pass

            # Seek
            if path == self._current_path:
                try:
                    self._mpv.seek(t, "absolute+exact")
                    self._ready = False   # will be set after render
                except Exception:
                    pass

        # --- Render pending frame ---
        if self._render_pending.is_set():
            self._render_pending.clear()
            if self._render_ctx.update():
                self._ensure_fbo()
                try:
                    self._render_ctx.render(
                        flip_y=False,
                        opengl_fbo={
                            "w": THUMB_W,
                            "h": THUMB_H,
                            "fbo": self._fbo,
                        },
                        block_for_target_time=False,
                    )
                    self._ready = True
                except Exception as exc:
                    log.debug("Thumbnail render: %s", exc)
                finally:
                    try:
                        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
                    except Exception:
                        pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """True when a rendered frame is available in the FBO texture."""
        return self._ready and self._texture != 0

    @property
    def texture(self) -> int:
        """GL texture id containing the latest thumbnail frame (0 = not ready)."""
        return self._texture if self._ready else 0

    @property
    def width(self) -> int:
        return THUMB_W

    @property
    def height(self) -> int:
        return THUMB_H

    # ------------------------------------------------------------------
    # Private GL helpers
    # ------------------------------------------------------------------

    def _ensure_fbo(self) -> None:
        if self._fbo != 0:
            return
        try:
            fbo_arr = gl.glGenFramebuffers(1)
            tex_arr = gl.glGenTextures(1)
            self._fbo     = int(fbo_arr) if not hasattr(fbo_arr, "__len__") else int(fbo_arr[0])
            self._texture = int(tex_arr)  if not hasattr(tex_arr, "__len__") else int(tex_arr[0])

            gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA,
                            THUMB_W, THUMB_H, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo)
            gl.glFramebufferTexture2D(
                gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                gl.GL_TEXTURE_2D, self._texture, 0,
            )
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
            log.debug("Thumbnail FBO created (%dx%d)", THUMB_W, THUMB_H)
        except Exception as exc:
            log.warning("Thumbnail FBO create failed: %s", exc)

    def _destroy_fbo(self) -> None:
        if self._fbo:
            try:
                gl.glDeleteFramebuffers(1, [self._fbo])
            except Exception:
                pass
            self._fbo = 0
        if self._texture:
            try:
                gl.glDeleteTextures(1, [self._texture])
            except Exception:
                pass
            self._texture = 0
