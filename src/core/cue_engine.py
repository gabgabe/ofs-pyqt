"""
CueEngine  --  executes control cues when the playhead crosses them.

The engine is ticked once per frame by the TimelineManager.  It scans
all CONTROL_CUE tracks for cues whose timestamp falls between the
previous and current transport position and fires each one exactly once.

Execution is immediate and synchronous on the main thread  --  cues are
one-shot commands (no duration, no fades, no interpolation).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.core.control_cue import ControlCue, CueType

if TYPE_CHECKING:
    from src.core.device_manager import DeviceManager
    from src.core.backends import (
        DeviceBackend, MK312Backend, OSCOutputBackend, WSOutputBackend,
    )

log = logging.getLogger(__name__)


class CueEngine:
    """Fires control cues as the playhead advances.

    Usage::

        engine = CueEngine()
        engine.set_device_manager(device_mgr)

        # once per frame, called by TimelineManager.Tick():
        engine.tick(prev_pos, cur_pos, cues_in_window)
    """

    def __init__(self) -> None:
        self._device_mgr: Optional["DeviceManager"] = None
        self._last_pos: float = -1.0    # last transport position seen
        self._fired: set[str] = set()   # cue_ids fired since last seek

    # -- Wiring --------------------------------------------------------

    def set_device_manager(self, dm: "DeviceManager") -> None:
        self._device_mgr = dm

    # -- Seek reset ----------------------------------------------------

    def reset(self) -> None:
        """Call on seek / project load to clear the fired-set."""
        self._fired.clear()
        self._last_pos = -1.0

    # -- Per-frame tick ------------------------------------------------

    def tick(self, prev_pos: float, cur_pos: float,
             cues: list[ControlCue]) -> None:
        """Fire cues in the (prev_pos, cur_pos] window.

        *cues* should already be filtered to the correct time window
        (track-local times converted to global).
        """
        if not cues:
            return

        # Determine scan window  --  handle forward and backward playback
        if cur_pos >= prev_pos:
            lo, hi = prev_pos, cur_pos
        else:
            lo, hi = cur_pos, prev_pos

        for cue in cues:
            # Fire if cue.time is in (lo, hi] and not already fired
            if lo < cue.time <= hi and cue.cue_id not in self._fired:
                self._execute(cue)
                self._fired.add(cue.cue_id)

    # -- Execution dispatch --------------------------------------------

    def _execute(self, cue: ControlCue) -> None:
        """Route cue to the appropriate backend."""
        log.info(f"[CueEngine] FIRE  {cue.name}  type={cue.cue_type.name}  "
                 f"t={cue.time:.3f}  params={cue.params}")

        try:
            if cue.cue_type == CueType.PARAMETER:
                self._exec_parameter(cue)
            elif cue.cue_type == CueType.OSC_COMMAND:
                self._exec_osc(cue)
            elif cue.cue_type == CueType.WS_MESSAGE:
                self._exec_ws(cue)
            elif cue.cue_type == CueType.MODE_CHANGE:
                self._exec_mode_change(cue)
            else:
                log.warning(f"[CueEngine] unknown cue type {cue.cue_type}")
        except Exception as exc:
            log.error(f"[CueEngine] error executing {cue.name}: {exc}",
                      exc_info=True)

    # -- Type-specific executors ---------------------------------------

    def _exec_parameter(self, cue: ControlCue) -> None:
        """Write register/value(s) to a device backend.

        Supports single entry (legacy)::
            {"device_instance_id": "mk312_0",
             "address": 0x4078, "value": 5}

        And multi-entry::
            {"device_instance_id": "mk312_0",
             "entries": [
                {"address": 0x4064, "value": 128},
                {"address": 0x407B, "value": 0x76},
             ]}
        """
        if not self._device_mgr:
            log.warning("[CueEngine] no device_manager - skipping PARAMETER cue")
            return

        inst_id = cue.params.get("device_instance_id", "")
        backend = self._device_mgr.get_backend(inst_id)
        if not backend or not backend.is_connected:
            log.warning(f"[CueEngine] device {inst_id} not connected")
            return

        # Build list of (address, value) pairs
        entries = cue.params.get("entries", [])
        if not entries:
            # Legacy single-entry format
            address = cue.params.get("address")
            value = cue.params.get("value")
            if address is not None and value is not None:
                entries = [{"address": address, "value": value}]

        if not entries:
            log.warning(f"[CueEngine] PARAMETER cue missing address/value")
            return

        for entry in entries:
            address = entry.get("address")
            value = entry.get("value")
            if address is None or value is None:
                continue
            if hasattr(backend, 'write_register'):
                ok = backend.write_register(int(address), int(value))
                log.info(f"[CueEngine] write 0x{int(address):04X} = "
                         f"0x{int(value):02X} -> {'OK' if ok else 'FAIL'}")
            elif hasattr(backend, '_write_addr') and hasattr(backend, '_lock'):
                import threading
                with backend._lock:
                    ok = backend._write_addr(int(address), int(value))
                    log.info(f"[CueEngine] write 0x{int(address):04X} = "
                             f"0x{int(value):02X} -> {'OK' if ok else 'FAIL'}")
            else:
                backend.push_values({"_cue_addr": float(address),
                                     "_cue_val": float(value)})

    def _exec_osc(self, cue: ControlCue) -> None:
        """Send an OSC message.

        Expected params::
            {"path": "/my/command", "args": [1.0, "hello"]}
        """
        if not self._device_mgr:
            return

        osc = self._device_mgr._osc
        if not osc or not osc.is_connected:
            log.warning("[CueEngine] OSC not connected - skipping")
            return

        path = cue.params.get("path", "")
        args = cue.params.get("args", [])
        if not path:
            log.warning("[CueEngine] OSC_COMMAND cue missing path")
            return

        if hasattr(osc, '_client') and osc._client:
            try:
                osc._client.send_message(path, args)
                log.info(f"[CueEngine] OSC -> {path} {args}")
            except Exception as exc:
                log.error(f"[CueEngine] OSC send failed: {exc}")

    def _exec_ws(self, cue: ControlCue) -> None:
        """Send a JSON payload over a WS output.

        Expected params::
            {"ws_instance_id": "wso_abc",
             "payload": {"type": "set_mode", "mode": "pulse"}}
        """
        if not self._device_mgr:
            return

        ws_id = cue.params.get("ws_instance_id", "")
        payload = cue.params.get("payload", {})
        backend = self._device_mgr._ws_outs.get(ws_id)
        if not backend or not backend.is_connected:
            log.warning(f"[CueEngine] WS output {ws_id} not connected")
            return

        # Use the backend's broadcast mechanism
        if hasattr(backend, '_clients') and backend._clients:
            import json
            msg = json.dumps(payload)
            import asyncio
            loop = getattr(backend, '_loop', None)
            if loop and loop.is_running():
                for ws in list(backend._clients):
                    asyncio.run_coroutine_threadsafe(ws.send(msg), loop)
                log.info(f"[CueEngine] WS -> {ws_id}: {payload}")

    def _exec_mode_change(self, cue: ControlCue) -> None:
        """Change the operational mode of a backend.

        Expected params::
            {"device_instance_id": "mk312_0",
             "mode": "intense"}

        For MK-312, "mode" maps to the mode register 0x4078.
        """
        if not self._device_mgr:
            return

        inst_id = cue.params.get("device_instance_id", "")
        mode = cue.params.get("mode")
        backend = self._device_mgr.get_backend(inst_id)
        if not backend or not backend.is_connected:
            log.warning(f"[CueEngine] device {inst_id} not connected")
            return

        # MK312 mode register
        if hasattr(backend, 'write_register'):
            mode_val = int(mode) if isinstance(mode, (int, float)) else 0
            ok = backend.write_register(0x407B, mode_val)
            log.info(f"[CueEngine] MODE_CHANGE -> 0x407B = "
                     f"0x{mode_val:02X} -> {'OK' if ok else 'FAIL'}")
        elif hasattr(backend, '_write_addr') and hasattr(backend, '_lock'):
            mode_val = int(mode) if isinstance(mode, (int, float)) else 0
            with backend._lock:
                ok = backend._write_addr(0x407B, mode_val)
                log.info(f"[CueEngine] MODE_CHANGE -> 0x407B = "
                         f"{mode_val} -> {'OK' if ok else 'FAIL'}")
        else:
            log.info(f"[CueEngine] MODE_CHANGE for {inst_id}: {mode} "
                     f"(backend has no write_register)")
