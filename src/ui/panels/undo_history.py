"""
UndoHistoryWindow — Python port of OFS_UndoSystem UI.

Shows a scrollable list of undo/redo entries with their state names.
Current undo-pointer highlighted. Click to jump to state (not yet implemented
in core, but UI is ready).
"""

from __future__ import annotations

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.undo_system import UndoSystem, StateType, state_label


class UndoHistoryWindow:
    """OFS Undo History panel."""

    WindowId = "Undo History###UndoHistory"

    def __init__(self) -> None:
        self._auto_scroll: bool = True

    # ──────────────────────────────────────────────────────────────────────

    def Show(self, undo: UndoSystem) -> None:
        _, self._auto_scroll = imgui.checkbox("Auto-scroll", self._auto_scroll)

        imgui.separator()

        avail = imgui.get_content_region_avail()
        if imgui.begin_child("##undolist", avail, False,
                             imgui.WindowFlags_.horizontal_scrollbar):

            undo_stack = undo.undo_stack
            redo_stack = undo.redo_stack

            cur_idx = len(undo_stack)
            total   = len(undo_stack) + len(redo_stack)

            # Draw undo entries (oldest → newest)
            for i, entry in enumerate(undo_stack):
                stype = entry.state_type
                name  = state_label(stype)
                is_cur = (i == cur_idx - 1)

                if is_cur:
                    imgui.push_style_color(imgui.Col_.text,
                                           ImVec4(0.3, 0.8, 0.3, 1.0))
                clicked, _ = imgui.selectable(f"{i:3d}  {name}", is_cur)
                if is_cur:
                    imgui.pop_style_color()
                if clicked and not is_cur:
                    # Jump to state i+1 (after this entry is applied)
                    undo.jump_to(i + 1)

            # Current position marker
            imgui.push_style_color(imgui.Col_.text, ImVec4(1.0, 1.0, 0.2, 1.0))
            imgui.text("─── now ───")
            imgui.pop_style_color()

            # Redo entries
            for i, entry in enumerate(redo_stack):
                stype = entry.state_type
                name  = state_label(stype)
                idx   = cur_idx + i
                imgui.push_style_color(imgui.Col_.text,
                                       ImVec4(0.5, 0.5, 0.5, 1.0))
                clicked, _ = imgui.selectable(f"{idx:3d}  {name}", False)
                imgui.pop_style_color()
                if clicked:
                    undo.jump_to(idx + 1)

            if self._auto_scroll and imgui.get_scroll_y() >= imgui.get_scroll_max_y():
                imgui.set_scroll_here_y(1.0)

        imgui.end_child()
