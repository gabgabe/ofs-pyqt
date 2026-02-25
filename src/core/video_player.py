"""
OFS_Videoplayer — Python port of OFS_Videoplayer.h / OFS_MpvVideoplayer.cpp

Architecture (identical to OFS C++):
  mpv(vo=libmpv)  →  MpvRenderContext  →  OpenGL FBO  →  GL texture
  main loop calls Update(delta) each frame which renders into the texture.
  The caller renders ImGui::Image(FrameTexture, size) to display video.

No Qt. No --wid embedding. Pure mpv render context.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import platform
import threading
import time as _time
from typing import Callable, Optional

log = logging.getLogger(__name__)

try:
    import mpv as _mpv_module
    MPV_AVAILABLE = True
except ImportError:
    MPV_AVAILABLE = False
    log.error("python-mpv not found — install with: pip install python-mpv")

try:
    from OpenGL import GL as gl
    _GL_AVAILABLE = True
except ImportError:
    _GL_AVAILABLE = False
    log.error("PyOpenGL not found — install with: pip install PyOpenGL")


# ---------------------------------------------------------------------------
# SDL2 proc-address helper for mpv render context
# ---------------------------------------------------------------------------

def _load_sdl2() -> Optional[ctypes.CDLL]:
    """Try to load SDL2 for SDL_GL_GetProcAddress — fallback only."""
    if platform.system() == "Darwin":
        # pysdl2-dll framework bundle
        try:
            import sdl2dll as _sdldll
            fw = os.path.join(
                _sdldll.get_dllpath(),
                "SDL2.framework", "Versions", "A", "SDL2",
            )
            lib = ctypes.CDLL(fw)
            lib.SDL_GL_GetProcAddress.restype = ctypes.c_void_p
            lib.SDL_GL_GetProcAddress.argtypes = [ctypes.c_char_p]
            return lib
        except Exception:
            pass
    return None


def _load_glfw() -> Optional[ctypes.CDLL]:
    """Load GLFW from imgui_bundle bundled dylib."""
    try:
        import imgui_bundle as _ib
        d = os.path.dirname(_ib.__file__)
        # imgui_bundle ships libglfw.3.dylib
        for name in ["libglfw.3.dylib", "libglfw.dylib", "libglfw.3.3.dylib"]:
            path = os.path.join(d, name)
            if os.path.exists(path):
                lib = ctypes.CDLL(path)
                lib.glfwGetProcAddress.restype = ctypes.c_void_p
                lib.glfwGetProcAddress.argtypes = [ctypes.c_char_p]
                log.info(f"GLFW loaded from: {path}")
                return lib
    except Exception:
        pass
    # System GLFW
    n = ctypes.util.find_library("glfw")
    if n:
        try:
            lib = ctypes.CDLL(n)
            lib.glfwGetProcAddress.restype = ctypes.c_void_p
            lib.glfwGetProcAddress.argtypes = [ctypes.c_char_p]
            return lib
        except OSError:
            pass
    return None


_sdl2: Optional[ctypes.CDLL] = None
_glfw: Optional[ctypes.CDLL] = None

# Must be a C function pointer — keep a module-level reference so GC doesn't collect it
_GET_PROC_FN_TYPE = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)

@_GET_PROC_FN_TYPE
def _get_proc_address(ctx, name) -> int:
    global _glfw, _sdl2
    # Prefer GLFW (same backend as hello_imgui)
    if _glfw is None:
        _glfw = _load_glfw()
    if _glfw is not None:
        if isinstance(name, str):
            name = name.encode()
        addr = _glfw.glfwGetProcAddress(name)
        if addr:
            return addr
    # Fallback to SDL2
    if _sdl2 is None:
        _sdl2 = _load_sdl2()
    if _sdl2 is not None:
        if isinstance(name, str):
            name = name.encode()
        addr = _sdl2.SDL_GL_GetProcAddress(name)
        return addr or 0
    return 0


# ---------------------------------------------------------------------------
# OFS_Videoplayer
# ---------------------------------------------------------------------------

class OFS_Videoplayer:
    """Mpv render-context video player. Mirrors ``OFS_Videoplayer`` (OFS_Videoplayer.h)."""

    MinPlaybackSpeed: float = 0.05
    MaxPlaybackSpeed: float = 3.0

    def __init__(self) -> None:
        self._mpv = None
        self._render_ctx = None

        # GL objects
        self._fbo: int = 0
        self._texture: int = 0
        self._fbo_w: int = 1920
        self._fbo_h: int = 1080

        # Data cache (mirrors MpvDataCache)
        self._duration: float  = 1.0
        self._percent_pos: float = 0.0
        self._speed: float     = 1.0
        self._fps: float       = 30.0
        self._paused: bool     = True
        self._video_width: int = 0
        self._video_height: int = 0
        self._volume: float    = 50.0
        self._last_volume: float = 50.0
        self._video_loaded: bool = False
        self._file_path: str   = ""
        self._logical_pos: float = 0.0  # mirrors logicalPosition
        self._last_seek_time: float = 0.0  # monotonic ts of last SeekFrames call

        # Actual measured playback speed (EMA of observed pos-change / wall-time)
        self._actual_speed: float = 1.0
        self._last_pct_for_speed: float = 0.0   # percent_pos at last measurement
        self._last_pct_wall: float = 0.0         # wall time at last measurement

        # Render update signal — set from mpv callback thread, cleared by main thread
        # Mirrors OFS SDL_atomic_t renderUpdate
        self._render_pending: threading.Event = threading.Event()

        # Event callbacks (replaces EV::Enqueue<T>)
        self.on_video_loaded:    Optional[Callable] = None
        self.on_duration_change: Optional[Callable] = None
        self.on_time_change:     Optional[Callable] = None
        self.on_pause_change:    Optional[Callable] = None
        self.on_speed_change:    Optional[Callable] = None

    # ------------------------------------------------------------------
    def Init(self, hw_accel: bool = True) -> bool:
        """Initialise mpv and the render context (requires current GL context). Mirrors ``OFS_Videoplayer::Init``."""
        if not MPV_AVAILABLE:
            log.error("python-mpv not available")
            return False
        if not _GL_AVAILABLE:
            log.error("PyOpenGL not available")
            return False

        # vo=libmpv: render into our OpenGL FBO — no native OS window is created.
        # Without this mpv defaults to vo=gpu and opens its own Cocoa/X11 window.
        self._mpv = _mpv_module.MPV(vo="libmpv")
        try:
            # Don't loop — timeline transport controls playback flow.
            # loop_file="inf" caused end-of-video flashing when transport
            # reached the clip's end boundary.
            self._mpv["loop-file"] = "no"
        except Exception:
            pass

        try:
            # Keep video open at last frame when reaching EOF (don't close).
            self._mpv["keep-open"] = "yes"
        except Exception:
            pass

        if hw_accel:
            try:
                # gpu-hq adds heavy GLSL shaders (debanding, ewa_lanczos scaling, etc.)
                # that are fine in native C++ but add significant Python FFI overhead.
                # Use hwdec only — let mpv choose quality defaults.
                self._mpv["hwdec"] = "auto-safe"
            except Exception:
                pass
        else:
            try:
                self._mpv["hwdec"] = "no"
            except Exception:
                pass

        try:
            self._mpv["pause"] = True
        except Exception:
            pass

        self._register_observers()

        try:
            # advanced_control=True: mirrors MPV_RENDER_PARAM_ADVANCED_CONTROL=1 in OFS.
            # Gives the application full control of render timing — mpv will NOT
            # drive its own scheduling loop or block our thread.
            self._render_ctx = _mpv_module.MpvRenderContext(
                self._mpv,
                "opengl",
                opengl_init_params={"get_proc_address": _get_proc_address},
                advanced_control=True,
            )
        except Exception as e:
            log.error(f"Failed to create mpv render context: {e}")
            return False

        # Wire render-update callback (mirrors OnMpvRenderUpdate + SDL_AtomicIncRef).
        # Called from mpv's internal thread when a new frame is ready.
        self._render_ctx.update_cb = lambda: self._render_pending.set()

        log.info("OFS_Videoplayer initialized")
        return True

    def Shutdown(self) -> None:
        """Destroy the render context and terminate mpv. Mirrors ``OFS_Videoplayer::Shutdown``."""
        if self._render_ctx is not None:
            try:
                self._render_ctx.free()
            except Exception:
                pass
            self._render_ctx = None
        if self._mpv is not None:
            self._mpv.terminate()
            self._mpv = None
        self._destroy_fbo()

    def _register_observers(self) -> None:
        @self._mpv.property_observer("duration")
        def _on_dur(name, value):
            if value is not None:
                self._duration = float(value)
                if self.on_duration_change:
                    self.on_duration_change(self._duration)

        @self._mpv.property_observer("percent-pos")
        def _on_pct(name, value):
            if value is not None:
                new_pct = float(value) / 100.0
                now = _time.monotonic()
                # Compute actual speed: Δpos * duration / Δwall_time
                dt = now - self._last_pct_wall
                dp = new_pct - self._last_pct_for_speed
                if dt > 0.01 and self._duration > 0 and dp > 0:
                    measured = (dp * self._duration) / dt
                    # EMA with α=0.2 — smooth out single-frame jitter
                    self._actual_speed = 0.8 * self._actual_speed + 0.2 * measured
                if not self._paused:
                    self._last_pct_for_speed = new_pct
                    self._last_pct_wall = now
                self._percent_pos = new_pct
                if self.on_time_change:
                    self.on_time_change(self._duration * self._percent_pos)

        @self._mpv.property_observer("pause")
        def _on_pause(name, value):
            if value is not None:
                self._paused = bool(value)
                if self._paused:
                    # Reset tracking so speed doesn't linger from old position
                    self._last_pct_for_speed = self._percent_pos
                    self._last_pct_wall = _time.monotonic()
                    self._actual_speed = self._speed
                if self.on_pause_change:
                    self.on_pause_change(self._paused)

        @self._mpv.property_observer("speed")
        def _on_speed(name, value):
            if value is not None:
                self._speed = float(value)
                if self.on_speed_change:
                    self.on_speed_change(self._speed)

        @self._mpv.property_observer("width")
        def _on_w(name, value):
            if value is not None:
                self._video_width = int(value)

        @self._mpv.property_observer("height")
        def _on_h(name, value):
            if value is not None:
                self._video_height = int(value)

        @self._mpv.property_observer("fps")
        def _on_fps(name, value):
            if value is not None:
                self._fps = float(value)

        @self._mpv.property_observer("path")
        def _on_path(name, value):
            if value is not None:
                self._file_path  = str(value)
                self._video_loaded = True
                if self.on_video_loaded:
                    self.on_video_loaded(self._file_path)

    # ------------------------------------------------------------------
    # FBO management
    # ------------------------------------------------------------------

    @staticmethod
    def _gl_gen_one(gen_fn) -> int:
        """Call glGenFramebuffers/glGenTextures(1) and return the ID as int.

        PyOpenGL can return an int, a numpy scalar, or a 1-element array
        depending on whether the C-accelerator is loaded.  This handles all cases.
        """
        v = gen_fn(1)
        try:
            return int(v)        # plain int or numpy scalar
        except TypeError:
            return int(v[0])     # array / list

    def _ensure_fbo(self) -> None:
        w = self._video_width  if self._video_width  > 0 else 1920
        h = self._video_height if self._video_height > 0 else 1080

        if self._fbo == 0:
            self._fbo     = self._gl_gen_one(gl.glGenFramebuffers)
            self._texture = self._gl_gen_one(gl.glGenTextures)

            gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, w, h, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                      gl.GL_TEXTURE_2D, self._texture, 0)
            from ctypes import c_uint
            draw_bufs = (c_uint * 1)(gl.GL_COLOR_ATTACHMENT0)
            gl.glDrawBuffers(1, draw_bufs)
            status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
            if status != gl.GL_FRAMEBUFFER_COMPLETE:
                log.error(f"FBO incomplete: {status:#x}")
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)

            self._fbo_w, self._fbo_h = w, h
            log.debug(f"FBO created {w}x{h}, texture={self._texture}")

        elif w != self._fbo_w or h != self._fbo_h:
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._texture)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, w, h, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
            self._fbo_w, self._fbo_h = w, h
            log.debug(f"FBO resized {w}x{h}")

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

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def Update(self, delta: float) -> None:
        """Render pending mpv frames into the FBO. Mirrors ``OFS_Videoplayer::Update``.

        OFS C++ drain loop:
          while(SDL_AtomicGet(&renderUpdate) > 0) {
              if (flags & MPV_RENDER_UPDATE_FRAME) RenderFrameToTexture();
              SDL_AtomicDecRef(&renderUpdate);
          }
        """
        if self._render_ctx is None:
            return

        # Fast-path: nothing pending (callback not fired since last frame)
        if not self._render_pending.is_set():
            return
        self._render_pending.clear()

        # Drain all frames mpv has queued (cap at 8 to avoid infinite loop)
        for _ in range(8):
            if not self._render_ctx.update():   # MPV_RENDER_UPDATE_FRAME check
                break
            self._ensure_fbo()
            try:
                self._render_ctx.render(
                    flip_y=False,
                    opengl_fbo={"w": self._fbo_w, "h": self._fbo_h, "fbo": self._fbo},
                    # block_for_target_time=False mirrors MPV_RENDER_PARAM_BLOCK_FOR_TARGET_TIME=0.
                    # Without this mpv sleeps inside render() to hit its own frame deadline,
                    # which fights hello_imgui's vsync and causes FPS drops.
                    block_for_target_time=False,
                )
            except Exception as e:
                log.warning(f"mpv render: {e}")
                break
            finally:
                # Restore default FBO so hello_imgui's render pass is unaffected
                try:
                    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
                except Exception:
                    pass

    def NotifySwap(self) -> None:
        """Signal a buffer swap to mpv. Mirrors ``OFS_Videoplayer::NotifySwap``."""
        if self._render_ctx is not None:
            try:
                self._render_ctx.report_swap()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Playback API (exact OFS names)
    # ------------------------------------------------------------------

    def OpenVideo(self, path: str) -> None:
        """Load and begin playing *path*. Mirrors ``OFS_Videoplayer::OpenVideo``."""
        if not self._mpv:
            return
        self._video_loaded = False
        self._mpv.play(path)

    def CloseVideo(self) -> None:
        """Stop playback and unload the current video. Mirrors ``OFS_Videoplayer::CloseVideo``."""
        if not self._mpv:
            return
        self._video_loaded = False
        self._file_path = ""
        try:
            self._mpv.command("stop")
        except Exception:
            pass

    def SetPaused(self, paused: bool) -> None:
        """Pause or resume playback. Mirrors ``OFS_Videoplayer::SetPaused``."""
        if not self._mpv:
            return
        try:
            self._mpv["pause"] = paused
        except Exception:
            pass

    def TogglePlay(self) -> None:
        """Toggle between play and pause. Mirrors ``OFS_Videoplayer::TogglePlay``."""
        self.SetPaused(not self.IsPaused())

    def SetPositionExact(self, time_s: float, pauses: bool = False) -> None:
        """Seek to an absolute time in seconds. Mirrors ``OFS_Videoplayer::SetPositionExact``."""
        if not self._mpv:
            return
        self._logical_pos = time_s
        if pauses:
            self.SetPaused(True)
        try:
            self._mpv.seek(time_s, "absolute+exact")
        except Exception:
            pass

    def SetPositionPercent(self, pct: float, pauses: bool = False) -> None:
        """Seek to a normalised position (0–1). Mirrors ``OFS_Videoplayer::SetPositionPercent``."""
        if not self._mpv:
            return
        self._logical_pos = pct * self._duration
        if pauses:
            self.SetPaused(True)
        try:
            self._mpv.seek(pct * 100.0, "absolute-percent+exact")
        except Exception:
            pass

    def SeekRelative(self, delta_s: float) -> None:
        """Seek forward or backward by *delta_s* seconds. Mirrors ``OFS_Videoplayer::SeekRelative``."""
        if not self._mpv:
            return
        try:
            self._mpv.seek(delta_s, "relative+exact")
        except Exception:
            pass

    def SeekFrames(self, offset: int) -> None:
        """Step forward or backward by *offset* video frames. Mirrors ``OFS_Videoplayer::SeekFrames``."""
        if not self._mpv:
            return
        # Rate-limit: don't flood mpv's command queue faster than a single
        # frame time.  This only throttles individual SeekFrames calls —
        # the keybinding system already handles repeat timing.
        now = _time.monotonic()
        min_interval = self.FrameTime() * 0.5
        if now - self._last_seek_time < min_interval:
            return
        self._last_seek_time = now
        try:
            cmd = "frame-step" if offset > 0 else "frame-back-step"
            for _ in range(abs(offset)):
                self._mpv.command(cmd)
        except Exception:
            pass

    def NextFrame(self) -> None:
        """Advance one video frame. Mirrors ``OFS_Videoplayer::NextFrame``."""
        self.SeekFrames(1)

    def PreviousFrame(self) -> None:
        """Step back one video frame. Mirrors ``OFS_Videoplayer::PreviousFrame``."""
        self.SeekFrames(-1)

    def SetSpeed(self, speed: float) -> None:
        """Set playback speed, clamped to valid range. Mirrors ``OFS_Videoplayer::SetSpeed``."""
        if not self._mpv:
            return
        speed = max(self.MinPlaybackSpeed, min(self.MaxPlaybackSpeed, speed))
        try:
            self._mpv["speed"] = speed
        except Exception:
            pass

    def AddSpeed(self, delta: float) -> None:
        """Increment playback speed by *delta*. Mirrors ``OFS_Videoplayer::AddSpeed``."""
        self.SetSpeed(self._speed + delta)

    def SetVolume(self, volume: float) -> None:
        """Set audio volume (0–100). Mirrors ``OFS_Videoplayer::SetVolume``."""
        if not self._mpv:
            return
        self._volume = max(0.0, min(100.0, volume))
        try:
            self._mpv["volume"] = self._volume
        except Exception:
            pass

    def Mute(self) -> None:
        """Mute audio, saving current volume for later restore. Mirrors ``OFS_Videoplayer::Mute``."""
        self._last_volume = self._volume
        self.SetVolume(0.0)

    def Unmute(self) -> None:
        """Restore volume to the level before mute. Mirrors ``OFS_Videoplayer::Unmute``."""
        self.SetVolume(self._last_volume)

    def CycleSubtitles(self) -> None:
        """Cycle through available subtitle tracks. Mirrors ``OFS_Videoplayer::CycleSubtitles``."""
        if not self._mpv:
            return
        try:
            self._mpv.command("cycle", "sub")
        except Exception:
            pass

    def SaveFrameToImage(self, directory: str) -> None:
        """Save the current frame as a PNG screenshot. Mirrors ``OFS_Videoplayer::SaveFrameToImage``."""
        if not self._mpv:
            return
        os.makedirs(directory, exist_ok=True)
        try:
            self._mpv.command("screenshot-to-file",
                              os.path.join(directory, "screenshot.png"), "video")
        except Exception as e:
            log.error(f"SaveFrameToImage: {e}")

    def SyncWithPlayerTime(self) -> None:
        """Re-seek to the current reported player time. Mirrors ``OFS_Videoplayer::SyncWithPlayerTime``."""
        self.SetPositionExact(self.CurrentPlayerTime())

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def VideoLoaded(self) -> bool:
        """True if a video file is currently loaded. Mirrors ``MpvDataCache::videoLoaded``."""
        return self._video_loaded

    def IsPaused(self) -> bool:
        """True if playback is paused. Mirrors ``MpvDataCache::paused``."""
        return self._paused

    def Duration(self) -> float:
        """Total duration in seconds. Mirrors ``MpvDataCache::duration``."""
        return self._duration

    def CurrentTime(self) -> float:
        """Current playback time in seconds. Mirrors ``MpvDataCache::percentPos * duration``."""
        return self._duration * self._percent_pos

    def CurrentPlayerTime(self) -> float:
        """Alias for ``CurrentTime``. Mirrors ``OFS_Videoplayer::CurrentPlayerTime``."""
        return self.CurrentTime()

    def CurrentPlayerPosition(self) -> float:
        """Current position as a normalised 0–1 value. Mirrors ``MpvDataCache::percentPos``."""
        return self._percent_pos

    def CurrentPercentPosition(self) -> float:
        """Logical position as a 0–1 fraction. Mirrors ``OFS_Videoplayer::CurrentPercentPosition``."""
        if self._duration > 0:
            return self._logical_pos / self._duration
        return 0.0

    def VideoWidth(self) -> int:
        """Width of the loaded video in pixels. Mirrors ``MpvDataCache::videoWidth``."""
        return self._video_width

    def VideoHeight(self) -> int:
        """Height of the loaded video in pixels. Mirrors ``MpvDataCache::videoHeight``."""
        return self._video_height

    def Fps(self) -> float:
        """Video frame rate (falls back to 30). Mirrors ``MpvDataCache::fps``."""
        return self._fps if self._fps > 0 else 30.0

    def FrameTime(self) -> float:
        """Duration of one video frame in seconds. Mirrors ``OFS_Videoplayer::FrameTime``."""
        return 1.0 / self.Fps()

    def CurrentSpeed(self) -> float:
        """Current playback speed multiplier. Mirrors ``MpvDataCache::speed``."""
        return self._speed

    def ActualSpeed(self) -> float:
        """Smoothed measured playback speed (EMA of observed position change)."""
        return self._actual_speed

    def Volume(self) -> float:
        """Current audio volume (0–100). Mirrors ``MpvDataCache::volume``."""
        return self._volume

    def VideoPath(self) -> str:
        """Absolute path of the currently loaded video. Mirrors ``MpvDataCache::filePath``."""
        return self._file_path

    @property
    def FrameTexture(self) -> int:
        """GL texture id for ``ImGui::Image()``. Mirrors ``OFS_Videoplayer::FrameTexture``."""
        return self._texture
