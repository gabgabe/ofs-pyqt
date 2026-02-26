"""
RoutingPanel — interactive routing matrix UI.

Renders a grid where:
  • Rows   = input axes  (funscript tracks, WS input instances)
  • Columns = output axes (OFS WS output, custom WS output, device channels)

Each cell is a clickable toggle (● / ○) representing a RouteLink.
Right-clicking a connected cell opens a popup to edit gain/offset/invert.

Additional controls:
  • Left sidebar: per-input track assignment combo
  • Top toolbar: Add WS Input / Add WS Output / Add Device instance buttons
  • Instance management: rename, remove, add axis
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.devices import (
    DEVICE_CATALOGUE,
    DeviceModel,
    list_device_models,
    OFS_WS_OUTPUT_AXES,
)
from src.core.routing_matrix import (
    DeviceInstance,
    NodeKind,
    RouteLink,
    RouteNode,
    RoutingMatrix,
    WSInputInstance,
    WSOutputInstance,
)

if TYPE_CHECKING:
    from src.core.timeline_manager import TimelineManager
    from src.core.timeline import Track

log = logging.getLogger(__name__)

# ── Styling constants ──────────────────────────────────────────────────
_CELL_SIZE     = 24.0
_ROW_LABEL_W   = 180.0
_COL_LABEL_H   = 100.0
_COMBO_W       = 120.0
_TOOLBAR_H     = 30.0

_COL_CONNECTED    = ImVec4(0.20, 0.75, 0.55, 1.0)   # green dot
_COL_DISCONNECTED = ImVec4(0.35, 0.35, 0.35, 0.60)   # grey dot
_COL_DISABLED     = ImVec4(0.60, 0.30, 0.15, 0.80)   # orange (linked but disabled)
_COL_GROUP_HDR    = ImVec4(0.25, 0.50, 0.70, 0.25)   # group header bg
_COL_VALUE_BAR    = ImVec4(0.25, 0.65, 0.50, 0.60)   # live value bar


class RoutingPanel:
    """Dear ImGui panel for the routing matrix view."""

    def __init__(self) -> None:
        # Popup state
        self._popup_inp: str = ""
        self._popup_out: str = ""

        # Add-instance wizards
        self._add_ws_in_open:  bool = False
        self._add_ws_in_name:  str  = "WS Input"
        self._add_ws_in_axes:  str  = "stroke"

        self._add_ws_out_open: bool = False
        self._add_ws_out_name: str  = "WS Output"
        self._add_ws_out_axes: str  = "stroke"

        self._add_dev_open:    bool = False
        self._add_dev_model:   int  = 0       # index into sorted catalogue
        self._add_dev_name:    str  = ""

        # Track assignment cache  (input_node_id → timeline track list for combo)
        self._track_options: List[Tuple[str, str]] = []   # (track_id, label)

    # ------------------------------------------------------------------
    # Main draw
    # ------------------------------------------------------------------

    def Show(self, routing: RoutingMatrix,
             timeline_mgr: "TimelineManager") -> None:
        """Draw the full routing panel contents (called inside a window/dock)."""

        self._refresh_track_list(timeline_mgr)

        # ── Toolbar ───────────────────────────────────────────────────
        self._draw_toolbar(routing)
        imgui.separator()

        # ── Matrix ────────────────────────────────────────────────────
        inp_order = routing.get_input_order()
        out_order = routing.get_output_order()

        if not inp_order and not out_order:
            imgui.text_disabled("No inputs or outputs configured.")
            imgui.text_disabled("Add a funscript track, WS input, or device to get started.")
            return

        # Scrollable child for the matrix
        avail = imgui.get_content_region_avail()
        imgui.begin_child("##routing_matrix", ImVec2(avail.x, avail.y),
                          imgui.ChildFlags_.none,
                          imgui.WindowFlags_.horizontal_scrollbar)

        self._draw_matrix(routing, inp_order, out_order)

        imgui.end_child()

        # ── Popups ────────────────────────────────────────────────────
        self._draw_link_popup(routing)
        self._draw_add_ws_input_popup(routing)
        self._draw_add_ws_output_popup(routing)
        self._draw_add_device_popup(routing)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _draw_toolbar(self, routing: RoutingMatrix) -> None:
        if imgui.button("+ WS Input"):
            self._add_ws_in_open = True
            self._add_ws_in_name = "WS Input"
            self._add_ws_in_axes = "stroke"
            imgui.open_popup("##add_ws_in")

        imgui.same_line()
        if imgui.button("+ WS Output"):
            self._add_ws_out_open = True
            self._add_ws_out_name = "WS Output"
            self._add_ws_out_axes = "stroke"
            imgui.open_popup("##add_ws_out")

        imgui.same_line()
        if imgui.button("+ Device"):
            self._add_dev_open = True
            self._add_dev_model = 0
            self._add_dev_name = ""
            imgui.open_popup("##add_dev")

        # Show instance removal buttons
        imgui.same_line()
        imgui.spacing()
        imgui.same_line()

        # Remove WS Input instances
        if routing.ws_inputs:
            imgui.same_line()
            if imgui.begin_combo("##rm_wsi", "Remove WS In…",
                                 imgui.ComboFlags_.no_preview):
                for inst_id, inst in list(routing.ws_inputs.items()):
                    if imgui.selectable(inst.name, False)[0]:
                        routing.remove_ws_input_instance(inst_id)
                imgui.end_combo()

        # Remove WS Output instances
        if routing.ws_outputs:
            imgui.same_line()
            if imgui.begin_combo("##rm_wso", "Remove WS Out…",
                                 imgui.ComboFlags_.no_preview):
                for inst_id, inst in list(routing.ws_outputs.items()):
                    if imgui.selectable(inst.name, False)[0]:
                        routing.remove_ws_output_instance(inst_id)
                imgui.end_combo()

        # Remove Device instances
        if routing.devices:
            imgui.same_line()
            if imgui.begin_combo("##rm_dev", "Remove Device…",
                                 imgui.ComboFlags_.no_preview):
                for inst_id, inst in list(routing.devices.items()):
                    if imgui.selectable(inst.name, False)[0]:
                        routing.remove_device_instance(inst_id)
                imgui.end_combo()

    # ------------------------------------------------------------------
    # Matrix grid
    # ------------------------------------------------------------------

    def _draw_matrix(self, routing: RoutingMatrix,
                     inp_order: List[str], out_order: List[str]) -> None:
        """Draw column headers + row labels + cells."""
        dl = imgui.get_window_draw_list()
        origin = imgui.get_cursor_screen_pos()

        total_w = _ROW_LABEL_W + _COMBO_W + len(out_order) * _CELL_SIZE + 40
        total_h = _COL_LABEL_H + len(inp_order) * _CELL_SIZE + 20

        # Invisible button to reserve space for scrolling
        imgui.invisible_button("##matrix_area", ImVec2(total_w, total_h))

        col_x0 = origin.x + _ROW_LABEL_W + _COMBO_W + 8

        # ── Column headers (rotated text) ─────────────────────────────
        prev_group = ""
        for ci, out_id in enumerate(out_order):
            out_node = routing.outputs.get(out_id)
            if not out_node:
                continue
            cx = col_x0 + ci * _CELL_SIZE + _CELL_SIZE * 0.5
            cy = origin.y + _COL_LABEL_H - 4

            # Group separator line
            if out_node.group != prev_group and prev_group:
                sep_x = col_x0 + ci * _CELL_SIZE - 2
                dl.add_line(
                    ImVec2(sep_x, origin.y),
                    ImVec2(sep_x, origin.y + total_h),
                    imgui.get_color_u32(ImVec4(0.5, 0.5, 0.5, 0.3)), 1.0,
                )
            prev_group = out_node.group

            # Vertical text (character by character)
            label = out_node.label[:14]  # truncate
            for k, ch in enumerate(label):
                dl.add_text(
                    ImVec2(cx - 4, origin.y + 4 + k * 10),
                    imgui.get_color_u32(ImVec4(0.8, 0.8, 0.8, 1.0)),
                    ch,
                )

        # ── Rows ──────────────────────────────────────────────────────
        prev_group = ""
        for ri, inp_id in enumerate(inp_order):
            inp_node = routing.inputs.get(inp_id)
            if not inp_node:
                continue

            ry = origin.y + _COL_LABEL_H + ri * _CELL_SIZE

            # Group header
            if inp_node.group != prev_group:
                if prev_group:
                    # Separator line
                    dl.add_line(
                        ImVec2(origin.x, ry - 1),
                        ImVec2(origin.x + total_w, ry - 1),
                        imgui.get_color_u32(ImVec4(0.5, 0.5, 0.5, 0.3)), 1.0,
                    )
                # Group label (small, dimmed)
                dl.add_rect_filled(
                    ImVec2(origin.x, ry),
                    ImVec2(origin.x + _ROW_LABEL_W + _COMBO_W, ry + _CELL_SIZE),
                    imgui.get_color_u32(_COL_GROUP_HDR),
                )
                prev_group = inp_node.group

            # ── Track assignment combo (for funscript inputs) ─────────
            if inp_node.kind == NodeKind.FUNSCRIPT_TRACK:
                imgui.set_cursor_screen_pos(ImVec2(origin.x + 2, ry + 2))
                imgui.push_id(f"trk_{inp_id}")
                imgui.set_next_item_width(_COMBO_W - 4)
                current_label = "—"
                for tid, tlabel in self._track_options:
                    if tid == inp_node.track_id:
                        current_label = tlabel
                        break
                if imgui.begin_combo("##trk", current_label, imgui.ComboFlags_.none):
                    # "None" option
                    if imgui.selectable("— (none)", inp_node.track_id == "")[0]:
                        inp_node.track_id = ""
                    for tid, tlabel in self._track_options:
                        sel = (tid == inp_node.track_id)
                        if imgui.selectable(tlabel, sel)[0]:
                            inp_node.track_id = tid
                    imgui.end_combo()
                imgui.pop_id()

            # ── Row label ─────────────────────────────────────────────
            lx = origin.x + _COMBO_W + 4
            dl.add_text(
                ImVec2(lx, ry + 4),
                imgui.get_color_u32(ImVec4(0.85, 0.85, 0.85, 1.0)),
                inp_node.label[:24],
            )

            # ── Live value bar ────────────────────────────────────────
            val = inp_node.value
            if val > 0.01:
                bar_w = (_ROW_LABEL_W - 8) * (val / 100.0)
                dl.add_rect_filled(
                    ImVec2(lx, ry + _CELL_SIZE - 4),
                    ImVec2(lx + bar_w, ry + _CELL_SIZE - 1),
                    imgui.get_color_u32(_COL_VALUE_BAR),
                )

            # ── Cells ─────────────────────────────────────────────────
            for ci, out_id in enumerate(out_order):
                cx = col_x0 + ci * _CELL_SIZE
                cell_center = ImVec2(cx + _CELL_SIZE * 0.5,
                                     ry + _CELL_SIZE * 0.5)

                link = routing.get_link(inp_id, out_id)
                is_linked = link is not None and link.enabled

                # Draw dot
                if is_linked:
                    col = _COL_CONNECTED
                    radius = 6.0
                elif link is not None:
                    col = _COL_DISABLED
                    radius = 5.0
                else:
                    col = _COL_DISCONNECTED
                    radius = 3.5

                dl.add_circle_filled(cell_center, radius,
                                     imgui.get_color_u32(col))

                # Interactive zone
                btn_id = f"##cell_{ri}_{ci}"
                imgui.set_cursor_screen_pos(ImVec2(cx, ry))
                imgui.push_id(btn_id)
                if imgui.invisible_button(btn_id, ImVec2(_CELL_SIZE, _CELL_SIZE)):
                    # Left click → toggle
                    routing.toggle_link(inp_id, out_id)

                # Right-click → open properties popup
                if imgui.is_item_clicked(imgui.MouseButton_.right):
                    if routing.get_link(inp_id, out_id) is None:
                        routing.set_link(inp_id, out_id, enabled=True)
                    self._popup_inp = inp_id
                    self._popup_out = out_id
                    imgui.open_popup("##link_props")

                # Tooltip
                if imgui.is_item_hovered():
                    out_node = routing.outputs.get(out_id)
                    tip = f"{inp_node.label}  →  {out_node.label if out_node else '?'}"
                    if link:
                        tip += f"\nGain: {link.gain:.2f}  Offset: {link.offset:.1f}"
                        if link.invert:
                            tip += "  [INVERTED]"
                        if not link.enabled:
                            tip += "  [DISABLED]"
                    else:
                        tip += "\n(Click to connect)"
                    imgui.set_tooltip(tip)

                imgui.pop_id()

    # ------------------------------------------------------------------
    # Link properties popup
    # ------------------------------------------------------------------

    def _draw_link_popup(self, routing: RoutingMatrix) -> None:
        if imgui.begin_popup("##link_props"):
            link = routing.get_link(self._popup_inp, self._popup_out)
            if link:
                inp_node = routing.inputs.get(self._popup_inp)
                out_node = routing.outputs.get(self._popup_out)
                imgui.text(f"{inp_node.label if inp_node else '?'}  →  "
                           f"{out_node.label if out_node else '?'}")
                imgui.separator()

                _, link.enabled = imgui.checkbox("Enabled", link.enabled)
                imgui.set_next_item_width(120)
                _, link.gain = imgui.slider_float("Gain", link.gain, 0.0, 3.0, "%.2f")
                imgui.set_next_item_width(120)
                _, link.offset = imgui.slider_float("Offset", link.offset, -100.0, 100.0, "%.1f")
                _, link.invert = imgui.checkbox("Invert", link.invert)

                imgui.spacing()
                if imgui.button("Remove link"):
                    routing.remove_link(self._popup_inp, self._popup_out)
                    imgui.close_current_popup()

            imgui.end_popup()

    # ------------------------------------------------------------------
    # Add WS Input popup
    # ------------------------------------------------------------------

    def _draw_add_ws_input_popup(self, routing: RoutingMatrix) -> None:
        if imgui.begin_popup("##add_ws_in"):
            imgui.text("Add WebSocket Input Instance")
            imgui.separator()

            imgui.text("Name:")
            imgui.set_next_item_width(200)
            _, self._add_ws_in_name = imgui.input_text("##wsi_name",
                                                        self._add_ws_in_name, 128)
            imgui.text("Axes (comma-separated):")
            imgui.set_next_item_width(200)
            _, self._add_ws_in_axes = imgui.input_text("##wsi_axes",
                                                        self._add_ws_in_axes, 256)
            imgui.text_disabled("e.g.  stroke, twist, vib")

            imgui.spacing()
            if imgui.button("Create", ImVec2(100, 0)):
                axes = [a.strip() for a in self._add_ws_in_axes.split(",") if a.strip()]
                if axes:
                    routing.add_ws_input_instance(self._add_ws_in_name, axes)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", ImVec2(80, 0)):
                imgui.close_current_popup()

            imgui.end_popup()

    # ------------------------------------------------------------------
    # Add WS Output popup
    # ------------------------------------------------------------------

    def _draw_add_ws_output_popup(self, routing: RoutingMatrix) -> None:
        if imgui.begin_popup("##add_ws_out"):
            imgui.text("Add WebSocket Output Instance")
            imgui.separator()

            imgui.text("Name:")
            imgui.set_next_item_width(200)
            _, self._add_ws_out_name = imgui.input_text("##wso_name",
                                                         self._add_ws_out_name, 128)
            imgui.text("Axes (comma-separated):")
            imgui.set_next_item_width(200)
            _, self._add_ws_out_axes = imgui.input_text("##wso_axes",
                                                         self._add_ws_out_axes, 256)
            imgui.text_disabled("e.g.  channel_a, channel_b")

            imgui.spacing()
            if imgui.button("Create", ImVec2(100, 0)):
                axes = [a.strip() for a in self._add_ws_out_axes.split(",") if a.strip()]
                if axes:
                    routing.add_ws_output_instance(self._add_ws_out_name, axes)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel##wso", ImVec2(80, 0)):
                imgui.close_current_popup()

            imgui.end_popup()

    # ------------------------------------------------------------------
    # Add Device popup
    # ------------------------------------------------------------------

    def _draw_add_device_popup(self, routing: RoutingMatrix) -> None:
        if imgui.begin_popup("##add_dev"):
            imgui.text("Add Device")
            imgui.separator()

            models = list_device_models()
            if not models:
                imgui.text_disabled("No device models in catalogue.")
                if imgui.button("Close"):
                    imgui.close_current_popup()
                imgui.end_popup()
                return

            model_labels = [m.label for m in models]
            imgui.text("Model:")
            imgui.set_next_item_width(220)
            _, self._add_dev_model = imgui.combo(
                "##dev_model", self._add_dev_model, model_labels)

            selected = models[self._add_dev_model]
            imgui.text_disabled(f"{selected.manufacturer}  —  {selected.description}")
            imgui.text_disabled(f"Axes: {', '.join(a.label for a in selected.axes)}")

            imgui.spacing()
            imgui.text("Instance name:")
            imgui.set_next_item_width(200)
            _, self._add_dev_name = imgui.input_text("##dev_name",
                                                      self._add_dev_name, 128)
            if not self._add_dev_name:
                imgui.same_line()
                imgui.text_disabled(f"(defaults to \"{selected.label}\")")

            imgui.spacing()
            if imgui.button("Create", ImVec2(100, 0)):
                routing.add_device_instance(
                    selected.model_id,
                    self._add_dev_name or selected.label,
                )
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel##dev", ImVec2(80, 0)):
                imgui.close_current_popup()

            imgui.end_popup()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_track_list(self, timeline_mgr: "TimelineManager") -> None:
        """Build the list of funscript tracks for the combo boxes."""
        from src.core.timeline import TrackType
        opts: List[Tuple[str, str]] = []
        tl = timeline_mgr.timeline
        if tl:
            for layer in tl.layers:
                for track in layer.tracks:
                    if track.track_type == TrackType.FUNSCRIPT:
                        opts.append((track.id, track.name))
        self._track_options = opts
