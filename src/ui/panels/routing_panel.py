"""
RoutingPanel  --  interactive routing matrix UI.

Renders a grid where:
  * Rows   = input axes  (funscript tracks, WS input instances)
  * Columns = output axes (OFS WS output, custom WS output, device channels)

Each cell is a clickable toggle (* / o) representing a RouteLink.
Right-clicking a connected cell opens a popup to edit gain/offset/invert.

Additional controls:
  * Left sidebar: per-input track assignment combo
  * Top toolbar: Add WS Input / Add WS Output / Add Device instance buttons
  * Instance management: rename, remove, add axis
"""

from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

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
from src.core.backends import BACKEND_ALTERNATIVES

if TYPE_CHECKING:
    from src.core.timeline_manager import TimelineManager
    from src.core.timeline import Track
    from src.core.device_manager import DeviceManager

log = logging.getLogger(__name__)

# -- Styling constants --------------------------------------------------
_CELL_SIZE     = 24.0
_ROW_LABEL_W   = 180.0
_COL_LABEL_H   = 150.0
_COMBO_W       = 120.0
_TOOLBAR_H     = 30.0

_COL_CONNECTED    = ImVec4(0.15, 1.00, 0.55, 1.0)   # bright green dot
_COL_DISCONNECTED = ImVec4(0.40, 0.40, 0.40, 0.45)  # subtle grey dot
_COL_DISABLED     = ImVec4(0.90, 0.45, 0.15, 0.90)  # bright orange (linked but disabled)
_COL_GROUP_HDR    = ImVec4(0.25, 0.50, 0.70, 0.25)  # group header bg
_COL_VALUE_BAR    = ImVec4(0.25, 0.65, 0.50, 0.60)  # live value bar
_COL_DEV_ONLINE   = ImVec4(0.20, 0.85, 0.45, 1.0)   # device online
_COL_DEV_OFFLINE  = ImVec4(0.55, 0.55, 0.55, 0.70)  # device offline
_COL_GRID_LINE    = ImVec4(0.45, 0.45, 0.45, 0.30)  # grid lines
_COL_CELL_HOVER   = ImVec4(0.50, 0.50, 0.80, 0.20)  # cell hover highlight
_COL_HEADER_TXT   = ImVec4(0.85, 0.85, 0.85, 1.0)   # column header text


def _draw_rotated_text(dl, text: str, cx: float, top_y: float,
                       color_u32: int, max_h: float = 0.0) -> None:
    """Draw *text* vertically, one character per line, reading top-to-bottom.

    Each glyph is centred horizontally around *cx*.  *top_y* is the
    y-coordinate of the first character.  Characters are spaced by
    ``font_size`` so they never overlap vertically.
    If *max_h* > 0, text is truncated to fit.
    """
    font_size = imgui.get_font_size()
    step = font_size                # full font height -> no overlap
    if max_h > 0:
        max_chars = max(1, int(max_h / step))
        text = text[:max_chars]
    for i, ch in enumerate(text):
        glyph_w = imgui.calc_text_size(ch).x
        px = cx - glyph_w * 0.5     # centre in column
        py = top_y + i * step
        dl.add_text(ImVec2(px, py), color_u32, ch)


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

        # Track assignment cache  (input_node_id -> timeline track list for combo)
        self._track_options: List[Tuple[str, str]] = []   # (track_id, label)

        # Device config popup state
        self._cfg_dev_id: str = ""         # instance id of device being configured
        self._cfg_open: bool = False
        self._cfg_fields: Dict[str, str] = {}   # editable string buffers
        self._cfg_backend_idx: int = 0           # selected backend alt combo index
        self._serial_ports: List[str] = []
        self._serial_ports_ts: float = 0.0
        # Channel tree popup state
        self._ch_tree_dev_id: str = ""     # device instance for channel add popup
        self._ch_tree_open: bool = False    # deferred open flag
        # OSC config popup
        self._osc_cfg_open: bool = False
        self._osc_cfg_fields: Dict[str, str] = {}
        # WS Output config popup
        self._ws_cfg_open: bool = False
        self._ws_cfg_fields: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Main draw
    # ------------------------------------------------------------------

    def Show(self, routing: RoutingMatrix,
             timeline_mgr: "TimelineManager",
             device_mgr: "DeviceManager | None" = None) -> None:
        """Draw the full routing panel contents (called inside a window/dock)."""

        self._refresh_track_list(timeline_mgr)

        # -- Toolbar ---------------------------------------------------
        self._draw_toolbar(routing, device_mgr)
        imgui.separator()

        # -- Matrix ----------------------------------------------------
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

        # -- Popups ----------------------------------------------------
        self._draw_link_popup(routing)
        self._draw_add_ws_input_popup(routing)
        self._draw_add_ws_output_popup(routing, device_mgr)
        self._draw_add_device_popup(routing, device_mgr)
        self._draw_device_config_popup(routing, device_mgr)
        self._draw_osc_config_popup(device_mgr)
        self._draw_ws_output_config_popup(device_mgr)
        self._draw_channel_tree_popup(routing, device_mgr)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _draw_toolbar(self, routing: RoutingMatrix,
                      device_mgr: "DeviceManager | None" = None) -> None:
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
            if imgui.begin_combo("##rm_wsi", "Remove WS In...",
                                 imgui.ComboFlags_.no_preview):
                for inst_id, inst in list(routing.ws_inputs.items()):
                    if imgui.selectable(inst.name, False)[0]:
                        routing.remove_ws_input_instance(inst_id)
                imgui.end_combo()

        # Remove WS Output instances
        if routing.ws_outputs:
            imgui.same_line()
            if imgui.begin_combo("##rm_wso", "Remove WS Out...",
                                 imgui.ComboFlags_.no_preview):
                for inst_id, inst in list(routing.ws_outputs.items()):
                    if imgui.selectable(inst.name, False)[0]:
                        routing.remove_ws_output_instance(inst_id)
                        if device_mgr:
                            device_mgr.unregister_ws_output(inst_id)
                imgui.end_combo()

        # Remove Device instances
        if routing.devices:
            imgui.same_line()
            if imgui.begin_combo("##rm_dev", "Remove Device...",
                                 imgui.ComboFlags_.no_preview):
                for inst_id, inst in list(routing.devices.items()):
                    if imgui.selectable(inst.name, False)[0]:
                        routing.remove_device_instance(inst_id)
                        if device_mgr:
                            device_mgr.unregister_device(inst_id)
                imgui.end_combo()

        # -- Device connection status row ------------------------------
        if device_mgr and routing.devices:
            imgui.spacing()
            for inst_id, inst in routing.devices.items():
                connected = device_mgr.is_connected(inst_id)
                col = _COL_DEV_ONLINE if connected else _COL_DEV_OFFLINE
                imgui.push_style_color(imgui.Col_.text, col)
                imgui.bullet()
                imgui.same_line()
                imgui.text(inst.name)
                imgui.pop_style_color()
                imgui.same_line()
                imgui.push_id(f"devctl_{inst_id}")
                if connected:
                    if imgui.small_button("Disconnect"):
                        device_mgr.disconnect_device(inst_id)
                else:
                    if imgui.small_button("Connect"):
                        ok = device_mgr.connect_device(inst_id)
                        if not ok:
                            err = device_mgr.last_error(inst_id)
                            log.warning(f"Connect failed: {err}")
                    err = device_mgr.last_error(inst_id)
                    if err:
                        imgui.same_line()
                        imgui.text_colored(ImVec4(1, 0.3, 0.3, 1), err)
                # Settings gear button
                imgui.same_line()
                if imgui.small_button("Settings"):
                    self._cfg_dev_id = inst_id
                    self._cfg_open = True
                    cfg = device_mgr.get_config(inst_id)
                    cls_name = device_mgr.get_backend_class_name(inst_id)
                    self._populate_cfg_fields(cls_name, cfg.params)
                    alts = BACKEND_ALTERNATIVES.get(inst.model_id, [])
                    self._cfg_backend_idx = 0
                    for i, (_lbl, cls) in enumerate(alts):
                        if cls.__name__ == cls_name:
                            self._cfg_backend_idx = i
                            break
                # Add Channel button (deferred open -- avoids ID scope mismatch)
                imgui.same_line()
                if imgui.small_button("+ Channel"):
                    self._ch_tree_dev_id = inst_id
                    self._ch_tree_open = True
                n_ch = len(routing.get_device_channels(inst_id))
                if n_ch:
                    imgui.same_line()
                    imgui.text_disabled(f"({n_ch} ch)")
                imgui.pop_id()
                # Each device on its own row — no same_line()

        # -- WS Output toggle (always shown when device_mgr available) --
        if device_mgr:
            imgui.spacing()
            ws_on = device_mgr.ws_output_enabled
            imgui.push_style_color(imgui.Col_.text,
                                   _COL_DEV_ONLINE if ws_on else _COL_DEV_OFFLINE)
            imgui.bullet()
            imgui.same_line()
            imgui.text("WS Output")
            imgui.pop_style_color()
            imgui.same_line()
            if ws_on:
                if imgui.small_button("Disable WS"):
                    device_mgr.disable_ws_output()
            else:
                if imgui.small_button("Enable WS"):
                    device_mgr.enable_ws_output()
            imgui.same_line()
            if imgui.small_button("WS Settings"):
                self._ws_cfg_open = True
                cfg = device_mgr.ws_output_config
                self._ws_cfg_fields = {k: str(v) for k, v in cfg.params.items()}
            if ws_on:
                imgui.same_line()
                ws_be = device_mgr.ws_output_backend
                if ws_be:
                    n_clients = getattr(ws_be, 'client_count', 0)
                    imgui.text_disabled(f"({n_clients} client{'s' if n_clients != 1 else ''})")

        # -- OSC toggle (always shown when device_mgr available) -------
        if device_mgr:
            imgui.spacing()
            osc_on = device_mgr.osc_enabled
            imgui.push_style_color(imgui.Col_.text,
                                   _COL_DEV_ONLINE if osc_on else _COL_DEV_OFFLINE)
            imgui.bullet()
            imgui.same_line()
            imgui.text("OSC Output")
            imgui.pop_style_color()
            imgui.same_line()
            if osc_on:
                if imgui.small_button("Disable OSC"):
                    device_mgr.disable_osc()
            else:
                if imgui.small_button("Enable OSC"):
                    device_mgr.enable_osc()
            imgui.same_line()
            if imgui.small_button("OSC Settings"):
                self._osc_cfg_open = True
                cfg = device_mgr.osc_config
                self._osc_cfg_fields = {k: str(v) for k, v in cfg.params.items()}

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

        # Reserve space for scrolling (dummy does not consume clicks)
        imgui.dummy(ImVec2(total_w, total_h))

        col_x0 = origin.x + _ROW_LABEL_W + _COMBO_W + 8

        # -- Grid lines (draw before dots so they sit behind) ----------
        grid_col = imgui.get_color_u32(_COL_GRID_LINE)
        rows_y0 = origin.y + _COL_LABEL_H
        # Horizontal lines (one per row)
        for ri in range(len(inp_order) + 1):
            gy = rows_y0 + ri * _CELL_SIZE
            dl.add_line(ImVec2(col_x0, gy),
                        ImVec2(col_x0 + len(out_order) * _CELL_SIZE, gy),
                        grid_col, 1.0)
        # Vertical lines (one per column)
        for ci in range(len(out_order) + 1):
            gx = col_x0 + ci * _CELL_SIZE
            dl.add_line(ImVec2(gx, rows_y0),
                        ImVec2(gx, rows_y0 + len(inp_order) * _CELL_SIZE),
                        grid_col, 1.0)

        # -- Column headers (rotated text  --  tilt head left to read) ----
        hdr_col = imgui.get_color_u32(_COL_HEADER_TXT)
        prev_group = ""
        for ci, out_id in enumerate(out_order):
            out_node = routing.outputs.get(out_id)
            if not out_node:
                continue
            # Text origin: centre of column, starting near top
            tx = col_x0 + ci * _CELL_SIZE + _CELL_SIZE * 0.5
            ty = origin.y + 4

            # Group separator line
            if out_node.group != prev_group and prev_group:
                sep_x = col_x0 + ci * _CELL_SIZE - 2
                dl.add_line(
                    ImVec2(sep_x, origin.y),
                    ImVec2(sep_x, origin.y + total_h),
                    imgui.get_color_u32(ImVec4(0.5, 0.5, 0.5, 0.4)), 1.0,
                )
            prev_group = out_node.group

            label = out_node.label[:14]  # truncate
            _draw_rotated_text(dl, label, tx, ty, hdr_col,
                               max_h=_COL_LABEL_H - 10)

            # -- Output value bar (vertical, bottom of header) ---------
            out_val = out_node.value
            if out_val > 0.01:
                bar_max_h = _COL_LABEL_H - 14
                bar_h = bar_max_h * (out_val / 100.0)
                bar_x0 = col_x0 + ci * _CELL_SIZE + 2
                bar_x1 = bar_x0 + _CELL_SIZE - 4
                bar_y1 = origin.y + _COL_LABEL_H - 2
                bar_y0 = bar_y1 - bar_h
                dl.add_rect_filled(
                    ImVec2(bar_x0, bar_y0), ImVec2(bar_x1, bar_y1),
                    imgui.get_color_u32(_COL_VALUE_BAR),
                )

        # -- Rows ------------------------------------------------------
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

            # -- Track assignment combo (for funscript inputs) ---------
            if inp_node.kind == NodeKind.FUNSCRIPT_TRACK:
                imgui.set_cursor_screen_pos(ImVec2(origin.x + 2, ry + 2))
                imgui.push_id(f"trk_{inp_id}")
                imgui.set_next_item_width(_COMBO_W - 4)
                current_label = "--"
                for tid, tlabel in self._track_options:
                    if tid == inp_node.track_id:
                        current_label = tlabel
                        break
                if imgui.begin_combo("##trk", current_label, imgui.ComboFlags_.none):
                    # "None" option
                    if imgui.selectable("-- (none)", inp_node.track_id == "")[0]:
                        inp_node.track_id = ""
                    for tid, tlabel in self._track_options:
                        sel = (tid == inp_node.track_id)
                        if imgui.selectable(tlabel, sel)[0]:
                            inp_node.track_id = tid
                    imgui.end_combo()
                imgui.pop_id()

            # -- Row label ---------------------------------------------
            lx = origin.x + _COMBO_W + 4
            dl.add_text(
                ImVec2(lx, ry + 4),
                imgui.get_color_u32(ImVec4(0.85, 0.85, 0.85, 1.0)),
                inp_node.label[:24],
            )

            # -- Live value bar ----------------------------------------
            val = inp_node.value
            if val > 0.01:
                bar_w = (_ROW_LABEL_W - 8) * (val / 100.0)
                dl.add_rect_filled(
                    ImVec2(lx, ry + _CELL_SIZE - 4),
                    ImVec2(lx + bar_w, ry + _CELL_SIZE - 1),
                    imgui.get_color_u32(_COL_VALUE_BAR),
                )

            # -- Cells -------------------------------------------------
            for ci, out_id in enumerate(out_order):
                cx = col_x0 + ci * _CELL_SIZE
                cell_center = ImVec2(cx + _CELL_SIZE * 0.5,
                                     ry + _CELL_SIZE * 0.5)

                link = routing.get_link(inp_id, out_id)
                is_linked = link is not None and link.enabled

                # Draw crosspoint
                if is_linked:
                    # Scale dot with live signal intensity
                    inp_val = inp_node.value / 100.0  # 0.0 - 1.0
                    # Base green dot  --  alpha and radius grow with signal
                    alpha = 0.5 + 0.5 * inp_val
                    radius = 5.0 + 3.0 * inp_val
                    col = ImVec4(0.15, 1.00, 0.55, alpha)
                    dl.add_circle_filled(cell_center, radius,
                                         imgui.get_color_u32(col))
                    dl.add_circle(cell_center, radius,
                                  imgui.get_color_u32(
                                      ImVec4(1.0, 1.0, 1.0, 0.25 + 0.35 * inp_val)),
                                  0, 1.5)
                elif link is not None:
                    col = _COL_DISABLED
                    radius = 5.5
                    dl.add_circle_filled(cell_center, radius,
                                         imgui.get_color_u32(col))
                    dl.add_circle(cell_center, radius,
                                  imgui.get_color_u32(
                                      ImVec4(1.0, 0.6, 0.2, 0.40)), 0, 1.0)
                else:
                    col = _COL_DISCONNECTED
                    radius = 3.0
                    dl.add_circle_filled(cell_center, radius,
                                         imgui.get_color_u32(col))

                # Interactive zone
                btn_id = f"##cell_{ri}_{ci}"
                imgui.set_cursor_screen_pos(ImVec2(cx, ry))
                imgui.push_id(btn_id)
                if imgui.invisible_button(btn_id, ImVec2(_CELL_SIZE, _CELL_SIZE)):
                    # Left click: if not linked, create link (interlock auto-clears)
                    # If already linked, disconnect.
                    if link is not None and link.enabled:
                        routing.remove_link(inp_id, out_id)
                    else:
                        routing.set_link(inp_id, out_id, enabled=True)

                # Hover highlight
                if imgui.is_item_hovered():
                    dl.add_rect_filled(
                        ImVec2(cx + 1, ry + 1),
                        ImVec2(cx + _CELL_SIZE - 1, ry + _CELL_SIZE - 1),
                        imgui.get_color_u32(_COL_CELL_HOVER),
                    )

                # Right-click on connected cell -> open properties popup
                if imgui.is_item_clicked(imgui.MouseButton_.right):
                    if link is not None:
                        self._popup_inp = inp_id
                        self._popup_out = out_id
                        imgui.open_popup("##link_props")

                # Tooltip
                if imgui.is_item_hovered():
                    out_node = routing.outputs.get(out_id)
                    tip = f"{inp_node.label}  ->  {out_node.label if out_node else '?'}"
                    if link and link.enabled:
                        tip += f"\nGain: {link.gain:.2f}  Offset: {link.offset:.1f}"
                        if link.invert:
                            tip += "  [INVERTED]"
                        tip += "\nLeft-click: disconnect"
                        tip += "\nRight-click: properties"
                    else:
                        tip += "\n(Left-click to connect)"
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
                imgui.text(f"{inp_node.label if inp_node else '?'}  ->  "
                           f"{out_node.label if out_node else '?'}")
                imgui.separator()

                _, link.enabled = imgui.checkbox("Enabled", link.enabled)
                imgui.set_next_item_width(120)
                _, link.gain = imgui.slider_float("Gain", link.gain, 0.0, 3.0, "%.2f")
                imgui.set_next_item_width(120)
                _, link.offset = imgui.slider_float("Offset", link.offset, -100.0, 100.0, "%.1f")
                _, link.invert = imgui.checkbox("Invert", link.invert)

                imgui.spacing()
                imgui.separator()
                imgui.text("Output Range")
                imgui.set_next_item_width(120)
                _, link.out_min = imgui.slider_float(
                    "Out Min", link.out_min, 0.0, link.out_max, "%.1f")
                imgui.set_next_item_width(120)
                _, link.out_max = imgui.slider_float(
                    "Out Max", link.out_max, link.out_min, 100.0, "%.1f")
                # Show effective hardware range hint for device channels
                out_node = routing.outputs.get(self._popup_out)
                if out_node and out_node.kind == NodeKind.DEVICE_CHANNEL:
                    imgui.text_disabled(
                        f"Maps 0-100% -> {link.out_min:.0f}%-{link.out_max:.0f}% "
                        f"of HW range")

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

    def _draw_add_ws_output_popup(self, routing: RoutingMatrix,
                                   device_mgr: "DeviceManager | None" = None) -> None:
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
                    if device_mgr:
                        device_mgr.sync_with_routing(routing)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel##wso", ImVec2(80, 0)):
                imgui.close_current_popup()

            imgui.end_popup()

    # ------------------------------------------------------------------
    # Add Device popup
    # ------------------------------------------------------------------

    def _draw_add_device_popup(self, routing: RoutingMatrix,
                               device_mgr: "DeviceManager | None" = None) -> None:
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
            imgui.text_disabled(f"{selected.manufacturer} - {selected.description}")
            imgui.text_disabled(f"Protocol: {selected.protocol}")
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
                inst = routing.add_device_instance(
                    selected.model_id,
                    self._add_dev_name or selected.label,
                )
                # Immediately register with device manager
                if device_mgr and inst:
                    device_mgr.sync_with_routing(routing)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel##dev", ImVec2(80, 0)):
                imgui.close_current_popup()

            imgui.end_popup()

    # ------------------------------------------------------------------
    # Device config popup (modal)
    # ------------------------------------------------------------------

    # Per-backend parameter schemas: (key, label, hint, widget)
    # widget: "str" | "int" | "bool" | "port" | "baudrate"
    _BACKEND_PARAMS: Dict[str, List[Tuple[str, str, str, str]]] = {
        "MK312Backend": [
            ("device",   "Serial Port", "", "port"),
            ("baudrate", "Baud Rate",   "", "baudrate"),
        ],
        "TCodeBackend": [
            ("device",   "Serial Port", "", "port"),
            ("baudrate", "Baud Rate",   "", "baudrate"),
        ],
        "DGLabSocketBackend": [
            ("ws_url",    "WebSocket URL", "wss://ws.dungeon-lab.cn/", "str"),
            ("target_id", "Target ID",     "From DG-Lab APP QR code",  "str"),
            ("v3",        "V3 Waveform",   "",                         "bool"),
        ],
        "DGLabBLEBackend": [
            ("address",  "BLE Address",      "Leave blank for auto-scan", "str"),
            ("limit_a",  "Strength Limit A", "0\u2013200",                     "int"),
            ("limit_b",  "Strength Limit B", "0\u2013200",                     "int"),
        ],
        "ButtplugBackend": [
            ("server", "Intiface URL", "ws://127.0.0.1:12345", "str"),
        ],
        "PiShockSerialBackend": [
            ("device",      "Serial Port",  "",                      "port"),
            ("baudrate",    "Baud Rate",    "",                      "baudrate"),
            ("shocker_id",  "Shocker ID",   "From PiShock hub",      "int"),
            ("model",       "RF Model",     "1=CaiXianlin 2=Petrainer 3=998DR", "int"),
            ("duration_ms", "Duration (ms)", "300\u201365535",              "int"),
        ],
        "OSSMBLEBackend": [
            ("address",     "BLE Address",   "Leave blank for auto-scan (advertises as 'setup')", "str"),
            ("interval_ms", "Interval (ms)", "10\u2013500 (default 16, ~62 Hz)",          "int"),
            ("mode",        "Mode",          "streaming / simplePenetration / strokeEngine", "str"),
            ("use_fts",     "FTS Binary",    "Use 3-byte binary protocol (faster)", "bool"),
        ],
        "WSOutputBackend": [
            ("host",       "Bind Address", "0.0.0.0 = all interfaces", "str"),
            ("port",       "Port",        "WebSocket port",      "int"),
            ("format",     "Format",      "json / tcode / tcode_mfp", "str"),
            ("update_hz",  "Update Hz",   "1\u2013120 (default 60)",       "int"),
            ("dirty_only", "Dirty Only",  "Send only changed axes", "bool"),
        ],
    }

    _BACKEND_FIELD_DEFAULTS: Dict[str, Dict[str, Any]] = {
        "MK312Backend":       {"device": "/dev/cu.usbserial", "baudrate": 19200},
        "TCodeBackend":       {"device": "/dev/cu.usbserial", "baudrate": 115200},
        "DGLabSocketBackend": {"ws_url": "wss://ws.dungeon-lab.cn/",
                               "target_id": "", "v3": True},
        "DGLabBLEBackend":    {"address": "", "limit_a": 200, "limit_b": 200},
        "ButtplugBackend":    {"server": "ws://127.0.0.1:12345"},
        "PiShockSerialBackend": {"device": "/dev/cu.usbserial",
                                 "baudrate": 115200, "shocker_id": 0,
                                 "model": 1, "duration_ms": 1000},
        "OSSMBLEBackend":       {"address": "", "interval_ms": 16,
                                 "mode": "streaming", "use_fts": True},
        "WSOutputBackend":      {"host": "0.0.0.0", "port": 8082,
                                 "format": "json", "update_hz": 60,
                                 "dirty_only": True},
    }

    _BAUD_RATES = [
        "9600", "19200", "38400", "57600",
        "115200", "230400", "460800",
    ]

    # -- helpers for the config popup ----------------------------------

    def _populate_cfg_fields(self, backend_cls: str,
                              existing: Dict[str, Any]) -> None:
        """Fill ``_cfg_fields`` from *existing* params + schema defaults."""
        schema = self._BACKEND_PARAMS.get(backend_cls, [])
        defaults = self._BACKEND_FIELD_DEFAULTS.get(backend_cls, {})
        self._cfg_fields = {}
        for key, _lbl, _hint, _wt in schema:
            if key in existing:
                self._cfg_fields[key] = str(existing[key])
            elif key in defaults:
                self._cfg_fields[key] = str(defaults[key])
            else:
                self._cfg_fields[key] = ""

    def _get_serial_ports(self) -> List[str]:
        """Return cached list of serial ports (refreshes every 3 s)."""
        now = time.monotonic()
        if now - self._serial_ports_ts > 3.0:
            self._serial_ports_ts = now
            try:
                from serial.tools.list_ports import comports
                self._serial_ports = sorted(p.device for p in comports())
            except ImportError:
                self._serial_ports = []
        return self._serial_ports

    def _apply_device_cfg(self, device_mgr: "DeviceManager",
                           inst: DeviceInstance) -> None:
        """Convert popup fields to typed params and push to device_mgr."""
        alts = BACKEND_ALTERNATIVES.get(inst.model_id, [])
        current_cls = device_mgr.get_backend_class_name(self._cfg_dev_id)
        selected_cls = current_cls
        if alts and 0 <= self._cfg_backend_idx < len(alts):
            selected_cls = alts[self._cfg_backend_idx][1].__name__

        schema = self._BACKEND_PARAMS.get(selected_cls, [])
        params: Dict[str, Any] = {}
        for key, _lbl, _hint, wtype in schema:
            v = self._cfg_fields.get(key, "")
            if wtype == "bool":
                params[key] = v.lower() in ("true", "1", "yes")
            elif wtype in ("int", "baudrate"):
                try:
                    params[key] = int(v)
                except ValueError:
                    params[key] = v
            else:
                params[key] = v
        device_mgr.set_config(self._cfg_dev_id, params)

        # Swap backend class if the user picked a different alternative
        if alts and len(alts) > 1:
            new_cls = alts[self._cfg_backend_idx][1]
            if new_cls.__name__ != current_cls:
                device_mgr.swap_backend(inst, new_cls)

    # -- main draw -----------------------------------------------------

    def _draw_device_config_popup(self, routing: RoutingMatrix,
                                   device_mgr: "DeviceManager | None") -> None:
        if not device_mgr:
            return

        # Deferred open (avoids ID-scope mismatch from toolbar push_id)
        if self._cfg_open:
            self._cfg_open = False
            imgui.open_popup("Device Settings###dev_cfg_modal")

        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            ImVec2(vp.work_pos.x + vp.work_size.x * 0.5,
                   vp.work_pos.y + vp.work_size.y * 0.5),
            imgui.Cond_.appearing, ImVec2(0.5, 0.5))
        imgui.set_next_window_size(ImVec2(420, 0), imgui.Cond_.appearing)
        imgui.set_next_window_size_constraints(ImVec2(340, 0), ImVec2(480, 600))

        visible = imgui.begin_popup_modal(
            "Device Settings###dev_cfg_modal", None,
            imgui.WindowFlags_.none)[0]
        if not visible:
            return

        inst = routing.devices.get(self._cfg_dev_id)
        if not inst:
            imgui.text_disabled("Device not found.")
            if imgui.button("Close", ImVec2(80, 0)):
                imgui.close_current_popup()
            imgui.end_popup()
            return

        model = DEVICE_CATALOGUE.get(inst.model_id)
        model_label = model.label if model else inst.model_id
        model_desc = model.description if model else ""
        _FIELD_W = 260.0  # fixed widget width for all fields

        # -- Header ----------------------------------------------------
        imgui.text(inst.name)
        imgui.same_line(imgui.get_content_region_avail().x - 55)
        connected = device_mgr.is_connected(self._cfg_dev_id)
        if connected:
            imgui.text_colored(_COL_DEV_ONLINE, "Online")
        else:
            imgui.text_colored(_COL_DEV_OFFLINE, "Offline")
        imgui.text_disabled(f"{model_label}  \u2014  {model_desc}")
        imgui.separator()
        imgui.spacing()

        # -- Backend alternative combo ---------------------------------
        alts = BACKEND_ALTERNATIVES.get(inst.model_id)
        current_cls = device_mgr.get_backend_class_name(self._cfg_dev_id)
        if alts and len(alts) > 1:
            alt_labels = [lbl for lbl, _c in alts]
            imgui.text("Connection method:")
            imgui.set_next_item_width(_FIELD_W)
            changed, new_idx = imgui.combo(
                "##backend_alt", self._cfg_backend_idx, alt_labels)
            if changed and new_idx != self._cfg_backend_idx:
                self._cfg_backend_idx = new_idx
                new_cls_name = alts[new_idx][1].__name__
                existing = device_mgr.get_config(self._cfg_dev_id).params
                self._populate_cfg_fields(new_cls_name, existing)
            imgui.spacing()
            selected_cls = alts[self._cfg_backend_idx][1].__name__
        else:
            selected_cls = current_cls

        # -- Connection parameters -------------------------------------
        schema = self._BACKEND_PARAMS.get(selected_cls, [])
        if schema:
            for key, label, hint, wtype in schema:
                imgui.push_id(f"p_{key}")
                val = self._cfg_fields.get(key, "")

                if wtype == "port":
                    ports = self._get_serial_ports()
                    imgui.text(f"{label}:")
                    refresh_btn_w = 26.0
                    imgui.set_next_item_width(_FIELD_W - refresh_btn_w - 4)
                    items = list(ports)
                    if val and val not in items:
                        items.append(val)
                    idx = 0
                    for i, p in enumerate(items):
                        if p == val:
                            idx = i
                            break
                    if items:
                        ch, ni = imgui.combo("##v", idx, items)
                        if ch and 0 <= ni < len(items):
                            self._cfg_fields[key] = items[ni]
                    else:
                        ch, nv = imgui.input_text("##v", val, 256)
                        if ch:
                            self._cfg_fields[key] = nv
                    # Refresh button next to port combo
                    imgui.same_line()
                    if imgui.button("\u21bb##port_refresh", ImVec2(refresh_btn_w, 0)):
                        self._serial_ports_ts = 0.0  # force immediate rescan
                        self._get_serial_ports()
                    if imgui.is_item_hovered():
                        imgui.set_tooltip("Refresh port list")
                    if not ports:
                        imgui.text_disabled("(install pyserial for port list)")

                elif wtype == "baudrate":
                    imgui.text(f"{label}:")
                    imgui.set_next_item_width(_FIELD_W)
                    idx = -1
                    for i, b in enumerate(self._BAUD_RATES):
                        if b == val:
                            idx = i
                            break
                    if idx >= 0:
                        ch, ni = imgui.combo("##v", idx, self._BAUD_RATES)
                        if ch:
                            self._cfg_fields[key] = self._BAUD_RATES[ni]
                    else:
                        ch, nv = imgui.input_text("##v", val, 32)
                        if ch:
                            self._cfg_fields[key] = nv

                elif wtype == "bool":
                    is_on = val.lower() in ("true", "1", "yes")
                    ch, is_on = imgui.checkbox(label, is_on)
                    if ch:
                        self._cfg_fields[key] = str(is_on)

                elif wtype == "int":
                    imgui.text(f"{label}:")
                    imgui.set_next_item_width(120)
                    ch, nv = imgui.input_text("##v", val, 32)
                    if ch:
                        self._cfg_fields[key] = nv
                    if hint:
                        imgui.same_line()
                        imgui.text_disabled(hint)

                else:  # "str"
                    imgui.text(f"{label}:")
                    imgui.set_next_item_width(_FIELD_W)
                    ch, nv = imgui.input_text("##v", val, 512)
                    if ch:
                        self._cfg_fields[key] = nv
                    if hint:
                        imgui.text_disabled(hint)

                imgui.pop_id()

        # -- DG-Lab socket live info -----------------------------------
        if selected_cls == "DGLabSocketBackend" and connected:
            backend = device_mgr.get_backend(self._cfg_dev_id)
            if backend and hasattr(backend, "get_qr_url"):
                imgui.spacing()
                imgui.separator()
                imgui.spacing()
                qr = backend.get_qr_url()
                if qr:
                    imgui.text("DG-Lab APP bind URL:")
                    imgui.set_next_item_width(_FIELD_W)
                    imgui.input_text("##qr", qr, len(qr) + 1,
                                     imgui.InputTextFlags_.read_only)
                    imgui.text_disabled("Paste into browser or scan as QR")
                if hasattr(backend, "is_bound"):
                    if backend.is_bound:
                        imgui.text_colored(ImVec4(0.2, 0.85, 0.45, 1),
                                           "\u2713 Bound to DG-Lab APP")
                    else:
                        imgui.text_colored(ImVec4(1, 0.8, 0.2, 1),
                                           "\u23f3 Waiting for APP bind\u2026")

        # -- PiShock safety warning ------------------------------------
        if inst.model_id == "pishock":
            imgui.spacing()
            imgui.separator()
            imgui.spacing()
            imgui.text_colored(ImVec4(1.0, 0.5, 0.0, 1.0),
                               "\u26a0 SAFETY LIMITS:")
            imgui.text("  \u2022 Max intensity: 100")
            imgui.text("  \u2022 Min duration: 300 ms")
            imgui.text("  \u2022 Max command rate: 4 Hz (250 ms)")
            imgui.text("  \u2022 Deadman switch: Stop after 2 s silence")
            if selected_cls == "PiShockSerialBackend":
                imgui.text_disabled("Limits enforced in backend + firmware")
            else:
                imgui.text_disabled("WiFi bridge: limits enforced in ESP firmware")

        # -- OSSM BLE live info ----------------------------------------
        if selected_cls == "OSSMBLEBackend" and connected:
            backend = device_mgr.get_backend(self._cfg_dev_id)
            if backend and hasattr(backend, "state"):
                imgui.spacing()
                imgui.separator()
                imgui.spacing()
                state = backend.state
                # State with colour
                if "idle" in state:
                    imgui.text_colored(ImVec4(0.2, 0.85, 0.45, 1),
                                       f"\u25b6 {state}")
                elif "homing" in state:
                    imgui.text_colored(ImVec4(0.5, 0.7, 1.0, 1),
                                       f"\u2302 {state}")
                elif "error" in state:
                    imgui.text_colored(ImVec4(1.0, 0.3, 0.3, 1),
                                       f"\u26a0 {state}")
                elif "preflight" in state:
                    imgui.text_colored(ImVec4(0.9, 0.85, 0.3, 1),
                                       f"\u23f3 {state}")
                else:
                    imgui.text_disabled(f"State: {state}")
                # FTS binary indicator
                if hasattr(backend, "has_fts"):
                    if backend.has_fts:
                        imgui.text_disabled("\u2713 FTS binary protocol active")
                    else:
                        imgui.text_disabled("\u2717 FTS not available (using text stream)")
                # Firmware params
                if hasattr(backend, "firmware_params"):
                    fw = backend.firmware_params
                    if fw:
                        imgui.text_disabled(
                            f"FW: spd={fw.get('speed','-')}  "
                            f"str={fw.get('stroke','-')}  "
                            f"dep={fw.get('depth','-')}  "
                            f"sen={fw.get('sensation','-')}  "
                            f"pat={fw.get('pattern','-')}")
                if hasattr(backend, "position_mm"):
                    imgui.text_disabled(f"Position: {backend.position_mm:.1f} mm")

        # -- Error display ---------------------------------------------
        err = device_mgr.last_error(self._cfg_dev_id)
        if err:
            imgui.spacing()
            imgui.text_colored(ImVec4(1, 0.3, 0.3, 1), f"Error: {err}")

        # -- Buttons ---------------------------------------------------
        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        if imgui.button("Apply", ImVec2(90, 0)):
            self._apply_device_cfg(device_mgr, inst)
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Cancel", ImVec2(90, 0)):
            imgui.close_current_popup()

        # Connect / Disconnect on the right side
        imgui.same_line(imgui.get_content_region_avail().x - 100)
        if connected:
            if imgui.button("Disconnect", ImVec2(100, 0)):
                device_mgr.disconnect_device(self._cfg_dev_id)
        else:
            if imgui.button("Connect", ImVec2(100, 0)):
                self._apply_device_cfg(device_mgr, inst)
                ok = device_mgr.connect_device(self._cfg_dev_id)
                if not ok:
                    log.warning(f"Connect failed: "
                                f"{device_mgr.last_error(self._cfg_dev_id)}")

        imgui.end_popup()

    # ------------------------------------------------------------------
    # Channel tree popup
    # ------------------------------------------------------------------

    def _draw_channel_tree_popup(self, routing: RoutingMatrix,
                                  device_mgr: "DeviceManager | None") -> None:
        """Hierarchical tree popup for adding/removing device channels."""
        if self._ch_tree_open:
            self._ch_tree_open = False
            imgui.open_popup("##add_channel")
        if imgui.begin_popup("##add_channel"):
            inst = routing.devices.get(self._ch_tree_dev_id)
            if not inst:
                imgui.text_disabled("Device not found.")
                imgui.end_popup()
                return

            model = DEVICE_CATALOGUE.get(inst.model_id)
            if not model:
                imgui.text_disabled("Unknown model.")
                imgui.end_popup()
                return

            imgui.text(f"Channels: {inst.name}")
            imgui.separator()

            active_ch = set(routing.get_device_channels(self._ch_tree_dev_id))

            # If the model has a channel_tree, draw it hierarchically
            tree = model.channel_tree
            if tree:
                changed = self._draw_channel_tree_nodes(
                    tree, routing, self._ch_tree_dev_id, active_ch)
                if changed and device_mgr:
                    device_mgr.sync_with_routing(routing)
            else:
                # Fallback: flat list of all axes
                for ax in model.axes:
                    is_on = ax.name in active_ch
                    clicked, new_val = imgui.checkbox(
                        f"{ax.label}##ch_{ax.name}", is_on)
                    if clicked:
                        if new_val:
                            routing.add_device_channel(
                                self._ch_tree_dev_id, ax.name)
                        else:
                            routing.remove_device_channel(
                                self._ch_tree_dev_id, ax.name)
                        if device_mgr:
                            device_mgr.sync_with_routing(routing)

            imgui.end_popup()

    def _draw_channel_tree_nodes(
        self,
        nodes: List,
        routing: RoutingMatrix,
        dev_id: str,
        active_ch: set,
    ) -> bool:
        """Recursively draw channel tree nodes. Returns True if any change."""
        changed = False
        for node in nodes:
            label, axis_name, children = node[0], node[1], node[2]
            if children is not None:
                # Branch node -- draw as tree node
                if imgui.tree_node(f"{label}##ct"):
                    ch = self._draw_channel_tree_nodes(
                        children, routing, dev_id, active_ch)
                    if ch:
                        changed = True
                    imgui.tree_pop()
            elif axis_name:
                # Leaf node -- checkbox
                is_on = axis_name in active_ch
                clicked, new_val = imgui.checkbox(
                    f"{label}##ch_{axis_name}", is_on)
                if clicked:
                    if new_val:
                        routing.add_device_channel(dev_id, axis_name)
                        active_ch.add(axis_name)
                    else:
                        routing.remove_device_channel(dev_id, axis_name)
                        active_ch.discard(axis_name)
                    changed = True
        return changed

    # ------------------------------------------------------------------
    # OSC config popup (modal)
    # ------------------------------------------------------------------

    def _draw_osc_config_popup(self, device_mgr: "DeviceManager | None") -> None:
        if not device_mgr:
            return

        if self._osc_cfg_open:
            self._osc_cfg_open = False
            imgui.open_popup("OSC Settings###osc_cfg_modal")

        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            ImVec2(vp.work_pos.x + vp.work_size.x * 0.5,
                   vp.work_pos.y + vp.work_size.y * 0.5),
            imgui.Cond_.appearing, ImVec2(0.5, 0.5))
        imgui.set_next_window_size(ImVec2(380, 0), imgui.Cond_.appearing)
        imgui.set_next_window_size_constraints(ImVec2(300, 0), ImVec2(440, 400))

        visible = imgui.begin_popup_modal(
            "OSC Settings###osc_cfg_modal", None,
            imgui.WindowFlags_.none)[0]
        if not visible:
            return

        _FW = 240.0
        imgui.text("OSC Output")
        imgui.same_line(imgui.get_content_region_avail().x - 55)
        if device_mgr.osc_enabled:
            imgui.text_colored(_COL_DEV_ONLINE, "Active")
        else:
            imgui.text_colored(_COL_DEV_OFFLINE, "Inactive")
        imgui.separator()
        imgui.spacing()

        imgui.text("Host:")
        imgui.set_next_item_width(_FW)
        ch, v = imgui.input_text("##osc_host",
                                  self._osc_cfg_fields.get("host", "127.0.0.1"),
                                  128)
        if ch:
            self._osc_cfg_fields["host"] = v

        imgui.text("Port:")
        imgui.set_next_item_width(120)
        ch, v = imgui.input_text("##osc_port",
                                  self._osc_cfg_fields.get("port", "8001"), 16)
        if ch:
            self._osc_cfg_fields["port"] = v

        imgui.text("Address prefix:")
        imgui.set_next_item_width(_FW)
        ch, v = imgui.input_text("##osc_prefix",
                                  self._osc_cfg_fields.get("prefix", "/ofs"),
                                  128)
        if ch:
            self._osc_cfg_fields["prefix"] = v

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        if imgui.button("Apply##osc", ImVec2(90, 0)):
            try:
                port_val = int(self._osc_cfg_fields.get("port", "8001"))
            except ValueError:
                port_val = 8001
            device_mgr.osc_config.params.update({
                "host":   self._osc_cfg_fields.get("host", "127.0.0.1"),
                "port":   port_val,
                "prefix": self._osc_cfg_fields.get("prefix", "/ofs"),
            })
            if device_mgr.osc_enabled:
                device_mgr.disable_osc()
                device_mgr.enable_osc()
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Cancel##osc_c", ImVec2(90, 0)):
            imgui.close_current_popup()

        imgui.end_popup()

    # ------------------------------------------------------------------
    # WS Output config popup (modal)
    # ------------------------------------------------------------------

    _WS_FORMATS = ["json", "tcode", "tcode_mfp"]

    def _draw_ws_output_config_popup(self, device_mgr: "DeviceManager | None") -> None:
        if not device_mgr:
            return

        if self._ws_cfg_open:
            self._ws_cfg_open = False
            imgui.open_popup("WS Output Settings###ws_cfg_modal")

        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            ImVec2(vp.work_pos.x + vp.work_size.x * 0.5,
                   vp.work_pos.y + vp.work_size.y * 0.5),
            imgui.Cond_.appearing, ImVec2(0.5, 0.5))
        imgui.set_next_window_size(ImVec2(400, 0), imgui.Cond_.appearing)
        imgui.set_next_window_size_constraints(ImVec2(320, 0), ImVec2(460, 500))

        visible = imgui.begin_popup_modal(
            "WS Output Settings###ws_cfg_modal", None,
            imgui.WindowFlags_.none)[0]
        if not visible:
            return

        _FW = 240.0

        # -- Header ----------------------------------------------------
        imgui.text("WebSocket Output Server")
        imgui.same_line(imgui.get_content_region_avail().x - 55)
        if device_mgr.ws_output_enabled:
            imgui.text_colored(_COL_DEV_ONLINE, "Active")
        else:
            imgui.text_colored(_COL_DEV_OFFLINE, "Inactive")
        imgui.text_disabled("Broadcasts OFS WS axes to connected clients")
        imgui.separator()
        imgui.spacing()

        # -- Fields ----------------------------------------------------
        imgui.text("Bind Address:")
        imgui.set_next_item_width(_FW)
        ch, v = imgui.input_text("##ws_host",
                                  self._ws_cfg_fields.get("host", "0.0.0.0"),
                                  128)
        if ch:
            self._ws_cfg_fields["host"] = v
        imgui.text_disabled("0.0.0.0 = all interfaces")

        imgui.text("Port:")
        imgui.set_next_item_width(120)
        ch, v = imgui.input_text("##ws_port",
                                  self._ws_cfg_fields.get("port", "8082"), 16)
        if ch:
            self._ws_cfg_fields["port"] = v

        imgui.text("Format:")
        imgui.set_next_item_width(_FW)
        cur_fmt = self._ws_cfg_fields.get("format", "json")
        fmt_idx = 0
        for i, f in enumerate(self._WS_FORMATS):
            if f == cur_fmt:
                fmt_idx = i
                break
        ch_fmt, new_fmt_idx = imgui.combo("##ws_fmt", fmt_idx, self._WS_FORMATS)
        if ch_fmt:
            self._ws_cfg_fields["format"] = self._WS_FORMATS[new_fmt_idx]
        imgui.text_disabled("json = OFS native  /  tcode = TCode string  /  tcode_mfp = MultiFunPlayer")

        imgui.text("Update Hz:")
        imgui.set_next_item_width(120)
        ch, v = imgui.input_text("##ws_hz",
                                  self._ws_cfg_fields.get("update_hz", "60"), 16)
        if ch:
            self._ws_cfg_fields["update_hz"] = v
        imgui.same_line()
        imgui.text_disabled("1\u2013120")

        dirty_val = self._ws_cfg_fields.get("dirty_only", "True")
        is_dirty = dirty_val.lower() in ("true", "1", "yes")
        ch_d, is_dirty = imgui.checkbox("Dirty Only (send only changed axes)", is_dirty)
        if ch_d:
            self._ws_cfg_fields["dirty_only"] = str(is_dirty)

        # -- Client count ----------------------------------------------
        if device_mgr.ws_output_enabled:
            ws_be = device_mgr.ws_output_backend
            if ws_be:
                n_clients = getattr(ws_be, 'client_count', 0)
                imgui.spacing()
                imgui.text_disabled(
                    f"Connected clients: {n_clients}")

        # -- Buttons ---------------------------------------------------
        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        if imgui.button("Apply##ws", ImVec2(90, 0)):
            try:
                port_val = int(self._ws_cfg_fields.get("port", "8082"))
            except ValueError:
                port_val = 8082
            try:
                hz_val = int(self._ws_cfg_fields.get("update_hz", "60"))
            except ValueError:
                hz_val = 60
            dirty_str = self._ws_cfg_fields.get("dirty_only", "True")
            dirty_bool = dirty_str.lower() in ("true", "1", "yes")
            device_mgr.ws_output_config.params.update({
                "host":      self._ws_cfg_fields.get("host", "0.0.0.0"),
                "port":      port_val,
                "format":    self._ws_cfg_fields.get("format", "json"),
                "update_hz": hz_val,
                "dirty_only": dirty_bool,
            })
            # Restart if running
            if device_mgr.ws_output_enabled:
                device_mgr.disable_ws_output()
                device_mgr.enable_ws_output()
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Cancel##ws_c", ImVec2(90, 0)):
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
