"""
MetadataEditorWindow — Python port of OFS_MetadataEditor.h / .cpp

Edits the metadata block stored in the .ofsp project:
  title, creator, description, duration, performers, tags, type, video_url

Mirrors OFS exactly.
"""

from __future__ import annotations

from typing import Optional

from imgui_bundle import imgui, ImVec2

from src.core.video_player import OFS_Videoplayer
from src.core.project      import OFS_Project


class MetadataEditorWindow:
    """OFS Metadata Editor panel."""

    WindowId = "Metadata###MetadataEditor"

    def __init__(self) -> None:
        self._buf: dict = {}

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player:  OFS_Videoplayer,
        project: OFS_Project,
        visible: bool,
    ) -> bool:
        """Returns updated visible flag."""
        if not visible:
            return False
        is_open = True
        imgui.set_next_window_size(ImVec2(420, 360), imgui.Cond_.first_use_ever)
        opened, is_open = imgui.begin("Metadata###MetadataEditor", is_open)
        if opened:
            self._draw(project)
        imgui.end()
        return is_open

    def _draw(self, project: OFS_Project) -> None:
        if not project.is_valid:
            imgui.text_disabled("No project loaded")
            return

        fs = project.active_script
        if fs is None:
            imgui.text_disabled("No active script")
            return
        meta = fs.metadata

        def _field(label: str, attr: str, multiline: bool = False, width: int = -1):
            imgui.text(label)
            imgui.same_line()
            imgui.set_next_item_width(width if width > 0 else -1)
            cur = str(getattr(meta, attr, "") or "")
            # list fields → comma-joined string
            if isinstance(getattr(meta, attr, None), list):
                cur = ", ".join(getattr(meta, attr))
            if multiline:
                changed, val = imgui.input_text_multiline(
                    f"##{attr}", cur, ImVec2(-1, 60))
            else:
                changed, val = imgui.input_text(f"##{attr}", cur)
            if changed:
                if isinstance(getattr(meta, attr, None), list):
                    setattr(meta, attr, [v.strip() for v in val.split(",") if v.strip()])
                else:
                    setattr(meta, attr, val)

        _field("Title      ", "title")
        _field("Creator    ", "creator")
        _field("Description", "description", multiline=True)
        _field("Performers ", "performers")
        _field("Tags       ", "tags")
        _field("Type       ", "type")
        _field("Video URL  ", "video_url")

        imgui.spacing()
        imgui.separator()

        if imgui.button("Save##meta", ImVec2(80, 0)):
            project.save()
