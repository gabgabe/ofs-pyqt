"""Main menu bar mixin — mirrors ``OpenFunscripter::ShowMainMenuBar`` in OpenFunscripter.cpp.

Renders the File / Project / Edit / Select / View / Options / ? menus
via Dear ImGui.  The unsaved-edits timer tints the menu bar red
after 5 minutes of unsaved work.
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from imgui_bundle import imgui, ImVec4

from src.ui.app_state import OFS_Status, FUNSCRIPT_AXIS_NAMES

if TYPE_CHECKING:
    from src.ui.app import OpenFunscripter


class MenuBarMixin:
    """Mixin providing ``_show_main_menu()`` — extracted from OpenFunscripter.

    Mirrors ``OpenFunscripter::ShowMainMenuBar`` (OpenFunscripter.cpp).
    """

    def _show_main_menu(self: "OpenFunscripter") -> None:
        """Called inside BeginMainMenuBar / EndMainMenuBar by hello_imgui."""

        # ── Menu bar alert: red background when unsaved > 5 min ───────────
        if self.project.is_valid and self.project.HasUnsavedEdits():
            if self._unsaved_since == 0.0:
                self._unsaved_since = time.monotonic()
            unsaved_secs = time.monotonic() - self._unsaved_since
            t = min(1.0, unsaved_secs / 300.0)
            if t > 0.0:
                base  = imgui.get_style_color_vec4(imgui.Col_.menu_bar_bg)
                alert = ImVec4(0.60, 0.06, 0.06, 1.0)
                blended = ImVec4(
                    base.x + (alert.x - base.x) * t,
                    base.y + (alert.y - base.y) * t,
                    base.z + (alert.z - base.z) * t,
                    1.0,
                )
                imgui.push_style_color(imgui.Col_.menu_bar_bg, blended)
                self._menu_bar_alert_pushed = True
        else:
            self._unsaved_since = 0.0

        # ── FILE ──────────────────────────────────────────────────────────
        if imgui.begin_menu("File"):
            if imgui.menu_item("Open...", "", False)[0]:
                self._open_file_dialog()
            if imgui.begin_menu("Recent files"):
                for p in reversed(self.recent_files[-10:]):
                    if imgui.menu_item(os.path.basename(p), "", False)[0]:
                        self.OpenFile(p)
                imgui.separator()
                if imgui.menu_item("Clear recent", "", False)[0]:
                    self.recent_files.clear()
                imgui.end_menu()
            imgui.separator()
            valid = self.project.is_valid
            if imgui.menu_item("Save project",     "Ctrl+S",    False, valid)[0]:
                self.SaveProject()
            if imgui.menu_item("Quick export",     "Ctrl+Shift+S", False, valid)[0]:
                self.QuickExport()
            if imgui.menu_item("Export active...", "", False, valid)[0]:
                self._export_active_dialog()
            multi = valid and len(self.project.funscripts) > 1
            if imgui.menu_item("Export all to dir...", "", False, multi)[0]:
                self._export_all_dialog()
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
                self.PickDifferentMedia()
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
            has_sel  = bool(s and s.HasSelection())
            has_copy = bool(self.copied_selection)

            if imgui.menu_item("Undo",   "Ctrl+Z", False, can_undo)[0]: self.Undo()
            if imgui.menu_item("Redo",   "Ctrl+Y", False, can_redo)[0]: self.Redo()
            imgui.separator()
            if imgui.menu_item("Cut",    "Ctrl+X", False, has_sel)[0]:  self.CutSelection()
            if imgui.menu_item("Copy",   "Ctrl+C", False, has_sel)[0]:  self.CopySelection()
            if imgui.menu_item("Paste",  "Ctrl+V", False, has_copy)[0]: self.PasteSelection()
            imgui.separator()
            if imgui.menu_item("Save frame as image", "F2", False)[0]:
                self.player.SaveFrameToImage(self._prefpath("screenshot"))
            has_heatmap = bool(self.player_controls._heatmap_colours)
            imgui.separator()
            if imgui.menu_item("Save heatmap…", "", False, has_heatmap)[0]:
                self._save_heatmap_dialog(with_chapters=False)
            if imgui.menu_item("Save heatmap with chapters…", "", False, has_heatmap)[0]:
                self._save_heatmap_dialog(with_chapters=True)
            imgui.end_menu()

        # ── SELECT ────────────────────────────────────────────────────────
        if imgui.begin_menu("Select"):
            s = self._active()
            has_sel = bool(s and s.HasSelection())
            if imgui.menu_item("Select all",   "Ctrl+A", False)[0]:
                if s: s.SelectAll()
            if imgui.menu_item("Deselect all", "Ctrl+D", False)[0]:
                if s: s.ClearSelection()
            imgui.separator()
            if imgui.menu_item("Select all left",  "Ctrl+Alt+Left", False)[0]:
                if s: s.SelectTime(0, self.player.CurrentTime())
            if imgui.menu_item("Select all right", "Ctrl+Alt+Right", False)[0]:
                if s: s.SelectTime(self.player.CurrentTime(), self.player.Duration())
            imgui.separator()
            if imgui.menu_item("Top points only",    "", False, has_sel)[0]: self._select_top_points()
            if imgui.menu_item("Middle points only", "", False, has_sel)[0]: self._select_middle_points()
            if imgui.menu_item("Bottom points only", "", False, has_sel)[0]: self._select_bottom_points()
            imgui.separator()
            if imgui.menu_item("Equalize", "E", False)[0]: self.EqualizeSelection()
            if imgui.menu_item("Invert",   "I", False)[0]: self.InvertSelection()
            if imgui.menu_item("Isolate",  "R", False)[0]: self.IsolateAction()
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
            _, self.show_track_info  = imgui.menu_item("Track Info",       "", self.show_track_info)
            imgui.separator()
            imgui.separator()
            _, self.always_show_bookmark_labels = imgui.menu_item(
                "Always show bookmark labels", "", self.always_show_bookmark_labels)
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

        # Pop alert style if pushed this frame
        if getattr(self, '_menu_bar_alert_pushed', False):
            imgui.pop_style_color()
            self._menu_bar_alert_pushed = False

        # Update heatmap if needed
        if self.status & OFS_Status.GRADIENT_NEEDS_UPDATE:
            self.status &= ~OFS_Status.GRADIENT_NEEDS_UPDATE
            s = self._active()
            if s:
                self.player_controls.UpdateHeatmap(
                    self.player.Duration(), list(s.actions)
                )
