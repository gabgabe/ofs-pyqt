"""
RoutingMatrix  --  zero-latency signal router.

Connects *input axes* (funscript tracks, incoming WebSocket axes) to
*output axes* (outgoing WS axes, device channels) through a sparse
connection matrix.  Computation runs **inside the existing frame loop**
(``Process()`` is called once per frame from ``_pre_new_frame`` in
app.py) so there is zero additional latency beyond the frame interval.

Architecture
============
::

    +- INPUTS ----------------------------+      +- OUTPUTS ----------------------+
    |                                     |      |                                |
    |  Funscript track -> current value  --+------+->  OFS WS axis (broadcast)     |
    |  WS input axis   -> live value     --+------+->  Custom WS output axis       |
    |                                     |      |  Device channel (serial/BLE)   |
    +-------------------------------------+      +--------------------------------+

The matrix is a dict of  ``(input_id, output_id) -> RouteLink``.
Each RouteLink carries an optional gain/invert/offset so users can
scale or remap the signal per-connection.

``Process(time_s)`` iterates *connected outputs only* (sparse), reads
the input value, applies the link transform, and writes to the output
value cache.  This cache is then consumed by the output backends
(WS broadcaster, serial writer, etc.) with no extra copy.

Thread safety: Process() runs on the main thread (imgui frame tick).
Output backends that need to ship data to a background I/O thread
should snapshot the output cache once per frame.

Persistence
===========
``to_dict()`` / ``from_dict()`` serialise the full routing state so it
can be stored in the ``.ofsp`` project file or a standalone JSON.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.core.devices import (
    AxisDef,
    AxisKind,
    DeviceModel,
    OFS_WS_OUTPUT_AXES,
    DEVICE_CATALOGUE,
    list_device_models,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / Output node descriptors
# ---------------------------------------------------------------------------

class NodeKind(Enum):
    """Discriminator for input/output nodes."""
    FUNSCRIPT_TRACK = auto()   # bound to a timeline funscript track
    WS_INPUT        = auto()   # incoming WebSocket axis (external controller)
    OFS_WS_OUTPUT   = auto()   # standard OFS WS broadcast axis
    WS_OUTPUT       = auto()   # custom WS output instance axis
    DEVICE_CHANNEL  = auto()   # physical device axis


@dataclass
class RouteNode:
    """A single input or output endpoint in the routing matrix."""
    id: str                         # unique, generated
    kind: NodeKind
    label: str = ""                 # human-readable name shown in the matrix
    axis_name: str = ""             # e.g. "stroke", "channel_a"
    group: str = ""                 # grouping key (device instance id, ws instance name...)
    # For FUNSCRIPT_TRACK inputs: which timeline track feeds this node
    track_id: str = ""              # timeline Track.id
    # For DEVICE_CHANNEL outputs: which device model
    device_model_id: str = ""
    device_instance_id: str = ""    # user-created device instance

    # Runtime value (written by Process, read by output backends)
    value: float = 0.0              # 0-100

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.name,
            "label": self.label,
            "axis_name": self.axis_name,
            "group": self.group,
            "track_id": self.track_id,
            "device_model_id": self.device_model_id,
            "device_instance_id": self.device_instance_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RouteNode":
        return cls(
            id=d.get("id", str(uuid.uuid4().hex[:12])),
            kind=NodeKind[d.get("kind", "FUNSCRIPT_TRACK")],
            label=d.get("label", ""),
            axis_name=d.get("axis_name", ""),
            group=d.get("group", ""),
            track_id=d.get("track_id", ""),
            device_model_id=d.get("device_model_id", ""),
            device_instance_id=d.get("device_instance_id", ""),
        )


# ---------------------------------------------------------------------------
# Route link (a single connection in the matrix)
# ---------------------------------------------------------------------------

@dataclass
class RouteLink:
    """Transform applied on a single input->output connection."""
    enabled: bool = True
    gain: float = 1.0        # multiplier (1.0 = passthrough)
    offset: float = 0.0      # added after gain  (in 0-100 space)
    invert: bool = False      # flip: value = 100 - value
    # Output range mapping (default 0-100 = full range)
    out_min: float = 0.0      # floor of output range  (0-100 space)
    out_max: float = 100.0    # ceiling of output range (0-100 space)

    def apply(self, v: float) -> float:
        if self.invert:
            v = 100.0 - v
        v = v * self.gain + self.offset
        v = max(0.0, min(100.0, v))
        # Map 0-100 -> out_min..out_max
        if self.out_min != 0.0 or self.out_max != 100.0:
            v = self.out_min + (v / 100.0) * (self.out_max - self.out_min)
            v = max(0.0, min(100.0, v))
        return v

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "gain": self.gain,
            "offset": self.offset,
            "invert": self.invert,
            "out_min": self.out_min,
            "out_max": self.out_max,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RouteLink":
        return cls(
            enabled=d.get("enabled", True),
            gain=float(d.get("gain", 1.0)),
            offset=float(d.get("offset", 0.0)),
            invert=bool(d.get("invert", False)),
            out_min=float(d.get("out_min", 0.0)),
            out_max=float(d.get("out_max", 100.0)),
        )


# ---------------------------------------------------------------------------
# WebSocket input instance (external controller sending data in)
# ---------------------------------------------------------------------------

@dataclass
class WSInputInstance:
    """A custom WebSocket input source (an external controller).

    Each instance can carry multiple axes  --  e.g. a multi-axis
    controller sending ``{"axes": {"stroke": 50, "twist": 30}}``.
    Axes are created dynamically when the first message arrives or
    when the user pre-configures them in the UI.
    """
    id: str                                # unique instance id
    name: str = "WS Input"                 # user-visible name
    axes: Dict[str, float] = field(default_factory=dict)   # axis_name -> latest value

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "axes": list(self.axes.keys())}

    @classmethod
    def from_dict(cls, d: dict) -> "WSInputInstance":
        inst = cls(id=d.get("id", ""), name=d.get("name", "WS Input"))
        for ax in d.get("axes", []):
            inst.axes[ax] = 0.0
        return inst


# ---------------------------------------------------------------------------
# WebSocket output instance
# ---------------------------------------------------------------------------

@dataclass
class WSOutputInstance:
    """A custom WebSocket output target.

    Carries its own set of named axes that are broadcast to connected
    WS clients under a specific namespace / topic.
    """
    id: str
    name: str = "WS Output"
    axes: List[str] = field(default_factory=list)    # axis names

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "axes": self.axes}

    @classmethod
    def from_dict(cls, d: dict) -> "WSOutputInstance":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", "WS Output"),
            axes=d.get("axes", []),
        )


# ---------------------------------------------------------------------------
# Device instance (a physical device the user has added)
# ---------------------------------------------------------------------------

@dataclass
class DeviceInstance:
    """A user-instantiated output device."""
    id: str
    model_id: str                    # key into DEVICE_CATALOGUE
    name: str = ""                   # user label, defaults to model label

    def to_dict(self) -> dict:
        return {"id": self.id, "model_id": self.model_id, "name": self.name}

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceInstance":
        return cls(
            id=d.get("id", ""),
            model_id=d.get("model_id", ""),
            name=d.get("name", ""),
        )


# ---------------------------------------------------------------------------
# RoutingMatrix  --  the engine
# ---------------------------------------------------------------------------

class RoutingMatrix:
    """
    Sparse input->output signal routing engine.

    **Where is routing computed?**
    ``Process(time_s)`` is called once per frame from ``_pre_new_frame()``
    in ``app.py``, right after ``TimelineManager.Tick()`` and before
    ``EV.process()``.  This means:

    1. Transport position is already up-to-date.
    2. Funscript interpolation reads the correct frame's value.
    3. Output values are ready before any UI draws or WS broadcasts.

    Since the work is O(connected_links) with no allocations on the hot
    path, it adds negligible time to the frame tick.
    """

    def __init__(self) -> None:
        # Node registries  (id -> RouteNode)
        self.inputs:  Dict[str, RouteNode] = {}
        self.outputs: Dict[str, RouteNode] = {}

        # Connection matrix  (input_id, output_id) -> RouteLink
        self.links: Dict[Tuple[str, str], RouteLink] = {}

        # Instance registries
        self.ws_inputs:  Dict[str, WSInputInstance]  = {}
        self.ws_outputs: Dict[str, WSOutputInstance] = {}
        self.devices:    Dict[str, DeviceInstance]    = {}

        # Callbacks  --  the app wires these so Process() can read live values
        self._get_funscript_value: Optional[Callable[[str, float], float]] = None
        # track_id, time_s -> 0-100

        # Output value snapshot (output_id -> value)  --  consumed by backends
        self.output_values: Dict[str, float] = {}

        # Ordered lists for UI (rebuilt when nodes change)
        self._input_order:  List[str] = []
        self._output_order: List[str] = []
        self._dirty = True

    # ------------------------------------------------------------------
    # Wiring callbacks (called once from app._post_init)
    # ------------------------------------------------------------------

    def SetFunscriptValueGetter(self, fn: Callable[[str, float], float]) -> None:
        """Register ``fn(track_id, time_s) -> 0-100`` for reading funscript data."""
        self._get_funscript_value = fn

    # ------------------------------------------------------------------
    # Node management  --  inputs
    # ------------------------------------------------------------------

    def add_funscript_input(self, track_id: str, label: str) -> RouteNode:
        """Register a funscript track as a routing input."""
        node = RouteNode(
            id=f"fs_{track_id}",
            kind=NodeKind.FUNSCRIPT_TRACK,
            label=label,
            axis_name=label,
            group="Funscript Tracks",
            track_id=track_id,
        )
        self.inputs[node.id] = node
        self._dirty = True
        return node

    def remove_funscript_input(self, track_id: str) -> None:
        nid = f"fs_{track_id}"
        if nid in self.inputs:
            del self.inputs[nid]
            self._remove_links_for(nid)
            self._dirty = True

    def add_ws_input_instance(self, name: str = "WS Input",
                              axes: List[str] | None = None) -> WSInputInstance:
        """Create a new WebSocket input instance with optional pre-defined axes."""
        inst = WSInputInstance(id=uuid.uuid4().hex[:12], name=name)
        if axes:
            for ax in axes:
                inst.axes[ax] = 0.0
        self.ws_inputs[inst.id] = inst
        # Create RouteNode per axis
        for ax in inst.axes:
            node = RouteNode(
                id=f"wsi_{inst.id}_{ax}",
                kind=NodeKind.WS_INPUT,
                label=f"{name} / {ax}",
                axis_name=ax,
                group=f"WS: {name}",
            )
            self.inputs[node.id] = node
        self._dirty = True
        return inst

    def add_ws_input_axis(self, instance_id: str, axis_name: str) -> Optional[RouteNode]:
        """Dynamically add an axis to an existing WS input instance."""
        inst = self.ws_inputs.get(instance_id)
        if not inst:
            return None
        if axis_name in inst.axes:
            return self.inputs.get(f"wsi_{inst.id}_{axis_name}")
        inst.axes[axis_name] = 0.0
        node = RouteNode(
            id=f"wsi_{inst.id}_{axis_name}",
            kind=NodeKind.WS_INPUT,
            label=f"{inst.name} / {axis_name}",
            axis_name=axis_name,
            group=f"WS: {inst.name}",
        )
        self.inputs[node.id] = node
        self._dirty = True
        return node

    def remove_ws_input_instance(self, instance_id: str) -> None:
        inst = self.ws_inputs.pop(instance_id, None)
        if not inst:
            return
        for ax in list(inst.axes.keys()):
            nid = f"wsi_{inst.id}_{ax}"
            self.inputs.pop(nid, None)
            self._remove_links_for(nid)
        self._dirty = True

    def feed_ws_input(self, instance_id: str, axis_name: str, value: float) -> None:
        """Feed a live value from an external WS controller. Thread-safe (atomic float write)."""
        inst = self.ws_inputs.get(instance_id)
        if inst:
            inst.axes[axis_name] = max(0.0, min(100.0, value))

    # ------------------------------------------------------------------
    # Node management  --  outputs
    # ------------------------------------------------------------------

    def rebuild_ofs_ws_outputs(self) -> None:
        """(Re)create the standard OFS WS output nodes."""
        for ax in OFS_WS_OUTPUT_AXES:
            nid = f"ofs_ws_{ax.name}"
            if nid not in self.outputs:
                self.outputs[nid] = RouteNode(
                    id=nid,
                    kind=NodeKind.OFS_WS_OUTPUT,
                    label=ax.label,
                    axis_name=ax.name,
                    group="OFS WS Output",
                )
        self._dirty = True

    def add_ws_output_instance(self, name: str = "WS Output",
                               axes: List[str] | None = None) -> WSOutputInstance:
        """Create a custom WS output group."""
        inst = WSOutputInstance(id=uuid.uuid4().hex[:12], name=name,
                                axes=axes or [])
        self.ws_outputs[inst.id] = inst
        for ax in inst.axes:
            nid = f"wso_{inst.id}_{ax}"
            self.outputs[nid] = RouteNode(
                id=nid,
                kind=NodeKind.WS_OUTPUT,
                label=f"{name} / {ax}",
                axis_name=ax,
                group=f"WS Out: {name}",
            )
        self._dirty = True
        return inst

    def add_ws_output_axis(self, instance_id: str, axis_name: str) -> Optional[RouteNode]:
        inst = self.ws_outputs.get(instance_id)
        if not inst:
            return None
        if axis_name in inst.axes:
            return self.outputs.get(f"wso_{inst.id}_{axis_name}")
        inst.axes.append(axis_name)
        nid = f"wso_{inst.id}_{axis_name}"
        node = RouteNode(
            id=nid,
            kind=NodeKind.WS_OUTPUT,
            label=f"{inst.name} / {axis_name}",
            axis_name=axis_name,
            group=f"WS Out: {inst.name}",
        )
        self.outputs[nid] = node
        self._dirty = True
        return node

    def remove_ws_output_instance(self, instance_id: str) -> None:
        inst = self.ws_outputs.pop(instance_id, None)
        if not inst:
            return
        for ax in inst.axes:
            nid = f"wso_{inst.id}_{ax}"
            self.outputs.pop(nid, None)
            self._remove_links_for(nid, is_output=True)
        self._dirty = True

    def add_device_instance(self, model_id: str,
                            name: str = "",
                            axes: List[str] | None = None) -> Optional[DeviceInstance]:
        """Instantiate a device from the catalogue.

        If *axes* is ``None`` the device is created with **no** output
        nodes -- the user adds channels individually via the tree menu.
        Pass a list of axis names to pre-populate specific channels.
        """
        model = DEVICE_CATALOGUE.get(model_id)
        if not model:
            log.warning(f"Unknown device model: {model_id}")
            return None
        inst = DeviceInstance(
            id=uuid.uuid4().hex[:12],
            model_id=model_id,
            name=name or model.label,
        )
        self.devices[inst.id] = inst
        if axes:
            ax_map = {a.name: a for a in model.axes}
            for ax_name in axes:
                ax = ax_map.get(ax_name)
                if ax:
                    nid = f"dev_{inst.id}_{ax.name}"
                    self.outputs[nid] = RouteNode(
                        id=nid,
                        kind=NodeKind.DEVICE_CHANNEL,
                        label=f"{inst.name} / {ax.label}",
                        axis_name=ax.name,
                        group=f"Dev: {inst.name}",
                        device_model_id=model_id,
                        device_instance_id=inst.id,
                    )
        self._dirty = True
        return inst

    def add_device_channel(self, instance_id: str, axis_name: str) -> Optional[RouteNode]:
        """Add a single output channel to an existing device instance."""
        inst = self.devices.get(instance_id)
        if not inst:
            return None
        model = DEVICE_CATALOGUE.get(inst.model_id)
        if not model:
            return None
        ax = None
        for a in model.axes:
            if a.name == axis_name:
                ax = a
                break
        if not ax:
            return None
        nid = f"dev_{inst.id}_{ax.name}"
        if nid in self.outputs:
            return self.outputs[nid]  # already present
        node = RouteNode(
            id=nid,
            kind=NodeKind.DEVICE_CHANNEL,
            label=f"{inst.name} / {ax.label}",
            axis_name=ax.name,
            group=f"Dev: {inst.name}",
            device_model_id=inst.model_id,
            device_instance_id=inst.id,
        )
        self.outputs[nid] = node
        self._dirty = True
        return node

    def remove_device_channel(self, instance_id: str, axis_name: str) -> None:
        """Remove a single output channel from a device instance."""
        nid = f"dev_{instance_id}_{axis_name}"
        self.outputs.pop(nid, None)
        self._remove_links_for(nid, is_output=True)
        self._dirty = True

    def get_device_channels(self, instance_id: str) -> List[str]:
        """Return axis names currently exposed for a device instance."""
        prefix = f"dev_{instance_id}_"
        return [
            n.axis_name for n in self.outputs.values()
            if n.id.startswith(prefix) and n.kind == NodeKind.DEVICE_CHANNEL
        ]

    def remove_device_instance(self, instance_id: str) -> None:
        inst = self.devices.pop(instance_id, None)
        if not inst:
            return
        # Remove all output nodes belonging to this instance
        prefix = f"dev_{instance_id}_"
        to_del = [nid for nid in self.outputs if nid.startswith(prefix)]
        for nid in to_del:
            self.outputs.pop(nid, None)
            self._remove_links_for(nid, is_output=True)
        self._dirty = True

    # ------------------------------------------------------------------
    # Link management
    # ------------------------------------------------------------------

    def _clear_other_inputs(self, input_id: str, output_id: str) -> None:
        """Interlock: remove every link that drives *output_id* from a different input."""
        to_remove = [
            k for k in self.links
            if k[1] == output_id and k[0] != input_id
        ]
        for k in to_remove:
            del self.links[k]

    def set_link(self, input_id: str, output_id: str,
                 enabled: bool = True, **kwargs) -> RouteLink:
        """Create or update a connection between input and output.

        Interlock: each output can only be driven by ONE input.
        Setting a new link automatically removes any other link to the
        same output.
        """
        if enabled:
            self._clear_other_inputs(input_id, output_id)
        key = (input_id, output_id)
        if key in self.links:
            link = self.links[key]
            link.enabled = enabled
            for k, v in kwargs.items():
                if hasattr(link, k):
                    setattr(link, k, v)
        else:
            link = RouteLink(enabled=enabled, **kwargs)
            self.links[key] = link
        return link

    def remove_link(self, input_id: str, output_id: str) -> None:
        self.links.pop((input_id, output_id), None)

    def toggle_link(self, input_id: str, output_id: str) -> bool:
        """Toggle a connection. Returns new state (True=connected).

        Interlock: enabling a link clears all other inputs to this output.
        """
        key = (input_id, output_id)
        if key in self.links:
            lnk = self.links[key]
            lnk.enabled = not lnk.enabled
            if lnk.enabled:
                self._clear_other_inputs(input_id, output_id)
            return lnk.enabled
        else:
            self._clear_other_inputs(input_id, output_id)
            self.links[key] = RouteLink(enabled=True)
            return True

    def is_linked(self, input_id: str, output_id: str) -> bool:
        lnk = self.links.get((input_id, output_id))
        return lnk is not None and lnk.enabled

    def get_link(self, input_id: str, output_id: str) -> Optional[RouteLink]:
        return self.links.get((input_id, output_id))

    # ------------------------------------------------------------------
    # Processing (called once per frame  --  zero allocation hot path)
    # ------------------------------------------------------------------

    def Process(self, time_s: float) -> None:
        """Evaluate all active links and update output values.

        Called from ``_pre_new_frame()`` after the transport is ticked
        so that ``time_s`` is the accurate playback position.

        Complexity: O(active_links).  No allocations on the hot path
        (dict lookups + float math only).
        """
        # Clear output accumulators
        out_vals = self.output_values
        out_vals.clear()

        for (inp_id, out_id), link in self.links.items():
            if not link.enabled:
                continue

            inp = self.inputs.get(inp_id)
            out = self.outputs.get(out_id)
            if not inp or not out:
                continue

            # Read input value
            raw: float
            if inp.kind == NodeKind.FUNSCRIPT_TRACK:
                if self._get_funscript_value:
                    raw = self._get_funscript_value(inp.track_id, time_s)
                else:
                    raw = 0.0
            elif inp.kind == NodeKind.WS_INPUT:
                # Parse instance_id from node id: "wsi_{inst_id}_{axis}"
                parts = inp.id.split("_", 2)
                if len(parts) >= 3:
                    inst = self.ws_inputs.get(parts[1])
                    raw = inst.axes.get(inp.axis_name, 0.0) if inst else 0.0
                else:
                    raw = 0.0
            else:
                raw = 0.0

            # Update input node value (for UI live display)
            inp.value = raw

            # Apply link transform
            val = link.apply(raw)

            # Accumulate (max-wins for multiple inputs to same output)
            prev = out_vals.get(out_id, 0.0)
            out_vals[out_id] = max(prev, val)

            # Also write the output node's .value for convenience
            out.value = out_vals[out_id]

    # ------------------------------------------------------------------
    # Ordered lists for UI
    # ------------------------------------------------------------------

    def get_input_order(self) -> List[str]:
        """Return input node IDs in display order (grouped)."""
        if self._dirty:
            self._rebuild_order()
        return self._input_order

    def get_output_order(self) -> List[str]:
        """Return output node IDs in display order (grouped)."""
        if self._dirty:
            self._rebuild_order()
        return self._output_order

    def _rebuild_order(self) -> None:
        """Sort nodes: funscript tracks first, then WS inputs by group."""
        # Inputs: funscript tracks first, then WS inputs grouped by instance
        fs = [n for n in self.inputs.values() if n.kind == NodeKind.FUNSCRIPT_TRACK]
        ws = [n for n in self.inputs.values() if n.kind == NodeKind.WS_INPUT]
        fs.sort(key=lambda n: n.label)
        ws.sort(key=lambda n: (n.group, n.axis_name))
        self._input_order = [n.id for n in fs] + [n.id for n in ws]

        # Outputs: OFS WS -> custom WS -> devices
        ofs_ws = [n for n in self.outputs.values() if n.kind == NodeKind.OFS_WS_OUTPUT]
        cust_ws = [n for n in self.outputs.values() if n.kind == NodeKind.WS_OUTPUT]
        devs = [n for n in self.outputs.values() if n.kind == NodeKind.DEVICE_CHANNEL]
        ofs_ws.sort(key=lambda n: n.axis_name)
        cust_ws.sort(key=lambda n: (n.group, n.axis_name))
        devs.sort(key=lambda n: (n.group, n.axis_name))
        self._output_order = ([n.id for n in ofs_ws]
                              + [n.id for n in cust_ws]
                              + [n.id for n in devs])
        self._dirty = False

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        links_list = []
        for (i, o), lnk in self.links.items():
            d = lnk.to_dict()
            d["input_id"] = i
            d["output_id"] = o
            links_list.append(d)

        # Save per-device which channels are exposed
        dev_list = []
        for inst in self.devices.values():
            dd = inst.to_dict()
            dd["channels"] = self.get_device_channels(inst.id)
            dev_list.append(dd)

        return {
            "ws_inputs":  [inst.to_dict() for inst in self.ws_inputs.values()],
            "ws_outputs": [inst.to_dict() for inst in self.ws_outputs.values()],
            "devices":    dev_list,
            "links":      links_list,
        }

    def from_dict(self, d: dict) -> None:
        """Restore routing state from serialized dict. Existing nodes are kept."""
        # WS inputs
        for wd in d.get("ws_inputs", []):
            inst = WSInputInstance.from_dict(wd)
            if inst.id not in self.ws_inputs:
                self.ws_inputs[inst.id] = inst
                for ax in inst.axes:
                    nid = f"wsi_{inst.id}_{ax}"
                    if nid not in self.inputs:
                        self.inputs[nid] = RouteNode(
                            id=nid, kind=NodeKind.WS_INPUT,
                            label=f"{inst.name} / {ax}",
                            axis_name=ax, group=f"WS: {inst.name}",
                        )

        # WS outputs
        for wd in d.get("ws_outputs", []):
            inst = WSOutputInstance.from_dict(wd)
            if inst.id not in self.ws_outputs:
                self.ws_outputs[inst.id] = inst
                for ax in inst.axes:
                    nid = f"wso_{inst.id}_{ax}"
                    if nid not in self.outputs:
                        self.outputs[nid] = RouteNode(
                            id=nid, kind=NodeKind.WS_OUTPUT,
                            label=f"{inst.name} / {ax}",
                            axis_name=ax, group=f"WS Out: {inst.name}",
                        )

        # Devices -- restore only the channels that were saved
        for dd in d.get("devices", []):
            inst = DeviceInstance.from_dict(dd)
            channels = dd.get("channels", [])
            if inst.id not in self.devices:
                self.add_device_instance(
                    inst.model_id, inst.name,
                    axes=channels if channels else None)

        # Links
        for ld in d.get("links", []):
            inp_id = ld.get("input_id", "")
            out_id = ld.get("output_id", "")
            if inp_id and out_id:
                self.links[(inp_id, out_id)] = RouteLink.from_dict(ld)

        self._dirty = True

    # ------------------------------------------------------------------
    # Sync helpers (called when project tracks change)
    # ------------------------------------------------------------------

    def sync_funscript_tracks(self, tracks: List[Tuple[str, str]]) -> None:
        """Synchronise funscript input nodes with current project tracks.

        *tracks*: list of ``(track_id, label)`` tuples from the timeline.
        Removes stale inputs, adds new ones.
        """
        current_ids = {f"fs_{tid}" for tid, _ in tracks}
        # Remove stale
        stale = [nid for nid in list(self.inputs.keys())
                 if nid.startswith("fs_") and nid not in current_ids]
        for nid in stale:
            del self.inputs[nid]
            self._remove_links_for(nid)
        # Add new
        for tid, label in tracks:
            nid = f"fs_{tid}"
            if nid not in self.inputs:
                self.add_funscript_input(tid, label)
        self._dirty = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _remove_links_for(self, node_id: str, is_output: bool = False) -> None:
        """Remove all links referencing *node_id*."""
        to_remove = []
        for key in self.links:
            if is_output and key[1] == node_id:
                to_remove.append(key)
            elif not is_output and key[0] == node_id:
                to_remove.append(key)
        for k in to_remove:
            del self.links[k]
