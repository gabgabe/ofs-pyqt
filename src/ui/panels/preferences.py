"""
PreferencesWindow — Python port of OFS_Preferences.h / OFS_Preferences.cpp

Settings persisted to ~/.ofs-pyqt/preferences.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from imgui_bundle import imgui, ImVec2

log = logging.getLogger(__name__)

PREFS_FILE = Path.home() / ".ofs-pyqt" / "preferences.json"


class PreferencesWindow:
    """OFS Preferences panel."""

    WindowId = "Preferences###Preferences"

    def __init__(self) -> None:
        # ── Video ──────────────────────────────────────────────────────
        self.force_hw_decoding: bool  = True
        self.fast_step_amount:  int   = 22
        self.default_speed:     float = 1.0

        # ── Scripting ─────────────────────────────────────────────────
        self.auto_backup_interval: int  = 60    # seconds
        self.show_heatmap:         bool = True

        # ── Appearance ────────────────────────────────────────────────
        self.font_size:     int   = 14
        self.bright_theme:  bool  = False
        self.action_radius: float = 4.0

        self._load()

    # ──────────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not PREFS_FILE.exists():
            return
        try:
            with open(PREFS_FILE) as f:
                d = json.load(f)
            for k, v in d.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except Exception as e:
            log.warning(f"Could not load preferences: {e}")

    def _save(self) -> None:
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        try:
            with open(PREFS_FILE, "w") as f:
                json.dump(d, f, indent=2)
        except Exception as e:
            log.warning(f"Could not save preferences: {e}")

    # ──────────────────────────────────────────────────────────────────────

    def Show(self) -> bool:
        """
        Returns True if window should stay open.
        Called from app when show_preferences=True.
        """
        is_open = True
        imgui.set_next_window_size(ImVec2(420, 380), imgui.Cond_.first_use_ever)
        opened, is_open = imgui.begin(
            "Preferences###Preferences", is_open,
            imgui.WindowFlags_.no_collapse,
        )
        if opened:
            self._draw()
        imgui.end()
        return is_open

    def _draw(self) -> None:
        dirty = False

        if imgui.collapsing_header("Video", imgui.TreeNodeFlags_.default_open):
            c, v = imgui.checkbox("Hardware decoding", self.force_hw_decoding)
            if c: self.force_hw_decoding = v; dirty = True
            imgui.set_next_item_width(100)
            c, v = imgui.input_int("Fast step (frames)", self.fast_step_amount, 1, 5)
            if c: self.fast_step_amount = max(1, v); dirty = True
            imgui.set_next_item_width(100)
            c, v = imgui.input_float("Default speed", self.default_speed, 0.05, 0.25, "%.2f")
            if c: self.default_speed = max(0.05, min(5.0, v)); dirty = True

        imgui.spacing()

        if imgui.collapsing_header("Scripting", imgui.TreeNodeFlags_.default_open):
            c, v = imgui.input_int("Auto-backup interval (s)",
                                   self.auto_backup_interval, 10, 30)
            if c: self.auto_backup_interval = max(10, v); dirty = True
            c, v = imgui.checkbox("Show heatmap", self.show_heatmap)
            if c: self.show_heatmap = v; dirty = True

        imgui.spacing()

        if imgui.collapsing_header("Appearance"):
            c, v = imgui.input_int("Font size", self.font_size, 1, 2)
            if c: self.font_size = max(8, min(32, v)); dirty = True
            c, v = imgui.checkbox("Light theme", self.bright_theme)
            if c: self.bright_theme = v; dirty = True

        imgui.spacing()
        imgui.separator()

        if imgui.button("Save", ImVec2(80, 0)):
            self._save()
            dirty = False
        imgui.same_line()
        if imgui.button("Reset defaults", ImVec2(120, 0)):
            self.__init__()
            dirty = True

        if dirty:
            self._save()
