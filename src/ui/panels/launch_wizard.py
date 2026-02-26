"""
LaunchWizard — startup project picker dialog.

Mimics a professional DAW / NLE project-launcher:

  ┌── Project ──────────────────────────────────────┐
  │  New Project     │  (list of recent projects)   │
  │  Recent Project  │  testlaserwave               │
  │  From Template   │  testmaterial                 │
  │  Open Project... │                               │
  │                  │                               │
  │──────────────────│───────────────────────────────│
  │  [✓] Show at Startup       Cancel     OK        │
  └─────────────────────────────────────────────────┘

Modes:
  0 — New Project         Ask for save location, create empty .ofsp
  1 — Recent Project      Show list of recently opened projects
  2 — From Template       Show .ofsp files in ~/.ofs-pyqt/templates/
  3 — Open Project...     Native file dialog
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from imgui_bundle import imgui, ImVec2

log = logging.getLogger(__name__)

# Sidebar tabs
_TAB_NEW      = 0
_TAB_RECENT   = 1
_TAB_TEMPLATE = 2
_TAB_OPEN     = 3
_TAB_LABELS = ["New Project", "Recent Project", "From Template", "Open Project..."]

_SIDEBAR_W    = 170.0
_WIN_W        = 620.0
_WIN_H        = 420.0
_BOTTOM_H     = 38.0
_BTN_W        = 90.0


class LaunchWizard:
    """Startup project launcher modal window."""

    def __init__(self, pref_dir: str) -> None:
        self._pref_dir = pref_dir           # ~/.ofs-pyqt
        self._visible: bool = False
        self._active_tab: int = _TAB_RECENT
        self._show_at_startup: bool = True
        self._selected_idx: int = 0         # index in current list
        self._recent_files: List[str] = []
        self._templates: List[str] = []     # abs paths to template .ofsp files
        self._new_name: str = ""            # for new-project name field

        # Result — set when user confirms, then read by app.py
        self._result_action: Optional[str] = None   # "new", "open", "recent", "template"
        self._result_path: Optional[str] = None

        # Load settings
        self._load()

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    @property
    def show_at_startup(self) -> bool:
        return self._show_at_startup

    @show_at_startup.setter
    def show_at_startup(self, v: bool) -> None:
        self._show_at_startup = v

    @property
    def visible(self) -> bool:
        return self._visible

    def Open(self) -> None:
        """Show the wizard."""
        self._visible = True
        self._result_action = None
        self._result_path = None
        self._selected_idx = 0
        self._new_name = ""
        self._scan_templates()

    def Close(self) -> None:
        self._visible = False

    def SetRecentFiles(self, files: List[str]) -> None:
        """Update the recent-files list (called from app)."""
        self._recent_files = list(files)

    def ConsumeResult(self) -> Tuple[Optional[str], Optional[str]]:
        """Return and clear the confirmed action.  (action, path) or (None, None)."""
        a, p = self._result_action, self._result_path
        self._result_action = None
        self._result_path = None
        return a, p

    # ──────────────────────────────────────────────────────────────────────
    # Draw
    # ──────────────────────────────────────────────────────────────────────

    def Show(self) -> None:
        """Render the wizard window.  Called from _show_gui every frame."""
        if not self._visible:
            return

        # Centre on viewport
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            ImVec2(vp.pos.x + (vp.size.x - _WIN_W) * 0.5,
                   vp.pos.y + (vp.size.y - _WIN_H) * 0.5),
            imgui.Cond_.appearing,
        )
        imgui.set_next_window_size(ImVec2(_WIN_W, _WIN_H), imgui.Cond_.appearing)

        flags = (
            imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_docking
            | imgui.WindowFlags_.no_saved_settings
        )
        opened, _ = imgui.begin("Project###LaunchWizard", True, flags)
        if not opened:
            imgui.end()
            return

        win_pos = imgui.get_window_pos()
        win_size = imgui.get_window_size()
        content_min = imgui.get_cursor_screen_pos()

        # ── Layout zones ──────────────────────────────────────────────
        sidebar_x = content_min.x
        sidebar_y = content_min.y
        body_x = sidebar_x + _SIDEBAR_W + 8
        body_w = win_pos.x + win_size.x - body_x - 12
        body_h = win_pos.y + win_size.y - sidebar_y - _BOTTOM_H - 12

        # ── Sidebar ────────────────────────────────────────────────────
        imgui.begin_child("##wiz_sidebar", ImVec2(_SIDEBAR_W, body_h), imgui.ChildFlags_.none)
        style = imgui.get_style()
        for i, label in enumerate(_TAB_LABELS):
            is_sel = (self._active_tab == i)
            if is_sel:
                imgui.push_style_color(imgui.Col_.button, style.color_(imgui.Col_.header))
                imgui.push_style_color(imgui.Col_.button_hovered, style.color_(imgui.Col_.header_hovered))
                imgui.push_style_color(imgui.Col_.button_active, style.color_(imgui.Col_.header_active))
            if imgui.button(label, ImVec2(_SIDEBAR_W - 8, 32)):
                self._active_tab = i
                self._selected_idx = 0
                if i == _TAB_OPEN:
                    self._do_open_dialog()
            if is_sel:
                imgui.pop_style_color(3)
        imgui.end_child()

        # ── Body ───────────────────────────────────────────────────────
        imgui.same_line()
        imgui.begin_child("##wiz_body", ImVec2(body_w, body_h), imgui.ChildFlags_.borders)

        if self._active_tab == _TAB_NEW:
            self._draw_new_project(body_w)
        elif self._active_tab == _TAB_RECENT:
            self._draw_recent(body_w)
        elif self._active_tab == _TAB_TEMPLATE:
            self._draw_templates(body_w)
        elif self._active_tab == _TAB_OPEN:
            imgui.text_disabled("Use the file dialog to pick a project or media file.")

        imgui.end_child()

        # ── Bottom bar ─────────────────────────────────────────────────
        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        _, self._show_at_startup = imgui.checkbox("Show at Startup", self._show_at_startup)
        imgui.same_line()

        # Right-align buttons
        avail = imgui.get_content_region_avail().x
        btn_total = _BTN_W * 2 + 8
        if avail > btn_total:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail - btn_total)

        if imgui.button("Cancel", ImVec2(_BTN_W, 0)):
            self._visible = False

        imgui.same_line()
        # OK button — uses theme's default button colours
        if imgui.button("OK", ImVec2(_BTN_W, 0)):
            self._confirm()

        imgui.end()

    # ──────────────────────────────────────────────────────────────────────
    # Tab content
    # ──────────────────────────────────────────────────────────────────────

    def _draw_new_project(self, w: float) -> None:
        imgui.text("Create a new project")
        imgui.spacing()
        imgui.text("Project name:")
        imgui.set_next_item_width(min(300, w - 16))
        _, self._new_name = imgui.input_text("##newname", self._new_name, 256)

        imgui.spacing()
        imgui.text_disabled(
            "An empty .ofsp project will be created.\n"
            "You can then add video and funscript tracks."
        )

    def _draw_recent(self, w: float) -> None:
        if not self._recent_files:
            imgui.text_disabled("No recent projects.")
            return

        # Draw selectable list (most recent first)
        for i, path in enumerate(reversed(self._recent_files)):
            name = Path(path).stem
            is_sel = (i == self._selected_idx)
            if imgui.selectable(name, is_sel, imgui.SelectableFlags_.none, ImVec2(0, 24))[0]:
                self._selected_idx = i
            if imgui.is_item_hovered():
                imgui.set_tooltip(path)
            # Double-click → confirm immediately
            if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                self._selected_idx = i
                self._confirm()

    def _draw_templates(self, w: float) -> None:
        if not self._templates:
            imgui.text_disabled("No templates found.")
            imgui.spacing()
            imgui.text_disabled(
                f"Place .ofsp files in:\n"
                f"  {self._templates_dir()}"
            )
            imgui.spacing()
            if imgui.button("Open templates folder"):
                tdir = self._templates_dir()
                Path(tdir).mkdir(parents=True, exist_ok=True)
                import subprocess
                subprocess.Popen(["open", tdir])
            return

        for i, path in enumerate(self._templates):
            name = Path(path).stem
            is_sel = (i == self._selected_idx)
            if imgui.selectable(name, is_sel, imgui.SelectableFlags_.none, ImVec2(0, 24))[0]:
                self._selected_idx = i
            if imgui.is_item_hovered():
                imgui.set_tooltip(path)
            if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                self._selected_idx = i
                self._confirm()

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────

    def _confirm(self) -> None:
        """Handle OK button press."""
        if self._active_tab == _TAB_NEW:
            name = self._new_name.strip()
            if not name:
                return  # nothing to do
            self._result_action = "new"
            self._result_path = name
            self._visible = False

        elif self._active_tab == _TAB_RECENT:
            rev = list(reversed(self._recent_files))
            if 0 <= self._selected_idx < len(rev):
                self._result_action = "recent"
                self._result_path = rev[self._selected_idx]
                self._visible = False

        elif self._active_tab == _TAB_TEMPLATE:
            if 0 <= self._selected_idx < len(self._templates):
                self._result_action = "template"
                self._result_path = self._templates[self._selected_idx]
                self._visible = False

        elif self._active_tab == _TAB_OPEN:
            # Already handled by _do_open_dialog
            pass

        if not self._visible:
            self._save()

    def _do_open_dialog(self) -> None:
        """Open a native file dialog (non-blocking on imgui_bundle)."""
        try:
            from imgui_bundle import portable_file_dialogs as pfd
            result = pfd.open_file(
                "Open project or media",
                filters=["Supported files", "*.ofsp *.funscript *.mp4 *.mkv *.webm *.avi *.mov *.m4v *.ts *.mpg *.mpeg *.mp3 *.aac *.ogg *.opus *.m4a *.flac *.wav"],
            ).result()
            if result and len(result) > 0:
                self._result_action = "open"
                self._result_path = result[0]
                self._visible = False
                self._save()
        except ImportError:
            log.warning("portable_file_dialogs not available for launch wizard")

    # ──────────────────────────────────────────────────────────────────────
    # Templates directory
    # ──────────────────────────────────────────────────────────────────────

    def _templates_dir(self) -> str:
        return str(Path(self._pref_dir) / "templates")

    def _scan_templates(self) -> None:
        """Scan the templates directory for .ofsp files."""
        tdir = Path(self._templates_dir())
        self._templates = []
        if not tdir.is_dir():
            return
        for f in sorted(tdir.iterdir()):
            if f.suffix.lower() == ".ofsp" and f.is_file():
                self._templates.append(str(f))

    # ──────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────

    def _settings_path(self) -> Path:
        return Path(self._pref_dir) / "launch_wizard.json"

    def _load(self) -> None:
        path = self._settings_path()
        if not path.exists():
            return
        try:
            d = json.loads(path.read_text())
            self._show_at_startup = d.get("show_at_startup", True)
            self._recent_files    = d.get("recent_files", [])
            # Prune non-existent entries
            self._recent_files = [p for p in self._recent_files if os.path.exists(p)]
        except Exception as e:
            log.warning(f"Could not load launch_wizard settings: {e}")

    def _save(self) -> None:
        d = {
            "show_at_startup": self._show_at_startup,
            "recent_files": self._recent_files[-20:],  # keep last 20
        }
        path = self._settings_path()
        try:
            Path(self._pref_dir).mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(d, indent=2))
        except Exception as e:
            log.warning(f"Could not save launch_wizard settings: {e}")

    def SaveRecentFiles(self) -> None:
        """Persist the current recent-files list (called from app on exit)."""
        self._save()
