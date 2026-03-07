"""
ActionEditorWindow  --  Python port of OFS_ActionEditor (action numeric buttons).

Shows a grid of position-labelled buttons (0..100 in configurable steps).
Clicking a button inserts/edits an action at the current time with that position.
Mirrors OFS action editor panel.
"""

from __future__ import annotations

from typing import Optional

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.funscript    import Funscript, FunscriptAction
from src.core.undo_system  import UndoSystem, StateType


class ActionEditorWindow:
    """OFS Action Editor panel. Mirrors ``OFS_ActionEditor`` (src/UI in the C++ tree)."""

    WindowId = "Action Editor###ActionEditor"

    def __init__(self) -> None:
        self._step: int  = 10   # default step between buttons
        self._show_grid: bool = True

    # ----------------------------------------------------------------------

    def Show(
        self,
        player:  OFS_Videoplayer,
        script:  Optional[Funscript],
        scripting,          # ScriptingMode (avoids circular import)
        undo:    UndoSystem,
        timeline_mgr=None,  # TimelineManager | None
        active_idx: int = -1,  # project.active_idx for track lookup
    ) -> None:
        """Render the action-editor button grid. Mirrors ``OFS_ActionEditor::ShowActionEditor``."""
        if not player.VideoLoaded():
            imgui.text_disabled("No video loaded")
            return

        imgui.text("Actions")
        imgui.separator()

        avail = imgui.get_content_region_avail()

        # Step selector
        imgui.set_next_item_width(80)
        changed, new_step = imgui.input_int("Step##aestep", self._step, 5, 10)
        if changed:
            self._step = max(1, min(50, new_step))

        imgui.spacing()

        if not self._show_grid:
            return

        # Button grid: from 100 down to 0 in rows of 5
        positions = list(range(100, -1, -self._step))
        if positions and positions[-1] != 0:
            positions.append(0)

        cols = 5
        btn_w = max(30.0, (avail.x - (cols - 1) * imgui.get_style().item_spacing.x) / cols)
        btn_size = ImVec2(btn_w, 28)

        # Current position for highlighting
        cur_pos: Optional[int] = None
        if script:
            ft = scripting.LogicalFrameTime()
            # Use funscript-local time for current-action lookup
            if timeline_mgr is not None and active_idx >= 0:
                trk = timeline_mgr.TrackForFunscript(active_idx)
                _local_t = trk.GlobalToLocal(timeline_mgr.transport.position) if trk else timeline_mgr.transport.position
            else:
                _local_t = player.CurrentTime()
            closest = script.GetActionAtTime(_local_t, ft * 0.5)
            if closest:
                cur_pos = closest.pos

        row = 0
        for i, pos in enumerate(positions):
            if i > 0 and i % cols == 0:
                row += 1

            is_cur = (cur_pos is not None and cur_pos == pos)
            if is_cur:
                imgui.push_style_color(imgui.Col_.button,
                                       ImVec4(0.60, 0.40, 0.10, 1.0))
                imgui.push_style_color(imgui.Col_.button_hovered,
                                       ImVec4(0.70, 0.50, 0.15, 1.0))

            if imgui.button(str(pos), btn_size):
                if script:
                    # Compute action time in funscript-local coordinates
                    if timeline_mgr is not None and active_idx >= 0:
                        global_t = timeline_mgr.transport.position
                        trk = timeline_mgr.TrackForFunscript(active_idx)
                        local_t = trk.GlobalToLocal(global_t) if trk else global_t
                        at_ms = int(local_t * 1000)
                    else:
                        at_ms = int(player.CurrentTime() * 1000)
                    action = FunscriptAction(at_ms, pos)
                    undo.Snapshot(StateType.ADD_EDIT_ACTIONS, script)
                    scripting.AddEditAction(action)

            if is_cur:
                imgui.pop_style_color(2)

            if (i + 1) % cols != 0 and i < len(positions) - 1:
                imgui.same_line()

        imgui.spacing()
        imgui.separator()

        # Quick-edit display of the nearest action
        if script:
            ft = scripting.LogicalFrameTime()
            # Use funscript-local time for nearest-action lookup
            if timeline_mgr is not None and active_idx >= 0:
                trk = timeline_mgr.TrackForFunscript(active_idx)
                local_t = trk.GlobalToLocal(timeline_mgr.transport.position) if trk else timeline_mgr.transport.position
            else:
                local_t = player.CurrentTime()
            closest = script.GetActionAtTime(local_t, ft)
            if closest:
                imgui.text(
                    f"Nearest action: {closest.at} ms  ->  {closest.pos}"
                )
            else:
                imgui.text_disabled("No action at current time")
