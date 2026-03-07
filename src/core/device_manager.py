"""
DeviceManager  --  lifecycle orchestrator for output device backends.

Sits between the RoutingMatrix and the physical backends.  Each frame,
after ``RoutingMatrix.Process()`` has populated ``output_values``, the
app calls ``DeviceManager.Dispatch()`` which groups those values by
device instance and pushes them to the appropriate backend thread.

Also manages:
- OSC output backend (singleton, non-device)
- WS output backends (one per WSOutputInstance)
- Device connect / disconnect lifecycle
- Per-instance connection parameters (serial port, WS URL, etc.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.backends import (
    DeviceBackend,
    MK312Backend,
    TCodeBackend,
    DGLabSocketBackend,
    DGLabBLEBackend,
    ButtplugBackend,
    OSCOutputBackend,
    WSOutputBackend,
    create_backend,
    BACKEND_ALTERNATIVES,
)
from src.core.routing_matrix import (
    DeviceInstance,
    NodeKind,
    RoutingMatrix,
    WSOutputInstance,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection config (persisted per instance)
# ---------------------------------------------------------------------------

@dataclass
class ConnectionConfig:
    """User-editable connection parameters for a backend."""
    params: Dict[str, Any] = field(default_factory=dict)
    # e.g. {"device": "/dev/cu.usbserial", "baudrate": 19200}
    #      {"ws_url": "wss://ws.dungeon-lab.cn/", "target_id": "abc123"}
    #      {"host": "127.0.0.1", "port": 8001, "prefix": "/ofs"}

    def to_dict(self) -> dict:
        return dict(self.params)

    @classmethod
    def from_dict(cls, d: dict) -> "ConnectionConfig":
        return cls(params=dict(d))


# Default params per model
_DEFAULT_PARAMS: Dict[str, Dict[str, Any]] = {
    "mk312bt":        {"device": "/dev/cu.usbserial", "baudrate": 19200},
    "et312b":         {"device": "/dev/cu.usbserial", "baudrate": 19200},
    "2b":             {"device": "/dev/cu.usbserial", "baudrate": 19200},
    "osr_sr6":        {"device": "/dev/cu.usbserial", "baudrate": 115200},
    "dg_lab_coyote":  {"ws_url": "wss://ws.dungeon-lab.cn/", "target_id": "", "v3": False},
    "dg_lab_coyote3": {"ws_url": "wss://ws.dungeon-lab.cn/", "target_id": "", "v3": True},
    "buttplug_generic": {"server": "ws://127.0.0.1:12345"},
}


class DeviceManager:
    """Manages all output device backends and dispatches routed values."""

    def __init__(self) -> None:
        # device instance id -> backend
        self._backends: Dict[str, DeviceBackend] = {}
        # device instance id -> connection config
        self._configs: Dict[str, ConnectionConfig] = {}

        # Non-device backends
        self._osc: Optional[OSCOutputBackend] = None
        self._ws_outs: Dict[str, WSOutputBackend] = {}  # ws output instance id -> backend

        # Global OSC config
        self._osc_config = ConnectionConfig(params={
            "host": "127.0.0.1", "port": 8001, "prefix": "/ofs"
        })
        self._osc_enabled = False

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    def register_device(self, inst: DeviceInstance) -> None:
        """Register a device instance (create backend + default config)."""
        if inst.id in self._backends:
            return
        backend = create_backend(inst.id, inst.model_id, inst.name)
        if backend:
            self._backends[inst.id] = backend
            if inst.id not in self._configs:
                defaults = _DEFAULT_PARAMS.get(inst.model_id, {})
                self._configs[inst.id] = ConnectionConfig(params=dict(defaults))
            log.info(f"[DeviceManager] registered {inst.name} ({inst.model_id})")

    def unregister_device(self, instance_id: str) -> None:
        """Disconnect and remove a device backend."""
        backend = self._backends.pop(instance_id, None)
        if backend:
            if backend.is_connected:
                backend.disconnect()
            log.info(f"[DeviceManager] unregistered {backend.name}")
        self._configs.pop(instance_id, None)

    def connect_device(self, instance_id: str) -> bool:
        """Connect a registered device using its stored config."""
        backend = self._backends.get(instance_id)
        if not backend:
            log.warning(f"[DeviceManager] no backend for {instance_id}")
            return False
        if backend.is_connected:
            log.info(f"[DeviceManager] {backend.name} already connected")
            return True
        cfg = self._configs.get(instance_id, ConnectionConfig())
        log.info(f"[DeviceManager] connecting {backend.name} "
                 f"({type(backend).__name__}) with params: {cfg.params}")
        ok = backend.connect(**cfg.params)
        if ok:
            log.info(f"[DeviceManager] {backend.name} connected OK")
        else:
            log.warning(f"[DeviceManager] {backend.name} connect FAILED: "
                        f"{backend.last_error}")
        return ok

    def disconnect_device(self, instance_id: str) -> None:
        """Disconnect a device without unregistering it."""
        backend = self._backends.get(instance_id)
        if backend and backend.is_connected:
            backend.disconnect()

    def is_connected(self, instance_id: str) -> bool:
        backend = self._backends.get(instance_id)
        return backend.is_connected if backend else False

    def last_error(self, instance_id: str) -> str:
        backend = self._backends.get(instance_id)
        return backend.last_error if backend else ""

    def get_config(self, instance_id: str) -> ConnectionConfig:
        return self._configs.get(instance_id, ConnectionConfig())

    def set_config(self, instance_id: str, params: Dict[str, Any]) -> None:
        if instance_id not in self._configs:
            self._configs[instance_id] = ConnectionConfig()
        self._configs[instance_id].params.update(params)

    def get_backend(self, instance_id: str) -> Optional[DeviceBackend]:
        return self._backends.get(instance_id)

    def get_backend_class_name(self, instance_id: str) -> str:
        """Return the class name of the current backend (e.g. 'DGLabSocketBackend')."""
        backend = self._backends.get(instance_id)
        return type(backend).__name__ if backend else ""

    def swap_backend(self, inst: DeviceInstance, backend_class: type) -> None:
        """Replace the backend for a device instance with a different class.

        Disconnects the old backend first.  Config is preserved.
        """
        old = self._backends.get(inst.id)
        if old:
            if old.is_connected:
                old.disconnect()
            # Already the same class? Nothing to do.
            if type(old) is backend_class:
                return
        new_backend = backend_class(inst.id, inst.model_id, inst.name)
        self._backends[inst.id] = new_backend
        log.info(f"[DeviceManager] swapped backend for {inst.name} -> "
                 f"{backend_class.__name__}")

    # ------------------------------------------------------------------
    # OSC lifecycle
    # ------------------------------------------------------------------

    def enable_osc(self) -> bool:
        if self._osc and self._osc.is_connected:
            return True
        self._osc = OSCOutputBackend("osc_singleton", "osc_output", "OSC Output")
        ok = self._osc.connect(**self._osc_config.params)
        self._osc_enabled = ok
        return ok

    def disable_osc(self) -> None:
        if self._osc:
            self._osc.disconnect()
        self._osc = None
        self._osc_enabled = False

    @property
    def osc_enabled(self) -> bool:
        return self._osc_enabled and self._osc is not None and self._osc.is_connected

    @property
    def osc_config(self) -> ConnectionConfig:
        return self._osc_config

    # ------------------------------------------------------------------
    # WS Output lifecycle
    # ------------------------------------------------------------------

    def register_ws_output(self, inst: WSOutputInstance) -> None:
        if inst.id in self._ws_outs:
            return
        backend = WSOutputBackend(inst.id, "ws_output", inst.name)
        self._ws_outs[inst.id] = backend

    def unregister_ws_output(self, instance_id: str) -> None:
        backend = self._ws_outs.pop(instance_id, None)
        if backend and backend.is_connected:
            backend.disconnect()

    def connect_ws_output(self, instance_id: str,
                          host: str = "localhost", port: int = 8082,
                          format: str = "json") -> bool:
        backend = self._ws_outs.get(instance_id)
        if not backend:
            return False
        return backend.connect(host=host, port=port, format=format)

    def disconnect_ws_output(self, instance_id: str) -> None:
        backend = self._ws_outs.get(instance_id)
        if backend and backend.is_connected:
            backend.disconnect()

    # ------------------------------------------------------------------
    # Frame dispatch (called once per frame after RoutingMatrix.Process)
    # ------------------------------------------------------------------

    def Dispatch(self, routing: RoutingMatrix) -> None:
        """Push routed output values to all connected backends.

        Groups output values by device/ws-output instance, then calls
        ``push_values()`` on each connected backend.
        """
        out_vals = routing.output_values
        if not out_vals:
            return

        # Group device output values by instance
        dev_groups: Dict[str, Dict[str, float]] = {}
        osc_vals: Dict[str, float] = {}
        ws_out_groups: Dict[str, Dict[str, float]] = {}

        for out_id, val in out_vals.items():
            node = routing.outputs.get(out_id)
            if not node:
                continue

            if node.kind == NodeKind.DEVICE_CHANNEL:
                inst_id = node.device_instance_id
                if inst_id:
                    grp = dev_groups.setdefault(inst_id, {})
                    grp[node.axis_name] = val

            elif node.kind == NodeKind.OFS_WS_OUTPUT:
                # OFS WS axes go to OSC output (if enabled)
                osc_vals[node.axis_name] = val

            elif node.kind == NodeKind.WS_OUTPUT:
                # Custom WS outputs: find the instance from the node id
                # Node id format: "wso_{inst_id}_{axis}"
                parts = out_id.split("_", 2)
                if len(parts) >= 3:
                    ws_inst_id = parts[1]
                    ws_grp = ws_out_groups.setdefault(ws_inst_id, {})
                    ws_grp[node.axis_name] = val

        # Push to device backends
        for inst_id, axes in dev_groups.items():
            backend = self._backends.get(inst_id)
            if backend and backend.is_connected:
                backend.push_values(axes)

        # Push to OSC
        if self._osc and self._osc.is_connected and osc_vals:
            self._osc.push_values(osc_vals)

        # Push to WS output backends
        for ws_id, axes in ws_out_groups.items():
            backend = self._ws_outs.get(ws_id)
            if backend and backend.is_connected:
                backend.push_values(axes)

    # ------------------------------------------------------------------
    # Sync with routing matrix (call when devices are added/removed)
    # ------------------------------------------------------------------

    def sync_with_routing(self, routing: RoutingMatrix) -> None:
        """Ensure all device instances in the routing matrix are registered."""
        # Register new devices
        for inst_id, inst in routing.devices.items():
            if inst_id not in self._backends:
                self.register_device(inst)

        # Unregister removed devices
        stale = [k for k in self._backends if k not in routing.devices]
        for k in stale:
            self.unregister_device(k)

        # Sync WS outputs
        for inst_id, inst in routing.ws_outputs.items():
            if inst_id not in self._ws_outs:
                self.register_ws_output(inst)
        stale_ws = [k for k in self._ws_outs if k not in routing.ws_outputs]
        for k in stale_ws:
            self.unregister_ws_output(k)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Disconnect all backends cleanly."""
        for backend in list(self._backends.values()):
            if backend.is_connected:
                try:
                    backend.disconnect()
                except Exception:
                    pass
        self._backends.clear()

        for backend in list(self._ws_outs.values()):
            if backend.is_connected:
                try:
                    backend.disconnect()
                except Exception:
                    pass
        self._ws_outs.clear()

        if self._osc and self._osc.is_connected:
            try:
                self._osc.disconnect()
            except Exception:
                pass
        self._osc = None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        configs = {}
        for inst_id, cfg in self._configs.items():
            configs[inst_id] = cfg.to_dict()
        # Persist which backend class is active per instance
        backend_classes = {}
        for inst_id, backend in self._backends.items():
            backend_classes[inst_id] = type(backend).__name__
        return {
            "configs": configs,
            "backend_classes": backend_classes,
            "osc_config": self._osc_config.to_dict(),
            "osc_enabled": self._osc_enabled,
        }

    def from_dict(self, d: dict) -> None:
        for inst_id, cfg_d in d.get("configs", {}).items():
            self._configs[inst_id] = ConnectionConfig.from_dict(cfg_d)
        # Store saved backend class names  --  applied after sync_with_routing
        self._saved_backend_classes: Dict[str, str] = d.get("backend_classes", {})
        osc_d = d.get("osc_config")
        if osc_d:
            self._osc_config = ConnectionConfig.from_dict(osc_d)
        if d.get("osc_enabled", False):
            self.enable_osc()

    def apply_saved_backend_classes(self, routing: RoutingMatrix) -> None:
        """Swap backends to match saved class selections (call after sync)."""
        saved = getattr(self, "_saved_backend_classes", {})
        if not saved:
            return
        _CLASS_LOOKUP = {
            "MK312Backend":       MK312Backend,
            "TCodeBackend":       TCodeBackend,
            "DGLabSocketBackend": DGLabSocketBackend,
            "DGLabBLEBackend":    DGLabBLEBackend,
            "ButtplugBackend":    ButtplugBackend,
        }
        for inst_id, cls_name in saved.items():
            inst = routing.devices.get(inst_id)
            if not inst:
                continue
            cls = _CLASS_LOOKUP.get(cls_name)
            if cls and self._backends.get(inst_id) and type(self._backends[inst_id]) is not cls:
                self.swap_backend(inst, cls)
        self._saved_backend_classes = {}

    # ------------------------------------------------------------------
    # Status queries (for UI)
    # ------------------------------------------------------------------

    def list_connected(self) -> List[str]:
        """Return instance IDs of all currently connected device backends."""
        return [k for k, b in self._backends.items() if b.is_connected]

    def list_all(self) -> List[Tuple[str, str, bool]]:
        """Return (instance_id, name, is_connected) for all registered."""
        return [(k, b.name, b.is_connected) for k, b in self._backends.items()]
