"""
PreferencesWindow  --  Python port of OFS_Preferences.h / OFS_Preferences.cpp

Settings persisted to ~/.ofs-pyqt/preferences.json.
Tabs: Application | Videoplayer | Scripting | Heatmap | Colors
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, List

from imgui_bundle import imgui, ImVec2

from src.ui.ui_colors import UIColors, COLOR_CATEGORIES

log = logging.getLogger(__name__)

PREFS_FILE = Path.home() / ".ofs-pyqt" / "preferences.json"

# Language CSV files live under docs/OFS/data/lang/
_LANG_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "docs" / "OFS" / "data" / "lang"
)


def _discover_languages() -> List[str]:
    langs = ["Default"]
    if _LANG_DIR.is_dir():
        for p in sorted(_LANG_DIR.glob("*.csv")):
            langs.append(p.stem)
    return langs


class PreferencesWindow:
    """OFS Preferences panel. Mirrors ``OFS_Preferences`` (OFS_Preferences.h / .cpp)."""

    WindowId = "Preferences###Preferences"

    def __init__(self) -> None:
        # -- Application -----------------------------------------------
        self.language:               str   = "Default"
        self.font_size:              int   = 14
        self.font_override_path:     str   = ""
        self.bright_theme:           bool  = False
        self.fps_limit:              int   = 0       # 0 = unlimited
        self.vsync:                  bool  = True
        self.show_metadata_on_new:   bool  = True

        # -- Videoplayer ------------------------------------------------
        self.force_hw_decoding:  bool  = True
        self.fast_step_amount:   int   = 22
        self.default_speed:      float = 1.0

        # -- Scripting -------------------------------------------------
        self.auto_backup_interval: int   = 60    # seconds
        self.show_heatmap:         bool  = True
        self.show_waveform:        bool  = False
        self.action_radius:        float = 4.0
        self.max_speed_highlight:  float = 500.0   # units/s threshold
        self.highlight_max_speed:  bool  = True
        # #3 ScaleAudio  --  amplitude multiplier applied to waveform overlay (1.0 = normal)
        self.waveform_scale: float = 1.0
        # #4 WaveformColor tint (RGBA 0-1 stored as list for JSON roundtrip)
        self.waveform_color: List[float] = [227/255, 66/255, 52/255, 0.42]
        # #6 MaxSpeed highlight colour
        self.max_speed_color: List[float] = [0.89, 0.10, 0.10, 0.55]

        # #15 heatmapSettings configurable defaults
        self.heatmap_default_width:  int = 1280
        self.heatmap_default_height: int = 100
        self.heatmap_default_path:   str = ""
        self._languages: List[str] = _discover_languages()
        self._font_buf: str = ""
        self.colors: UIColors = UIColors()
        self._load()

    # ----------------------------------------------------------------------

    def _load(self) -> None:
        if not PREFS_FILE.exists():
            return
        try:
            with open(PREFS_FILE) as f:
                d = json.load(f)
            for k, v in d.items():
                if k == "colors":
                    if isinstance(v, dict):
                        self.colors.from_dict(v)
                    continue
                if hasattr(self, k):
                    setattr(self, k, v)
            self._font_buf = self.font_override_path
        except Exception as e:
            log.warning(f"Could not load preferences: {e}")

    def _save(self) -> None:
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        d = {k: v for k, v in self.__dict__.items()
             if not k.startswith("_") and k != "colors"}
        d["colors"] = self.colors.to_dict()
        try:
            with open(PREFS_FILE, "w") as f:
                json.dump(d, f, indent=2)
        except Exception as e:
            log.warning(f"Could not save preferences: {e}")

    # ----------------------------------------------------------------------

    def Show(self) -> bool:
        """Render the preferences window. Mirrors ``OFS_Preferences::ShowPreferencesWindow``."""
        is_open = True
        imgui.set_next_window_size(ImVec2(460, 400), imgui.Cond_.first_use_ever)
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

        if imgui.begin_tab_bar("##prefs_tabs"):

            # -- Tab: Application --------------------------------------
            if imgui.begin_tab_item("Application")[0]:
                dirty |= self._tab_application()
                imgui.end_tab_item()

            # -- Tab: Videoplayer --------------------------------------
            if imgui.begin_tab_item("Videoplayer")[0]:
                dirty |= self._tab_videoplayer()
                imgui.end_tab_item()

            # -- Tab: Scripting ----------------------------------------
            if imgui.begin_tab_item("Scripting")[0]:
                dirty |= self._tab_scripting()
                imgui.end_tab_item()
            # -- Tab: Heatmap -------------------------------------------
            if imgui.begin_tab_item("Heatmap")[0]:
                dirty |= self._tab_heatmap()
                imgui.end_tab_item()

            # -- Tab: Colors --------------------------------------------
            if imgui.begin_tab_item("Colors")[0]:
                dirty |= self._tab_colors()
                imgui.end_tab_item()

            imgui.end_tab_bar()

        imgui.spacing()
        imgui.separator()

        if imgui.button("Save", ImVec2(80, 0)):
            self._save()
            dirty = False
        imgui.same_line()
        if imgui.button("Reset defaults", ImVec2(120, 0)):
            _orig_font = self.font_override_path
            self.__init__()
            dirty = True

        if dirty:
            self._save()
            # Hot-apply font scale immediately (no restart needed)
            try:
                from imgui_bundle import imgui as _imgui
                base_font_size = 14  # original compiled font size
                _imgui.get_io().font_global_scale = self.font_size / base_font_size
            except Exception:
                pass

    # ----------------------------------------------------------------------
    # Tabs
    # ----------------------------------------------------------------------

    def _tab_application(self) -> bool:
        dirty = False

        # Language
        imgui.text("Language")
        imgui.same_line(spacing=8)
        imgui.set_next_item_width(160)
        lang_names = self._languages
        cur_idx = lang_names.index(self.language) if self.language in lang_names else 0
        ch, new_idx = imgui.combo("##lang", cur_idx, lang_names)
        if ch:
            self.language = lang_names[new_idx]
            dirty = True
        imgui.spacing()

        # Font size
        imgui.set_next_item_width(80)
        c, v = imgui.input_int("Font size", self.font_size, 1, 2)
        if c:
            self.font_size = max(8, min(32, v))
            dirty = True

        # Font override
        imgui.text("Font file")
        imgui.same_line(spacing=8)
        imgui.set_next_item_width(220)
        ch_f, self._font_buf = imgui.input_text("##font_path", self._font_buf)
        imgui.same_line(spacing=4)
        if imgui.button("Change##font"):
            # Pick via tinyfd if available, else just accept typed path
            try:
                import tinyfd  # type: ignore
                path = tinyfd.open_file_dialog(
                    "Select font file", "", ["*.ttf", "*.otf"], "Font files")
                if path:
                    self._font_buf = path
                    self.font_override_path = path
                    dirty = True
            except Exception:
                self.font_override_path = self._font_buf
                dirty = True
        elif ch_f:
            self.font_override_path = self._font_buf
            dirty = True
        imgui.same_line(spacing=4)
        if imgui.button("Clear##font"):
            self._font_buf = ""
            self.font_override_path = ""
            dirty = True

        if self.font_override_path:
            imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(1.0, 0.8, 0.2, 1.0))
            imgui.text_disabled("[!]  Font file change requires restart to apply.")
            imgui.pop_style_color()
        imgui.spacing()

        # Theme
        c, v = imgui.checkbox("Light theme", self.bright_theme)
        if c:
            self.bright_theme = v
            dirty = True
        imgui.spacing()

        # Frame-rate limit
        imgui.set_next_item_width(80)
        c, v = imgui.input_int("FPS limit (0 = unlimited)", self.fps_limit, 10, 60)
        if c:
            self.fps_limit = max(0, v)
            dirty = True

        # VSync
        c, v = imgui.checkbox("VSync", self.vsync)
        if c:
            self.vsync = v
            dirty = True
        imgui.spacing()

        # Metadata on new project
        c, v = imgui.checkbox("Show metadata dialog on new project",
                              self.show_metadata_on_new)
        if c:
            self.show_metadata_on_new = v
            dirty = True

        return dirty

    def _tab_videoplayer(self) -> bool:
        dirty = False

        c, v = imgui.checkbox("Hardware decoding", self.force_hw_decoding)
        if c:
            self.force_hw_decoding = v
            dirty = True
        imgui.spacing()

        imgui.set_next_item_width(100)
        c, v = imgui.input_int("Fast step (frames)", self.fast_step_amount, 1, 5)
        if c:
            self.fast_step_amount = max(1, v)
            dirty = True
        if imgui.is_item_hovered():
            imgui.set_tooltip("Frames to step when holding the step keys")
        imgui.spacing()

        imgui.set_next_item_width(100)
        c, v = imgui.input_float("Default speed", self.default_speed, 0.05, 0.25, "%.2f")
        if c:
            self.default_speed = max(0.05, min(5.0, v))
            dirty = True

        return dirty

    def _tab_scripting(self) -> bool:
        dirty = False

        c, v = imgui.input_int("Auto-backup interval (s)",
                               self.auto_backup_interval, 10, 30)
        if c:
            self.auto_backup_interval = max(10, v)
            dirty = True
        imgui.spacing()

        c, v = imgui.checkbox("Show heatmap", self.show_heatmap)
        if c:
            self.show_heatmap = v
            dirty = True

        c, v = imgui.checkbox("Show waveform", self.show_waveform)
        if c:
            self.show_waveform = v
            dirty = True
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Overlay audio waveform on the script timeline.\n"
                "Requires ffmpeg in PATH. Loads in background."
            )
        imgui.spacing()

        imgui.set_next_item_width(80)
        c, v = imgui.input_float("Action dot radius (px)",
                                 self.action_radius, 0.5, 1.0, "%.1f")
        if c:
            self.action_radius = max(1.0, min(16.0, v))
            dirty = True
        imgui.spacing()

        c, v = imgui.checkbox("Highlight max-speed segments", self.highlight_max_speed)
        if c:
            self.highlight_max_speed = v
            dirty = True
        if self.highlight_max_speed:
            imgui.set_next_item_width(100)
            c, v = imgui.input_float("Max speed threshold (units/s)",
                                     self.max_speed_highlight, 10.0, 50.0, "%.0f")
            if c:
                self.max_speed_highlight = max(1.0, v)
                dirty = True
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Speed above this threshold is shown in red on the heatmap")
            # MaxSpeedColor picker (backed by UIColors)
            imgui.set_next_item_width(200)
            col4 = list(self.colors.max_speed_highlight)
            while len(col4) < 4:
                col4.append(1.0)
            c, new_col = imgui.color_edit4("Max speed colour##msc", col4)
            if c:
                self.colors.max_speed_highlight = list(new_col)
                dirty = True
        imgui.spacing()

        # Waveform settings
        if self.show_waveform:
            imgui.separator()
            imgui.text_disabled("Waveform")
            # ScaleAudio slider
            imgui.set_next_item_width(160)
            c, v = imgui.slider_float("Amplitude scale##wvscale",
                                      self.waveform_scale, 0.1, 5.0, "%.2f")
            if c:
                self.waveform_scale = max(0.1, min(5.0, v))
                dirty = True
            if imgui.is_item_hovered():
                imgui.set_tooltip("Vertically scale the waveform amplitude (1.0 = normal)")
            # WaveformColor tint picker (backed by UIColors)
            imgui.set_next_item_width(200)
            col4w = list(self.colors.waveform_tint)
            while len(col4w) < 4:
                col4w.append(1.0)
            c, new_wc = imgui.color_edit4("Waveform colour##wvcol", col4w)
            if c:
                self.colors.waveform_tint = list(new_wc)
                dirty = True
        imgui.spacing()

        return dirty

    def _tab_heatmap(self) -> bool:
        """#15 heatmapSettings  --  configurable defaults for heatmap export."""
        dirty = False
        imgui.set_next_item_width(100)
        c, v = imgui.input_int("Default width (px)##hmw",
                               self.heatmap_default_width, 10, 100)
        if c:
            self.heatmap_default_width = max(100, v)
            dirty = True
        imgui.set_next_item_width(100)
        c, v = imgui.input_int("Default height (px)##hmh",
                               self.heatmap_default_height, 5, 20)
        if c:
            self.heatmap_default_height = max(10, v)
            dirty = True
        imgui.text("Default output path")
        imgui.set_next_item_width(-1)
        c, v = imgui.input_text("##hmpath", self.heatmap_default_path)
        if c:
            self.heatmap_default_path = v
            dirty = True
        if imgui.is_item_hovered():
            imgui.set_tooltip("Leave empty to use the project folder")
        return dirty

    def _tab_colors(self) -> bool:
        """Full colour table with category headers and RGBA pickers."""
        dirty = False
        colors = self.colors

        # Reset all colours button
        if imgui.button("Reset all colours"):
            colors.reset()
            dirty = True
        imgui.same_line()
        imgui.text_disabled("(?)")
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Reset every colour in the table to factory defaults.\n"
                "Click Save at the bottom of the window to persist changes."
            )
        imgui.spacing()
        imgui.separator()

        # Scrollable child region for the colour table
        avail = imgui.get_content_region_avail()
        if imgui.begin_child("##color_scroll", ImVec2(0, avail.y - 4), imgui.ChildFlags_.none):
            for cat_name, entries in COLOR_CATEGORIES:
                # Collapsible header per category
                if imgui.collapsing_header(cat_name, imgui.TreeNodeFlags_.default_open):
                    for field_name, label in entries:
                        val = getattr(colors, field_name, None)
                        if val is None:
                            continue
                        col4 = list(val)
                        while len(col4) < 4:
                            col4.append(1.0)
                        imgui.set_next_item_width(220)
                        c, new_col = imgui.color_edit4(
                            f"{label}##{field_name}",
                            col4,
                            imgui.ColorEditFlags_.alpha_bar
                            | imgui.ColorEditFlags_.alpha_preview_half,
                        )
                        if c:
                            setattr(colors, field_name, list(new_col))
                            dirty = True
                    imgui.spacing()
            imgui.end_child()

        return dirty
