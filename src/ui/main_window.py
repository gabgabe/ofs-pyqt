"""
Main Window — Full OFS-parity implementation.

Layout (mirrors OFS setupDefaultLayout):
  Centre      : MPV video player
  Bottom      : Script timeline (full width)
  Right dock  : Scripting Mode → Simulator → Action Editor → Statistics → Undo History
  Floating    : Special Functions, Chapters, Metadata, Preferences, Keybindings

All OFS keybindings, menu items, undo/redo, auto-backup and project
management are wired here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar, QMessageBox, QFileDialog,
    QApplication, QSlider, QPushButton, QComboBox, QSizePolicy,
    QMenu
)
from PySide6.QtCore import Qt, QTimer, QSettings, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QCloseEvent

from src.core.funscript import Funscript, FunscriptAction
from src.core.project import OFS_Project
from src.core.undo_system import UndoSystem, StateType
from src.core.keybindings import KeybindingSystem
from src.core.video_player import MpvVideoPlayer
from src.core.websocket_api import WebSocketAPI
from src.ui.widgets.timeline_widget import ScriptTimelineWidget

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transport bar
# ---------------------------------------------------------------------------

class TransportBar(QWidget):
    """Playback controls: time, play/pause, frame step, seek slider, speed."""

    play_pause_clicked = Signal()
    prev_frame_clicked = Signal()
    next_frame_clicked = Signal()
    seek_requested     = Signal(float)   # ms

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._duration_ms = 0.0
        self._slider_dragging = False
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        self.time_lbl = QLabel("00:00.000")
        self.time_lbl.setFont(QFont("Menlo", 11))
        self.time_lbl.setMinimumWidth(90)
        lay.addWidget(self.time_lbl)

        for icon, sig in [("⏮", self.prev_frame_clicked),
                          ("▶", self.play_pause_clicked),
                          ("⏭", self.next_frame_clicked)]:
            btn = QPushButton(icon)
            btn.setFixedSize(28, 28)
            btn.clicked.connect(sig)
            lay.addWidget(btn)
            if icon == "▶":
                self.btn_play = btn

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 10_000)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, '_slider_dragging', True))
        self.seek_slider.sliderReleased.connect(self._on_slider_release)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        lay.addWidget(self.seek_slider, stretch=1)

        self.dur_lbl = QLabel("00:00.000")
        self.dur_lbl.setFont(QFont("Menlo", 11))
        self.dur_lbl.setMinimumWidth(90)
        lay.addWidget(self.dur_lbl)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.1x","0.25x","0.5x","0.75x","1.0x","1.25x","1.5x","2.0x","4.0x"])
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.setFixedWidth(68)
        lay.addWidget(self.speed_combo)

    def set_position(self, ms: float) -> None:
        if not self._slider_dragging:
            if self._duration_ms > 0:
                v = int((ms / self._duration_ms) * 10_000)
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(v)
                self.seek_slider.blockSignals(False)
        self.time_lbl.setText(self._fmt(ms))

    def set_duration(self, ms: float) -> None:
        self._duration_ms = ms
        self.dur_lbl.setText(self._fmt(ms))

    def set_playing(self, playing: bool) -> None:
        self.btn_play.setText("⏸" if playing else "▶")

    def _on_slider_release(self) -> None:
        self._slider_dragging = False
        if self._duration_ms > 0:
            ms = (self.seek_slider.value() / 10_000) * self._duration_ms
            self.seek_requested.emit(ms)

    def _on_slider_moved(self, value: int) -> None:
        if self._duration_ms > 0:
            ms = (value / 10_000) * self._duration_ms
            self.time_lbl.setText(self._fmt(ms))

    @staticmethod
    def _fmt(ms: float) -> str:
        s = ms / 1000.0
        m = int(s) // 60
        sec = s - m * 60
        return f"{m:02d}:{sec:06.3f}"


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """OFS-parity main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OFS-PyQt")
        self.resize(1280, 800)

        # Core systems
        self._project   = OFS_Project()
        self._undo      = UndoSystem()

        # WebSocket API (optional)
        ws_port = int(QSettings().value("websocket/port", 8080))
        self._ws_api = WebSocketAPI(port=ws_port)
        if bool(QSettings().value("websocket/enabled", False)):
            self._ws_api.start()

        # Clipboard
        self._clipboard: List[FunscriptAction] = []

        # State
        self._last_backup_time = datetime.now()
        self._recent_files: List[str] = []

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._setup_keybindings()
        self._setup_timers()
        self._restore_geometry()

        self._load_recent_files()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self) -> None:
        """Create central widget + docked panels."""
        # ----- Central: video player -----
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self._video = MpvVideoPlayer()
        self._video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        central_layout.addWidget(self._video, stretch=1)

        # Transport bar (below video, above timeline in central)
        self._transport = TransportBar()
        central_layout.addWidget(self._transport)

        self.setCentralWidget(central)

        # ----- Bottom dock: timeline -----
        self._timeline = ScriptTimelineWidget()
        timeline_dock = self._make_dock("Script Timeline", self._timeline,
                                        Qt.BottomDockWidgetArea)
        timeline_dock.setObjectName("TimelineDock")
        timeline_dock.setMinimumHeight(220)

        # Wire timeline signals
        self._timeline.seek_requested.connect(self._on_seek)
        self._timeline.action_add_requested.connect(self._on_action_add)
        self._timeline.action_remove_requested.connect(self._on_action_remove)
        self._timeline.action_move_requested.connect(self._on_action_move)

        # Wire transport signals
        self._transport.play_pause_clicked.connect(self._on_play_pause)
        self._transport.prev_frame_clicked.connect(self._on_prev_frame)
        self._transport.next_frame_clicked.connect(self._on_next_frame)
        self._transport.seek_requested.connect(self._on_seek)
        self._transport.speed_combo.currentTextChanged.connect(self._on_speed_change)

        # Wire video signals (player emits seconds; we convert to ms)
        self._video.signals.position_changed.connect(
            lambda s: self._on_position_changed(s * 1000.0)
        )
        self._video.signals.duration_changed.connect(
            lambda s: self._on_duration_changed(s * 1000.0)
        )
        self._video.signals.play_pause_changed.connect(self._transport.set_playing)

        # ----- Right dock: stacked panels -----
        self._import_panels()

    def _import_panels(self) -> None:
        """Create and dock all right-side panels."""
        from src.ui.panels.scripting_mode import ScriptingModePanel
        from src.ui.panels.simulator import SimulatorPanel
        from src.ui.panels.action_editor import ActionEditorPanel
        from src.ui.panels.statistics import StatisticsPanel
        from src.ui.panels.undo_history import UndoHistoryPanel
        from src.ui.panels.special_functions import SpecialFunctionsPanel
        from src.ui.panels.chapter_manager import ChapterManagerPanel

        self._scripting_panel = ScriptingModePanel()
        self._make_dock("Scripting Mode", self._scripting_panel,
                        Qt.RightDockWidgetArea).setObjectName("ScriptingDock")

        self._simulator_panel = SimulatorPanel()
        self._make_dock("Simulator", self._simulator_panel,
                        Qt.RightDockWidgetArea).setObjectName("SimulatorDock")

        self._action_editor = ActionEditorPanel()
        self._make_dock("Action Editor", self._action_editor,
                        Qt.RightDockWidgetArea).setObjectName("ActionEditorDock")
        self._action_editor.action_requested.connect(self._on_action_position)
        self._action_editor.remove_requested.connect(self._on_remove_action)

        self._stats_panel = StatisticsPanel()
        self._make_dock("Statistics", self._stats_panel,
                        Qt.RightDockWidgetArea).setObjectName("StatsDock")

        self._undo_history = UndoHistoryPanel()
        self._make_dock("Undo / Redo History", self._undo_history,
                        Qt.RightDockWidgetArea).setObjectName("UndoHistDock")

        self._special_fn_panel = SpecialFunctionsPanel()
        self._make_dock("Special Functions", self._special_fn_panel,
                        Qt.RightDockWidgetArea).setObjectName("SpecialFnDock")
        self._special_fn_panel.range_extend_requested.connect(self._on_range_extend)
        self._special_fn_panel.rdp_simplify_requested.connect(self._on_rdp_simplify)

        self._chapter_panel = ChapterManagerPanel()
        self._make_dock("Chapters", self._chapter_panel,
                        Qt.RightDockWidgetArea).setObjectName("ChaptersDock")
        self._chapter_panel.seek_requested.connect(
            lambda s: self._on_seek(s * 1000.0)
        )
        self._chapter_panel.chapters_changed.connect(self._on_chapters_changed)

    def _make_dock(self, title: str, widget: QWidget,
                   area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(area, dock)
        return dock

    # ==================================================================
    # Menu bar (mirrors OFS ShowMainMenuBar)
    # ==================================================================

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # ---- File ----
        file_menu = mb.addMenu("&File")
        self._act("&Open…",                file_menu, self._on_open,           "Ctrl+O")
        self._act("Open &Funscript…",      file_menu, self._on_open_funscript)
        self._act("Open &Media…",          file_menu, self._on_open_media)
        file_menu.addSeparator()
        self._act("&Save Project",         file_menu, self._on_save,           "Ctrl+S")
        self._act("Quick &Export",         file_menu, self._on_quick_export,   "Ctrl+Shift+S")
        self._act("Export A&ll Scripts",   file_menu, self._on_export_all)
        file_menu.addSeparator()
        self._recent_menu = file_menu.addMenu("&Recent Files")
        file_menu.addSeparator()
        self._act("Close &Project",        file_menu, self._on_close_project)
        file_menu.addSeparator()
        self._act("E&xit",                 file_menu, self.close,              "Ctrl+Q")

        # ---- Edit ----
        edit_menu = mb.addMenu("&Edit")
        self._act("&Undo",    edit_menu, self._on_undo, "Ctrl+Z")
        self._act("&Redo",    edit_menu, self._on_redo, "Ctrl+Y")
        edit_menu.addSeparator()
        self._act("Cu&t",     edit_menu, self._on_cut,   "Ctrl+X")
        self._act("&Copy",    edit_menu, self._on_copy,  "Ctrl+C")
        self._act("&Paste",   edit_menu, self._on_paste, "Ctrl+V")
        self._act("Paste &Exact", edit_menu, self._on_paste_exact, "Ctrl+Shift+V")
        edit_menu.addSeparator()
        self._act("Remove Action",       edit_menu, self._on_remove_action,  "Delete")
        edit_menu.addSeparator()
        self._act("Save &Frame as Image", edit_menu, self._on_save_frame, "F2")

        # ---- Select ----
        sel_menu = mb.addMenu("&Select")
        self._act("Select &All",           sel_menu, self._on_select_all,   "Ctrl+A")
        self._act("&Deselect All",         sel_menu, self._on_deselect_all, "Ctrl+D")
        sel_menu.addSeparator()
        self._act("Select All &Left",      sel_menu, self._on_select_all_left,  "Ctrl+Alt+Left")
        self._act("Select All &Right",     sel_menu, self._on_select_all_right, "Ctrl+Alt+Right")
        sel_menu.addSeparator()
        self._act("Select &Top Points",    sel_menu, self._on_select_top)
        self._act("Select &Mid Points",    sel_menu, self._on_select_mid)
        self._act("Select &Bottom Points", sel_menu, self._on_select_bottom)
        sel_menu.addSeparator()
        self._act("&Equalize",  sel_menu, self._on_equalize, "E")
        self._act("&Invert",    sel_menu, self._on_invert,   "I")
        self._act("&Isolate",   sel_menu, self._on_isolate,  "R")

        # ---- View ----
        view_menu = mb.addMenu("&View")
        for title, obj_name in [
            ("Script Timeline",    "TimelineDock"),
            ("Scripting Mode",     "ScriptingDock"),
            ("Simulator",          "SimulatorDock"),
            ("Action Editor",      "ActionEditorDock"),
            ("Statistics",         "StatsDock"),
            ("Undo / Redo History","UndoHistDock"),
            ("Special Functions",  "SpecialFnDock"),
            ("Chapters",           "ChaptersDock"),
        ]:
            dock = self.findChild(QDockWidget, obj_name)
            if dock:
                view_menu.addAction(dock.toggleViewAction())

        # ---- Options ----
        opt_menu = mb.addMenu("&Options")
        self._act("&Keybindings…",   opt_menu, self._on_open_keybindings)
        self._act("&Preferences…",   opt_menu, self._on_preferences)
        opt_menu.addSeparator()
        self._fullscreen_act = self._act("&Fullscreen", opt_menu, self._on_fullscreen, "F10")
        self._fullscreen_act.setCheckable(True)
        opt_menu.addSeparator()
        ws_act = self._act("Enable &WebSocket API", opt_menu, self._on_toggle_websocket)
        ws_act.setCheckable(True)
        ws_act.setChecked(bool(QSettings().value("websocket/enabled", False)))
        self._ws_act = ws_act

        # ---- Help ----
        help_menu = mb.addMenu("&Help")
        self._act("&About…", help_menu, self._on_about)

    def _act(self, text: str, menu: QMenu, slot,
             shortcut: str = "") -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ==================================================================
    # Toolbar
    # ==================================================================

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setObjectName("MainToolbar")
        tb.setMovable(False)

        for text, slot in [
            ("Open",  self._on_open),
            ("Save",  self._on_save),
            ("Undo",  self._on_undo),
            ("Redo",  self._on_redo),
        ]:
            a = QAction(text, self)
            a.triggered.connect(slot)
            tb.addAction(a)

    # ==================================================================
    # Keybindings
    # ==================================================================

    def _setup_keybindings(self) -> None:
        self._kb = KeybindingSystem(self)
        self._kb.register_actions({
            # Core
            "save_project":                     self._on_save,
            "quick_export":                     self._on_quick_export,
            "cycle_loaded_forward_scripts":     lambda: self._cycle_scripts(1),
            "cycle_loaded_backward_scripts":    lambda: self._cycle_scripts(-1),
            # Navigation
            "prev_action":           self._on_nav_prev_action,
            "next_action":           self._on_nav_next_action,
            "prev_frame":            lambda: self._video.seek_frame(False),
            "next_frame":            lambda: self._video.seek_frame(True),
            "fast_backstep":         lambda: self._video.seek_relative(-5.0),
            "fast_step":             lambda: self._video.seek_relative(5.0),
            # Utility
            "undo":                  self._on_undo,
            "redo":                  self._on_redo,
            "copy":                  self._on_copy,
            "paste":                 self._on_paste,
            "paste_exact":           self._on_paste_exact,
            "cut":                   self._on_cut,
            "select_all":            self._on_select_all,
            "deselect_all":          self._on_deselect_all,
            "select_all_left":       self._on_select_all_left,
            "select_all_right":      self._on_select_all_right,
            "select_top_points":     self._on_select_top,
            "select_middle_points":  self._on_select_mid,
            "select_bottom_points":  self._on_select_bottom,
            "fullscreen_toggle":     self._on_fullscreen,
            # Moving
            "move_actions_up_ten":          lambda: self._move_pos(10),
            "move_actions_down_ten":        lambda: self._move_pos(-10),
            "move_actions_up_five":         lambda: self._move_pos(5),
            "move_actions_down_five":       lambda: self._move_pos(-5),
            "move_actions_up":              lambda: self._move_pos(1),
            "move_actions_down":            lambda: self._move_pos(-1),
            "move_actions_left":            lambda: self._move_time(-1),
            "move_actions_right":           lambda: self._move_time(1),
            "move_actions_left_snapped":    lambda: self._move_time_snapped(False),
            "move_actions_right_snapped":   lambda: self._move_time_snapped(True),
            "move_action_to_current_pos":   self._on_move_to_current_pos,
            # Special
            "equalize_actions":      self._on_equalize,
            "invert_actions":        self._on_invert,
            "isolate_action":        self._on_isolate,
            "repeat_stroke":         self._on_repeat_stroke,
            "remove_action":         self._on_remove_action,
            # Actions (numpad positions)
            **{f"action_{p}": (lambda pos=p: self._on_action_position(pos))
               for p in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]},
            # Videoplayer
            "toggle_play":           self._on_play_pause,
            "decrement_speed":       self._on_decrement_speed,
            "increment_speed":       self._on_increment_speed,
            # Chapters
            "create_chapter":        self._on_create_chapter,
            "create_bookmark":       self._on_create_bookmark,
        })
        self._kb.activate()

    # ==================================================================
    # Timers
    # ==================================================================

    def _setup_timers(self) -> None:
        # Auto-backup
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._on_auto_backup)
        self._backup_timer.start(60_000)  # every 60s (overridden by prefs)

        # Statistics refresh
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_statistics)
        self._stats_timer.start(2000)

    # ==================================================================
    # Settings persistence
    # ==================================================================

    def _restore_geometry(self) -> None:
        s = QSettings()
        if s.contains("mainWindow/geometry"):
            self.restoreGeometry(s.value("mainWindow/geometry"))
        if s.contains("mainWindow/state"):
            self.restoreState(s.value("mainWindow/state"))

    def _save_geometry(self) -> None:
        s = QSettings()
        s.setValue("mainWindow/geometry", self.saveGeometry())
        s.setValue("mainWindow/state",    self.saveState())

    # ==================================================================
    # Recent files
    # ==================================================================

    def _load_recent_files(self) -> None:
        s = QSettings()
        self._recent_files = list(s.value("recentFiles/list", []) or [])
        self._rebuild_recent_menu()

    def _add_recent_file(self, path: str) -> None:
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        max_recent = int(QSettings().value("recentFiles/max", 10))
        self._recent_files = self._recent_files[:max_recent]
        QSettings().setValue("recentFiles/list", self._recent_files)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        for path in self._recent_files:
            a = QAction(Path(path).name, self)
            a.setToolTip(path)
            a.triggered.connect(lambda checked, p=path: self._open_project(p))
            self._recent_menu.addAction(a)
        if not self._recent_files:
            self._recent_menu.addAction("(no recent files)").setEnabled(False)

    # ==================================================================
    # File operations
    # ==================================================================

    def _on_open(self) -> None:
        """Open .ofsp or .funscript."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project / Funscript", "",
            "OFS Project / Funscript (*.ofsp *.funscript);;All Files (*)"
        )
        if path:
            self._open_project(path)

    def _on_open_funscript(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Funscript", "", "Funscript (*.funscript);;All Files (*)"
        )
        if path:
            self._open_project(path)

    def _on_open_media(self) -> None:
        from src.core.project import VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, MEDIA_EXTENSIONS
        v_exts  = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        a_exts  = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        all_ext = " ".join(f"*{e}" for e in sorted(MEDIA_EXTENSIONS))
        filt = (
            f"All Media ({all_ext})"
            f";;Video ({v_exts})"
            f";;Audio ({a_exts})"
            ";;All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, "Open Media", "", filt)
        if path:
            self._open_project(path)

    def _open_project(self, path: str) -> None:
        if not os.path.isfile(path):
            QMessageBox.warning(self, "File Not Found", f"Not found:\n{path}")
            return
        if self._project.is_valid and self._project.has_unsaved_edits():
            ans = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Close the current project?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Save:
                self._on_save()
            elif ans == QMessageBox.StandardButton.Cancel:
                return

        self._project.reset()
        self._undo.clear()

        ext = Path(path).suffix.lower()
        if ext == ".ofsp":
            ok = self._project.load(path)
        elif ext == ".funscript":
            ok = self._project.import_from_funscript(path)
        else:
            ok = self._project.import_from_media(path)

        if not ok:
            QMessageBox.critical(self, "Open Failed",
                                 f"Could not open:\n{path}\n\n{self._project.errors}")
            return

        self._add_recent_file(path)
        self._after_project_load()

    def _after_project_load(self) -> None:
        """Post-load setup: load media, update timeline, etc."""
        media = self._project.media_path
        if media and os.path.isfile(media):
            self._video.load_video(media)
        self._refresh_timeline()
        self._refresh_statistics()
        self.setWindowTitle(f"OFS-PyQt — {Path(self._project.path).name}")
        self.statusBar().showMessage(
            f"Loaded {len(self._project.funscripts)} script(s)", 3000
        )

    def _on_save(self) -> None:
        if not self._project.is_valid:
            self._on_save_as()
            return
        ok = self._project.save()
        if ok:
            self.statusBar().showMessage("Project saved", 2000)
        else:
            QMessageBox.critical(self, "Save Failed", "Could not save the project.")

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "OFS Project (*.ofsp)"
        )
        if path:
            self._project.save(path)
            self._add_recent_file(path)

    def _on_quick_export(self) -> None:
        if not self._project.is_valid:
            return
        if self._project.quick_export():
            self.statusBar().showMessage("Quick export done", 2000)
        else:
            QMessageBox.warning(self, "Export", "Nothing to export.")

    def _on_export_all(self) -> None:
        if not self._project.is_valid:
            return
        n = self._project.export_funscripts()
        self.statusBar().showMessage(f"Exported {n} script(s)", 3000)

    def _on_close_project(self) -> None:
        if self._project.is_valid and self._project.has_unsaved_edits():
            ans = QMessageBox.question(
                self, "Unsaved Changes", "Save before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Save:
                self._on_save()
            elif ans == QMessageBox.StandardButton.Cancel:
                return
        self._project.reset()
        self._undo.clear()
        self._video.load_video("")
        self._timeline.set_scripts([])
        self.setWindowTitle("OFS-PyQt")

    # ==================================================================
    # Undo / Redo
    # ==================================================================

    def _snapshot(self, state_type: StateType) -> None:
        """Take a snapshot of the active script (call BEFORE mutating)."""
        s = self._project.active_script
        if s:
            self._undo.snapshot(state_type, s)

    def _on_undo(self) -> None:
        if self._undo.undo():
            self._refresh_timeline()
            self._refresh_undo_history()
            self.statusBar().showMessage("Undo", 1500)

    def _on_redo(self) -> None:
        if self._undo.redo():
            self._refresh_timeline()
            self._refresh_undo_history()
            self.statusBar().showMessage("Redo", 1500)

    # ==================================================================
    # Script editing helpers
    # ==================================================================

    def _active_script(self) -> Optional[Funscript]:
        return self._project.active_script if self._project.is_valid else None

    def _current_ms(self) -> float:
        return self._video.position_ms

    # ==================================================================
    # Timeline signal handlers
    # ==================================================================

    def _on_action_add(self, script_idx: int, at_ms: int, pos: int) -> None:
        if not self._project.is_valid:
            return
        if 0 <= script_idx < len(self._project.funscripts):
            script = self._project.funscripts[script_idx]
            self._undo.snapshot(StateType.ADD_EDIT_ACTION, script)
            script.add_edit_action(FunscriptAction(at=at_ms, pos=pos), tolerance_s=0.025)
            self._refresh_timeline()
            self._refresh_undo_history()

    def _on_action_remove(self, script_idx: int, at_ms: int) -> None:
        if not self._project.is_valid:
            return
        if 0 <= script_idx < len(self._project.funscripts):
            script = self._project.funscripts[script_idx]
            a = script.get_action_at_time(at_ms / 1000.0, tolerance_s=0.025)
            if a:
                self._undo.snapshot(StateType.REMOVE_ACTION, script)
                script.remove_action(a)
                self._refresh_timeline()
                self._refresh_undo_history()

    def _on_action_move(self, script_idx: int, old_at: int, new_at: int, new_pos: int) -> None:
        if not self._project.is_valid:
            return
        if 0 <= script_idx < len(self._project.funscripts):
            script = self._project.funscripts[script_idx]
            old = script.get_action_at_time(old_at / 1000.0, tolerance_s=0.025)
            if old:
                self._undo.snapshot(StateType.ACTIONS_MOVED, script)
                script.edit_action(old, FunscriptAction(at=new_at, pos=new_pos))
                self._refresh_timeline()
                self._refresh_undo_history()

    # ==================================================================
    # Action Editor panel handlers
    # ==================================================================

    def _on_action_position(self, pos: int) -> None:
        """Insert action at current playhead with given position."""
        s = self._active_script()
        if s is None:
            return
        at_ms = int(self._current_ms())
        self._undo.snapshot(StateType.ADD_EDIT_ACTION, s)
        s.add_edit_action(FunscriptAction(at=at_ms, pos=pos), tolerance_s=0.025)
        self._refresh_timeline()
        self._refresh_undo_history()

    def _on_remove_action(self) -> None:
        s = self._active_script()
        if s is None:
            return
        a = s.get_action_at_time(self._current_ms() / 1000.0, tolerance_s=0.05)
        if a:
            self._undo.snapshot(StateType.REMOVE_ACTION, s)
            s.remove_action(a)
            self._refresh_timeline()
            self._refresh_undo_history()

    # ==================================================================
    # Selection operations
    # ==================================================================

    def _on_select_all(self) -> None:
        s = self._active_script()
        if s:
            s.select_all()
            self._refresh_timeline()

    def _on_deselect_all(self) -> None:
        s = self._active_script()
        if s:
            s.clear_selection()
            self._refresh_timeline()

    def _on_select_all_left(self) -> None:
        s = self._active_script()
        if s:
            t = self._current_ms() / 1000.0
            s.select_time(0, t)
            self._refresh_timeline()

    def _on_select_all_right(self) -> None:
        s = self._active_script()
        if s:
            t = self._current_ms() / 1000.0
            dur = self._video.duration or t + 3600
            s.select_time(t, dur)
            self._refresh_timeline()

    def _on_select_top(self) -> None:
        s = self._active_script()
        if s:
            s.select_all()
            s.select_top_actions()
            self._refresh_timeline()

    def _on_select_mid(self) -> None:
        s = self._active_script()
        if s:
            s.select_all()
            s.select_middle_actions()
            self._refresh_timeline()

    def _on_select_bottom(self) -> None:
        s = self._active_script()
        if s:
            s.select_all()
            s.select_bottom_actions()
            self._refresh_timeline()

    # ==================================================================
    # Transform operations
    # ==================================================================

    def _on_equalize(self) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._snapshot(StateType.EQUALIZE_ACTIONS)
            s.equalize_selection()
            self._refresh_timeline()
            self._refresh_undo_history()

    def _on_invert(self) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._snapshot(StateType.INVERT_ACTIONS)
            s.invert_selection()
            self._refresh_timeline()
            self._refresh_undo_history()

    def _on_isolate(self) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._snapshot(StateType.ISOLATE_ACTION)
            s.remove_actions_in_interval(0.0, s.actions[0].at_s if s.actions else 0.0)
            self._refresh_timeline()
            self._refresh_undo_history()

    def _on_repeat_stroke(self) -> None:
        s = self._active_script()
        if s is None:
            return
        t_s = self._current_ms() / 1000.0
        stroke = s.get_last_stroke(t_s)
        if len(stroke) < 2:
            return
        self._snapshot(StateType.REPEAT_STROKE)
        duration_s = stroke[-1].at_s - stroke[0].at_s
        offset_s = t_s - stroke[0].at_s
        for a in stroke:
            new_at = int((a.at_s + offset_s) * 1000)
            s.add_edit_action(FunscriptAction(at=new_at, pos=a.pos), tolerance_s=0.025)
        self._refresh_timeline()
        self._refresh_undo_history()

    def _on_range_extend(self, range_extend: int) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._snapshot(StateType.RANGE_EXTEND)
            s.range_extend_selection(range_extend)
            self._refresh_timeline()
            self._refresh_undo_history()

    def _on_rdp_simplify(self, epsilon: float) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._snapshot(StateType.SIMPLIFY)
            s.rdp_simplify_selection(epsilon)
            self._refresh_timeline()
            self._refresh_undo_history()

    # ==================================================================
    # Cut / Copy / Paste
    # ==================================================================

    def _on_cut(self) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._clipboard = [FunscriptAction(a.at, a.pos) for a in s.selection]
            self._snapshot(StateType.CUT_SELECTION)
            s.remove_selected_actions()
            self._refresh_timeline()
            self._refresh_undo_history()

    def _on_copy(self) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._clipboard = [FunscriptAction(a.at, a.pos) for a in s.selection]

    def _on_paste(self) -> None:
        s = self._active_script()
        if s is None or not self._clipboard:
            return
        t_cur = self._current_ms()
        t_first = self._clipboard[0].at
        offset = t_cur - t_first
        self._snapshot(StateType.PASTE_COPIED_ACTIONS)
        for a in self._clipboard:
            new_at = max(0, int(a.at + offset))
            s.add_edit_action(FunscriptAction(at=new_at, pos=a.pos), tolerance_s=0.025)
        self._refresh_timeline()
        self._refresh_undo_history()

    def _on_paste_exact(self) -> None:
        """Paste at original timestamps (no offset)."""
        s = self._active_script()
        if s is None or not self._clipboard:
            return
        self._snapshot(StateType.PASTE_COPIED_ACTIONS)
        for a in self._clipboard:
            s.add_edit_action(FunscriptAction(at=a.at, pos=a.pos), tolerance_s=0.025)
        self._refresh_timeline()
        self._refresh_undo_history()

    # ==================================================================
    # Movement
    # ==================================================================

    def _move_pos(self, delta: int) -> None:
        s = self._active_script()
        if s and s.has_selection():
            self._snapshot(StateType.ACTIONS_MOVED)
            s.move_selection_position(delta)
            self._refresh_timeline()
            self._refresh_undo_history()

    def _move_time(self, frames: int) -> None:
        """Move selected actions by ±frames at the current video frame rate."""
        s = self._active_script()
        if s and s.has_selection():
            fps = self._video.fps if hasattr(self._video, 'fps') else 30.0
            delta_s = frames / max(1.0, fps)
            self._snapshot(StateType.ACTIONS_MOVED)
            s.move_selection_time(delta_s)
            self._refresh_timeline()
            self._refresh_undo_history()

    def _move_time_snapped(self, forward: bool) -> None:
        """Move selected actions by one frame AND snap video to the nearest moved action.
        Port of OFS move_actions_horizontal_with_video."""
        self._move_time(1 if forward else -1)
        s = self._active_script()
        if s and s.has_selection():
            sel = list(s.selection)
            if sel:
                cur_ms = self._current_ms()
                closest = min(sel, key=lambda a: abs(a.at - cur_ms))
                self._video.seek_to(closest.at_s)

    def _on_move_to_current_pos(self) -> None:
        s = self._active_script()
        if s is None or not s.has_selection():
            return
        t_ms = self._current_ms()
        sel = list(s.selection)
        if not sel:
            return
        self._snapshot(StateType.MOVE_ACTION_TO_CURRENT_POS)
        # Move the closest selected action to t_ms
        closest = min(sel, key=lambda a: abs(a.at - t_ms))
        new_a = FunscriptAction(at=int(t_ms), pos=closest.pos)
        s.edit_action(closest, new_a)
        self._refresh_timeline()
        self._refresh_undo_history()

    # ==================================================================
    # Navigation
    # ==================================================================

    def _on_nav_prev_action(self) -> None:
        s = self._active_script()
        if s:
            t_s = self._current_ms() / 1000.0
            a = s.get_previous_action_behind(t_s)
            if a:
                self._on_seek(float(a.at))

    def _on_nav_next_action(self) -> None:
        s = self._active_script()
        if s:
            t_s = self._current_ms() / 1000.0
            a = s.get_next_action_ahead(t_s)
            if a:
                self._on_seek(float(a.at))

    def _cycle_scripts(self, direction: int) -> None:
        self._project.cycle_active_script(direction)
        self._timeline.set_active_index(self._project.active_idx)

    # ==================================================================
    # Video player
    # ==================================================================

    def _on_play_pause(self) -> None:
        self._video.toggle_play_pause()

    def _on_prev_frame(self) -> None:
        self._video.seek_frame(False)

    def _on_next_frame(self) -> None:
        self._video.seek_frame(True)

    def _on_seek(self, ms: float) -> None:
        self._video.seek_absolute(ms / 1000.0)  # convert ms → seconds

    def _on_speed_change(self, text: str) -> None:
        try:
            speed = float(text.replace("x", ""))
            self._video.set_speed(speed)
        except ValueError:
            pass

    def _on_increment_speed(self) -> None:
        speeds = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0]
        combo = self._transport.speed_combo
        idx = combo.currentIndex()
        if idx < combo.count() - 1:
            combo.setCurrentIndex(idx + 1)

    def _on_decrement_speed(self) -> None:
        combo = self._transport.speed_combo
        idx = combo.currentIndex()
        if idx > 0:
            combo.setCurrentIndex(idx - 1)

    def _on_position_changed(self, ms: float) -> None:
        self._transport.set_position(ms)
        self._timeline.set_position(ms)
        # Update simulator
        s = self._active_script()
        pos = None
        if s and len(s.actions) >= 2:
            pos = s.actions.interpolate(ms)
            self._simulator_panel.set_position(pos)
        # WebSocket broadcast
        self._ws_api.broadcast_position(ms / 1000.0, pos)

    def _on_duration_changed(self, ms: float) -> None:
        self._transport.set_duration(ms)
        self._timeline.set_duration(ms)
        self._ws_api.broadcast_duration(ms / 1000.0)

    # ==================================================================
    # Chapter operations
    # ==================================================================

    def _on_create_chapter(self) -> None:
        s = self._active_script()
        if s:
            from src.core.funscript import Chapter
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "New Chapter", "Chapter name:")
            if ok and name:
                t = self._current_ms() / 1000.0
                s.chapters.append(Chapter(name, t, t + 10.0))
                self._chapter_panel.set_chapters(s.chapters)

    def _on_create_bookmark(self) -> None:
        s = self._active_script()
        if s:
            from src.core.funscript import Chapter
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "New Bookmark", "Bookmark name:")
            if ok and name:
                t = self._current_ms() / 1000.0
                s.chapters.append(Chapter(name, t, t))
                self._chapter_panel.set_chapters(s.chapters)

    def _on_chapters_changed(self) -> None:
        """Write chapter panel state back to the active script."""
        s = self._active_script()
        if s:
            s.chapters = self._chapter_panel._chapters[:]

    # ==================================================================
    # Misc actions
    # ==================================================================

    def _on_save_frame(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Frame as Image", "", "PNG Image (*.png)"
        )
        if path:
            # mpv screenshot-to-file
            try:
                self._video._player.screenshot_to_file(path, mode="video")
                self.statusBar().showMessage(f"Frame saved: {path}", 3000)
            except Exception as e:
                QMessageBox.warning(self, "Save Frame", str(e))

    def _on_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._fullscreen_act.setChecked(False)
        else:
            self.showFullScreen()
            self._fullscreen_act.setChecked(True)

    def _on_open_keybindings(self) -> None:
        from src.ui.panels.keybinding_editor import KeybindingEditorDialog
        dlg = KeybindingEditorDialog(self._kb, self)
        dlg.exec()

    def _on_preferences(self) -> None:
        from src.ui.panels.preferences import PreferencesDialog
        dlg = PreferencesDialog(self)
        dlg.exec()
        # Reapply backup timer interval
        interval_s = int(QSettings().value("backup/interval_s", 60))
        self._backup_timer.setInterval(interval_s * 1000)

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About OFS-PyQt",
            "<b>OFS-PyQt</b><br>"
            "A Python/PySide6 port of OpenFunscripter.<br>"
            "<a href='https://github.com/OpenFunscripter/OFS'>OFS on GitHub</a>"
        )

    # ==================================================================
    # Auto-backup
    # ==================================================================

    def _on_auto_backup(self) -> None:
        if not self._project.is_valid:
            return
        if not bool(QSettings().value("backup/enabled", True)):
            return
        backup_dir = str(QSettings().value("backup/dir", ""))
        dest = self._project.create_backup(backup_dir or None)
        if dest:
            self.statusBar().showMessage(f"Auto-backup: {Path(dest).name}", 2000)

    # ==================================================================
    # UI refresh helpers
    # ==================================================================

    def _refresh_timeline(self) -> None:
        if self._project.is_valid:
            self._timeline.set_scripts(
                self._project.funscripts,
                self._project.active_idx
            )
        else:
            self._timeline.set_scripts([])
        self._timeline.refresh()

    def _refresh_statistics(self) -> None:
        if self._project.is_valid:
            self._stats_panel.update_scripts(self._project.funscripts)

    def _refresh_undo_history(self) -> None:
        self._undo_history.refresh(self._undo)

    def _on_toggle_websocket(self) -> None:
        enabled = self._ws_act.isChecked()
        QSettings().setValue("websocket/enabled", enabled)
        if enabled:
            started = self._ws_api.start()
            if started:
                self.statusBar().showMessage(
                    f"WebSocket API listening on port {self._ws_api.port}", 3000
                )
            else:
                QMessageBox.warning(
                    self, "WebSocket API",
                    "Could not start WebSocket server.\n"
                    "Make sure the 'websockets' package is installed:\n"
                    "  pip install websockets"
                )
                self._ws_act.setChecked(False)
                QSettings().setValue("websocket/enabled", False)
        else:
            self._ws_api.stop()
            self.statusBar().showMessage("WebSocket API stopped", 2000)

    # ==================================================================
    # Close event
    # ==================================================================

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._project.is_valid and self._project.has_unsaved_edits():
            ans = QMessageBox.question(
                self, "Unsaved Changes", "Save before exiting?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Save:
                self._on_save()
            elif ans == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self._save_geometry()
        self._kb.save_to_settings()
        self._ws_api.stop()
        event.accept()
