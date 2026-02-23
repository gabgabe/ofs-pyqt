"""
TimelineManager — controller bridging the Timeline model with the video player,
project, and event system.

Responsibilities
================
* Build / rebuild the timeline layer structure from the current OFS_Project.
* Keep the video player slaved to the Transport clock.
* Expand funscript track durations when new actions are written past the end.
* Serialise / deserialise the layout via ``project._extra_state["timeline"]``.
* Provide helper methods used by the UI (e.g. create-new-track popups).
"""

from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

from src.core.events import EV, OFS_Events
from src.core.timeline import (
    Timeline, Transport, Layer, Track, TrackType,
    VideoTrackData, FunscriptTrackData, TriggerTrackData,
)

if TYPE_CHECKING:
    from src.core.video_player import OFS_Videoplayer
    from src.core.project      import OFS_Project
    from src.core.funscript    import Funscript

log = logging.getLogger(__name__)

# Default colours per track type (RGBA 0-1)
_VIDEO_COLOR      = (0.15, 0.42, 0.70, 1.0)
_FUNSCRIPT_COLORS = [
    (0.55, 0.27, 0.68, 1.0),
    (0.27, 0.55, 0.68, 1.0),
    (0.68, 0.55, 0.27, 1.0),
    (0.27, 0.68, 0.40, 1.0),
    (0.68, 0.27, 0.40, 1.0),
    (0.40, 0.68, 0.27, 1.0),
]
_TRIGGER_COLOR    = (0.80, 0.55, 0.10, 1.0)


class TimelineManager:
    """Controller that connects the :class:`Timeline` model to the rest of the app."""

    def __init__(self) -> None:
        self.timeline: Timeline = Timeline()
        self._player: Optional["OFS_Videoplayer"]  = None
        self._project: Optional["OFS_Project"]     = None
        self._slaving_video: bool = True   # True → transport drives mpv
        self._last_transport_pos: float = -1.0

    # ──────────────────────────────────────────────────────────────────────
    # Wiring
    # ──────────────────────────────────────────────────────────────────────

    def SetPlayer(self, player: "OFS_Videoplayer") -> None:
        self._player = player

    def SetProject(self, project: "OFS_Project") -> None:
        self._project = project

    # ──────────────────────────────────────────────────────────────────────
    # Per-frame tick — called from _pre_new_frame
    # ──────────────────────────────────────────────────────────────────────

    def Tick(self) -> None:
        """Advance the transport and slave the video player to it."""
        transport = self.timeline.transport
        transport.Tick()

        if not self._player or not self._player.VideoLoaded():
            return

        pos = transport.position

        # Slave the video player to the transport position.
        # Only seek if position changed significantly (avoids seeking every frame
        # when paused, which would spam mpv with seeks).
        if self._slaving_video:
            # Determine the video track so we can apply its offset + trim
            vtracks = self.timeline.VideoTracks()
            if vtracks:
                _layer, vtrack = vtracks[0]
                # GlobalToMedia accounts for offset AND trim_in
                media_t = vtrack.GlobalToMedia(pos)
                media_t = max(0.0, min(self._player.Duration(), media_t))
                # Determine if transport is within the video clip range
                in_clip = vtrack.ContainsGlobal(pos)
            else:
                media_t = pos
                in_clip = True

            if transport.is_playing:
                if in_clip:
                    # While playing, let mpv free-run and only correct drift.
                    mpv_t = self._player.CurrentTime()
                    drift = abs(mpv_t - media_t)
                    if drift > 0.15:
                        self._player.SetPositionExact(media_t)
                    # Ensure mpv is playing
                    if self._player.IsPaused():
                        self._player.SetPaused(False)
                    # Sync playback speed
                    if abs(self._player.CurrentSpeed() - transport.speed) > 0.01:
                        self._player.SetSpeed(transport.speed)
                else:
                    # Transport is outside the video clip — pause mpv
                    if not self._player.IsPaused():
                        self._player.SetPaused(True)
            else:
                # Paused / stopped: keep mpv paused and seek on demand
                if not self._player.IsPaused():
                    self._player.SetPaused(True)
                if abs(pos - self._last_transport_pos) > 0.001:
                    self._player.SetPositionExact(media_t)
            self._last_transport_pos = pos

    # ──────────────────────────────────────────────────────────────────────
    # Build from project  (call AFTER video is loaded)
    # ──────────────────────────────────────────────────────────────────────

    def BuildFromProject(self) -> None:
        """
        Populate the timeline layers from the current project.

        * Tries to restore a previously saved layout from
          ``project._extra_state["timeline"]``.
        * If none exists, builds a default layout:
          Layer 0 → video track, one layer per loaded funscript.
        """
        if not self._project:
            return

        saved = self._project._extra_state.get("timeline")
        if saved:
            try:
                self.timeline = Timeline.from_dict(saved)
                log.info("Timeline restored from project extra-state")
                self._reconcile_funscripts()
                return
            except Exception as exc:
                log.warning(f"Failed to restore timeline from state: {exc}")

        self._build_default_layout()

    def _build_default_layout(self) -> None:
        """Create a fresh layer layout from the current project data."""
        tl = Timeline()
        p = self._project
        if not p:
            self.timeline = tl
            return

        # Layer 0 — Video track (waveform + media)
        vid_dur = self._player.Duration() if (self._player and self._player.VideoLoaded()) else 10.0
        vid_layer = tl.AddLayer("Video")
        vid_track = Track(
            name="Video",
            track_type=TrackType.VIDEO,
            offset=0.0,
            duration=vid_dur,
            color=_VIDEO_COLOR,
            trim_in=0.0,
            trim_out=vid_dur,
            media_duration=vid_dur,
            video_data=VideoTrackData(
                media_path=p.media_path or "",
                fps=self._player.Fps() if (self._player and self._player.VideoLoaded()) else 30.0,
            ),
        )
        vid_layer.AddTrack(vid_track)

        # One layer per funscript
        for idx, fs in enumerate(p.funscripts):
            col = _FUNSCRIPT_COLORS[idx % len(_FUNSCRIPT_COLORS)]
            name = fs.title or f"Script {idx}"
            layer = tl.AddLayer(name)
            dur = self._funscript_duration(fs)
            track = Track(
                name=name,
                track_type=TrackType.FUNSCRIPT,
                offset=0.0,
                duration=dur,
                color=col,
                funscript_data=FunscriptTrackData(funscript_idx=idx),
            )
            layer.AddTrack(track)

        self.timeline = tl
        log.info(f"Default timeline built: {len(tl.layers)} layers")

    def _reconcile_funscripts(self) -> None:
        """After restoring a saved layout, make sure every project funscript
        has a track and stale tracks are removed.  Also ensures a Video
        layer exists."""
        if not self._project:
            return

        # Ensure at least one Video layer+track exists
        vtracks = self.timeline.VideoTracks()
        if not vtracks:
            vid_dur = self._player.Duration() if (self._player and self._player.VideoLoaded()) else 10.0
            vid_layer = self.timeline.AddLayer("Video")
            # Insert at position 0 so Video is always the first layer
            self.timeline.layers.remove(vid_layer)
            self.timeline.layers.insert(0, vid_layer)
            vid_track = Track(
                name="Video",
                track_type=TrackType.VIDEO,
                offset=0.0,
                duration=vid_dur,
                color=_VIDEO_COLOR,
                trim_in=0.0,
                trim_out=vid_dur,
                media_duration=vid_dur,
                video_data=VideoTrackData(
                    media_path=self._project.media_path or "",
                    fps=self._player.Fps() if (self._player and self._player.VideoLoaded()) else 30.0,
                ),
            )
            vid_layer.AddTrack(vid_track)

        existing_idxs = set()
        for _lay, trk in self.timeline.FunscriptTracks():
            if trk.funscript_data:
                existing_idxs.add(trk.funscript_data.funscript_idx)

        for idx, fs in enumerate(self._project.funscripts):
            if idx not in existing_idxs:
                # Add a new layer + track for this script
                col = _FUNSCRIPT_COLORS[idx % len(_FUNSCRIPT_COLORS)]
                name = fs.title or f"Script {idx}"
                layer = self.timeline.AddLayer(name)
                dur = self._funscript_duration(fs)
                track = Track(
                    name=name,
                    track_type=TrackType.FUNSCRIPT,
                    offset=0.0,
                    duration=dur,
                    color=col,
                    funscript_data=FunscriptTrackData(funscript_idx=idx),
                )
                layer.AddTrack(track)

    # ──────────────────────────────────────────────────────────────────────
    # Add video track  (deferred — called from _on_video_loaded)
    # ──────────────────────────────────────────────────────────────────────

    def AddOrUpdateVideoTrack(self) -> None:
        """Create or update the Video track with actual video duration and trim.

        Also ensures every funscript track is at least as long as the
        trimmed video clip so nothing gets clipped visually.
        """
        if not self._player or not self._player.VideoLoaded():
            return
        vid_dur = self._player.Duration()
        if vid_dur <= 0:
            return  # Duration not yet known — wait for duration-change event
        fps     = self._player.Fps()

        vtracks = self.timeline.VideoTracks()
        if vtracks:
            _layer, vtrack = vtracks[0]
            old_md = vtrack.media_duration
            vtrack.media_duration = vid_dur
            if vtrack.video_data:
                vtrack.video_data.fps = fps
                vtrack.video_data.media_path = (
                    self._project.media_path if self._project else "")
            # Detect placeholder: media_duration was 0 or changed significantly
            was_placeholder = (old_md <= 0 or abs(old_md - vid_dur) > 0.5)
            # Reset trim to full range when the source changed, or trim is invalid
            if was_placeholder or vtrack.trim_out <= 0 or vtrack.trim_out > vid_dur:
                vtrack.trim_in = 0.0
                vtrack.trim_out = vid_dur
            if vtrack.trim_in > vtrack.trim_out:
                vtrack.trim_in = 0.0
            vtrack.duration = vtrack.trim_out - vtrack.trim_in
        else:
            # No video track yet — create one
            vid_layer = self.timeline.AddLayer("Video")
            self.timeline.layers.remove(vid_layer)
            self.timeline.layers.insert(0, vid_layer)
            vtrack = Track(
                name="Video",
                track_type=TrackType.VIDEO,
                offset=0.0,
                duration=vid_dur,
                color=_VIDEO_COLOR,
                trim_in=0.0,
                trim_out=vid_dur,
                media_duration=vid_dur,
                video_data=VideoTrackData(
                    media_path=self._project.media_path if self._project else "",
                    fps=fps,
                ),
            )
            vid_layer.AddTrack(vtrack)

        # Sync funscript tracks so they’re at least as long as the video clip
        effective_dur = vtrack.duration
        for _lay, trk in self.timeline.FunscriptTracks():
            if trk.duration < effective_dur:
                trk.duration = effective_dur
        log.info(f"Video track synced: media={vid_dur:.2f}s  trim=[{vtrack.trim_in:.2f}..{vtrack.trim_out:.2f}]  clip={vtrack.duration:.2f}s")

    # ──────────────────────────────────────────────────────────────────────
    # Funscript track auto-expand
    # ──────────────────────────────────────────────────────────────────────

    def ExpandIfNeeded(self, script_idx: int, action_time_s: float) -> None:
        """Called after an action is added.  If it approaches the track end, grow."""
        for _lay, trk in self.timeline.FunscriptTracks():
            if trk.funscript_data and trk.funscript_data.funscript_idx == script_idx:
                local_t = trk.GlobalToLocal(action_time_s)
                self.timeline.ExpandFunscriptTrack(trk, local_t)
                return

    # ──────────────────────────────────────────────────────────────────────
    # Add / remove tracks
    # ──────────────────────────────────────────────────────────────────────

    def AddFunscriptTrack(
        self, script_idx: int, *, offset: float = 0.0,
        duration: float = 0.0, layer_idx: int = -1
    ) -> Optional[Track]:
        """Add a funscript track.  If *layer_idx* < 0, creates a new layer."""
        if not self._project:
            return None
        scripts = self._project.funscripts
        if not (0 <= script_idx < len(scripts)):
            return None
        fs = scripts[script_idx]
        name = fs.title or f"Script {script_idx}"
        col  = _FUNSCRIPT_COLORS[script_idx % len(_FUNSCRIPT_COLORS)]

        if duration <= 0:
            duration = self._funscript_duration(fs)

        track = Track(
            name=name,
            track_type=TrackType.FUNSCRIPT,
            offset=offset,
            duration=duration,
            color=col,
            funscript_data=FunscriptTrackData(funscript_idx=script_idx),
        )

        if layer_idx < 0 or layer_idx >= len(self.timeline.layers):
            layer = self.timeline.AddLayer(name)
        else:
            layer = self.timeline.layers[layer_idx]

        if layer.AddTrack(track):
            return track
        return None

    def AddTriggerTrack(
        self, name: str = "Triggers", *,
        offset: float = 0.0, duration: float = 60.0, layer_idx: int = -1,
    ) -> Optional[Track]:
        """Add a new trigger track."""
        track = Track(
            name=name,
            track_type=TrackType.TRIGGER,
            offset=offset,
            duration=duration,
            color=_TRIGGER_COLOR,
            trigger_data=TriggerTrackData(),
        )
        if layer_idx < 0 or layer_idx >= len(self.timeline.layers):
            layer = self.timeline.AddLayer(name)
        else:
            layer = self.timeline.layers[layer_idx]
        if layer.AddTrack(track):
            return track
        return None

    def RemoveTrack(self, track_id: str) -> bool:
        result = self.timeline.FindTrack(track_id)
        if result is None:
            return False
        layer, _track = result
        layer.RemoveTrack(track_id)
        return True

    # ──────────────────────────────────────────────────────────────────────
    # Move track to a different layer
    # ──────────────────────────────────────────────────────────────────────

    def MoveTrackToLayer(self, track_id: str, target_layer_idx: int) -> bool:
        """Move a track from its current layer into a different one."""
        result = self.timeline.FindTrack(track_id)
        if result is None:
            return False
        src_layer, track = result
        if target_layer_idx < 0 or target_layer_idx >= len(self.timeline.layers):
            return False
        dst_layer = self.timeline.layers[target_layer_idx]
        if not dst_layer.CanPlace(track.offset, track.duration):
            return False
        src_layer.RemoveTrack(track_id)
        dst_layer.AddTrack(track)
        return True

    # ──────────────────────────────────────────────────────────────────────
    # Serialisation helpers (project._extra_state)
    # ──────────────────────────────────────────────────────────────────────

    def SaveToProject(self) -> None:
        """Persist the timeline layout into the project's extra-state dict."""
        if self._project:
            self._project._extra_state["timeline"] = self.timeline.to_dict()
            log.debug("Timeline saved to project extra-state")

    def LoadFromProject(self) -> None:
        """Restore the timeline layout from the project's extra-state dict."""
        self.BuildFromProject()

    # ──────────────────────────────────────────────────────────────────────
    # Transport shortcuts (convenience for keybindings / WS API)
    # ──────────────────────────────────────────────────────────────────────

    def SyncFromPlayer(self) -> None:
        """Pull the transport position from the video player.

        Call this after external code (ScriptingMode frame-stepping, etc.)
        moves the player directly.  It keeps the transport in sync without
        requiring every caller to know about the transport.
        """
        if not self._player or not self._player.VideoLoaded():
            return
        mpv_t = self._player.CurrentTime()
        # Convert media time back to global via video track offset + trim_in
        vtracks = self.timeline.VideoTracks()
        if vtracks:
            _layer, vtrack = vtracks[0]
            # Reverse of GlobalToMedia:  media_t = (global - offset) + trim_in
            #   => global = offset + media_t - trim_in
            global_t = vtrack.offset + mpv_t - vtrack.trim_in
        else:
            global_t = mpv_t
        # Only update if drift is significant (avoid feedback loop)
        if abs(self.transport.position - global_t) > 0.005:
            self.transport.position = max(0.0, global_t)
            self._last_transport_pos = self.transport.position

    @property
    def transport(self) -> Transport:
        return self.timeline.transport

    def TogglePlay(self) -> None:
        self.transport.TogglePlay()

    def Seek(self, t: float) -> None:
        self.transport.Seek(t)

    def SeekRelative(self, delta: float) -> None:
        self.transport.SeekRelative(delta)

    def CurrentTime(self) -> float:
        return self.transport.position

    def Duration(self) -> float:
        return self.timeline.duration

    def IsPlaying(self) -> bool:
        return self.transport.is_playing

    def SetSpeed(self, speed: float) -> None:
        self.transport.speed = speed

    def AddSpeed(self, delta: float) -> None:
        self.transport.speed = max(0.1, self.transport.speed + delta)

    # ──────────────────────────────────────────────────────────────────────
    # Query helpers used by the UI
    # ──────────────────────────────────────────────────────────────────────

    def TrackForFunscript(self, script_idx: int) -> Optional[Track]:
        """Return the Track mapped to funscript[script_idx], or None."""
        for _lay, trk in self.timeline.FunscriptTracks():
            if trk.funscript_data and trk.funscript_data.funscript_idx == script_idx:
                return trk
        return None

    def LayerForFunscript(self, script_idx: int) -> Optional[Layer]:
        """Return the Layer that holds funscript[script_idx]'s track."""
        for lay, trk in self.timeline.FunscriptTracks():
            if trk.funscript_data and trk.funscript_data.funscript_idx == script_idx:
                return lay
        return None

    def IsMuted(self, script_idx: int) -> bool:
        lay = self.LayerForFunscript(script_idx)
        return lay.muted if lay else False

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _funscript_duration(self, fs: "Funscript") -> float:
        """Compute initial duration for a funscript track.

        * If the script has actions → last action + 5 s margin.
        * If empty and video is loaded → video duration.
        * Otherwise → 10 s placeholder (resized in AddOrUpdateVideoTrack).
        """
        if fs.actions and len(fs.actions) > 0:
            last_ms = fs.actions[-1].at
            return (last_ms / 1000.0) + 5.0
        if self._player and self._player.VideoLoaded():
            return self._player.Duration()
        return 10.0
