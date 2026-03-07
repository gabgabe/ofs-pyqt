"""
OpenFunscripter  --  Python port of OpenFunscripter.h / OpenFunscripter.cpp

Architecture mirrors OFS C++ exactly:
  Init()   --  SDL2 + OpenGL + ImGui + mpv + keybindings + event listeners
  Run()    --  hello_imgui main loop (callbacks: pre_new_frame, show_gui, after_swap)
  Step()   --  processEvents -> update -> ImGui panels -> render
  Shutdown()  --  destroy in correct order

ImGui + SDL2 + OpenGL via imgui-bundle (hello_imgui runner).
Video via mpv render context -> GL texture -> imgui.image().
No Qt anywhere.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from imgui_bundle import hello_imgui, imgui, ImVec2, ImVec4
from imgui_bundle import icons_fontawesome_6 as fa

from src.core.events      import EV, OFS_Events
from src.core.funscript   import Funscript, FunscriptAction
from src.core.project     import OFS_Project
from src.core.undo_system import UndoSystem, StateType
from src.core.video_player import OFS_Videoplayer
from src.core.keybindings  import OFS_KeybindingSystem
from src.core.websocket_api import WebSocketAPI
from src.core.waveform     import WaveformData
from src.core.thumbnail    import VideoThumbnailManager
from src.core.timeline_manager import TimelineManager

from src.ui.videoplayer_window   import OFS_VideoplayerWindow
from src.ui.videoplayer_controls import OFS_VideoplayerControls
from src.ui.script_timeline      import ScriptTimeline
from src.ui.panels.scripting_mode    import ScriptingMode
from src.ui.panels.special_functions import SpecialFunctionsWindow
from src.ui.panels.action_editor     import ActionEditorWindow
from src.ui.panels.statistics        import StatisticsWindow
from src.ui.panels.undo_history      import UndoHistoryWindow
from src.ui.panels.simulator         import SimulatorWindow
from src.ui.panels.preferences       import PreferencesWindow
from src.ui.panels.chapter_manager   import ChapterManagerWindow
from src.ui.panels.metadata_editor   import MetadataEditorWindow
from src.ui.panels.track_info         import TrackInfoWindow
from src.ui.panels.launch_wizard       import LaunchWizard
from src.ui.panels.routing_panel       import RoutingPanel
from src.core.routing_matrix           import RoutingMatrix
from src.core.device_manager            import DeviceManager
from src.ui.app_state    import OFS_Status, AUTO_BACKUP_INTERVAL, FUNSCRIPT_AXIS_NAMES
from src.ui.app_editing  import EditingCommandsMixin
from src.ui.app_keybindings import KeybindingsMixin
from src.ui.app_menu       import MenuBarMixin

log = logging.getLogger(__name__)


class OpenFunscripter(EditingCommandsMixin, KeybindingsMixin, MenuBarMixin):
    """
    Python port of C++ OpenFunscripter.
    Single instance. Call Init() -> Run() -> Shutdown().
    """

    ptr: Optional["OpenFunscripter"] = None  # global singleton

    def __init__(self) -> None:
        # Core systems
        self.player       = OFS_Videoplayer()  # primary (legacy) player
        self._video_players: dict = {}  # track_id -> OFS_Videoplayer (player pool)
        self.project      = OFS_Project()
        self.undo_system  = UndoSystem()
        self.keys         = OFS_KeybindingSystem(
            settings_path=Path.home() / ".ofs-pyqt" / "keybindings.json"
        )
        self.web_api      = WebSocketAPI()
        self.waveform     = WaveformData()
        self.thumbnail_mgr = VideoThumbnailManager()
        self.timeline_mgr = TimelineManager()

        # UI subsystems
        self.player_window   = OFS_VideoplayerWindow()
        self.player_controls = OFS_VideoplayerControls()
        self.script_timeline = ScriptTimeline()
        self.scripting       = ScriptingMode()
        self.special_funcs   = SpecialFunctionsWindow()
        self.action_editor   = ActionEditorWindow()
        self.statistics      = StatisticsWindow()
        self.undo_history    = UndoHistoryWindow()
        self.simulator       = SimulatorWindow()
        self.preferences     = PreferencesWindow()
        self.chapter_mgr     = ChapterManagerWindow()
        self.metadata_editor = MetadataEditorWindow()
        self.track_info      = TrackInfoWindow()
        self.launch_wizard   = LaunchWizard(str(Path.home() / ".ofs-pyqt"))
        self.routing         = RoutingMatrix()
        self.routing_panel   = RoutingPanel()
        self.device_mgr      = DeviceManager()

        # State
        self.status: int         = OFS_Status.NONE
        self.copied_selection: List[FunscriptAction] = []
        self._last_backup: float = time.monotonic()
        self.recent_files: List[str] = self.launch_wizard._recent_files

        # Unsaved-edits timer (for menu bar alert)
        self._unsaved_since: float = 0.0   # monotonic sec when unsaved edits began

        # Window visibility flags (mirrors OFS OpenFunscripterState)
        self.show_statistics    : bool = False
        self.show_history       : bool = False
        self.show_simulator     : bool = True
        self.show_action_editor : bool = True
        self.show_special_funcs : bool = False
        self.show_chapter_mgr   : bool = False
        self.show_metadata      : bool = False
        self.show_ws_api        : bool = False
        self.show_video         : bool = True
        self.show_preferences    : bool = False
        self.show_about          : bool = False
        self.show_project_editor : bool = False
        self.show_track_info     : bool = True
        self.show_routing       : bool = False

        # Timeline display flags
        self.always_show_bookmark_labels: bool = False

        # WebSocket server auto-start preference (persisted on exit)
        self._ws_active: bool = True

        # Pending "close without saving?" action
        self._pending_open_path:   Optional[str] = None   # path to open after confirm
        self._show_close_confirm:  bool           = False  # modal visible flag
        self._pending_remove_idx:  int            = -1     # track to remove (confirm modal)

        # -- Add Track wizard state --
        self._axis_wiz_open: bool   = False
        self._axis_wiz_name: str    = ""       # display name (axis or filename)
        self._axis_wiz_axis: str    = ""       # axis suffix ("surge", etc.)  --  empty for file-based
        self._axis_wiz_path: str    = ""       # full path (for file-based adds)
        self._axis_wiz_mode: int    = 0        # 0 = copy from track, 1 = custom
        self._axis_wiz_copy_idx: int = 0       # index into layer list
        self._axis_wiz_offset: float   = 0.0
        self._axis_wiz_duration: float = 60.0
        self._axis_wiz_color_idx: int  = 0     # selected palette index
        self._axis_wiz_color: tuple    = (0.55, 0.27, 0.68, 1.0)

        # Loaded file from CLI (set in Init)
        self._cli_file: Optional[str] = None
        # Timestamp of last keybinding activity (for idling suppression)
        self._last_key_activity: float = 0.0

    # ----------------------------------------------------------------------
    # Init
    # ----------------------------------------------------------------------

    def Init(self, cli_file: Optional[str] = None) -> bool:
        """Initialise the singleton instance. Mirrors ``OpenFunscripter::Init``."""
        assert OpenFunscripter.ptr is None, "Only one OFS instance allowed"
        OpenFunscripter.ptr = self
        self._cli_file = cli_file
        log.info("OpenFunscripter.Init()")
        return True

    # ----------------------------------------------------------------------
    # Run  --  hello_imgui main loop
    # ----------------------------------------------------------------------

    def Run(self) -> None:
        """Start the hello_imgui main loop. Mirrors ``OpenFunscripter::Run``."""
        params = hello_imgui.RunnerParams()

        # Window
        params.app_window_params.window_title = "timeline"
        params.app_window_params.window_geometry.size = (1920, 1080)
        params.app_window_params.restore_previous_geometry = True

        # ImGui window style
        params.imgui_window_params.default_imgui_window_type = (
            hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
        )
        params.imgui_window_params.show_menu_bar     = True
        params.imgui_window_params.show_status_bar   = False
        params.imgui_window_params.menu_app_title    = "timeline"

        # FPS idling  --  disabled while video plays, re-enabled when paused/idle.
        # Toggled every frame in _pre_new_frame based on playback state.
        params.fps_idling.enable_idling = True
        params.fps_idling.fps_idle      = 9.0

        # Docking layout
        params.docking_params = self._build_docking_params()

        # Callbacks
        params.callbacks.post_init      = self._post_init
        params.callbacks.pre_new_frame  = self._pre_new_frame
        params.callbacks.show_gui       = self._show_gui
        params.callbacks.show_menus     = self._show_main_menu
        params.callbacks.after_swap     = self._after_swap
        params.callbacks.before_exit    = self._before_exit
        params.callbacks.any_backend_event_callback = self._on_backend_event

        hello_imgui.run(params)

    # ----------------------------------------------------------------------
    # Docking layout  --  mirrors OFS setupDefaultLayout
    # ----------------------------------------------------------------------

    def _build_docking_params(self) -> hello_imgui.DockingParams:
        dp = hello_imgui.DockingParams()

        # Splits (order matters  --  applied top-down)
        dp.docking_splits = [
            # Bottom strip 10%  -> BottomDock  (controls + progress)
            hello_imgui.DockingSplit("MainDockSpace", "BottomDock",
                                     imgui.Dir.down,  0.10),
            # Timeline 15% of remaining
            hello_imgui.DockingSplit("MainDockSpace", "TimelineDock",
                                     imgui.Dir.down,  0.165),
            # Right panel 18%
            hello_imgui.DockingSplit("MainDockSpace", "RightDock",
                                     imgui.Dir.right, 0.18),
            # Controls buttons on the left 15% of BottomDock
            hello_imgui.DockingSplit("BottomDock",    "ControlsDock",
                                     imgui.Dir.left,  0.15),
            # Right sub-splits
            hello_imgui.DockingSplit("RightDock", "ActionDock",
                                     imgui.Dir.down, 0.38),
            hello_imgui.DockingSplit("RightDock", "StatsDock",
                                     imgui.Dir.down, 0.38),
            hello_imgui.DockingSplit("RightDock", "UndoDock",
                                     imgui.Dir.down, 0.50),
        ]

        app = self  # capture for closures

        def _wrap(fn):
            """Return a no-arg lambda that calls fn()."""
            return lambda: fn()

        dp.dockable_windows = [
            hello_imgui.DockableWindow(
                label_="Video###VIDEOPLAYER",
                dock_space_name_="MainDockSpace",
                gui_function_=lambda: app.player_window.Draw(
                    app.player, app.show_video,
                    timeline_mgr=app.timeline_mgr,
                ),
                is_visible_=True,
            ),
            hello_imgui.DockableWindow(
                label_="Progress###Timeline",
                dock_space_name_="BottomDock",
                gui_function_=lambda: app.player_controls.DrawTimeline(
                    app.player, app.project.active_script, app.chapter_mgr,
                    app.always_show_bookmark_labels,
                    app.thumbnail_mgr,
                ),
                is_visible_=True,
            ),
            hello_imgui.DockableWindow(
                label_="Controls###Controls",
                dock_space_name_="ControlsDock",
                gui_function_=lambda: app.player_controls.DrawControls(app.player),
                is_visible_=True,
            ),
            hello_imgui.DockableWindow(
                label_="Timeline###ScriptTimeline",
                dock_space_name_="TimelineDock",
                gui_function_=lambda: app.script_timeline.Show(
                    app.player, app.project.funscripts,
                    app.project.active_idx,
                    timeline_mgr=app.timeline_mgr,
                ),
                is_visible_=True,
            ),
            hello_imgui.DockableWindow(
                label_="Scripting###ScriptingMode",
                dock_space_name_="RightDock",
                gui_function_=lambda: app.scripting.Show(app.player),
                is_visible_=True,
            ),
            hello_imgui.DockableWindow(
                label_="Action Editor###ActionEditor",
                dock_space_name_="ActionDock",
                gui_function_=lambda: app.action_editor.Show(
                    app.player, app.project.active_script,
                    app.scripting, app.undo_system,
                    timeline_mgr=app.timeline_mgr,
                    active_idx=app.project.active_idx,
                ),
                is_visible_=app.show_action_editor,
            ),
            hello_imgui.DockableWindow(
                label_="Statistics###Statistics",
                dock_space_name_="StatsDock",
                gui_function_=lambda: app.statistics.Show(
                    app.player, app.project.active_script
                ),
                is_visible_=app.show_statistics,
            ),
            hello_imgui.DockableWindow(
                label_="Undo History###UndoHistory",
                dock_space_name_="UndoDock",
                gui_function_=lambda: app.undo_history.Show(app.undo_system),
                is_visible_=app.show_history,
            ),
            hello_imgui.DockableWindow(
                label_="Track Info###TrackInfo",
                dock_space_name_="StatsDock",
                gui_function_=lambda: app.track_info.Show(
                    app.timeline_mgr, app.device_mgr, app.routing),
                is_visible_=app.show_track_info,
            ),
        ]

        return dp

    # ----------------------------------------------------------------------
    # hello_imgui callbacks
    # ----------------------------------------------------------------------

    def _post_init(self) -> None:
        """Called after GL context + ImGui are ready."""
        log.info("_post_init: GL context ready")

        # Restore persisted panel visibility and settings
        self._load_app_state()

        # Init video player (needs GL context current)
        hw_accel = self.preferences.force_hw_decoding
        if not self.player.Init(hw_accel):
            log.error("Failed to init video player")

        # Init thumbnail manager (needs same GL context as player)
        self.thumbnail_mgr.Init()

        # Init player controls + heatmap
        self.player_controls.Init(self.player)

        # Wire player events
        self.player.on_video_loaded    = self._on_video_loaded
        self.player.on_duration_change = self._on_duration_change
        self.player.on_time_change     = self._on_time_change
        self.player.on_pause_change    = self._on_pause_change

        # Register keybindings
        self._register_bindings()

        # Register event listeners
        self._register_events()

        # Init scripting mode
        self.scripting.Init(self.player, self.undo_system)
        self.scripting.SetActiveGetter(self._active)
        self.scripting.SetTimelineManager(self.timeline_mgr)

        # Init timeline
        self.script_timeline.Init()
        self.script_timeline.waveform = self.waveform
        self.script_timeline.set_colors(self.preferences.colors)

        # Wire shared colour table into sub-components
        self.player_controls.set_colors(self.preferences.colors)
        self.simulator.set_colors(self.preferences.colors)

        # Init timeline manager (DAW-mode transport controller)
        self.timeline_mgr.SetPlayer(self.player)
        self.timeline_mgr.SetProject(self.project)
        # Wire cue engine to device manager so cues can fire device commands
        self.timeline_mgr.cue_engine.set_device_manager(self.device_mgr)

        # Wire ScriptingMode's FPS override + step_size into transport-level stepping.
        def _scripting_fps_info():
            sc = self.scripting
            fps_ov = sc._frame_fps_value if sc._frame_fps_override else None
            return (fps_ov, sc._step_size)
        self.timeline_mgr.SetScriptingFpsGetter(_scripting_fps_info)

        # Wire transport into player controls so play/pause/seek/speed
        # go through the transport instead of calling the player directly.
        self.player_controls.SetTimelineManager(self.timeline_mgr)
        self.chapter_mgr._timeline_mgr = self.timeline_mgr

        # Faster key-repeat: default ImGui settings (delay=0.275s, rate=0.050s)
        # feel sluggish for frame-by-frame stepping and action moving.
        # Shorter delay + higher rate makes held-key scrolling smooth.
        try:
            io = imgui.get_io()
            io.key_repeat_delay = 0.150   # was 0.275 s  --  start repeating sooner
            io.key_repeat_rate  = 0.020   # was 0.050 s -> 50 Hz repeat
        except Exception:
            pass

        # Apply saved font scale
        if self.preferences.font_size != 14:
            try:
                imgui.get_io().font_global_scale = self.preferences.font_size / 14.0
            except Exception:
                pass

        # Wire WebSocket API state getters and command callbacks
        self.web_api.SetStateGetters(
            get_time=self.timeline_mgr.CurrentTime,
            get_duration=self.timeline_mgr.Duration,
            get_playing=self.timeline_mgr.IsPlaying,
            get_speed=lambda: self.timeline_mgr.transport.speed,
            get_media=self.player.VideoPath,
            get_funscripts=(
                lambda: self.project.funscripts if self.project.is_valid else []
            ),
        )
        self.web_api.SetCallbacks(
            on_change_time=lambda t: self.timeline_mgr.Seek(t),
            on_change_play=lambda p: (self.timeline_mgr.transport.Play() if p
                                      else self.timeline_mgr.transport.Pause()),
            on_change_playbackspeed=self.timeline_mgr.SetSpeed,
        )

        # Broadcast speed changes to WS clients
        _prev_speed_cb = self.player.on_speed_change
        def _on_speed_change(speed: float) -> None:
            self.web_api.BroadcastPlaybackspeedChange(speed)
            if _prev_speed_cb:
                _prev_speed_cb(speed)
        self.player.on_speed_change = _on_speed_change

        # Init routing matrix
        self.routing.rebuild_ofs_ws_outputs()
        self.routing.SetFunscriptValueGetter(self._routing_read_funscript)
        self._routing_sync_tracks()
        self.device_mgr.sync_with_routing(self.routing)

        # Init web API (auto-start only if was active on last exit)
        if self._ws_active:
            self.web_api.Start()

        # Load CLI file or show launch wizard
        if self._cli_file:
            self.OpenFile(self._cli_file)
        elif self.launch_wizard.show_at_startup:
            self.launch_wizard.SetRecentFiles(self.recent_files)
            self.launch_wizard.Open()

        log.info("_post_init: complete")

    def _pre_new_frame(self) -> None:
        """Called every frame before imgui.new_frame()."""
        delta = imgui.get_io().delta_time

        # Update ALL video players in the pool (render pending mpv frames)
        for p in self._video_players.values():
            p.Update(delta)
        # Fallback: if primary player is not in pool, still update it
        if self.player not in self._video_players.values():
            self.player.Update(delta)

        try:
            self.timeline_mgr.Tick()
        except Exception as exc:
            log.error(f"TimelineManager.Tick() error: {exc}")

        # Process routing matrix (zero-alloc, O(active_links))
        try:
            self.routing.Process(self.timeline_mgr.CurrentTime())
            self.device_mgr.Dispatch(self.routing)
        except Exception as exc:
            log.error(f"RoutingMatrix.Process() error: {exc}", exc_info=True)

        # Idle detection: any player playing -> not idle
        any_playing = self.timeline_mgr.AnyPlayerPlaying() or (
            self.player.VideoLoaded() and not self.player.IsPaused())
        idle = not any_playing
        self.project.update(delta, idle)
        EV.process()
        self.keys.ProcessKeybindings()
        # Suppress FPS idling while video plays OR while keys are held.
        # Without this, paused + held arrow key -> 9 FPS idle -> jerky stepping.
        if self.keys.any_key_active:
            self._last_key_activity = time.monotonic()
        try:
            rp = hello_imgui.get_runner_params()
            playing  = self.timeline_mgr.IsPlaying() or any_playing
            key_held = (time.monotonic() - self._last_key_activity) < 0.25
            rp.fps_idling.enable_idling = not playing and not key_held
        except Exception:
            pass
        self.scripting.SetActivePosition(
            self.simulator.mouse_value * 100.0,
            self.simulator.mouse_on_sim,
        )
        self.scripting.Update()
        # Sync transport from player after scripting frame-steps
        self.timeline_mgr.SyncFromPlayer()
        self.script_timeline.Update()
        # Update thumbnail manager (renders pending frame with GL ctx current)
        self.thumbnail_mgr.Update()
        # Sync waveform visibility + lazy-load if just enabled
        self.script_timeline.show_waveform = self.preferences.show_waveform
        if (
            self.preferences.show_waveform
            and self.player.VideoLoaded()
            and not self.waveform.ready
            and not self.waveform.loading
        ):
            self.waveform.load_async(self.player.VideoPath())
        # Sync preferences into ScriptTimeline render flags each frame
        # (Colour values are synced by script_timeline._refresh_colors() from UIColors)
        self.script_timeline.show_max_speed_highlight = self.preferences.highlight_max_speed
        self.script_timeline.max_speed_threshold      = self.preferences.max_speed_highlight
        self.script_timeline.waveform_scale           = self.preferences.waveform_scale

        # Sync overlay mode + params from ScriptingMode -> ScriptTimeline
        sc = self.scripting
        self.script_timeline.overlay_mode = int(sc.overlay_mode)
        # For FRAME overlay: use override fps if enabled, else actual video fps
        if sc._frame_fps_override and sc._frame_fps_value > 0:
            self.script_timeline.overlay_fps = sc._frame_fps_value
        else:
            self.script_timeline.overlay_fps = (
                self.player.Fps() if self.player.VideoLoaded() else 30.0)
        # For TEMPO overlay
        self.script_timeline.overlay_bpm              = sc._tempo_bpm
        self.script_timeline.overlay_tempo_offset_s   = sc._tempo_offset_s
        self.script_timeline.overlay_tempo_measure_idx = sc._tempo_measure_idx
        self._maybe_auto_backup()

    def _show_gui(self) -> None:
        """All floating / non-docked windows drawn here."""
        # Simulator  --  top-level floating window, no_docking prevents it from
        # accidentally snapping into any dock space (including the video).
        if self.show_simulator:
            flags = (
                imgui.WindowFlags_.no_docking
                | imgui.WindowFlags_.no_collapse
            )
            imgui.set_next_window_size(ImVec2(200, 460), imgui.Cond_.first_use_ever)
            imgui.set_next_window_pos(
                ImVec2(imgui.get_main_viewport().size.x - 220, 40),
                imgui.Cond_.first_use_ever,
            )
            opened, self.show_simulator = imgui.begin(
                "Simulator###Simulator", self.show_simulator, flags
            )
            if opened:
                self.simulator.Show(self.player, self.project.active_script)
            imgui.end()

        self.show_special_funcs = self.special_funcs.Show(
            self.project.active_script, self.undo_system, self.show_special_funcs
        )
        self.show_chapter_mgr = self.chapter_mgr.Show(
            self.player, self.project, self.show_chapter_mgr
        )
        self.show_metadata = self.metadata_editor.Show(
            self.player, self.project, self.show_metadata, self.timeline_mgr
        )
        if self.show_preferences:
            self.show_preferences = self.preferences.Show()
        if self.show_ws_api:
            self._show_ws_window()
        if self.show_about:
            self._show_about_window()
        if self.show_project_editor:
            self._show_project_window()
        # Routing panel
        if self.show_routing:
            flags = (
                imgui.WindowFlags_.no_docking
                | imgui.WindowFlags_.no_collapse
            )
            imgui.set_next_window_size(ImVec2(700, 450), imgui.Cond_.first_use_ever)
            opened, self.show_routing = imgui.begin(
                "Routing###Routing", self.show_routing, flags
            )
            if opened:
                self.routing_panel.Show(self.routing, self.timeline_mgr, self.device_mgr)
            imgui.end()

        self._draw_remove_confirm()
        self._draw_close_confirm()
        self._draw_axis_wizard()
        # Launch wizard
        self.launch_wizard.Show()
        self._process_wizard_result()

    # ----------------------------------------------------------------------
    # Launch wizard result handler
    # ----------------------------------------------------------------------

    def _process_wizard_result(self) -> None:
        """Check if the launch wizard has a confirmed action and execute it."""
        action, path = self.launch_wizard.ConsumeResult()
        if action is None:
            return

        if action == "new":
            # path is the project name (no directory yet)
            self._wizard_new_project(path)
        elif action == "recent":
            if path and os.path.exists(path):
                self.OpenFile(path)
            else:
                self._alert("File not found", f"Could not find:\n{path}")
        elif action == "template":
            self._wizard_open_template(path)
        elif action == "open":
            if path:
                self.OpenFile(path)

    def _wizard_new_project(self, name: str) -> None:
        """Create a new empty project with the given name via Save dialog."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.save_file(
                "Save new project",
                name + ".ofsp",
                ["OFS Project", "*.ofsp"],
            ).result()
            if not result:
                return
            path = result
            if not path.endswith(".ofsp"):
                path += ".ofsp"
        except ImportError:
            log.warning("portable_file_dialogs not available")
            return

        # Close current
        self.project.reset()
        self._destroy_all_pool_players()
        self.player.CloseVideo()
        from src.core.timeline import Timeline
        self.timeline_mgr.timeline = Timeline()

        # Init empty project at chosen path
        self.project._path = path
        self.project._valid = True
        self.project.Save()
        if path not in self.recent_files:
            self.recent_files.append(path)

        # Build empty timeline
        self.timeline_mgr.SetProject(self.project)
        self.timeline_mgr.BuildFromProject()
        self._update_title()
        log.info(f"Wizard: new project created: {path}")

    def _wizard_open_template(self, template_path: str) -> None:
        """Create a new project from a template  --  copy then open."""
        if not os.path.exists(template_path):
            self._alert("Template not found", template_path)
            return
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            import shutil
            result = pfd.save_file(
                "Save project from template",
                Path(template_path).stem + ".ofsp",
                ["OFS Project", "*.ofsp"],
            ).result()
            if not result:
                return
            dest = result
            if not dest.endswith(".ofsp"):
                dest += ".ofsp"
            shutil.copy2(template_path, dest)
            self.OpenFile(dest)
            log.info(f"Wizard: created project from template {template_path} -> {dest}")
        except ImportError:
            log.warning("portable_file_dialogs not available")

    def _after_swap(self) -> None:
        """Called after SDL_GL_SwapWindow."""
        # Notify ALL players about the buffer swap
        for p in self._video_players.values():
            p.NotifySwap()
        if self.player not in self._video_players.values():
            self.player.NotifySwap()

    def _before_exit(self) -> None:
        self.Shutdown()

    # ----------------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------------

    def Shutdown(self) -> None:
        """Tear down all subsystems. Mirrors ``OpenFunscripter::Shutdown``."""
        log.info("Shutdown")
        self._save_app_state()
        self.launch_wizard.SetRecentFiles(self.recent_files)
        self.launch_wizard.SaveRecentFiles()
        kb_path = Path.home() / ".ofs-pyqt" / "keybindings.json"
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        self.keys.Save(kb_path)
        self.web_api.Stop()
        self.device_mgr.shutdown()
        self.thumbnail_mgr.Shutdown()
        # Shutdown all pool players (including primary if registered)
        self._destroy_all_pool_players()
        # Always shutdown the primary player too (in case it wasn't in the pool)
        self.player.Shutdown()

    # ----------------------------------------------------------------------
    # Event listeners
    # ----------------------------------------------------------------------

    def _register_events(self) -> None:
        EV.listen(OFS_Events.FUNSCRIPT_CHANGED,    self._on_funscript_changed)
        EV.listen(OFS_Events.FUNSCRIPT_REMOVED,    self._on_funscript_removed)
        EV.listen(OFS_Events.ACTION_CLICKED,       self._on_timeline_action_clicked)
        EV.listen(OFS_Events.ACTION_SHOULD_CREATE, self._on_timeline_action_created)
        EV.listen(OFS_Events.ACTION_SHOULD_MOVE,   self._on_timeline_action_moved)
        EV.listen(OFS_Events.CHANGE_ACTIVE_SCRIPT, self._on_change_active_script)
        EV.listen(OFS_Events.TIMELINE_TRACK_SELECTED, self._on_track_selected)
        EV.listen(OFS_Events.TIMELINE_TRACK_DESELECTED, self._on_track_deselected)
        EV.listen(OFS_Events.TIMELINE_ADD_AXIS_REQUEST, self._on_add_axis_request)
        EV.listen(OFS_Events.TIMELINE_BUILT,               self._on_timeline_built)

    # ----------------------------------------------------------------------
    # Routing matrix helpers
    # ----------------------------------------------------------------------

    def _routing_read_funscript(self, track_id: str, time_s: float) -> float:
        """Read the interpolated funscript value for a track at *time_s*.

        Used as the RoutingMatrix callback.  Returns 0-100.
        """
        from src.core.timeline import TrackType
        tl = self.timeline_mgr.timeline
        if not tl:
            return 0.0
        for _lay, trk in tl.FunscriptTracks():
            if trk.id == track_id and trk.funscript_data is not None:
                idx = trk.funscript_data.funscript_idx
                if 0 <= idx < len(self.project.funscripts):
                    fs = self.project.funscripts[idx]
                    # Convert global time -> track-local time
                    local_ms = (time_s - trk.offset) * 1000.0
                    if local_ms < 0:
                        return 0.0
                    return fs.actions.Interpolate(local_ms)
        return 0.0

    def _routing_sync_tracks(self) -> None:
        """Synchronise routing input nodes with current timeline funscript tracks."""
        from src.core.timeline import TrackType
        tracks = []
        tl = self.timeline_mgr.timeline
        if tl:
            for _lay, trk in tl.FunscriptTracks():
                tracks.append((trk.id, trk.name))
        self.routing.sync_funscript_tracks(tracks)

    def _on_timeline_built(self, **kw) -> None:
        """Called when the timeline layout is rebuilt  --  re-sync routing inputs."""
        self._routing_sync_tracks()
        self.device_mgr.sync_with_routing(self.routing)

    # ----------------------------------------------------------------------
    # Video player pool management
    # ----------------------------------------------------------------------

    def _create_player_for_track(self, track_id: str, media_path: str) -> Optional[OFS_Videoplayer]:
        """Create, init, and register a new video player for a track.

        Returns the player, or None if init failed.
        Requires a current GL context (call from main thread only).
        """
        player = OFS_Videoplayer()
        hw_accel = self.preferences.force_hw_decoding
        if not player.Init(hw_accel):
            log.error(f"Failed to init video player for track {track_id}")
            return None

        # Wire callbacks with closures that include the track_id
        def _on_loaded(path, _tid=track_id):
            self._on_video_loaded_for_track(_tid, path)
        def _on_dur(dur, _tid=track_id):
            self._on_duration_change_for_track(_tid, dur)

        player.on_video_loaded    = _on_loaded
        player.on_duration_change = _on_dur
        player.on_time_change     = self._on_time_change
        player.on_pause_change    = self._on_pause_change

        # Register in pool
        self._video_players[track_id] = player
        self.timeline_mgr.RegisterPlayer(track_id, player)

        if media_path and os.path.exists(media_path):
            player.OpenVideo(media_path)

        log.info(f"Created player for track {track_id}: {media_path}")
        return player

    def _destroy_player_for_track(self, track_id: str) -> None:
        """Shutdown and unregister a player for a track."""
        player = self._video_players.pop(track_id, None)
        self.timeline_mgr.UnregisterPlayer(track_id)
        if player:
            player.Shutdown()
            log.info(f"Destroyed player for track {track_id}")

    def _destroy_all_pool_players(self) -> None:
        """Shutdown all players in the pool."""
        for tid in list(self._video_players.keys()):
            self._destroy_player_for_track(tid)

    def _on_video_loaded_for_track(self, track_id: str, path: str) -> None:
        """Callback when a pooled player finishes loading its video."""
        log.info(f"Video loaded for track {track_id}: {path}")
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        self.timeline_mgr.AddOrUpdateVideoTrack(track_id)
        # Waveform + thumbnails: use the primary (first) video
        vtracks = self.timeline_mgr.timeline.VideoTracks()
        if vtracks and vtracks[0][1].id == track_id:
            self.waveform.clear()
            if self.preferences.show_waveform:
                self.waveform.load_async(path)
            self.thumbnail_mgr.SetVideo(path)
        self.web_api.BroadcastMediaChange(path)
        self.web_api.BroadcastProjectChange()

    def _on_duration_change_for_track(self, track_id: str, duration: float) -> None:
        """Callback when a pooled player reports its duration."""
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        self.timeline_mgr.AddOrUpdateVideoTrack(track_id)
        self.web_api.BroadcastDurationChange(duration)

    # ----------------------------------------------------------------------
    # Timeline action handlers  (mirrors OFS ScriptTimelineAction* handlers)
    # ----------------------------------------------------------------------

    def _on_timeline_action_clicked(self, action, script, **kw) -> None:
        """Left-click on dot: Ctrl/Shift -> multi-select, else -> seek  (mirrors OFS ScriptTimelineActionClicked)."""
        from imgui_bundle import imgui as _imgui
        io = _imgui.get_io()
        if io.key_ctrl or io.key_shift:
            # Toggle selection (Ctrl or Shift for multi-select)
            if action in script.selection:
                script.DeselectAction(action)
            else:
                script.SelectAction(action)
        else:
            # Seek: convert action local time to global transport time via track offset
            local_t = action.at / 1000.0
            fs_idx = self.project.funscripts.index(script) if script in self.project.funscripts else -1
            trk = self.timeline_mgr.TrackForFunscript(fs_idx) if fs_idx >= 0 else None
            global_t = trk.LocalToGlobal(local_t) if trk else local_t
            self.timeline_mgr.Seek(global_t)

    def _on_change_active_script(self, idx: int, **kw) -> None:
        """Timeline clicked on a different track (mirrors OFS ScriptTimelineActiveScriptChanged)."""
        scripts = self.project.funscripts
        if 0 <= idx < len(scripts) and scripts[idx].enabled:
            self.project.active_idx = idx
            self._update_title()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _on_timeline_action_created(self, action, script, **kw) -> None:
        """Ctrl+click in empty timeline space: snapshot + add action."""
        self.undo_system.Snapshot(StateType.ADD_ACTION, script)
        script.AddEditAction(action, self.scripting.LogicalFrameTime())

    def _on_timeline_action_moved(self, action, script, move_started: bool, **kw) -> None:
        """Drag an action dot: snapshot on first frame, then move every frame."""
        if move_started:
            self.undo_system.Snapshot(StateType.ACTIONS_MOVED, script)
        else:
            if script.SelectionSize() == 1:
                old = next(iter(script.selection))
                script.RemoveAction(old)
                script.AddAction(action)
                script.SelectAction(action)

    def _on_track_selected(self, track_id: str, **kw) -> None:
        """A track was clicked in the DAW  --  select it in the Track Info panel."""
        self.track_info.SelectTrack(track_id)
        self.player_controls.SetSelectedTrackId(track_id)
        self.script_timeline._selected_track_id = track_id
        # Recompute heatmap for the new effective range
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _on_track_deselected(self, **kw) -> None:
        """Clicked empty space in DAW  --  deselect the track."""
        self.track_info.SelectTrack(None)
        self.player_controls.SetSelectedTrackId(None)
        self.script_timeline._selected_track_id = None
        # Clear heatmap when no track is selected
        self.player_controls._heatmap_colours = []
        self.player_controls._heatmap_dirty = True

    def _on_add_axis_request(self, axis: str, **kw) -> None:
        """DAW context menu requested adding a new axis track."""
        self._add_axis_funscript(axis)

    def _on_video_loaded(self, path: str) -> None:
        """Primary player loaded a video. Find which track it belongs to and delegate."""
        log.info(f"Video loaded (primary): {path}")
        # Find the track_id that the primary player was registered for
        for tid, p in self._video_players.items():
            if p is self.player:
                self._on_video_loaded_for_track(tid, path)
                return
        # Legacy fallback  --  no pool registration
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        self.timeline_mgr.AddOrUpdateVideoTrack()
        self.waveform.clear()
        if self.preferences.show_waveform:
            self.waveform.load_async(path)
        self.thumbnail_mgr.SetVideo(path)
        self.web_api.BroadcastMediaChange(path)
        self.web_api.BroadcastProjectChange()

    def _on_duration_change(self, duration: float) -> None:
        """Primary player reported duration. Find track and delegate."""
        for tid, p in self._video_players.items():
            if p is self.player:
                self._on_duration_change_for_track(tid, duration)
                return
        # Legacy fallback
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        self.web_api.BroadcastDurationChange(duration)
        self.timeline_mgr.AddOrUpdateVideoTrack()

    def _on_time_change(self, time_s: float) -> None:
        self.web_api.BroadcastTimeChange(time_s)

    def _on_pause_change(self, paused: bool) -> None:
        self.web_api.BroadcastPlayChange(not paused)

    def _on_funscript_changed(self, **kw) -> None:
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        # Start unsaved timer if not already running
        if self._unsaved_since == 0.0:
            self._unsaved_since = time.monotonic()
        script = kw.get("script")
        if script is not None:
            self.web_api.BroadcastFunscriptChange(
                script.title, list(script.actions)
            )

    def _on_funscript_removed(self, title: str = "", **kw) -> None:
        if title:
            self.web_api.BroadcastFunscriptRemove(title)

    def _on_backend_event(self, event) -> bool:
        """SDL2 backend event callback  --  handle drop-file events.
        Returns True if the event was consumed."""
        try:
            # event is a hello_imgui.BackendEvent (contains .sdl_event)
            sdl_ev = getattr(event, 'sdl_event', None) or event
            # SDL_DROPFILE = 0x1000
            ev_type = getattr(sdl_ev, 'type', None)
            if ev_type == 0x1000:   # SDL_DROPFILE
                raw_file = getattr(sdl_ev.drop, 'file', None)
                if raw_file:
                    import ctypes
                    if isinstance(raw_file, (bytes, bytearray)):
                        path = raw_file.rstrip(b'\x00').decode('utf-8', errors='replace')
                    elif isinstance(raw_file, ctypes.c_char_p):
                        path = (raw_file.value or b'').decode('utf-8', errors='replace')
                    else:
                        path = str(raw_file)
                    if path:
                        self.OpenFile(path)
                    return True
        except Exception as e:
            log.debug(f"_on_backend_event: {e}")
        return False

    # ----------------------------------------------------------------------
    # Project management (mirrors OFS openFile / initProject / closeProject)
    # ----------------------------------------------------------------------

    def OpenFile(self, path: str) -> None:
        """Open a media / funscript / project file. Mirrors ``OpenFunscripter::openFile``."""
        if not os.path.exists(path):
            self._alert("File not found", f"Could not find:\n{path}")
            return
        # Ask to save if there are unsaved edits (mirrors OFS closeWithoutSavingDialog)
        if self.project.is_valid and self.project.HasUnsavedEdits():
            self._pending_open_path  = path
            self._show_close_confirm = True
            return
        self._do_open_file(path)

    def _do_open_file(self, path: str) -> None:
        """Actually open a file without any unsaved-edits guard."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".ofsp":
            self.project.reset()
            ok = self.project.Load(path)
            if ok:
                if path not in self.recent_files:
                    self.recent_files.append(path)
                self._init_project()
            else:
                self._alert("Failed to open", self.project.errors)
        elif ext == ".funscript":
            # Import funscript into existing project as new track
            if self.project.is_valid:
                self._import_funscript_to_timeline(path)
            else:
                # No project open  --  create one from the funscript
                self.project.reset()
                ok = self.project.ImportFromFunscript(path)
                if ok:
                    if path not in self.recent_files:
                        self.recent_files.append(path)
                    self._init_project()
                else:
                    self._alert("Failed to import", self.project.errors)
        else:
            # Media file  --  add as video track to timeline
            if self.project.is_valid:
                self._add_media_to_timeline(path)
            else:
                # No project open  --  create one from the media
                self.project.reset()
                ok = self.project.ImportFromMedia(path)
                if ok:
                    if path not in self.recent_files:
                        self.recent_files.append(path)
                    self._init_project()
                    if self.preferences.show_metadata_on_new:
                        self.show_metadata = True
                else:
                    self._alert("Failed to open", self.project.errors)

    def _init_project(self) -> None:
        # Destroy any existing pool players before rebuilding
        self._destroy_all_pool_players()

        # Build timeline BEFORE opening video so the Video layer already
        # exists when _on_video_loaded fires (prevents duplicate tracks).
        self.timeline_mgr.SetProject(self.project)
        self.timeline_mgr.BuildFromProject()

        # Restore routing + device config from project
        routing_d = self.project._extra_state.get("routing")
        if routing_d:
            self.routing.from_dict(routing_d)
        dm_d = self.project._extra_state.get("device_manager")
        if dm_d:
            self.device_mgr.from_dict(dm_d)
        self.device_mgr.sync_with_routing(self.routing)
        self.device_mgr.apply_saved_backend_classes(self.routing)

        # Create a player for every video track that has a media_path.
        # The first track reuses self.player (legacy primary); additional
        # tracks get fresh player instances from the pool.
        vtracks = self.timeline_mgr.timeline.VideoTracks()
        first_player_assigned = False
        for _lay, vt in vtracks:
            mpath = (vt.video_data.media_path if vt.video_data else "") or ""
            if not first_player_assigned:
                # Register the primary player for the first video track
                self._video_players[vt.id] = self.player
                self.timeline_mgr.RegisterPlayer(vt.id, self.player)
                first_player_assigned = True
                if mpath and os.path.exists(mpath):
                    self.player.OpenVideo(mpath)
                elif not mpath:
                    # Empty placeholder track (new project)  --  no video to open
                    pass
                else:
                    # Fallback: try legacy project.media_path for old .ofsp files
                    media = self.project.media_path
                    if media and os.path.exists(media):
                        self.player.OpenVideo(media)
            else:
                # Additional video tracks get their own player
                if mpath:
                    self._create_player_for_track(vt.id, mpath)

        # If no video tracks at all, still register primary for fallback
        if not first_player_assigned:
            media = self.project.media_path
            if media and os.path.exists(media):
                self.player.OpenVideo(media)

        # Auto-select the Video track in Track Info panel
        if vtracks:
            self.track_info.SelectTrack(vtracks[0][1].id)
        self._update_title()
        self._last_backup = time.monotonic()

    def SaveProject(self) -> None:
        """Persist the current project to disk. Mirrors ``OpenFunscripter::saveProject``."""
        if not self.project.is_valid:
            return
        # Persist timeline layout in project extra-state
        self.timeline_mgr.SaveToProject()
        # Persist routing matrix + device manager config
        self.project._extra_state["routing"] = self.routing.to_dict()
        self.project._extra_state["device_manager"] = self.device_mgr.to_dict()
        self.project.Save()

    def QuickExport(self) -> None:
        """Export all funscripts next to the media file. Mirrors ``OpenFunscripter::quickExport``."""
        self.project.QuickExport()

    def NewProject(self) -> None:
        """Create a brand-new empty project via Save dialog."""
        if self.project.is_valid and self.project.HasUnsavedEdits():
            self._pending_open_path = "__new__"
            self._show_close_confirm = True
            return
        self._do_new_project()

    def _do_new_project(self) -> None:
        """Actually create the new empty project."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.save_file(
                "New project",
                filters=["OFS Project", "*.ofsp"]
            ).result()
            if not result:
                return
            path = result
            if not path.endswith(".ofsp"):
                path += ".ofsp"
        except ImportError:
            log.warning("portable_file_dialogs not available")
            return

        # Close current
        self.project.reset()
        self._destroy_all_pool_players()
        self.player.CloseVideo()
        from src.core.timeline import Timeline
        self.timeline_mgr.timeline = Timeline()

        # Init empty project at chosen path
        self.project._path = path
        self.project._valid = True
        self.project.Save()
        if path not in self.recent_files:
            self.recent_files.append(path)

        # Build empty timeline  --  user adds video/funscript tracks manually
        self.timeline_mgr.SetProject(self.project)
        self.timeline_mgr.BuildFromProject()

        self._update_title()
        log.info(f"New empty project created: {path}")

    def _save_as_dialog(self) -> None:
        """Save current project to a new path (copy)."""
        if not self.project.is_valid:
            return
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.save_file(
                "Save project as",
                filters=["OFS Project", "*.ofsp"]
            ).result()
            if not result:
                return
            path = result
            if not path.endswith(".ofsp"):
                path += ".ofsp"
        except ImportError:
            log.warning("portable_file_dialogs not available")
            return

        self.timeline_mgr.SaveToProject()
        self.project.Save(path)
        if path not in self.recent_files:
            self.recent_files.append(path)
        self._update_title()
        log.info(f"Project saved as: {path}")

    def CloseProject(self) -> None:
        """Close the current project and video."""
        if self.project.is_valid and self.project.HasUnsavedEdits():
            self._pending_open_path = "__close__"
            self._show_close_confirm = True
            return
        self._do_close_project()

    def _do_close_project(self) -> None:
        """Actually close without any unsaved-edits guard."""
        self.project.reset()
        # Destroy all pool players (additional tracks)
        self._destroy_all_pool_players()
        self.player.CloseVideo()
        # Reset DAW timeline
        from src.core.timeline import Timeline
        self.timeline_mgr.timeline = Timeline()
        self._update_title()

    def _update_title(self) -> None:
        title = "OpenFunscripter"
        if self.project.is_valid:
            title = f"OpenFunscripter - {self.project.path}"
        hello_imgui.get_runner_params().app_window_params.window_title = title

    # ----------------------------------------------------------------------
    # About window
    # ----------------------------------------------------------------------

    def _show_ws_window(self) -> None:
        """Simple WebSocket API status window with start/stop toggle."""
        imgui.set_next_window_size(ImVec2(320, 120), imgui.Cond_.first_use_ever)
        opened, self.show_ws_api = imgui.begin(
            "WebSocket API###ws_api", self.show_ws_api,
            imgui.WindowFlags_.no_docking | imgui.WindowFlags_.always_auto_resize,
        )
        if opened:
            running = self.web_api.is_running
            changed, want_active = imgui.checkbox("Enable server", self._ws_active)
            if changed:
                self._ws_active = want_active
                if want_active and not running:
                    self.web_api.Start()
                elif not want_active and running:
                    self.web_api.Stop()
            imgui.same_line()
            status_col = ImVec4(0.2, 0.8, 0.2, 1.0) if running else ImVec4(0.6, 0.6, 0.6, 1.0)
            imgui.text_colored(status_col, "Running" if running else "Stopped")
            imgui.spacing()
            imgui.text_disabled(f"ws://localhost:{self.web_api.port}")
            imgui.text_disabled(f"Clients: {self.web_api.client_count}")
        imgui.end()

    def _show_about_window(self) -> None:
        imgui.set_next_window_size(ImVec2(400, 200), imgui.Cond_.first_use_ever)
        opened, self.show_about = imgui.begin(
            "About###about", self.show_about,
            imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.always_auto_resize
        )
        if opened:
            imgui.text_unformatted("OpenFunscripter - Python port")
            imgui.text_unformatted("Uses Dear ImGui + SDL2 + mpv render context")
            imgui.separator()
            if imgui.button("Close", ImVec2(-1, 0)):
                self.show_about = False
        imgui.end()

    # ----------------------------------------------------------------------
    # File dialogs
    # ----------------------------------------------------------------------

    # -- Project window ----------------------------------------------------

    def _show_project_window(self) -> None:
        """Mirrors OFS_Project::ShowProjectWindow  --  modal popup."""
        imgui.open_popup("Project###project_cfg")
        flags = imgui.WindowFlags_.no_docking | imgui.WindowFlags_.always_auto_resize
        opened, self.show_project_editor = imgui.begin_popup_modal(
            "Project###project_cfg", self.show_project_editor, flags)
        if opened:
            p = self.project
            imgui.text(f"Media: {p.state.relative_media_path or '(none)'}")
            # Time spent
            total_s = int(p.state.active_timer)
            h, rem = divmod(total_s, 3600)
            m, s   = divmod(rem, 60)
            imgui.text(f"Time spent: {h:02d}:{m:02d}:{s:02d}")
            imgui.separator()
            imgui.spacing()
            imgui.text_disabled("Scripts")
            for i, script in enumerate(p.funscripts):
                label = script.title or f"Script {i}"
                if imgui.button(label, ImVec2(-1, 0)):
                    # Let user pick a new save location for this script
                    self._repath_funscript_dialog(i)
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Click to change save location")
            imgui.end_popup()

    def _repath_funscript_dialog(self, idx: int) -> None:
        """Open a save dialog to change the saved path of funscript[idx]."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            script = self.project.funscripts[idx]
            current = self.project._make_path_absolute(script.relative_path)
            result = pfd.save_file(
                "Change save location", current or "",
                filters=["Funscript", "*.funscript"]
            ).result()
            if result:
                script.relative_path = self.project._make_path_relative(result)
                log.info(f"Script {idx} repathed to {result}")
        except Exception as exc:
            log.warning(f"_repath_funscript_dialog: {exc}")

    # -- Script track management -------------------------------------------

    def _is_script_already_loaded(self, path: str) -> bool:
        """Return True if a funscript with the same filename is already loaded."""
        from pathlib import Path as _P
        filename = _P(path).name
        return any(_P(s.relative_path).name == filename
                   for s in self.project.funscripts)

    def _add_axis_funscript(self, axis: str) -> None:
        """Open the Add Track wizard for the given axis suffix (e.g. 'surge')."""
        from pathlib import Path as _P
        scripts = self.project.funscripts
        if scripts:
            root_abs = self.project._make_path_absolute(scripts[0].relative_path)
            root = _P(root_abs)
            new_path = str(root.with_suffix("").with_suffix("").parent /
                           (root.stem.split(".")[0] + f".{axis}.funscript"))
        elif self.project.media_path:
            mp = _P(self.project.media_path)
            new_path = str(mp.with_suffix("").parent /
                           (mp.stem + f".{axis}.funscript"))
        else:
            # No legacy media_path  --  try per-track video media path
            vtracks = self.timeline_mgr.timeline.VideoTracks()
            vpath = ""
            for _lay, vt in vtracks:
                if vt.video_data and vt.video_data.media_path:
                    vpath = vt.video_data.media_path
                    break
            if vpath:
                mp = _P(vpath)
                new_path = str(mp.with_suffix("").parent /
                               (mp.stem + f".{axis}.funscript"))
            elif self.project.path:
                # Derive from project .ofsp path
                pp = _P(self.project.path)
                new_path = str(pp.with_suffix("").parent /
                               (pp.stem + f".{axis}.funscript"))
            else:
                log.warning("Cannot add axis: no project path to derive filename")
                return
        if self._is_script_already_loaded(new_path):
            return
        # Open wizard
        self._axis_wiz_open = True
        self._axis_wiz_name = axis
        self._axis_wiz_axis = axis
        self._axis_wiz_path = new_path
        self._axis_wiz_mode = 0
        self._axis_wiz_copy_idx = 0
        # Pick next palette colour based on how many funscript tracks exist
        n_fs = len(self.timeline_mgr.timeline.FunscriptTracks())
        self._axis_wiz_color_idx = n_fs % len(self._WIZ_PALETTE)
        self._axis_wiz_color = self._WIZ_PALETTE[self._axis_wiz_color_idx]
        # Pre-fill defaults from video track if available
        vtracks = self.timeline_mgr.timeline.VideoTracks()
        if vtracks:
            vt = vtracks[0][1]
            self._axis_wiz_offset = vt.offset
            self._axis_wiz_duration = vt.duration
        else:
            self._axis_wiz_offset = 0.0
            self._axis_wiz_duration = self.timeline_mgr.Duration() or 60.0

    def _add_new_funscript_dialog(self) -> None:
        """Open a save-file dialog, then show the Add Track wizard."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            default = self.project.path or ""
            result = pfd.save_file(
                "Add new funscript", default,
                filters=["Funscript", "*.funscript"]
            ).result()
            if result:
                if self._is_script_already_loaded(result):
                    return
                from pathlib import Path as _P
                fname = _P(result).stem
                # Open wizard
                self._axis_wiz_open = True
                self._axis_wiz_name = fname
                self._axis_wiz_axis = ""
                self._axis_wiz_path = result
                self._axis_wiz_mode = 0
                self._axis_wiz_copy_idx = 0
                n_fs = len(self.timeline_mgr.timeline.FunscriptTracks())
                self._axis_wiz_color_idx = n_fs % len(self._WIZ_PALETTE)
                self._axis_wiz_color = self._WIZ_PALETTE[self._axis_wiz_color_idx]
                vtracks = self.timeline_mgr.timeline.VideoTracks()
                if vtracks:
                    vt = vtracks[0][1]
                    self._axis_wiz_offset = vt.offset
                    self._axis_wiz_duration = vt.duration
                else:
                    self._axis_wiz_offset = 0.0
                    self._axis_wiz_duration = self.timeline_mgr.Duration() or 60.0
        except Exception as exc:
            log.warning(f"_add_new_funscript_dialog: {exc}")

    def _add_existing_funscript_dialog(self) -> None:
        """Open a file dialog to import existing .funscript files into the project.

        Existing files already have actions, so they're added directly with
        timing matching the video track (no wizard needed).
        """
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.open_file(
                "Add existing funscript",
                filters=["Funscript", "*.funscript"]
            ).result()
            if result:
                # Determine default timing from video track
                vtracks = self.timeline_mgr.timeline.VideoTracks()
                if vtracks:
                    vt = vtracks[0][1]
                    offset = vt.offset
                    duration = vt.duration
                else:
                    offset = 0.0
                    duration = self.timeline_mgr.Duration() or 60.0
                for path in result:
                    if self._is_script_already_loaded(path):
                        continue
                    self.project.AddFunscript(path)
                    new_idx = len(self.project.funscripts) - 1
                    self.timeline_mgr.AddFunscriptTrack(
                        new_idx, offset=offset, duration=duration)
                self.project.active_idx = len(self.project.funscripts) - 1
                self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        except Exception as exc:
            log.warning(f"_add_existing_funscript_dialog: {exc}")

    def _draw_close_confirm(self) -> None:
        """'You have unsaved changes  --  save, discard, or cancel?' modal."""
        if not self._show_close_confirm:
            return
        imgui.open_popup("Unsaved changes###close_confirm")
        flags = imgui.WindowFlags_.no_docking | imgui.WindowFlags_.always_auto_resize
        opened, _ = imgui.begin_popup_modal("Unsaved changes###close_confirm", True, flags)
        if opened:
            imgui.text("You have unsaved changes.")
            imgui.text_disabled("Save them before continuing?")
            imgui.spacing()
            if imgui.button("Save", ImVec2(110, 0)):
                self.SaveProject()
                path = self._pending_open_path
                self._pending_open_path  = None
                self._show_close_confirm = False
                imgui.close_current_popup()
                if path == "__new__":
                    self._do_new_project()
                elif path == "__close__":
                    self._do_close_project()
                elif path:
                    self._do_open_file(path)
            imgui.same_line()
            if imgui.button("Discard", ImVec2(110, 0)):
                path = self._pending_open_path
                self._pending_open_path  = None
                self._show_close_confirm = False
                imgui.close_current_popup()
                if path == "__new__":
                    self._do_new_project()
                elif path == "__close__":
                    self._do_close_project()
                elif path:
                    self._do_open_file(path)
            imgui.same_line()
            if imgui.button("Cancel", ImVec2(110, 0)):
                self._pending_open_path  = None
                self._show_close_confirm = False
                imgui.close_current_popup()
            imgui.end_popup()

    # -- Add Track wizard ----------------------------------------------

    # Colour palette for the Add Track wizard
    _WIZ_PALETTE = [
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

    def _draw_axis_wizard(self) -> None:
        """Modal popup for adding a new funscript track with timing options."""
        if not self._axis_wiz_open:
            return

        popup_id = "Add Track###axis_wizard"
        imgui.open_popup(popup_id)
        flags = imgui.WindowFlags_.no_docking | imgui.WindowFlags_.always_auto_resize
        opened, _ = imgui.begin_popup_modal(popup_id, True, flags)
        if not opened:
            return

        # -- Editable track name ---------------------------------------
        imgui.text("Name")
        imgui.same_line(100)
        imgui.set_next_item_width(250)
        ch, nv = imgui.input_text("##wiz_name", self._axis_wiz_name, 64)
        if ch:
            self._axis_wiz_name = nv

        imgui.separator()
        imgui.spacing()

        # -- Colour palette --------------------------------------------
        imgui.text("Colour")
        imgui.same_line(100)
        pal = self._WIZ_PALETTE
        for i, c in enumerate(pal):
            if i > 0:
                imgui.same_line()
            selected = (i == self._axis_wiz_color_idx)
            # Draw a coloured selectable square
            r, g, b, a = c
            if selected:
                imgui.push_style_color(imgui.Col_.button, ImVec4(r, g, b, a))
                imgui.push_style_color(imgui.Col_.button_hovered, ImVec4(r, g, b, a))
                imgui.push_style_color(imgui.Col_.button_active, ImVec4(r, g, b, a))
                imgui.push_style_color(imgui.Col_.border, ImVec4(1.0, 1.0, 1.0, 1.0))
                imgui.push_style_var(imgui.StyleVar_.frame_border_size, 2.0)
            else:
                imgui.push_style_color(imgui.Col_.button, ImVec4(r, g, b, a))
                imgui.push_style_color(imgui.Col_.button_hovered, ImVec4(min(1,r+0.15), min(1,g+0.15), min(1,b+0.15), a))
                imgui.push_style_color(imgui.Col_.button_active, ImVec4(r, g, b, a))
            if imgui.button(f"##pal{i}", ImVec2(22, 22)):
                self._axis_wiz_color_idx = i
                self._axis_wiz_color = c
            if selected:
                imgui.pop_style_var()
                imgui.pop_style_color(4)
            else:
                imgui.pop_style_color(3)

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        # -- Mode selection: Copy vs Custom ----------------------------
        if imgui.radio_button("Copy from existing track", self._axis_wiz_mode == 0):
            self._axis_wiz_mode = 0
        if imgui.radio_button("Custom timing", self._axis_wiz_mode == 1):
            self._axis_wiz_mode = 1

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        tl = self.timeline_mgr.timeline
        all_tracks = tl.AllTracks()

        if self._axis_wiz_mode == 0:
            # -- Copy from track ---------------------------------------
            labels = []
            for _lay, trk in all_tracks:
                t_label = "VIDEO" if trk.track_type == 0 else trk.name
                labels.append(f"{t_label}  ({trk.offset:.1f}s \u2013 {trk.end:.1f}s)")

            if labels:
                imgui.text("Source track")
                imgui.set_next_item_width(320)
                ch, self._axis_wiz_copy_idx = imgui.combo(
                    "##wiz_src", self._axis_wiz_copy_idx, labels)
                if self._axis_wiz_copy_idx < 0:
                    self._axis_wiz_copy_idx = 0
                if self._axis_wiz_copy_idx >= len(all_tracks):
                    self._axis_wiz_copy_idx = len(all_tracks) - 1

                if 0 <= self._axis_wiz_copy_idx < len(all_tracks):
                    _, src = all_tracks[self._axis_wiz_copy_idx]
                    imgui.spacing()
                    imgui.text_disabled("Preview:")
                    imgui.text(f"  Offset:    {src.offset:.3f} s")
                    imgui.text(f"  Duration:  {src.duration:.3f} s")
                    imgui.text(f"  End:       {src.end:.3f} s")
            else:
                imgui.text_disabled("No tracks available to copy from.")
        else:
            # -- Custom timing -----------------------------------------
            field_w = 200.0

            imgui.text("Offset")
            imgui.same_line(100)
            imgui.set_next_item_width(field_w)
            _, self._axis_wiz_offset = imgui.input_float(
                "##wiz_off", self._axis_wiz_offset, 0.1, 1.0, "%.3f s")
            self._axis_wiz_offset = max(0.0, self._axis_wiz_offset)

            imgui.text("Duration")
            imgui.same_line(100)
            imgui.set_next_item_width(field_w)
            _, self._axis_wiz_duration = imgui.input_float(
                "##wiz_dur", self._axis_wiz_duration, 0.1, 1.0, "%.3f s")
            self._axis_wiz_duration = max(0.001, self._axis_wiz_duration)

            end_t = self._axis_wiz_offset + self._axis_wiz_duration
            imgui.text("End")
            imgui.same_line(100)
            imgui.text(f"{end_t:.3f} s")

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        # -- Action buttons --------------------------------------------
        if imgui.button("Create", ImVec2(120, 0)):
            self._finalize_add_track()
            self._axis_wiz_open = False
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Cancel", ImVec2(120, 0)):
            self._axis_wiz_open = False
            imgui.close_current_popup()

        imgui.end_popup()

    def _finalize_add_track(self) -> None:
        """Actually create the funscript and DAW track from wizard state."""
        path = self._axis_wiz_path
        if not path or self._is_script_already_loaded(path):
            return

        # Determine timing from wizard mode
        if self._axis_wiz_mode == 0:
            # Copy from existing track
            all_tracks = self.timeline_mgr.timeline.AllTracks()
            idx = self._axis_wiz_copy_idx
            if 0 <= idx < len(all_tracks):
                _, src = all_tracks[idx]
                offset = src.offset
                duration = src.duration
            else:
                offset = 0.0
                duration = self.timeline_mgr.Duration() or 60.0
        else:
            # Custom timing
            offset = self._axis_wiz_offset
            duration = self._axis_wiz_duration

        # Create the funscript in the project
        self.project.AddFunscript(path)
        new_idx = len(self.project.funscripts) - 1
        self.project.active_idx = new_idx
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

        # Add corresponding track in the DAW timeline with chosen timing
        trk_name = self._axis_wiz_name or None
        trk_color = self._axis_wiz_color if self._axis_wiz_color else None
        self.timeline_mgr.AddFunscriptTrack(
            new_idx, offset=offset, duration=duration,
            color=trk_color, name=trk_name)

    def _confirm_remove_funscript(self, idx: int) -> None:
        """Store pending remove index; actual removal happens in _draw_remove_confirm."""
        self._pending_remove_idx = idx

    def _draw_remove_confirm(self) -> None:
        """Inline confirmation popup for removing a funscript track."""
        if self._pending_remove_idx < 0:
            return
        imgui.open_popup("Remove script?###rm_confirm")
        flags = imgui.WindowFlags_.no_docking | imgui.WindowFlags_.always_auto_resize
        opened, _ = imgui.begin_popup_modal("Remove script?###rm_confirm", True, flags)
        if opened:
            idx = self._pending_remove_idx
            title = ""
            if 0 <= idx < len(self.project.funscripts):
                title = self.project.funscripts[idx].title or f"Script {idx}"
            imgui.text(f"Remove '{title}' from the project?")
            imgui.text_disabled("(The file will not be deleted from disk.)")
            imgui.spacing()
            if imgui.button("Yes", ImVec2(120, 0)):
                # Remove the corresponding timeline track first
                trk = self.timeline_mgr.TrackForFunscript(idx)
                if trk:
                    self.timeline_mgr.RemoveTrack(trk.id)
                self.project.RemoveFunscript(idx)
                # Keep active index valid
                if self.project.active_idx > 0:
                    self.project.active_idx -= 1
                # Rebuild timeline to fix funscript_idx references
                self.timeline_mgr.BuildFromProject()
                self._update_title()
                self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
                self._pending_remove_idx = -1
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("No", ImVec2(120, 0)):
                self._pending_remove_idx = -1
                imgui.close_current_popup()
            imgui.end_popup()

    def _open_file_dialog(self) -> None:
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.open_file(
                "Open project",
                filters=["OFS Project", "*.ofsp"]
            ).result()
            if result:
                self.OpenFile(result[0])
        except ImportError:
            log.warning("portable_file_dialogs not available")

    def _add_media_dialog(self) -> None:
        """Open a file dialog for media files and add as a video track."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.open_file(
                "Add media",
                filters=["Media files",
                         "*.mp4 *.mkv *.webm *.mov *.avi *.wav *.mp3 *.ogg *.flac"]
            ).result()
            if result:
                self._add_media_to_timeline(result[0])
        except ImportError:
            log.warning("portable_file_dialogs not available")

    def _add_media_to_timeline(self, path: str) -> None:
        """Add a media file as a new video track on the timeline."""
        from src.core.timeline import Track, TrackType, VideoTrackData

        if not self.project.is_valid:
            log.warning("No project open - cannot add media track.")
            return

        # Use the filename (no extension) as the track name
        name = os.path.splitext(os.path.basename(path))[0]

        # Find the rightmost end to place new media after existing content
        all_tracks = self.timeline_mgr.timeline.AllTracks()
        offset = 0.0
        if all_tracks:
            offset = max(t.end for _l, t in all_tracks)

        # Create a placeholder video track  --  duration will be updated once
        # mpv reports the real duration.
        placeholder_dur = 10.0
        vtrack = Track(
            name=name,
            track_type=TrackType.VIDEO,
            offset=offset,
            duration=placeholder_dur,
            color=(0.39, 0.59, 0.86, 0.78),   # 0-1 floats!
            trim_in=0.0,
            trim_out=placeholder_dur,
            media_duration=0.0,
            video_data=VideoTrackData(media_path=path, fps=0.0),
        )
        # Place on the first Video layer, or create one
        vid_layers = [
            l for l in self.timeline_mgr.timeline.layers
            if any(t.track_type == TrackType.VIDEO for t in l.tracks)
        ]
        if vid_layers:
            vid_layers[0].AddTrack(vtrack)
        else:
            layer = self.timeline_mgr.timeline.AddLayer("Video")
            self.timeline_mgr.timeline.layers.remove(layer)
            self.timeline_mgr.timeline.layers.insert(0, layer)
            layer.AddTrack(vtrack)

        log.info(f"Added media track '{name}' at offset={offset:.2f}s  path={path}")

        # Create a player for this new video track
        self._create_player_for_track(vtrack.id, path)

        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _import_funscript_to_timeline(self, path: str) -> None:
        """Import a .funscript file into the current project as a new axis track."""
        if not self.project.is_valid:
            log.warning("No project open - cannot import funscript.")
            return
        ok = self.project.AddFunscript(path)
        if ok:
            self.timeline_mgr.BuildFromProject()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
            self._update_title()
        else:
            self._alert("Failed to import", self.project.errors)

    def _export_active_dialog(self) -> None:
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            s = self._active()
            if not s:
                return
            default = str(Path(self.project.path).parent / (s.title + ".funscript"))
            result = pfd.save_file("Export funscript", default,
                                   filters=["Funscript", "*.funscript"]).result()
            if result:
                self.project.ExportFunscript(result, self.project.active_idx)
        except ImportError:
            pass

    def _export_all_dialog(self) -> None:
        """Open a directory picker and export all funscripts into it.

        Mirrors OFS ShowMainMenuBar -> Export All (multi-script path):
          Util::OpenDirectoryDialog -> LoadedProject->ExportFunscripts(dir)
        """
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            default = str(Path(self.project.path).parent) if self.project.path else ""
            result = pfd.select_folder("Export all funscripts to...", default).result()
            if result:
                count = self.project.ExportFunscripts(output_dir=result)
                log.info(f"Exported {count} script(s) to {result}")
        except ImportError:
            pass

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    # ----------------------------------------------------------------------
    # App state persistence (panel visibility, display flags, WS preference)
    # ----------------------------------------------------------------------

    def _load_app_state(self) -> None:
        """Restore panel visibility + misc flags from ~/.ofs-pyqt/app_state.json."""
        path = Path(self._prefpath()) / "app_state.json"
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text())
            self.show_statistics             = state.get("show_statistics",             self.show_statistics)
            self.show_history                = state.get("show_history",                self.show_history)
            self.show_simulator              = state.get("show_simulator",              self.show_simulator)
            self.show_action_editor          = state.get("show_action_editor",          self.show_action_editor)
            self.show_special_funcs          = state.get("show_special_funcs",          self.show_special_funcs)
            self.show_chapter_mgr            = state.get("show_chapter_mgr",            self.show_chapter_mgr)
            self.show_metadata               = state.get("show_metadata",               self.show_metadata)
            self.show_ws_api                 = state.get("show_ws_api",                 self.show_ws_api)
            self.show_video                  = state.get("show_video",                  self.show_video)
            self.show_track_info             = state.get("show_track_info",             self.show_track_info)
            self.show_routing                = state.get("show_routing",                self.show_routing)
            self.always_show_bookmark_labels = state.get("always_show_bookmark_labels", self.always_show_bookmark_labels)
            self._ws_active                  = state.get("ws_active",                   self._ws_active)
            self.player_window.video_mode    = state.get("video_mode",                 self.player_window.video_mode)
            log.info("App state restored")
        except Exception as e:
            log.warning(f"Could not load app state: {e}")

    def _save_app_state(self) -> None:
        """Persist panel visibility + misc flags to ~/.ofs-pyqt/app_state.json."""
        state = {
            "show_statistics":             self.show_statistics,
            "show_history":                self.show_history,
            "show_simulator":              self.show_simulator,
            "show_action_editor":          self.show_action_editor,
            "show_special_funcs":          self.show_special_funcs,
            "show_chapter_mgr":            self.show_chapter_mgr,
            "show_metadata":               self.show_metadata,
            "show_ws_api":                 self.show_ws_api,
            "show_video":                  self.show_video,
            "show_track_info":             self.show_track_info,
            "show_routing":                self.show_routing,
            "always_show_bookmark_labels": self.always_show_bookmark_labels,
            "ws_active":                   self._ws_active,
            "video_mode":                  self.player_window.video_mode,
        }
        path = Path(self._prefpath()) / "app_state.json"
        try:
            path.write_text(json.dumps(state, indent=2))
            log.info("App state saved")
        except Exception as e:
            log.warning(f"Could not save app state: {e}")

    def _prefpath(self, sub: str = "") -> str:
        base = Path.home() / ".ofs-pyqt"
        if sub:
            base = base / sub
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _toggle_fullscreen(self) -> None:
        rp = hello_imgui.get_runner_params()
        cur = rp.app_window_params.window_geometry.full_screen_mode
        rp.app_window_params.window_geometry.full_screen_mode = (
            hello_imgui.FullScreenMode.full_screen
            if cur == hello_imgui.FullScreenMode.no_full_screen
            else hello_imgui.FullScreenMode.no_full_screen
        )

    def _maybe_auto_backup(self) -> None:
        if not (self.status & OFS_Status.AUTO_BACKUP):
            return
        if not self.project.is_valid:
            return
        if time.monotonic() - self._last_backup < AUTO_BACKUP_INTERVAL:
            return
        self._last_backup = time.monotonic()
        backup_dir = self._prefpath("backup")
        result = self.project.create_backup(backup_dir)
        if result:
            log.info(f"Auto-backup: {result}")

    @staticmethod
    def _alert(title: str, msg: str) -> None:
        log.warning(f"[ALERT] {title}: {msg}")
