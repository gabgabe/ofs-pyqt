"""
MetadataEditorWindow — Python port of OFS_MetadataEditor.h / .cpp

Edits the metadata block stored in the .ofsp project:
  title, creator, description, duration, performers, tags, type,
  script_url, video_url, notes, license

Rendered as a modal popup (blocks input while open), matching OFS behaviour.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from imgui_bundle import imgui, ImVec2

from src.core.video_player import OFS_Videoplayer
from src.core.project      import OFS_Project

log = logging.getLogger(__name__)

_POPUP_ID = "Metadata Editor###MetadataEditor"
_LICENSES  = ["", "Free", "Paid", "CC BY", "CC BY-SA", "CC BY-NC", "CC BY-NC-SA", "Other"]
_TEMPLATE_PATH = Path.home() / ".ofs-pyqt" / "metadata_template.json"


class MetadataEditorWindow:
    """OFS Metadata Editor — modal popup."""

    WindowId = _POPUP_ID

    def __init__(self) -> None:
        self._was_open: bool = False
        self._buf: dict = {}   # per-field input buffers

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player:  OFS_Videoplayer,
        project: OFS_Project,
        visible: bool,
    ) -> bool:
        """Returns updated visible flag."""
        if not visible:
            self._was_open = False
            return False

        # Open the popup on the first frame when visible becomes True
        if not self._was_open:
            imgui.open_popup(_POPUP_ID)
            self._was_open = True

        center = imgui.get_main_viewport().get_center()
        imgui.set_next_window_pos(center, imgui.Cond_.appearing, ImVec2(0.5, 0.5))
        imgui.set_next_window_size(ImVec2(480, 0), imgui.Cond_.appearing)

        opened, still_open = imgui.begin_popup_modal(
            _POPUP_ID, True,
            imgui.WindowFlags_.always_auto_resize,
        )
        if opened:
            self._draw(project, player)
            imgui.end_popup()

        if not still_open:
            self._was_open = False
            return False
        return True

    # ──────────────────────────────────────────────────────────────────────

    def _draw(self, project: OFS_Project, player: OFS_Videoplayer) -> None:
        if not project.is_valid:
            imgui.text_disabled("No project loaded")
            imgui.spacing()
            if imgui.button("Close", ImVec2(80, 0)):
                imgui.close_current_popup()
            return

        meta = project.metadata

        # ── Title ─────────────────────────────────────────────────────
        self._text_field("Title",       meta, "title")
        self._text_field("Creator",     meta, "creator")
        self._text_field("Description", meta, "description", multiline=True)
        self._text_field("Video URL",   meta, "video_url")
        self._text_field("Script URL",  meta, "script_url")

        # ── Notes ─────────────────────────────────────────────────────
        imgui.text("Notes")
        imgui.set_next_item_width(-1)
        notes = str(meta.notes or "")
        changed, val = imgui.input_text_multiline("##notes", notes, ImVec2(-1, 56))
        if changed:
            meta.notes = val

        # ── Type ──────────────────────────────────────────────────────
        self._text_field("Type", meta, "type")

        # ── License combo ─────────────────────────────────────────────
        imgui.text("License")
        imgui.same_line(spacing=8)
        imgui.set_next_item_width(160)
        lic_idx = _LICENSES.index(meta.license) if meta.license in _LICENSES else 0
        changed_l, new_l = imgui.combo("##license", lic_idx, _LICENSES)
        if changed_l:
            meta.license = _LICENSES[new_l]

        imgui.separator()

        # ── Performers — chip row ──────────────────────────────────────
        self._chip_row("Performers", meta.performers, "perf")

        # ── Tags — chip row ────────────────────────────────────────────
        self._chip_row("Tags", meta.tags, "tags")

        imgui.separator()

        # ── Duration (read-only) ───────────────────────────────────────
        if player.VideoLoaded():
            dur = player.Duration()
            h = int(dur) // 3600
            m = (int(dur) % 3600) // 60
            s = dur % 60
            dur_str = (f"{h:02d}:{m:02d}:{s:05.2f}" if h
                       else f"{m:02d}:{s:05.2f}")
            imgui.text_disabled(f"Duration: {dur_str}")

        imgui.spacing()
        imgui.separator()

        # ── Buttons ────────────────────────────────────────────────────
        if imgui.button("Save##meta", ImVec2(80, 0)):
            project.save()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Save project with updated metadata")

        imgui.same_line()
        if imgui.button("Save template##meta", ImVec2(110, 0)):
            self._save_template(meta)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Save current metadata as default template for new projects")

        imgui.same_line()
        if imgui.button("Load template##meta", ImVec2(110, 0)):
            self._load_template(meta)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Fill fields from saved template")

        imgui.same_line()
        if imgui.button("Close##meta", ImVec2(80, 0)):
            imgui.close_current_popup()

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _text_field(
        self,
        label: str,
        obj,
        attr: str,
        multiline: bool = False,
    ) -> None:
        imgui.text(f"{label:<12}")
        imgui.same_line()
        imgui.set_next_item_width(-1)
        cur = str(getattr(obj, attr, "") or "")
        if multiline:
            changed, val = imgui.input_text_multiline(f"##{attr}", cur, ImVec2(-1, 56))
        else:
            changed, val = imgui.input_text(f"##{attr}", cur)
        if changed:
            setattr(obj, attr, val)

    def _chip_row(self, label: str, items: List[str], key: str) -> None:
        """Render a chip row — small labelled buttons for each item, + add button."""
        imgui.text(f"{label}:")
        imgui.same_line()

        del_idx = -1
        for i, item in enumerate(items):
            imgui.push_id(i + hash(key))
            # Chip: item label + ×
            if imgui.small_button(f"{item}  \u00d7"):
                del_idx = i
            if imgui.is_item_hovered():
                imgui.set_tooltip("Click to remove")
            imgui.same_line(spacing=4)
            imgui.pop_id()

        if del_idx >= 0:
            items.pop(del_idx)

        # New-item input + add button
        buf = self._buf.get(key, "")
        imgui.set_next_item_width(110)
        changed, new_buf = imgui.input_text(f"##new_{key}", buf)
        if changed:
            self._buf[key] = new_buf
        imgui.same_line(spacing=4)
        if imgui.small_button(f"+##{key}"):
            v = self._buf.get(key, "").strip()
            if v:
                items.append(v)
                self._buf[key] = ""
        imgui.spacing()

    # ──────────────────────────────────────────────────────────────────────
    # Template save / load
    # ──────────────────────────────────────────────────────────────────────

    def _save_template(self, meta) -> None:
        _TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(_TEMPLATE_PATH, "w") as f:
                json.dump({
                    "creator": meta.creator,
                    "tags": list(meta.tags),
                    "performers": list(meta.performers),
                    "license": meta.license,
                    "type": meta.type,
                }, f, indent=2)
            log.info(f"Metadata template saved to {_TEMPLATE_PATH}")
        except Exception as e:
            log.warning(f"Could not save metadata template: {e}")

    def _load_template(self, meta) -> None:
        if not _TEMPLATE_PATH.exists():
            return
        try:
            with open(_TEMPLATE_PATH) as f:
                d = json.load(f)
            for k, v in d.items():
                if hasattr(meta, k):
                    setattr(meta, k, v)
        except Exception as e:
            log.warning(f"Could not load metadata template: {e}")
