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
import time as _time
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

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
        self._player: Optional["OFS_Videoplayer"]  = None   # legacy primary
        self._players: Dict[str, "OFS_Videoplayer"] = {}     # track_id → player
        self._project: Optional["OFS_Project"]     = None
        self._slaving_video: bool = True   # True → transport drives mpv
        self._last_transport_pos: float = -1.0
        self._last_positions: Dict[str, float] = {}  # per-track last seek position
        self._was_in_clip: Dict[str, bool] = {}      # per-track: was inside clip last tick?
        self._last_seek_wall: Dict[str, float] = {}  # per-track: monotonic time of last seek issued
        self._SEEK_COOLDOWN: float = 0.35            # seconds — don't drift-correct within this of a seek
        self._transport_initiated: bool = False       # True after Transport.Seek(); prevents SyncFromPlayer from overriding
        self._frame_step_pending: bool = False        # True when player was frame-stepped; bypasses cooldown in SyncFromPlayer
        self._last_step_wall: float = 0.0             # monotonic time of last StepFrames() call
        self._step_settle_pending: bool = False        # True while waiting to re-center cache after stepping stops
        self._STEP_SETTLE_DELAY: float = 0.20          # seconds of idle after last step before re-centering cache
        # Optional callback → (fps_override: Optional[float], step_size: int)
        # Allows ScriptingMode's FPS override and step-size to feed into
        # transport-level stepping without a hard dependency.
        self._scripting_fps_getter: Optional[Callable] = None

    # ──────────────────────────────────────────────────────────────────────
    # Wiring
    # ──────────────────────────────────────────────────────────────────────

    def SetPlayer(self, player: "OFS_Videoplayer") -> None:
        """Set the legacy primary player (backward compat)."""
        self._player = player

    def SetProject(self, project: "OFS_Project") -> None:
        self._project = project

    def SetScriptingFpsGetter(self, fn: Optional[Callable]) -> None:
        """Set a callback that returns ``(fps_override, step_size)``.

        *fps_override* is either a positive float (ScriptingMode FPS
        override) or ``None`` (use video / project FPS).
        *step_size* is an int ≥ 1 (ScriptingMode step multiplier).
        """
        self._scripting_fps_getter = fn

    # ──────────────────────────────────────────────────────────────────────
    # Player pool management
    # ──────────────────────────────────────────────────────────────────────

    def RegisterPlayer(self, track_id: str, player: "OFS_Videoplayer") -> None:
        """Register a video player for a specific track."""
        self._players[track_id] = player
        log.debug(f"Registered player for track {track_id}")

    def UnregisterPlayer(self, track_id: str) -> Optional["OFS_Videoplayer"]:
        """Remove and return the player for a track (caller must Shutdown)."""
        p = self._players.pop(track_id, None)
        self._last_positions.pop(track_id, None)
        self._was_in_clip.pop(track_id, None)
        self._last_seek_wall.pop(track_id, None)
        if p:
            log.debug(f"Unregistered player for track {track_id}")
        return p

    def GetPlayerForTrack(self, track_id: str) -> Optional["OFS_Videoplayer"]:
        """Return the player instance for a specific track, or None."""
        return self._players.get(track_id)

    def ActivePlayer(self, pos: Optional[float] = None) -> Optional["OFS_Videoplayer"]:
        """Return the player for the topmost video track containing *pos*.

        Falls back to the legacy primary player if no pool match.
        """
        if pos is None:
            pos = self.timeline.transport.position
        for _lay, vt in self.timeline.VideoTracks():
            if vt.ContainsGlobal(pos):
                p = self._players.get(vt.id)
                if p and p.VideoLoaded():
                    return p
        # Fallback to legacy primary
        return self._player if (self._player and self._player.VideoLoaded()) else None

    def AllPlayers(self) -> Dict[str, "OFS_Videoplayer"]:
        """Return a copy of the track_id → player dict."""
        return dict(self._players)

    def AnyPlayerLoaded(self) -> bool:
        """True if any registered player has a video loaded."""
        if self._player and self._player.VideoLoaded():
            return True
        return any(p.VideoLoaded() for p in self._players.values())

    def AnyPlayerPlaying(self) -> bool:
        """True if any registered player is currently playing."""
        if self._player and self._player.VideoLoaded() and not self._player.IsPaused():
            return True
        return any(p.VideoLoaded() and not p.IsPaused() for p in self._players.values())

    def IsBuffering(self) -> bool:
        """True if any active video player is in a buffering state.

        Omakase pattern: the manager exposes a single ``is_buffering``
        flag that the UI can query to show a spinner/indicator.
        """
        pos = self.timeline.transport.position
        for _lay, vtrack in self.timeline.VideoTracks():
            if not vtrack.ContainsGlobal(pos):
                continue
            player = self._players.get(vtrack.id)
            if player and player.VideoLoaded() and player.IsBuffering():
                return True
        return False

    # ──────────────────────────────────────────────────────────────────────
    # Per-frame tick — called from _pre_new_frame
    # ──────────────────────────────────────────────────────────────────────

    def Tick(self) -> None:
        """Advance the transport and slave all video players to it."""
        transport = self.timeline.transport
        transport.Tick()

        pos = transport.position

        # Slave each video player to its corresponding track.
        if not self._slaving_video:
            return

        for _lay, vtrack in self.timeline.VideoTracks():
            player = self._players.get(vtrack.id)
            if not player or not player.VideoLoaded():
                continue

            # GlobalToMedia accounts for offset AND trim_in
            media_t = vtrack.GlobalToMedia(pos)
            media_t = max(0.0, min(player.Duration(), media_t))
            in_clip = vtrack.ContainsGlobal(pos)
            last_pos = self._last_positions.get(vtrack.id, -1.0)
            was_in_clip = self._was_in_clip.get(vtrack.id, False)

            now = _time.monotonic()
            last_seek = self._last_seek_wall.get(vtrack.id, 0.0)
            since_seek = now - last_seek

            if transport.is_playing:
                if in_clip:
                    if not was_in_clip:
                        # ── Entering clip: seek FIRST, then unpause. ──
                        player.SetPositionExact(media_t)
                        self._last_seek_wall[vtrack.id] = now
                        player.SetPaused(False)
                        if abs(player.CurrentSpeed() - transport.speed) > 0.01:
                            player.SetSpeed(transport.speed)
                    else:
                        # ── Already inside clip: let mpv play freely ──
                        # During normal playback, mpv's internal position
                        # naturally lags the transport by up to ~0.3 s.
                        # Issuing seeks to correct this small drift
                        # forces mpv to flush its decode pipeline and
                        # causes visible video stutter.  Only intervene
                        # for catastrophic drift (>2 s — e.g. after a
                        # speed change or external seek).
                        mpv_t = player.CurrentTime()
                        drift = abs(mpv_t - media_t)
                        if drift > 2.0 and since_seek > self._SEEK_COOLDOWN:
                            player.SetPositionExact(media_t)
                            self._last_seek_wall[vtrack.id] = now
                        # Ensure mpv is playing
                        if player.IsPaused():
                            player.SetPaused(False)
                        # Sync playback speed
                        if abs(player.CurrentSpeed() - transport.speed) > 0.01:
                            player.SetSpeed(transport.speed)
                else:
                    # Transport is outside the video clip — pause this player.
                    if not player.IsPaused():
                        player.SetPaused(True)
                    # ── Pre-seek: position the player at the clip start so
                    # it's ready to go when the transport enters the clip.
                    if pos < vtrack.offset:
                        pre_t = vtrack.GlobalToMedia(vtrack.offset)
                        pre_t = max(0.0, min(player.Duration(), pre_t))
                        cur_t = player.CurrentTime()
                        if abs(cur_t - pre_t) > 0.1 and since_seek > self._SEEK_COOLDOWN:
                            player.SetPositionExact(pre_t)
                            self._last_seek_wall[vtrack.id] = now
            else:
                # Paused / stopped: keep player paused and seek on demand.
                # Don't force-pause if the player is mid-frame-step
                # (mpv's frame-step internally unpauses briefly).
                if not player.IsPaused() and not player._seeking:
                    player.SetPaused(True)
                # If the player was frame-stepped externally (ScriptingMode),
                # set _frame_step_pending so SyncFromPlayer bypasses the
                # seek cooldown.
                if player._seeking and not self._transport_initiated:
                    self._frame_step_pending = True
                # Seek the player when the transport position changed.
                # When transport_initiated, skip the cooldown entirely —
                # the user just stepped and expects instant visual feedback.
                pos_changed = abs(pos - last_pos) > 0.001
                cooldown_ok = since_seek > self._SEEK_COOLDOWN
                if pos_changed and (cooldown_ok or self._transport_initiated):
                    player.SetPositionExact(media_t)
                    self._last_seek_wall[vtrack.id] = now
                # Once the player has finished the transport-commanded seek
                # (player._seeking cleared) AND there's no pending position
                # change, we can safely lower the flag.  This allows
                # subsequent external frame-steps to be detected by
                # SyncFromPlayer.
                if (self._transport_initiated
                        and not player._seeking
                        and not pos_changed):
                    self._transport_initiated = False

            self._was_in_clip[vtrack.id] = in_clip
            self._last_positions[vtrack.id] = pos

        self._last_transport_pos = pos

        # ── Cache settle: re-center mpv demuxer cache after stepping stops ─
        # When the user stops pressing arrow keys, re-issue a seek to the
        # current position.  This forces mpv to flush its old cache and
        # read ahead/behind from the NEW position, so the next burst of
        # steps hits cache instead of disk.
        if self._step_settle_pending and not transport.is_playing:
            now = _time.monotonic()
            if (now - self._last_step_wall) > self._STEP_SETTLE_DELAY:
                self._step_settle_pending = False
                for _lay2, vt2 in self.timeline.VideoTracks():
                    p2 = self._players.get(vt2.id)
                    if not p2 or not p2.VideoLoaded():
                        continue
                    if vt2.ContainsGlobal(pos):
                        mt2 = vt2.GlobalToMedia(pos)
                        mt2 = max(0.0, min(p2.Duration(), mt2))
                        p2.SetPositionExact(mt2)
                        self._last_seek_wall[vt2.id] = now

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
                EV.enqueue(OFS_Events.TIMELINE_BUILT)
                return
            except Exception as exc:
                log.warning(f"Failed to restore timeline from state: {exc}")

        self._build_default_layout()
        EV.enqueue(OFS_Events.TIMELINE_BUILT)

    def _build_default_layout(self) -> None:
        """Create a fresh layer layout from the current project data."""
        tl = Timeline()
        p = self._project
        if not p:
            self.timeline = tl
            return

        # Layer 0 — Video track (only if project has media)
        if p.media_path:
            vid_dur = 10.0
            vid_layer = tl.AddLayer("Video")
            vid_track = Track(
                name="Video",
                track_type=TrackType.VIDEO,
                offset=0.0,
                duration=vid_dur,
                color=_VIDEO_COLOR,
                trim_in=0.0,
                trim_out=vid_dur,
                media_duration=0.0,
                video_data=VideoTrackData(
                    media_path=p.media_path,
                    fps=0.0,
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
        has a track and stale tracks are removed."""
        if not self._project:
            return

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
    # Update video tracks  (deferred — called from _on_video_loaded)
    # ──────────────────────────────────────────────────────────────────────

    def AddOrUpdateVideoTrack(self, track_id: Optional[str] = None) -> None:
        """Update video track(s) with actual video duration and trim.

        If *track_id* is given, only that track is updated.
        Otherwise ALL video tracks with a registered player are updated.

        Also ensures every funscript track is at least as long as the
        longest trimmed video clip so nothing gets clipped visually.
        """
        longest_dur = 0.0

        for _lay, vtrack in self.timeline.VideoTracks():
            if track_id and vtrack.id != track_id:
                # Still collect existing duration for funscript sync
                if vtrack.duration > longest_dur:
                    longest_dur = vtrack.duration
                continue

            player = self._players.get(vtrack.id)
            if not player or not player.VideoLoaded():
                if vtrack.duration > longest_dur:
                    longest_dur = vtrack.duration
                continue
            vid_dur = player.Duration()
            if vid_dur <= 0:
                if vtrack.duration > longest_dur:
                    longest_dur = vtrack.duration
                continue
            fps = player.Fps()

            old_md = vtrack.media_duration
            vtrack.media_duration = vid_dur
            if vtrack.video_data:
                vtrack.video_data.fps = fps
                vtrack.video_data.media_duration = vid_dur
                vtrack.video_data.width = player.VideoWidth()
                vtrack.video_data.height = player.VideoHeight()

            # Detect placeholder: media_duration was 0 or changed significantly
            was_placeholder = (old_md <= 0 or abs(old_md - vid_dur) > 0.5)
            # Reset trim to full range when the source changed, or trim is invalid
            if was_placeholder or vtrack.trim_out <= 0 or vtrack.trim_out > vid_dur:
                vtrack.trim_in = 0.0
                vtrack.trim_out = vid_dur
            if vtrack.trim_in > vtrack.trim_out:
                vtrack.trim_in = 0.0
            vtrack.duration = vtrack.trim_out - vtrack.trim_in

            if vtrack.duration > longest_dur:
                longest_dur = vtrack.duration

            log.info(f"Video track '{vtrack.name}' synced: media={vid_dur:.2f}s  "
                     f"trim=[{vtrack.trim_in:.2f}..{vtrack.trim_out:.2f}]  "
                     f"clip={vtrack.duration:.2f}s")

        # Sync funscript tracks so they're at least as long as the longest video
        if longest_dur > 0:
            for _lay, trk in self.timeline.FunscriptTracks():
                if trk.duration < longest_dur:
                    trk.duration = longest_dur

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
        duration: float = 0.0, layer_idx: int = -1,
        color: Optional[tuple] = None, name: Optional[str] = None,
    ) -> Optional[Track]:
        """Add a funscript track.  If *layer_idx* < 0, creates a new layer."""
        if not self._project:
            return None
        scripts = self._project.funscripts
        if not (0 <= script_idx < len(scripts)):
            return None
        fs = scripts[script_idx]
        trk_name = name or fs.title or f"Script {script_idx}"
        col = color if color else _FUNSCRIPT_COLORS[script_idx % len(_FUNSCRIPT_COLORS)]

        if duration <= 0:
            duration = self._funscript_duration(fs)

        track = Track(
            name=trk_name,
            track_type=TrackType.FUNSCRIPT,
            offset=offset,
            duration=duration,
            color=col,
            funscript_data=FunscriptTrackData(funscript_idx=script_idx),
        )

        if layer_idx < 0 or layer_idx >= len(self.timeline.layers):
            layer = self.timeline.AddLayer(trk_name)
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
        """Pull the transport position from the active video player.

        Call this after external code (ScriptingMode frame-stepping, etc.)
        moves the player directly.  It keeps the transport in sync without
        requiring every caller to know about the transport.

        When the transport is **playing** the transport is the master clock,
        so we skip the sync entirely — otherwise we'd pull the transport
        back to a stale mpv position before mpv has finished processing a
        seek, creating a ping-pong loop.

        When the transport is outside all video clip ranges we also skip
        so that transport-initiated seeks beyond the video are not pulled back.
        """
        # Transport is master when playing — don't override it.
        if self.transport.is_playing:
            return

        # If the last seek was transport-initiated (user click / keybinding),
        # don't override with mpv's frame-rounded position — that causes
        # the visible off-by-one-frame cursor jump.
        if self._transport_initiated:
            return

        pos = self.transport.position
        now = _time.monotonic()

        # Find the first video track that contains the transport position
        # and has a loaded player — sync from that player.
        has_video_tracks = False
        for _lay, vtrack in self.timeline.VideoTracks():
            has_video_tracks = True
            if not vtrack.ContainsGlobal(pos):
                continue
            player = self._players.get(vtrack.id)
            if not player or not player.VideoLoaded():
                continue

            # Don't sync from player if a seek was recently issued — mpv
            # hasn't finished processing it yet and CurrentTime() is stale.
            # Also skip if the player itself is mid-seek (e.g. frame-step).
            if player._seeking:
                return
            # Bypass cooldown when a frame-step just completed — we need
            # to pull the new position into the transport immediately so
            # the cursor updates on the same frame the arrow key was pressed.
            if not self._frame_step_pending:
                last_seek = self._last_seek_wall.get(vtrack.id, 0.0)
                if (now - last_seek) < self._SEEK_COOLDOWN:
                    return

            # Reverse of GlobalToMedia:  media_t = (global - offset) + trim_in
            #   => global = offset + media_t - trim_in
            mpv_t = player.CurrentTime()
            global_t = vtrack.offset + mpv_t - vtrack.trim_in
            # Only update if drift is significant (avoid feedback loop)
            if abs(pos - global_t) > 0.005:
                self.transport.position = max(0.0, global_t)
                self._last_transport_pos = self.transport.position
                # Update _last_positions so Tick() doesn't re-seek the
                # player to the same position (preventing feedback loop).
                self._last_positions[vtrack.id] = self.transport.position
            self._frame_step_pending = False
            return

        # Fallback: legacy single player (only when no video tracks exist)
        if not has_video_tracks and self._player and self._player.VideoLoaded():
            mpv_t = self._player.CurrentTime()
            global_t = mpv_t
            if abs(pos - global_t) > 0.005:
                self.transport.position = max(0.0, global_t)
                self._last_transport_pos = self.transport.position

    @property
    def transport(self) -> Transport:
        return self.timeline.transport

    def TogglePlay(self) -> None:
        self.transport.TogglePlay()

    def Seek(self, t: float) -> None:
        self.transport.Seek(t)
        # Mark that this seek came from the transport (user / keybinding) so
        # SyncFromPlayer doesn't override it with mpv's frame-rounded position.
        self._transport_initiated = True
        # Record seek wall-time for ALL active players so that Tick()'s
        # drift-correction doesn't immediately fight the transport jump.
        now = _time.monotonic()
        for _lay, vtrack in self.timeline.VideoTracks():
            if vtrack.id in self._players:
                self._last_seek_wall[vtrack.id] = now

    def SeekRelative(self, delta: float) -> None:
        self._transport_initiated = True
        self.transport.SeekRelative(delta)

    def EffectiveFps(self, pos: Optional[float] = None) -> float:
        """Return the FPS to use for frame-stepping at *pos*.

        Priority:
        1. ScriptingMode FPS override (if active).
        2. Video track FPS (if *pos* is inside a video track).
        3. ``transport.project_fps`` (user-configurable fallback).
        """
        # 1. ScriptingMode FPS override
        if self._scripting_fps_getter:
            try:
                fps_ov, _ss = self._scripting_fps_getter()
                if fps_ov is not None and fps_ov > 0:
                    return fps_ov
            except Exception:
                pass
        # 2. Video track FPS
        if pos is None:
            pos = self.transport.position
        for _lay, vtrack in self.timeline.VideoTracks():
            if not vtrack.ContainsGlobal(pos):
                continue
            # Use track metadata FPS if available
            if vtrack.video_data and vtrack.video_data.fps > 0:
                return vtrack.video_data.fps
            # Fall back to the registered player's FPS
            player = self._players.get(vtrack.id)
            if player and player.VideoLoaded() and player.Fps() > 0:
                return player.Fps()
        return self.transport.project_fps

    def StepFrames(self, n: int) -> None:
        """Step the transport by *n* frames at the effective FPS.

        Respects ScriptingMode's step_size multiplier and FPS override
        when they are active.  The transport position is moved directly
        and Tick() slaves the video player via SetPositionExact().
        """
        fps = self.EffectiveFps()
        # Apply ScriptingMode step-size multiplier (e.g. step_size=2
        # means each arrow press moves 2 frames instead of 1).
        step_mult = 1
        if self._scripting_fps_getter:
            try:
                _fps_ov, ss = self._scripting_fps_getter()
                if ss and ss > 1:
                    step_mult = ss
            except Exception:
                pass
        self.transport.StepFrames(n * step_mult, fps)
        # Mark as transport-initiated so Tick() slaves the player
        # (bypassing cooldown) and SyncFromPlayer doesn't override
        # the position.
        self._transport_initiated = True
        # Do NOT stamp _last_seek_wall here — Tick() will do it when
        # it actually issues the SetPositionExact() to the player.
        # Stamping here would make Tick() wait for the cooldown,
        # adding 350 ms of perceived latency to every step.
        self._last_step_wall = _time.monotonic()
        self._step_settle_pending = True

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
        * If any video player is loaded → use its duration.
        * Otherwise → 10 s placeholder (resized in AddOrUpdateVideoTrack).
        """
        if fs.actions and len(fs.actions) > 0:
            last_ms = fs.actions[-1].at
            return (last_ms / 1000.0) + 5.0
        # Use first loaded player's duration
        for p in self._players.values():
            if p.VideoLoaded() and p.Duration() > 0:
                return p.Duration()
        if self._player and self._player.VideoLoaded():
            return self._player.Duration()
        return 10.0
