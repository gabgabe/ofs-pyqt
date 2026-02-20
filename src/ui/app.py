"""
OpenFunscripter — Python port of OpenFunscripter.h / OpenFunscripter.cpp

Architecture mirrors OFS C++ exactly:
  Init()  — SDL2 + OpenGL + ImGui + mpv + keybindings + event listeners
  Run()   — hello_imgui main loop (callbacks: pre_new_frame, show_gui, after_swap)
  Step()  — processEvents → update → ImGui panels → render
  Shutdown() — destroy in correct order

ImGui + SDL2 + OpenGL via imgui-bundle (hello_imgui runner).
Video via mpv render context → GL texture → imgui.image().
No Qt anywhere.
"""

from __future__ import annotations

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

log = logging.getLogger(__name__)

# ── Status flags (mirrors OFS_Status) ─────────────────────────────────────
class OFS_Status:
    NONE                = 0x0
    SHOULD_EXIT         = 0x1
    FULLSCREEN          = 0x1 << 1
    GRADIENT_NEEDS_UPDATE = 0x1 << 2
    AUTO_BACKUP         = 0x1 << 4


AUTO_BACKUP_INTERVAL = 60  # seconds

# Mirrors Funscript::AxisNames from OFS
FUNSCRIPT_AXIS_NAMES = (
    "surge", "sway", "suck", "twist", "roll",
    "pitch", "vib", "pump", "raw",
)


class OpenFunscripter:
    """
    Python port of C++ OpenFunscripter.
    Single instance. Call Init() → Run() → Shutdown().
    """

    ptr: Optional["OpenFunscripter"] = None  # global singleton

    def __init__(self) -> None:
        # Core systems
        self.player       = OFS_Videoplayer()
        self.project      = OFS_Project()
        self.undo_system  = UndoSystem()
        self.keys         = OFS_KeybindingSystem()
        self.web_api      = WebSocketAPI()

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

        # State
        self.status: int         = OFS_Status.NONE
        self.copied_selection: List[FunscriptAction] = []
        self._last_backup: float = time.monotonic()
        self.recent_files: List[str] = []

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

        # Pending "close without saving?" action
        self._pending_open_path:   Optional[str] = None   # path to open after confirm
        self._show_close_confirm:  bool           = False  # modal visible flag
        self._pending_remove_idx:  int            = -1     # track to remove (confirm modal)

        # Loaded file from CLI (set in Init)
        self._cli_file: Optional[str] = None

    # ──────────────────────────────────────────────────────────────────────
    # Init
    # ──────────────────────────────────────────────────────────────────────

    def Init(self, cli_file: Optional[str] = None) -> bool:
        assert OpenFunscripter.ptr is None, "Only one OFS instance allowed"
        OpenFunscripter.ptr = self
        self._cli_file = cli_file
        log.info("OpenFunscripter.Init()")
        return True

    # ──────────────────────────────────────────────────────────────────────
    # Run — hello_imgui main loop
    # ──────────────────────────────────────────────────────────────────────

    def Run(self) -> None:
        params = hello_imgui.RunnerParams()

        # Window
        params.app_window_params.window_title = "OpenFunscripter"
        params.app_window_params.window_geometry.size = (1920, 1080)
        params.app_window_params.restore_previous_geometry = True

        # ImGui window style
        params.imgui_window_params.default_imgui_window_type = (
            hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
        )
        params.imgui_window_params.show_menu_bar     = True
        params.imgui_window_params.show_status_bar   = False
        params.imgui_window_params.menu_app_title    = ""

        # FPS idling — disabled while video plays, re-enabled when paused/idle.
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

        hello_imgui.run(params)

    # ──────────────────────────────────────────────────────────────────────
    # Docking layout — mirrors OFS setupDefaultLayout
    # ──────────────────────────────────────────────────────────────────────

    def _build_docking_params(self) -> hello_imgui.DockingParams:
        dp = hello_imgui.DockingParams()

        # Splits (order matters — applied top-down)
        dp.docking_splits = [
            # Bottom strip 10%  → BottomDock  (controls + progress)
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
            hello_imgui.DockingSplit("RightDock", "SimulatorDock",
                                     imgui.Dir.down, 0.15),
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
                    app.player, app.show_video
                ),
                is_visible_=True,
            ),
            hello_imgui.DockableWindow(
                label_="Progress###Timeline",
                dock_space_name_="BottomDock",
                gui_function_=lambda: app.player_controls.DrawTimeline(
                    app.player, app.project.active_script, app.chapter_mgr
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
                    app.project.active_idx
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
                label_="Simulator###Simulator",
                dock_space_name_="SimulatorDock",
                gui_function_=lambda: app.simulator.Show(
                    app.player, app.project.active_script
                ),
                is_visible_=app.show_simulator,
            ),
            hello_imgui.DockableWindow(
                label_="Action Editor###ActionEditor",
                dock_space_name_="ActionDock",
                gui_function_=lambda: app.action_editor.Show(
                    app.player, app.project.active_script,
                    app.scripting, app.undo_system
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
        ]

        return dp

    # ──────────────────────────────────────────────────────────────────────
    # hello_imgui callbacks
    # ──────────────────────────────────────────────────────────────────────

    def _post_init(self) -> None:
        """Called after GL context + ImGui are ready."""
        log.info("_post_init: GL context ready")

        # Init video player (needs GL context current)
        hw_accel = self.preferences.force_hw_decoding
        if not self.player.Init(hw_accel):
            log.error("Failed to init video player")

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

        # Init timeline
        self.script_timeline.Init()

        # Init web API
        self.web_api.start()

        # Load CLI file or recent
        if self._cli_file:
            self.open_file(self._cli_file)

        log.info("_post_init: complete")

    def _pre_new_frame(self) -> None:
        """Called every frame before imgui.new_frame()."""
        delta = imgui.get_io().delta_time
        self.player.Update(delta)
        idle = not (self.player.VideoLoaded() and not self.player.IsPaused())
        self.project.update(delta, idle)
        # Disable FPS idling while video is playing so the render loop runs at
        # full speed.  Re-enable when paused so CPU is not wasted at idle.
        try:
            rp = hello_imgui.get_runner_params()
            playing = self.player.VideoLoaded() and not self.player.IsPaused()
            rp.fps_idling.enable_idling = not playing
        except Exception:
            pass
        self.keys.ProcessKeybindings()
        EV.process()
        self.scripting.Update()
        self.script_timeline.Update()
        self._maybe_auto_backup()

    def _show_gui(self) -> None:
        """All floating / non-docked windows drawn here."""
        self.show_special_funcs = self.special_funcs.Show(
            self.project.active_script, self.undo_system, self.show_special_funcs
        )
        self.show_chapter_mgr = self.chapter_mgr.Show(
            self.player, self.project, self.show_chapter_mgr
        )
        self.show_metadata = self.metadata_editor.Show(
            self.player, self.project, self.show_metadata
        )
        if self.show_preferences:
            self.show_preferences = self.preferences.Show()
        if self.show_about:
            self._show_about_window()
        if self.show_project_editor:
            self._show_project_window()
        self._draw_remove_confirm()
        self._draw_close_confirm()

    def _after_swap(self) -> None:
        """Called after SDL_GL_SwapWindow."""
        self.player.NotifySwap()

    def _before_exit(self) -> None:
        self.Shutdown()

    # ──────────────────────────────────────────────────────────────────────
    # Shutdown
    # ──────────────────────────────────────────────────────────────────────

    def Shutdown(self) -> None:
        log.info("Shutdown")
        self.web_api.stop()
        self.player.Shutdown()

    # ──────────────────────────────────────────────────────────────────────
    # Event listeners
    # ──────────────────────────────────────────────────────────────────────

    def _register_events(self) -> None:
        EV.listen(OFS_Events.FUNSCRIPT_CHANGED,    self._on_funscript_changed)
        EV.listen(OFS_Events.ACTION_CLICKED,       self._on_timeline_action_clicked)
        EV.listen(OFS_Events.ACTION_SHOULD_CREATE, self._on_timeline_action_created)
        EV.listen(OFS_Events.ACTION_SHOULD_MOVE,   self._on_timeline_action_moved)
        EV.listen(OFS_Events.CHANGE_ACTIVE_SCRIPT, self._on_change_active_script)

    # ──────────────────────────────────────────────────────────────────────
    # Timeline action handlers  (mirrors OFS ScriptTimelineAction* handlers)
    # ──────────────────────────────────────────────────────────────────────

    def _on_timeline_action_clicked(self, action, script, **kw) -> None:
        """Left-click on dot: Ctrl → select, else → seek  (mirrors OFS ScriptTimelineActionClicked)."""
        from imgui_bundle import imgui as _imgui
        io = _imgui.get_io()
        if io.key_ctrl:
            script.select_action(action)
        else:
            self.player.SetPositionExact(action.at / 1000.0)

    def _on_change_active_script(self, idx: int, **kw) -> None:
        """Timeline clicked on a different track (mirrors OFS ScriptTimelineActiveScriptChanged)."""
        scripts = self.project.funscripts
        if 0 <= idx < len(scripts) and scripts[idx].enabled:
            self.project.active_idx = idx
            self._update_title()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _on_timeline_action_created(self, action, script, **kw) -> None:
        """Ctrl+click in empty timeline space: snapshot + add action."""
        self.undo_system.snapshot(StateType.ADD_ACTION, script)
        script.add_edit_action(action, self.scripting.LogicalFrameTime())

    def _on_timeline_action_moved(self, action, script, move_started: bool, **kw) -> None:
        """Drag an action dot: snapshot on first frame, then move every frame."""
        if move_started:
            self.undo_system.snapshot(StateType.ACTIONS_MOVED, script)
        else:
            if script.selection_size() == 1:
                old = next(iter(script.selection))
                script.remove_action(old)
                script.add_action(action)
                script.select_action(action)

    def _on_video_loaded(self, path: str) -> None:
        log.info(f"Video loaded: {path}")
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _on_duration_change(self, duration: float) -> None:
        if self.project.is_valid:
            # Update duration (ms) on all loaded funscripts' metadata
            duration_ms = int(duration * 1000)
            for fs in self.project.funscripts:
                fs.metadata.duration = duration_ms
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _on_time_change(self, time_s: float) -> None:
        pass  # timeline polls player directly each frame

    def _on_pause_change(self, paused: bool) -> None:
        pass  # idle toggled per-frame in _pre_new_frame

    def _on_funscript_changed(self, **kw) -> None:
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    # ──────────────────────────────────────────────────────────────────────
    # Project management (mirrors OFS openFile / initProject / closeProject)
    # ──────────────────────────────────────────────────────────────────────

    def open_file(self, path: str) -> None:
        if not os.path.exists(path):
            self._alert("File not found", f"Could not find:\n{path}")
            return
        # Ask to save if there are unsaved edits (mirrors OFS closeWithoutSavingDialog)
        if self.project.is_valid and self.project.has_unsaved_edits():
            self._pending_open_path  = path
            self._show_close_confirm = True
            return
        self._do_open_file(path)

    def _do_open_file(self, path: str) -> None:
        """Actually open a file without any unsaved-edits guard."""
        self.project.reset()
        ext = os.path.splitext(path)[1].lower()
        if ext == ".ofsp":
            ok = self.project.load(path)
        elif ext == ".funscript":
            ok = self.project.import_from_funscript(path)
        else:
            ok = self.project.import_from_media(path)
        if ok:
            if path not in self.recent_files:
                self.recent_files.append(path)
            self._init_project()
            # OFS: show metadata editor automatically for new projects
            if ext != ".ofsp" and self.preferences.show_metadata_on_new:
                self.show_metadata = True
        else:
            self._alert("Failed to open", self.project.errors)

    def _init_project(self) -> None:
        media = self.project.media_path
        if media and os.path.exists(media):
            self.player.OpenVideo(media)
        self._update_title()
        self._last_backup = time.monotonic()

    def save_project(self) -> None:
        if not self.project.is_valid:
            return
        self.project.save()

    def quick_export(self) -> None:
        self.project.quick_export()

    def close_project(self) -> None:
        self.project.reset()
        self.player.CloseVideo()
        self._update_title()

    def pick_different_media(self) -> None:
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.open_file(
                "Pick media",
                filters=["Media files", "*.mp4 *.mkv *.webm *.mov *.avi *"]
            ).result()
            if result:
                self.project.set_media_path(result[0])
                self.player.OpenVideo(result[0])
        except Exception as exc:
            log.warning(f"pick_different_media: {exc}")

    def _update_title(self) -> None:
        title = "OpenFunscripter"
        if self.project.is_valid:
            title = f"OpenFunscripter — {self.project.path}"
        hello_imgui.get_runner_params().app_window_params.window_title = title

    # ──────────────────────────────────────────────────────────────────────
    # Editing operations (mirrors OFS methods)
    # ──────────────────────────────────────────────────────────────────────

    def _active(self) -> Optional[Funscript]:
        return self.project.active_script

    def add_edit_action(self, pos: int) -> None:
        s = self._active()
        if not s:
            return
        self.undo_system.snapshot(StateType.ADD_EDIT_ACTIONS, s)
        self.scripting.add_edit_action(FunscriptAction(
            int(self.player.CurrentTime() * 1000), pos
        ))

    def remove_action(self) -> None:
        s = self._active()
        if not s:
            return
        if s.has_selection():
            self.undo_system.snapshot(StateType.REMOVE_SELECTION, s)
            s.remove_selected_actions()
        else:
            closest = s.get_closest_action(self.player.CurrentTime())
            if closest:
                self.undo_system.snapshot(StateType.REMOVE_ACTION, s)
                s.remove_action(closest)

    def cut_selection(self) -> None:
        s = self._active()
        if s and s.has_selection():
            self.copy_selection()
            self.undo_system.snapshot(StateType.CUT_SELECTION, s)
            s.remove_selected_actions()

    def copy_selection(self) -> None:
        s = self._active()
        if s and s.has_selection():
            self.copied_selection = sorted(s.selection, key=lambda a: a.at)

    def paste_selection(self) -> None:
        s = self._active()
        if not s or not self.copied_selection:
            return
        self.undo_system.snapshot(StateType.PASTE_COPIED_ACTIONS, s)
        t0 = self.player.CurrentTime() * 1000
        offset = t0 - self.copied_selection[0].at
        dur = (self.copied_selection[-1].at - self.copied_selection[0].at) / 1000.0
        s.remove_actions_in_interval(
            self.player.CurrentTime() - 0.0005,
            self.player.CurrentTime() + dur + 0.0005
        )
        for a in self.copied_selection:
            s.add_action(FunscriptAction(a.at + int(offset), a.pos))
        last = self.copied_selection[-1]
        self.player.SetPositionExact((last.at + int(offset)) / 1000.0)

    def paste_exact(self) -> None:
        s = self._active()
        if not s or not self.copied_selection:
            return
        self.undo_system.snapshot(StateType.PASTE_COPIED_ACTIONS, s)
        if len(self.copied_selection) >= 2:
            s.remove_actions_in_interval(
                self.copied_selection[0].at / 1000.0,
                self.copied_selection[-1].at / 1000.0
            )
        for a in self.copied_selection:
            s.add_action(a)

    def equalize_selection(self) -> None:
        s = self._active()
        if not s:
            return
        if not s.has_selection():
            closest = s.get_closest_action(self.player.CurrentTime())
            if closest:
                behind = s.get_previous_action_behind(closest.at / 1000.0)
                ahead  = s.get_next_action_ahead(closest.at / 1000.0)
                if behind and ahead:
                    self.undo_system.snapshot(StateType.EQUALIZE_ACTIONS, s)
                    s.select_action(behind); s.select_action(closest); s.select_action(ahead)
                    s.equalize_selection()
                    s.clear_selection()
        elif len(list(s.selection)) >= 3:
            self.undo_system.snapshot(StateType.EQUALIZE_ACTIONS, s)
            s.equalize_selection()

    def invert_selection(self) -> None:
        s = self._active()
        if not s:
            return
        if not s.has_selection():
            closest = s.get_closest_action(self.player.CurrentTime())
            if closest:
                self.undo_system.snapshot(StateType.INVERT_ACTIONS, s)
                s.select_action(closest); s.invert_selection(); s.clear_selection()
        elif len(list(s.selection)) >= 3:
            self.undo_system.snapshot(StateType.INVERT_ACTIONS, s)
            s.invert_selection()

    def isolate_action(self) -> None:
        s = self._active()
        if not s:
            return
        closest = s.get_closest_action(self.player.CurrentTime())
        if not closest:
            return
        self.undo_system.snapshot(StateType.ISOLATE_ACTION, s)
        prev = s.get_previous_action_behind(closest.at / 1000.0 - 0.001)
        nxt  = s.get_next_action_ahead(closest.at / 1000.0 + 0.001)
        if prev:
            s.remove_action(prev)
        if nxt:
            s.remove_action(nxt)

    def repeat_last_stroke(self) -> None:
        s = self._active()
        if not s:
            return
        stroke = s.get_last_stroke(self.player.CurrentTime())
        if len(stroke) < 2:
            return
        offset = self.player.CurrentTime() * 1000 - stroke[-1].at
        self.undo_system.snapshot(StateType.REPEAT_STROKE, s)
        on_action = s.get_action_at_time(self.player.CurrentTime(),
                                         self.scripting.LogicalFrameTime())
        start = len(stroke) - 2 if on_action else len(stroke) - 1
        for i in range(start, -1, -1):
            s.add_action(FunscriptAction(stroke[i].at + int(offset), stroke[i].pos))
        self.player.SetPositionExact((stroke[0].at + int(offset)) / 1000.0)

    def _select_top_points(self) -> None:
        s = self._active()
        if s and s.has_selection():
            self.undo_system.snapshot(StateType.TOP_POINTS_ONLY, s)
            s.select_top_actions()

    def _select_middle_points(self) -> None:
        s = self._active()
        if s and s.has_selection():
            self.undo_system.snapshot(StateType.MID_POINTS_ONLY, s)
            s.select_middle_actions()

    def _select_bottom_points(self) -> None:
        s = self._active()
        if s and s.has_selection():
            self.undo_system.snapshot(StateType.BOTTOM_POINTS_ONLY, s)
            s.select_bottom_actions()

    # ──────────────────────────────────────────────────────────────────────
    # Undo / Redo
    # ──────────────────────────────────────────────────────────────────────

    def Undo(self) -> None:
        if self.undo_system.undo():
            self.scripting.Undo()
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def Redo(self) -> None:
        if self.undo_system.redo():
            self.scripting.Redo()
        self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    # ──────────────────────────────────────────────────────────────────────
    # Keybindings (mirrors OFS registerBindings exactly)
    # ──────────────────────────────────────────────────────────────────────

    def _register_bindings(self) -> None:
        K  = imgui.Key
        M  = imgui.Key   # mods same namespace in imgui-bundle

        def reg_grp(id_, label):
            self.keys.RegisterGroup(id_, label)

        def reg(id_, fn, label, grp, chords=None, repeat=False):
            self.keys.RegisterAction(id_, fn, label, grp, chords, repeat)

        # ── Actions ───────────────────────────────────────────────────────
        reg_grp("Actions", "Actions")
        reg("remove_action", self.remove_action, "Remove action", "Actions",
            [(0, K.delete)])
        for val, key in [(0, K.keypad0),(10,K.keypad1),(20,K.keypad2),(30,K.keypad3),
                         (40,K.keypad4),(50,K.keypad5),(60,K.keypad6),(70,K.keypad7),
                         (80,K.keypad8),(90,K.keypad9),(100,K.keypad_divide)]:
            v = val  # capture
            reg(f"action_{v}", lambda _v=v: self.add_edit_action(_v),
                f"Add action {v}", "Actions", [(0, key)])

        # ── Core ──────────────────────────────────────────────────────────
        reg_grp("Core", "Core")
        reg("save_project",   self.save_project,  "Save project",     "Core",
            [(K.mod_ctrl, K.s)])
        reg("quick_export",   self.quick_export,  "Quick export",     "Core",
            [(K.mod_ctrl | K.mod_shift, K.s)])
        reg("sync_timestamps",
            lambda: self.player.SyncWithPlayerTime(),
            "Sync time with player", "Core", [(0, K.s)])

        def _cycle_fwd():
            scripts = self.project.funscripts
            if not scripts:
                return
            n = len(scripts)
            idx = self.project.active_idx
            for _ in range(n):
                idx = (idx + 1) % n
                if scripts[idx].enabled:
                    break
            self.project.active_idx = idx
            self._update_title()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

        def _cycle_bwd():
            scripts = self.project.funscripts
            if not scripts:
                return
            n = len(scripts)
            idx = self.project.active_idx
            for _ in range(n):
                idx = (idx - 1) % n
                if scripts[idx].enabled:
                    break
            self.project.active_idx = idx
            self._update_title()
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

        reg("cycle_loaded_forward_scripts",  _cycle_fwd, "Cycle scripts forward",  "Core", [(0, K.page_down)])
        reg("cycle_loaded_backward_scripts", _cycle_bwd, "Cycle scripts backward", "Core", [(0, K.page_up)])

        # ── Navigation ────────────────────────────────────────────────────
        reg_grp("Navigation", "Navigation")

        def _prev_action():
            s = self._active()
            if s:
                a = s.get_previous_action_behind(self.player.CurrentTime() - 0.001)
                if a:
                    self.player.SetPositionExact(a.at / 1000.0)

        def _next_action():
            s = self._active()
            if s:
                a = s.get_next_action_ahead(self.player.CurrentTime() + 0.001)
                if a:
                    self.player.SetPositionExact(a.at / 1000.0)

        reg("prev_action", _prev_action, "Previous action", "Navigation",
            [(0, K.down_arrow, True)], repeat=True)
        reg("next_action", _next_action, "Next action",     "Navigation",
            [(0, K.up_arrow, True)],   repeat=True)

        reg("prev_frame",
            lambda: self.scripting.PreviousFrame() if self.player.IsPaused() else None,
            "Previous frame", "Navigation", [(0, K.left_arrow, True)], repeat=True)
        reg("next_frame",
            lambda: self.scripting.NextFrame() if self.player.IsPaused() else None,
            "Next frame", "Navigation", [(0, K.right_arrow, True)], repeat=True)

        fast_step = self.preferences.fast_step_amount
        reg("fast_step",     lambda: self.player.SeekFrames( fast_step), "Fast step",     "Navigation", [(K.mod_ctrl, K.right_arrow, True)], repeat=True)
        reg("fast_backstep", lambda: self.player.SeekFrames(-fast_step), "Fast backstep", "Navigation", [(K.mod_ctrl, K.left_arrow,  True)], repeat=True)

        # ── Utility ───────────────────────────────────────────────────────
        reg_grp("Utility", "Utility")
        reg("undo", self.Undo, "Undo", "Utility", [(K.mod_ctrl, K.z, True)], repeat=True)
        reg("redo", self.Redo, "Redo", "Utility", [(K.mod_ctrl, K.y, True)], repeat=True)

        reg("copy",       self.copy_selection,  "Copy",       "Utility", [(K.mod_ctrl, K.c)])
        reg("paste",      self.paste_selection, "Paste",      "Utility", [(K.mod_ctrl, K.v)])
        reg("paste_exact",self.paste_exact,     "Paste exact","Utility", [(K.mod_ctrl | K.mod_shift, K.v)])
        reg("cut",        self.cut_selection,   "Cut",        "Utility", [(K.mod_ctrl, K.x)])

        reg("select_all",
            lambda: self._active().select_all() if self._active() else None,
            "Select all", "Utility", [(K.mod_ctrl, K.a)])
        reg("deselect_all",
            lambda: self._active().clear_selection() if self._active() else None,
            "Deselect all", "Utility", [(K.mod_ctrl, K.d)])
        reg("select_all_left",
            lambda: self._active().select_time(0, self.player.CurrentTime()) if self._active() else None,
            "Select all left",  "Utility", [(K.mod_ctrl | K.mod_alt, K.left_arrow)])
        reg("select_all_right",
            lambda: self._active().select_time(self.player.CurrentTime(), self.player.Duration()) if self._active() else None,
            "Select all right", "Utility", [(K.mod_ctrl | K.mod_alt, K.right_arrow)])

        reg("select_top_points",    self._select_top_points,    "Select top points",    "Utility")
        reg("select_middle_points", self._select_middle_points, "Select middle points", "Utility")
        reg("select_bottom_points", self._select_bottom_points, "Select bottom points", "Utility")

        reg("save_frame_as_image",
            lambda: self.player.SaveFrameToImage(self._prefpath("screenshot")),
            "Save frame as image", "Utility", [(0, K.f2)])
        reg("cycle_subtitles",
            lambda: self.player.CycleSubtitles(),
            "Cycle subtitles", "Utility", [(0, K.j)])
        reg("fullscreen_toggle",
            lambda: self._toggle_fullscreen(),
            "Toggle fullscreen", "Utility", [(0, K.f10)])

        # ── Moving ────────────────────────────────────────────────────────
        reg_grp("Moving", "Moving")

        def _move_pos(delta):
            s = self._active()
            if not s:
                return
            if s.has_selection():
                self.undo_system.snapshot(StateType.ACTIONS_MOVED, s)
                s.move_selection_position(delta)
            else:
                c = s.get_closest_action(self.player.CurrentTime())
                if c:
                    moved = FunscriptAction(c.at, max(0, min(100, c.pos + delta)))
                    self.undo_system.snapshot(StateType.ACTIONS_MOVED, s)
                    s.edit_action(c, moved)

        def _move_time(forward: bool, snap_video: bool = False):
            s = self._active()
            if not s:
                return
            sel = list(s.selection)
            if sel:
                t = (self.scripting.SteppingIntervalForward(sel[0].at / 1000.0)
                     if forward else
                     self.scripting.SteppingIntervalBackward(sel[0].at / 1000.0))
                self.undo_system.snapshot(StateType.ACTIONS_MOVED, s)
                s.move_selection_time(t, self.scripting.LogicalFrameTime())
                if snap_video:
                    c = s.get_closest_action_selection(self.player.CurrentTime())
                    self.player.SetPositionExact(
                        (c.at / 1000.0) if c else (sel[0].at / 1000.0)
                    )
            else:
                c = s.get_closest_action(self.player.CurrentTime())
                if c:
                    t = (self.scripting.SteppingIntervalForward(c.at / 1000.0)
                         if forward else
                         self.scripting.SteppingIntervalBackward(c.at / 1000.0))
                    moved = FunscriptAction(int(c.at + t * 1000), c.pos)
                    clash = s.get_action_at_time(moved.at / 1000.0,
                                                 self.scripting.LogicalFrameTime())
                    if (clash is None or
                        (forward and clash.at < moved.at) or
                        (not forward and clash.at > moved.at)):
                        self.undo_system.snapshot(StateType.ACTIONS_MOVED, s)
                        s.edit_action(c, moved)
                        if snap_video:
                            self.player.SetPositionExact(moved.at / 1000.0)

        reg("move_actions_up_ten",   lambda: _move_pos(10),  "Move up 10",   "Moving")
        reg("move_actions_down_ten", lambda: _move_pos(-10), "Move down 10", "Moving")
        reg("move_actions_up_five",  lambda: _move_pos(5),   "Move up 5",    "Moving")
        reg("move_actions_down_five",lambda: _move_pos(-5),  "Move down 5",  "Moving")
        reg("move_actions_up",       lambda: _move_pos(1),   "Move up 1",    "Moving",
            [(K.mod_shift, K.up_arrow, True)], repeat=True)
        reg("move_actions_down",     lambda: _move_pos(-1),  "Move down 1",  "Moving",
            [(K.mod_shift, K.down_arrow, True)], repeat=True)

        reg("move_actions_left",         lambda: _move_time(False),       "Move left",         "Moving", [(K.mod_shift, K.left_arrow,  True)], repeat=True)
        reg("move_actions_right",        lambda: _move_time(True),        "Move right",        "Moving", [(K.mod_shift, K.right_arrow, True)], repeat=True)
        reg("move_actions_left_snapped", lambda: _move_time(False, True), "Move left (snap)",  "Moving", [(K.mod_ctrl | K.mod_shift, K.left_arrow,  True)], repeat=True)
        reg("move_actions_right_snapped",lambda: _move_time(True,  True), "Move right (snap)", "Moving", [(K.mod_ctrl | K.mod_shift, K.right_arrow, True)], repeat=True)

        reg("move_action_to_current_pos",
            lambda: self._move_action_to_current(),
            "Move action to current pos", "Moving", [(0, K.end)])

        # ── Special ───────────────────────────────────────────────────────
        reg_grp("Special", "Special")
        reg("equalize_actions", self.equalize_selection, "Equalize actions", "Special", [(0, K.e)])
        reg("invert_actions",   self.invert_selection,   "Invert actions",   "Special", [(0, K.i)])
        reg("isolate_action",   self.isolate_action,     "Isolate action",   "Special", [(0, K.r)])
        reg("repeat_stroke",    self.repeat_last_stroke, "Repeat stroke",    "Special", [(0, K.home)])

        # ── Videoplayer ───────────────────────────────────────────────────
        reg_grp("Videoplayer", "Videoplayer")
        reg("toggle_play",      lambda: self.player.TogglePlay(),    "Toggle play",     "Videoplayer", [(0, K.space)])
        reg("decrement_speed",  lambda: self.player.AddSpeed(-0.1),  "Decrease speed",  "Videoplayer", [(0, K.keypad_subtract)])
        reg("increment_speed",  lambda: self.player.AddSpeed( 0.1),  "Increase speed",  "Videoplayer", [(0, K.keypad_add)])
        reg("goto_start",  lambda: self.player.SetPositionPercent(0.0), "Go to start", "Videoplayer")
        reg("goto_end",    lambda: self.player.SetPositionPercent(1.0), "Go to end",   "Videoplayer")

        # ── Chapters ──────────────────────────────────────────────────────
        reg_grp("Chapters", "Chapters")
        reg("create_chapter",  lambda: self.chapter_mgr.add_chapter(self.player.CurrentTime(), self.player.Duration()), "Create chapter",  "Chapters")
        reg("create_bookmark", lambda: self.chapter_mgr.add_bookmark(self.player.CurrentTime()), "Create bookmark", "Chapters")

    def _move_action_to_current(self) -> None:
        s = self._active()
        if not s:
            return
        c = s.get_closest_action(self.player.CurrentTime())
        if c:
            self.undo_system.snapshot(StateType.MOVE_ACTION_TO_CURRENT_POS, s)
            s.edit_action(c, FunscriptAction(
                int(self.player.CurrentTime() * 1000), c.pos))

    # ──────────────────────────────────────────────────────────────────────
    # Main menu bar (mirrors OFS ShowMainMenuBar)
    # ──────────────────────────────────────────────────────────────────────

    def _show_main_menu(self) -> None:
        """Called inside BeginMainMenuBar / EndMainMenuBar by hello_imgui."""

        # ── FILE ──────────────────────────────────────────────────────────
        if imgui.begin_menu("File"):
            if imgui.menu_item("Open...", "", False)[0]:
                self._open_file_dialog()
            if imgui.begin_menu("Recent files"):
                for p in reversed(self.recent_files[-10:]):
                    if imgui.menu_item(os.path.basename(p), "", False)[0]:
                        self.open_file(p)
                imgui.separator()
                if imgui.menu_item("Clear recent", "", False)[0]:
                    self.recent_files.clear()
                imgui.end_menu()
            imgui.separator()
            valid = self.project.is_valid
            if imgui.menu_item("Save project",     "Ctrl+S",    False, valid)[0]:
                self.save_project()
            if imgui.menu_item("Quick export",     "Ctrl+Shift+S", False, valid)[0]:
                self.quick_export()
            if imgui.menu_item("Export active...", "", False, valid)[0]:
                self._export_active_dialog()
            imgui.separator()
            auto_bk = bool(self.status & OFS_Status.AUTO_BACKUP)
            changed, auto_bk = imgui.menu_item("Auto backup", "", auto_bk)
            if changed:
                if auto_bk:
                    self.status |= OFS_Status.AUTO_BACKUP
                else:
                    self.status &= ~OFS_Status.AUTO_BACKUP
            if imgui.menu_item("Open backup dir", "", False)[0]:
                import subprocess
                subprocess.Popen(["open", self._prefpath("backup")])
            imgui.end_menu()

        # ── PROJECT ───────────────────────────────────────────────────────
        valid = self.project.is_valid
        if imgui.begin_menu("Project", valid):
            _, self.show_project_editor = imgui.menu_item(
                "Configure", "", self.show_project_editor)
            imgui.separator()
            if imgui.menu_item("Pick different media", "", False)[0]:
                self.pick_different_media()
            imgui.separator()
            # ── Add submenu ──────────────────────────────────
            if imgui.begin_menu("Add"):
                if imgui.begin_menu("Add axis"):
                    for axis in FUNSCRIPT_AXIS_NAMES:
                        if imgui.menu_item(axis, "", False)[0]:
                            self._add_axis_funscript(axis)
                    imgui.end_menu()
                if imgui.menu_item("Add new...", "", False)[0]:
                    self._add_new_funscript_dialog()
                if imgui.menu_item("Add existing...", "", False)[0]:
                    self._add_existing_funscript_dialog()
                imgui.end_menu()
            # ── Remove submenu ──────────────────────────────
            if imgui.begin_menu("Remove", valid and len(self.project.funscripts) > 0):
                remove_idx = -1
                for i, s in enumerate(self.project.funscripts):
                    if imgui.menu_item(s.title or f"Script {i}", "", False)[0]:
                        remove_idx = i
                if remove_idx >= 0:
                    self._confirm_remove_funscript(remove_idx)
                imgui.end_menu()
            imgui.end_menu()

        # ── EDIT ──────────────────────────────────────────────────────────
        if imgui.begin_menu("Edit"):
            s = self._active()
            can_undo = not self.undo_system.undo_empty
            can_redo = not self.undo_system.redo_empty
            has_sel  = bool(s and s.has_selection())
            has_copy = bool(self.copied_selection)

            if imgui.menu_item("Undo",   "Ctrl+Z", False, can_undo)[0]: self.Undo()
            if imgui.menu_item("Redo",   "Ctrl+Y", False, can_redo)[0]: self.Redo()
            imgui.separator()
            if imgui.menu_item("Cut",    "Ctrl+X", False, has_sel)[0]:  self.cut_selection()
            if imgui.menu_item("Copy",   "Ctrl+C", False, has_sel)[0]:  self.copy_selection()
            if imgui.menu_item("Paste",  "Ctrl+V", False, has_copy)[0]: self.paste_selection()
            imgui.separator()
            if imgui.menu_item("Save frame as image", "F2", False)[0]:
                self.player.SaveFrameToImage(self._prefpath("screenshot"))
            imgui.end_menu()

        # ── SELECT ────────────────────────────────────────────────────────
        if imgui.begin_menu("Select"):
            s = self._active()
            has_sel = bool(s and s.has_selection())
            if imgui.menu_item("Select all",   "Ctrl+A", False)[0]:
                if s: s.select_all()
            if imgui.menu_item("Deselect all", "Ctrl+D", False)[0]:
                if s: s.clear_selection()
            imgui.separator()
            if imgui.menu_item("Select all left",  "Ctrl+Alt+Left", False)[0]:
                if s: s.select_time(0, self.player.CurrentTime())
            if imgui.menu_item("Select all right", "Ctrl+Alt+Right", False)[0]:
                if s: s.select_time(self.player.CurrentTime(), self.player.Duration())
            imgui.separator()
            if imgui.menu_item("Top points only",    "", False, has_sel)[0]: self._select_top_points()
            if imgui.menu_item("Middle points only", "", False, has_sel)[0]: self._select_middle_points()
            if imgui.menu_item("Bottom points only", "", False, has_sel)[0]: self._select_bottom_points()
            imgui.separator()
            if imgui.menu_item("Equalize", "E", False)[0]: self.equalize_selection()
            if imgui.menu_item("Invert",   "I", False)[0]: self.invert_selection()
            if imgui.menu_item("Isolate",  "R", False)[0]: self.isolate_action()
            imgui.end_menu()

        # ── VIEW ──────────────────────────────────────────────────────────
        if imgui.begin_menu("View"):
            _, self.show_statistics  = imgui.menu_item("Statistics",       "", self.show_statistics)
            _, self.show_history     = imgui.menu_item("Undo history",     "", self.show_history)
            _, self.show_simulator   = imgui.menu_item("Simulator",        "", self.show_simulator)
            _, self.show_action_editor=imgui.menu_item("Action editor",    "", self.show_action_editor)
            _, self.show_special_funcs=imgui.menu_item("Special functions","", self.show_special_funcs)
            _, self.show_chapter_mgr = imgui.menu_item("Chapters",         "", self.show_chapter_mgr)
            _, self.show_metadata    = imgui.menu_item("Metadata",         "", self.show_metadata)
            _, self.show_ws_api      = imgui.menu_item("WebSocket API",    "", self.show_ws_api)
            imgui.separator()
            _, self.show_video = imgui.menu_item("Draw video", "", self.show_video)
            if imgui.menu_item("Reset video position", "", False)[0]:
                self.player_window.reset_translation_and_zoom()
            imgui.end_menu()

        # ── OPTIONS ───────────────────────────────────────────────────────
        if imgui.begin_menu("Options"):
            if imgui.menu_item("Keybindings...", "", False)[0]:
                self.keys.ShowModal()
            if imgui.menu_item("Preferences...", "", self.show_preferences)[0]:
                self.show_preferences = True
            imgui.end_menu()

        # ── ? ─────────────────────────────────────────────────────────────
        if imgui.begin_menu("?"):
            imgui.end_menu()
        if imgui.is_item_clicked():
            self.show_about = True

        # Render floating windows from here (keybinding window)
        self.keys.RenderKeybindingWindow()

        # Update heatmap if needed
        if self.status & OFS_Status.GRADIENT_NEEDS_UPDATE:
            self.status &= ~OFS_Status.GRADIENT_NEEDS_UPDATE
            s = self._active()
            if s:
                self.player_controls.UpdateHeatmap(
                    self.player.Duration(), list(s.actions)
                )

    # ──────────────────────────────────────────────────────────────────────
    # About window
    # ──────────────────────────────────────────────────────────────────────

    def _show_about_window(self) -> None:
        imgui.set_next_window_size(ImVec2(400, 200), imgui.Cond_.first_use_ever)
        opened, self.show_about = imgui.begin(
            "About###about", self.show_about,
            imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.always_auto_resize
        )
        if opened:
            imgui.text_unformatted("OpenFunscripter — Python port")
            imgui.text_unformatted("Uses Dear ImGui + SDL2 + mpv render context")
            imgui.separator()
            if imgui.button("Close", ImVec2(-1, 0)):
                self.show_about = False
        imgui.end()

    # ──────────────────────────────────────────────────────────────────────
    # File dialogs
    # ──────────────────────────────────────────────────────────────────────

    # ── Project window ────────────────────────────────────────────────────

    def _show_project_window(self) -> None:
        """Mirrors OFS_Project::ShowProjectWindow — modal popup."""
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

    # ── Script track management ───────────────────────────────────────────

    def _is_script_already_loaded(self, path: str) -> bool:
        """Return True if a funscript with the same filename is already loaded."""
        from pathlib import Path as _P
        filename = _P(path).name
        return any(_P(s.relative_path).name == filename
                   for s in self.project.funscripts)

    def _add_axis_funscript(self, axis: str) -> None:
        """Add a new empty script for the given axis suffix (e.g. 'surge')."""
        scripts = self.project.funscripts
        if not scripts:
            return
        root_abs = self.project._make_path_absolute(scripts[0].relative_path)
        from pathlib import Path as _P
        root = _P(root_abs)
        new_path = str(root.with_suffix("").with_suffix("") .parent /
                       (root.stem.split(".")[0] + f".{axis}.funscript"))
        if not self._is_script_already_loaded(new_path):
            self.project.add_funscript(new_path)
            self.project.active_idx = len(self.project.funscripts) - 1
            self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE

    def _add_new_funscript_dialog(self) -> None:
        """Open a save-file dialog to create a new blank funscript track."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            default = self.project.path or ""
            result = pfd.save_file(
                "Add new funscript", default,
                filters=["Funscript", "*.funscript"]
            ).result()
            if result:
                if not self._is_script_already_loaded(result):
                    self.project.add_funscript(result)
                    self.project.active_idx = len(self.project.funscripts) - 1
                    self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        except Exception as exc:
            log.warning(f"_add_new_funscript_dialog: {exc}")

    def _add_existing_funscript_dialog(self) -> None:
        """Open a file dialog to import an existing .funscript into the project."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.open_file(
                "Add existing funscript",
                filters=["Funscript", "*.funscript"]
            ).result()
            if result:
                for path in result:
                    if not self._is_script_already_loaded(path):
                        self.project.add_funscript(path)
                self.project.active_idx = len(self.project.funscripts) - 1
                self.status |= OFS_Status.GRADIENT_NEEDS_UPDATE
        except Exception as exc:
            log.warning(f"_add_existing_funscript_dialog: {exc}")

    def _draw_close_confirm(self) -> None:
        """'You have unsaved changes — save, discard, or cancel?' modal."""
        if not self._show_close_confirm:
            return
        imgui.open_popup("Unsaved changes###close_confirm")
        flags = imgui.WindowFlags_.no_docking | imgui.WindowFlags_.always_auto_resize
        opened, _ = imgui.begin_popup_modal("Unsaved changes###close_confirm", True, flags)
        if opened:
            imgui.text("You have unsaved changes.")
            imgui.text_disabled("Save them before opening a new file?")
            imgui.spacing()
            if imgui.button("Save", ImVec2(110, 0)):
                self.save_project()
                path = self._pending_open_path
                self._pending_open_path  = None
                self._show_close_confirm = False
                imgui.close_current_popup()
                if path:
                    self._do_open_file(path)
            imgui.same_line()
            if imgui.button("Discard", ImVec2(110, 0)):
                path = self._pending_open_path
                self._pending_open_path  = None
                self._show_close_confirm = False
                imgui.close_current_popup()
                if path:
                    self._do_open_file(path)
            imgui.same_line()
            if imgui.button("Cancel", ImVec2(110, 0)):
                self._pending_open_path  = None
                self._show_close_confirm = False
                imgui.close_current_popup()
            imgui.end_popup()

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
                self.project.remove_funscript(idx)
                # Keep active index valid
                if self.project.active_idx > 0:
                    self.project.active_idx -= 1
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
                "Open file",
                filters=["Media / funscript / project",
                         "*.mp4 *.mkv *.webm *.mov *.avi *.funscript *.ofsp *"]
            ).result()
            if result:
                self.open_file(result[0])
        except ImportError:
            log.warning("portable_file_dialogs not available")

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
                self.project.export_funscript(result, self.project.active_idx)
        except ImportError:
            pass

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

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
