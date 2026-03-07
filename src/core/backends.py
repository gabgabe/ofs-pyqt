"""
Device output backends  --  abstract base + concrete implementations.

Each backend runs its I/O on a **background thread** with a lock-free
queue so the main frame loop (which calls ``push_values``) never blocks.

The ``DeviceBackend`` ABC defines the contract:

    connect()     -> bool           # open hardware / network link
    disconnect()                   # close link
    push_values(axis_values)       # main-thread: enqueue data (non-blocking)
    is_connected -> bool

Concrete backends
-----------------
- ``MK312Backend``      --  MK-312BT / ET-312B via RS232 serial
- ``TCodeBackend``      --  OSR / SR6 via serial TCode v0.3
- ``DGLabSocketBackend``  --  DG-Lab Coyote v2/v3 via WebSocket relay
- ``ButtplugBackend``   --  Any Buttplug.io / Intiface Central device
- ``OSCOutputBackend``  --  Generic OSC UDP output
- ``WSOutputBackend``   --  Custom WebSocket axis broadcast
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Maximum pending frames in the write queue before we start dropping
_MAX_QUEUE = 8


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class DeviceBackend(abc.ABC):
    """Abstract output backend driven by the routing matrix."""

    def __init__(self, instance_id: str, model_id: str, name: str = "") -> None:
        self.instance_id = instance_id
        self.model_id = model_id
        self.name = name or model_id
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._queue: Deque[Dict[str, float]] = deque(maxlen=_MAX_QUEUE)
        self._error: str = ""

    # -- public API (called from main thread) --------------------------

    @abc.abstractmethod
    def connect(self, **kwargs) -> bool:
        """Open the hardware / network link.  Returns True on success."""
        ...

    def disconnect(self) -> None:
        """Stop the writer thread and close the link."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._connected = False
        self._do_close()

    def push_values(self, axis_values: Dict[str, float]) -> None:
        """Non-blocking enqueue of one frame of axis values (0-100 each).

        Called once per frame from the main thread.  If the writer
        thread is behind, the oldest frame is silently dropped.
        """
        if self._connected:
            self._queue.append(dict(axis_values))

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> str:
        return self._error

    # -- internal API (override in subclasses) -------------------------

    @abc.abstractmethod
    def _do_write(self, axis_values: Dict[str, float]) -> None:
        """Actually send data to the device.  Runs on writer thread."""
        ...

    def _do_close(self) -> None:
        """Close the underlying link.  Override if cleanup is needed."""
        pass

    def _writer_loop(self, interval_s: float = 0.004) -> None:
        """Background thread: drain queue -> _do_write at *interval_s*."""
        while not self._stop.is_set():
            if self._queue:
                try:
                    vals = self._queue.pop()
                    self._queue.clear()  # skip stale frames
                    self._do_write(vals)
                except Exception as exc:
                    self._error = str(exc)
                    log.error(f"[{self.name}] write error: {exc}")
            self._stop.wait(interval_s)

    def _start_writer(self, interval_s: float = 0.004) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._writer_loop,
            args=(interval_s,),
            daemon=True,
            name=f"DevOut-{self.name}",
        )
        self._thread.start()


# ===========================================================================
# MK-312BT / ET-312B  (RS232, XOR-encrypted, checksum protocol)
# ===========================================================================

# Key memory addresses (from mk312/constants.py)
_MK_LEVEL_A   = 0x4064   # channel A intensity
_MK_LEVEL_B   = 0x4065   # channel B intensity
_MK_LEVEL_MA  = 0x4070   # multi-adjust value
_MK_KEY_ADDR  = 0x4213   # encryption key register
_MK_ADC_DIS   = 0x400F   # ADC disable flags
_MK_MODE      = 0x407B   # current mode register

# Dynamic axis name -> (register_address, value_max) mapping.
# The routing matrix sends 0-100 float; we scale to 0..value_max.
# Core axes always written; extended axes written only when present.
_MK312_AXIS_MAP: Dict[str, Tuple[int, int]] = {
    # Core axes (always written by the background writer)
    "channel_a":      (0x4064, 255),
    "channel_b":      (0x4065, 255),
    "ma":             (0x4070, 255),
    # Mode (integer value, not scaled)
    "current_mode":   (0x407B, 255),
    # Channel A parameters
    "a_ramp_value":   (0x409C, 255),
    "a_ramp_min":     (0x409D, 255),
    "a_ramp_max":     (0x409E, 255),
    "a_ramp_rate":    (0x409F, 255),
    "a_gate_value":   (0x40A5, 255),
    "a_gate_ontime":  (0x40A8, 255),
    "a_gate_offtime": (0x40A9, 255),
    "a_gate_select":  (0x40AA, 255),
    "a_freq_value":   (0x40AE, 255),
    "a_freq_min":     (0x40AC, 255),
    "a_freq_max":     (0x40AD, 255),
    "a_freq_rate":    (0x40AF, 255),
    "a_width_value":  (0x40B4, 255),
    "a_width_min":    (0x40B2, 255),
    "a_width_max":    (0x40B3, 255),
    "a_width_rate":   (0x40B5, 255),
    "a_intensity":    (0x40C0, 255),
    "a_intensity_min":(0x40C2, 255),
    "a_intensity_max":(0x40C3, 255),
    "a_intensity_rate":(0x40C4, 255),
    # Channel B parameters
    "b_ramp_value":   (0x41A0, 255),
    "b_ramp_min":     (0x41A1, 255),
    "b_ramp_max":     (0x41A2, 255),
    "b_ramp_rate":    (0x41A3, 255),
    "b_gate_value":   (0x41A9, 255),
    "b_gate_ontime":  (0x41AC, 255),
    "b_gate_offtime": (0x41AD, 255),
    "b_gate_select":  (0x41AE, 255),
    "b_freq_value":   (0x41B2, 255),
    "b_freq_min":     (0x41B0, 255),
    "b_freq_max":     (0x41B1, 255),
    "b_freq_rate":    (0x41B3, 255),
    "b_width_value":  (0x41B8, 255),
    "b_width_min":    (0x41B6, 255),
    "b_width_max":    (0x41B7, 255),
    "b_width_rate":   (0x41B9, 255),
    "b_intensity":    (0x41C4, 255),
    "b_intensity_min":(0x41C6, 255),
    "b_intensity_max":(0x41C7, 255),
    "b_intensity_rate":(0x41C8, 255),
    # Advanced / panel
    "ramp_select":    (0x4014, 255),
    "ramp_level":     (0x4086, 255),
    "power_level":    (0x4062, 255),
}


class MK312Backend(DeviceBackend):
    """MK-312BT / ET-312B via RS232 serial.

    Protocol:
    - 19200 baud, 8N1, no flow control
    - XOR-encrypted packet framing with checksum
    - Key exchange handshake on connect
    - Channel A/B intensity: 0-255 at addresses 0x4064/0x4065
    - Multi-adjust: 0-255 at address 0x4070
    """

    def __init__(self, instance_id: str, model_id: str = "mk312bt",
                 name: str = "MK-312BT") -> None:
        super().__init__(instance_id, model_id, name)
        self._port = None
        self._key: Optional[int] = None
        self._lock = threading.Lock()

    def connect(self, device: str = "/dev/cu.usbserial",
                baudrate: int = 19200, **kwargs) -> bool:
        try:
            import serial
        except ImportError:
            self._error = "pyserial not installed"
            log.error(self._error)
            return False

        # -- macOS Bluetooth: use IOBluetooth RFCOMM instead of serial -----
        from src.core.rfcomm_serial import (
            is_rfcomm_available, is_bt_serial_port, RFCOMMSerialPort,
        )
        use_rfcomm = is_rfcomm_available() and is_bt_serial_port(device)

        log.info(f"[{self.name}] opening {device} @ {baudrate} baud"
                 f"{' (macOS RFCOMM)' if use_rfcomm else ''}")
        try:
            if use_rfcomm:
                self._port = RFCOMMSerialPort(
                    device, baudrate=baudrate, timeout=0.3,
                )
            else:
                self._port = serial.Serial(
                    device, baudrate=baudrate,
                    bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE, timeout=0.3,
                    xonxoff=False, rtscts=False,
                )
                if not self._port.is_open:
                    self._port.open()
            log.info(f"[{self.name}] port opened OK")

            # Toggle DTR to reset BT-SPP modules / wake ET-312
            # (no-op on RFCOMMSerialPort  --  harmless)
            self._port.dtr = False
            time.sleep(0.1)
            self._port.dtr = True
            time.sleep(0.1)

            # Flush stale data
            self._port.reset_input_buffer()
            self._port.reset_output_buffer()

            # -- Handshake with 3-attempt retry (matches zHappy flow) --
            # Attempt 1: key=None -> plaintext key exchange.
            # If box has cached encryption, key exchange returns empty ->
            #   _handshake sets _key=0x55, returns False.
            # Attempt 2: key=0x55 -> encrypted key exchange.
            # Attempt 3: last try with whatever key was set.
            self._key = None   # start plaintext
            connected = False
            for attempt in range(3):
                try:
                    if self._handshake():
                        connected = True
                        break
                    else:
                        log.info(f"[{self.name}] handshake attempt {attempt + 1}/3 "
                                 f"failed, key now "
                                 f"{'None' if self._key is None else f'0x{self._key:02X}'}")
                except Exception as he:
                    log.warning(f"[{self.name}] handshake attempt {attempt + 1}/3 "
                                f"exception: {he}")
                    if attempt < 2:
                        self._key = 0x55  # retry with default encrypted key
                        time.sleep(0.5)

            if not connected:
                self._error = "Handshake failed after 3 attempts"
                log.error(f"[{self.name}] {self._error}")
                self._port.close()
                return False

            self._connected = True
            self._start_writer(interval_s=0.008)  # ~125 Hz
            log.info(f"[{self.name}] connected on {device}, key=0x{self._key:02X}")
            return True
        except Exception as exc:
            self._error = str(exc)
            log.error(f"[{self.name}] connect failed: {exc}", exc_info=True)
            if self._port and self._port.is_open:
                self._port.close()
            return False

    def _do_close(self) -> None:
        log.info(f"[{self.name}] closing serial connection")
        with self._lock:
            if self._port and self._port.is_open:
                try:
                    if self._key:
                        log.debug(f"[{self.name}] clearing key register")
                        self._write_addr(_MK_KEY_ADDR, 0x00)
                        self._key = None
                except Exception as exc:
                    log.debug(f"[{self.name}] key clear failed: {exc}")
                self._port.close()
        self._port = None

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        with self._lock:
            if not self._port or not self._port.is_open:
                return
            # Write every axis present in axis_values using the register map
            for axis_name, val_100 in axis_values.items():
                mapping = _MK312_AXIS_MAP.get(axis_name)
                if not mapping:
                    continue
                reg_addr, val_max = mapping
                # Scale 0-100 -> 0..val_max
                hw_val = int(val_100 / 100.0 * val_max)
                hw_val = max(0, min(val_max, hw_val))
                self._write_addr(reg_addr, hw_val)

    def write_register(self, address: int, value: int) -> bool:
        """Direct register write (for cue engine). Thread-safe."""
        with self._lock:
            if not self._port or not self._port.is_open:
                return False
            return self._write_addr(address, value & 0xFF)

    # -- MK312 serial protocol ----------------------------------------

    def _handshake(self) -> bool:
        """Sync + key exchange (matches zHappy / mk312-py working flow).

        Step 1  --  Sync: send 0x00, wait for 0x07 (single ACK).
        Step 2  --  Key exchange: send [0x2F, 0x00, checksum]  --  encrypted if
                 ``_key`` is already set (retry with cached encryption).
        Step 3  --  Receive [0x21, their_key, checksum], compute final key.

        Returns ``False`` without raising if key exchange gets empty reply
        (sets ``_key = 0x55`` so the caller can retry encrypted).
        """
        # -- Step 1: sync (send 0x00, expect 0x07) ---------------------
        log.debug(f"[{self.name}] handshake: starting sync "
                  f"(key={'None' if self._key is None else f'0x{self._key:02X}'})")
        empty_count = 0
        max_empty = 12
        for attempt in range(24):
            self._port.write(bytes([0x00]))
            rd = self._port.read(1)
            if rd:
                log.debug(f"[{self.name}] sync #{attempt}: "
                          f"got 0x{rd[0]:02X}")
                if rd[0] == 0x07:
                    log.info(f"[{self.name}] handshake: sync OK "
                             f"(attempt {attempt})")
                    break
                # got unexpected byte  --  keep trying
            else:
                empty_count += 1
                log.debug(f"[{self.name}] sync #{attempt}: "
                          f"timeout ({empty_count}/{max_empty})")
                if empty_count >= max_empty:
                    log.error(f"[{self.name}] handshake: sync failed "
                              f"after {empty_count} timeouts")
                    self._error = "Sync failed - device not responding"
                    return False
        else:
            log.error(f"[{self.name}] handshake: sync failed after 24 attempts")
            self._error = "Sync failed - no 0x07 received"
            return False

        # -- Step 2: key exchange --------------------------------------
        pkt = [0x2F, 0x00]
        pkt.append(sum(pkt) % 256)   # checksum = 0x2F

        # Encrypt if we already have a key (retry with cached encryption)
        if self._key is not None:
            pkt = [b ^ self._key for b in pkt]
            log.debug(f"[{self.name}] handshake: sending ENCRYPTED key exchange "
                      f"(key=0x{self._key:02X}): "
                      f"{[f'0x{b:02X}' for b in pkt]}")
        else:
            log.debug(f"[{self.name}] handshake: sending plaintext key exchange "
                      f"{[f'0x{b:02X}' for b in pkt]}")

        self._port.write(bytes(pkt))
        rd = self._port.read(3)

        # Empty response -> box may have cached encryption.
        # Set key to 0x55 (default) so caller can retry encrypted.
        if len(rd) == 0:
            log.warning(f"[{self.name}] handshake: key exchange got empty "
                        f"response - setting key=0x55 for retry")
            self._key = 0x55
            return False

        if len(rd) < 3:
            log.error(f"[{self.name}] handshake: key exchange response "
                      f"too short ({len(rd)} bytes: {rd.hex()})")
            self._error = f"Key exchange: got {len(rd)}/3 bytes"
            return False

        log.debug(f"[{self.name}] handshake: got key response "
                  f"[0x{rd[0]:02X}, 0x{rd[1]:02X}, 0x{rd[2]:02X}]")

        # Validate checksum
        expected_ck = sum(rd[:-1]) % 256
        if expected_ck != rd[-1]:
            log.error(f"[{self.name}] handshake: checksum mismatch "
                      f"(computed 0x{expected_ck:02X}, got 0x{rd[-1]:02X})")
            self._error = "Key exchange: checksum mismatch"
            return False

        # -- Step 3: compute encryption key ----------------------------
        their_key = rd[1]
        self._key = 0x55 ^ their_key
        log.info(f"[{self.name}] handshake: OK  their_key=0x{their_key:02X}  "
                 f"final_key=0x{self._key:02X}")
        return True

    def _read_addr(self, address: int) -> Optional[int]:
        pkt = [0x3C, address >> 8, address & 0xFF]
        pkt.append(sum(pkt) % 256)
        if self._key:
            pkt = [b ^ self._key for b in pkt]
        self._port.write(bytes(pkt))
        rd = self._port.read(3)
        if len(rd) != 3:
            log.debug(f"[{self.name}] read 0x{address:04X}: "
                      f"got {len(rd)} bytes (expected 3)")
            return None
        if sum(rd[:-1]) % 256 != rd[-1]:
            log.debug(f"[{self.name}] read 0x{address:04X}: checksum fail")
            return None
        return rd[1]

    def _write_addr(self, address: int, data: int) -> bool:
        pkt = [0x4D, address >> 8, address & 0xFF, data & 0xFF]
        pkt.append(sum(pkt) % 256)
        if self._key:
            pkt = [b ^ self._key for b in pkt]
        self._port.write(bytes(pkt))
        rd = self._port.read(1)
        ok = bool(rd and rd[0] == 0x06)
        if not ok:
            log.debug(f"[{self.name}] write 0x{address:04X}=0x{data:02X}: "
                      f"ACK failed (got {rd.hex() if rd else 'nothing'})")
        return ok


# ===========================================================================
# TCode (OSR / SR6)  --  serial, text-based TCode v0.3
# ===========================================================================

# TCode axis -> command prefix mapping
_TCODE_AXES = {
    "stroke": "L0", "surge": "L1", "sway": "L2",
    "twist":  "R0", "roll":  "R1", "pitch": "R2",
    "vib":    "V0", "pump":  "A0", "suck":  "A1",
}


class TCodeBackend(DeviceBackend):
    """OSR / SR6 stroker via TCode v0.3 over serial.

    Protocol:
    - Text-based: ``L09999I100\\n`` = axis L0, value 9999 (0-9999), interval 100ms
    - Multiple axes per line separated by space
    - 115200 baud default
    """

    def __init__(self, instance_id: str, model_id: str = "osr_sr6",
                 name: str = "OSR / SR6") -> None:
        super().__init__(instance_id, model_id, name)
        self._port = None
        self._interval_ms = 100  # TCode interval command

    def connect(self, device: str = "/dev/cu.usbserial",
                baudrate: int = 115200, **kwargs) -> bool:
        try:
            import serial
        except ImportError:
            self._error = "pyserial not installed"
            return False
        try:
            self._port = serial.Serial(device, baudrate=baudrate, timeout=0.1)
            if not self._port.is_open:
                self._port.open()
            self._connected = True
            self._start_writer(interval_s=0.010)  # 100 Hz
            log.info(f"[{self.name}] connected on {device}")
            return True
        except Exception as exc:
            self._error = str(exc)
            log.error(f"[{self.name}] connect failed: {exc}")
            return False

    def _do_close(self) -> None:
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        if not self._port or not self._port.is_open:
            return
        # Build TCode command string
        parts = []
        for axis_name, val_100 in axis_values.items():
            prefix = _TCODE_AXES.get(axis_name)
            if prefix is None:
                continue
            # Map 0-100 -> 0-9999
            tcode_val = int(max(0.0, min(100.0, val_100)) * 99.99)
            parts.append(f"{prefix}{tcode_val:04d}I{self._interval_ms}")
        if parts:
            cmd = " ".join(parts) + "\n"
            self._port.write(cmd.encode("ascii"))


# ===========================================================================
# DG-Lab Coyote v2/v3 via WebSocket relay (DG-Lab Socket protocol)
# ===========================================================================

class DGLabSocketBackend(DeviceBackend):
    """DG-Lab Coyote v2/v3 via the DG-Lab WebSocket relay server.

    Architecture: Controller -> WS relay server -> DG-Lab APP -> BLE -> Coyote

    Message types sent:
    - strength:  ``strength-{channel}+{mode}+{value}``
        channel: 1=A, 2=B; mode: 0=dec, 1=inc, 2=set; value: 0-200
    - waveform (v3): ``pulse-{ch}:["{hex}",...]``
        ch: A or B; hex = 16-char hex string (4 freq bytes + 4 intensity bytes)
    """

    def __init__(self, instance_id: str, model_id: str = "dg_lab_coyote",
                 name: str = "DG-Lab Coyote") -> None:
        super().__init__(instance_id, model_id, name)
        self._ws_url: str = ""
        self._target_id: str = ""   # APP's clientId (from QR code / bind)
        self._client_id: str = ""   # our clientId (received on connect)
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bound = False
        self._last_strength_a: int = 0
        self._last_strength_b: int = 0
        self._v3_mode: bool = True  # use v3 waveform encoding

    def connect(self, ws_url: str = "wss://ws.dungeon-lab.cn/",
                target_id: str = "", v3: bool = True, **kwargs) -> bool:
        """Connect to the DG-Lab WebSocket relay.

        *target_id* is the APP's clientId obtained from the QR code
        or a previous bind.  If empty, the backend waits for a bind
        event (the user scans a QR code in the APP).
        """
        try:
            import websockets  # noqa: F401
        except ImportError:
            self._error = "websockets not installed"
            return False

        self._ws_url = ws_url
        self._target_id = target_id
        self._v3_mode = v3

        self._loop = asyncio.new_event_loop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"DGLab-{self.name}")
        self._thread.start()
        # Wait briefly for connection
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not self._connected:
            time.sleep(0.05)
        return self._connected

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._ws_task())

    async def _ws_task(self) -> None:
        import websockets
        try:
            async with websockets.connect(self._ws_url) as ws:
                self._ws = ws
                # First message should be our clientId
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)
                if "clientId" in data:
                    self._client_id = data["clientId"]
                    log.info(f"[{self.name}] connected, clientId={self._client_id}")

                # If we have a target, send bind request
                if self._target_id:
                    bind_msg = {
                        "type": "bind",
                        "clientId": self._client_id,
                        "targetId": self._target_id,
                        "message": "DGLAB"
                    }
                    await ws.send(json.dumps(bind_msg))

                self._connected = True

                # Run send/recv loop
                recv_task = asyncio.ensure_future(self._recv_loop(ws))
                send_task = asyncio.ensure_future(self._send_loop(ws))

                done, pending = await asyncio.wait(
                    [recv_task, send_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

        except Exception as exc:
            self._error = str(exc)
            log.error(f"[{self.name}] WS error: {exc}")
        finally:
            self._connected = False
            self._ws = None

    async def _recv_loop(self, ws) -> None:
        """Handle incoming messages (bind confirmations, strength feedback)."""
        try:
            async for msg in ws:
                if self._stop.is_set():
                    break
                try:
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    if msg_type == "bind":
                        self._bound = True
                        self._target_id = data.get("targetId", self._target_id)
                        log.info(f"[{self.name}] bound to {self._target_id}")
                    elif msg_type == "msg":
                        # Could be strength feedback: "strength-A+B+limA+limB"
                        payload = data.get("message", "")
                        if payload.startswith("strength-"):
                            parts = payload[9:].split("+")
                            if len(parts) >= 2:
                                self._last_strength_a = int(parts[0])
                                self._last_strength_b = int(parts[1])
                    elif msg_type == "break":
                        log.warning(f"[{self.name}] peer disconnected")
                        self._bound = False
                except Exception:
                    pass
        except Exception:
            pass

    async def _send_loop(self, ws) -> None:
        """Drain the queue and send waveform/strength data."""
        while not self._stop.is_set():
            if self._queue and self._bound:
                vals = self._queue.pop()
                self._queue.clear()
                try:
                    await self._send_frame(ws, vals)
                except Exception as exc:
                    self._error = str(exc)
                    log.error(f"[{self.name}] send error: {exc}")
            await asyncio.sleep(0.050)  # 50ms -> ~20Hz waveform update

    async def _send_frame(self, ws, axis_values: Dict[str, float]) -> None:
        """Convert routing values to DG-Lab messages and send."""
        if not self._target_id:
            return

        # Read intensity (0-100) and frequency (0-100)
        int_a = max(0.0, min(100.0, axis_values.get("channel_a", 0)))
        int_b = max(0.0, min(100.0, axis_values.get("channel_b", 0)))
        freq_a = max(0.0, min(100.0, axis_values.get("freq_a", 50.0)))
        freq_b = max(0.0, min(100.0, axis_values.get("freq_b", 50.0)))

        # Map intensity 0-100 -> strength 0-200
        str_a = int(int_a * 2.0)
        str_b = int(int_b * 2.0)

        # Send strength (absolute set, mode=2)
        strength_msg = self._relay_msg(f"strength-1+2+{str_a}")
        await ws.send(strength_msg)
        strength_msg = self._relay_msg(f"strength-2+2+{str_b}")
        await ws.send(strength_msg)

        # Send waveform
        if self._v3_mode:
            hex_a = self._encode_v3_wave(freq_a, int_a)
            hex_b = self._encode_v3_wave(freq_b, int_b)
        else:
            hex_a = self._encode_v2_wave(freq_a, int_a)
            hex_b = self._encode_v2_wave(freq_b, int_b)

        wave_a = self._relay_msg(f'pulse-A:["{hex_a}"]')
        wave_b = self._relay_msg(f'pulse-B:["{hex_b}"]')
        await ws.send(wave_a)
        await ws.send(wave_b)

    def _relay_msg(self, message: str) -> str:
        """Wrap a message in the DG-Lab relay JSON envelope."""
        return json.dumps({
            "type": "msg",
            "clientId": self._client_id,
            "targetId": self._target_id,
            "message": message,
        })

    @staticmethod
    def _encode_v3_wave(freq_pct: float, intensity_pct: float) -> str:
        """Encode a single 100ms V3 waveform frame (16 hex chars).

        V3 format: 4 frequency bytes + 4 intensity bytes (4 x 25ms sub-frames).
        Frequency: 0-100% -> 10-1000 input range -> 10-240 byte range.
        Intensity: 0-100% -> 0-100 byte range.
        """
        # Map frequency percentage to Hz (10-1000)
        freq_hz = 10 + freq_pct * 9.9  # 0->10Hz, 100->1000Hz
        # Compress Hz to V3 byte encoding
        if freq_hz <= 100:
            freq_byte = int(freq_hz)
        elif freq_hz <= 600:
            freq_byte = int((freq_hz - 100) / 5 + 100)
        else:
            freq_byte = int((freq_hz - 600) / 10 + 200)
        freq_byte = max(10, min(240, freq_byte))
        # Intensity 0-100% -> 0-100
        int_byte = max(0, min(100, int(intensity_pct)))
        # 4 identical sub-frames
        return (f"{freq_byte:02X}" * 4) + (f"{int_byte:02X}" * 4)

    @staticmethod
    def _encode_v2_wave(freq_pct: float, intensity_pct: float) -> str:
        """Encode a single 100ms V2 waveform frame (6 hex chars).

        V2 format: 3 bytes bit-packed [Z(5b)|Y(10b)|X(5b)].
        X = pulse count, Y = gap ms, Z = pulse width.
        """
        # Map frequency to period in ms
        freq_hz = max(1, 10 + freq_pct * 9.9)
        period_ms = int(1000 / freq_hz)
        # X/Y split (from DG-Lab formula)
        import math
        x = int(math.sqrt(freq_hz / 1000) * 15)
        x = max(1, min(31, x))
        y = max(0, min(1023, period_ms - x))
        # Z from intensity (0-100% -> 0-20, avoid >20 which is painful)
        z = max(0, min(20, int(intensity_pct * 0.2)))
        # Pack into 3 bytes: [Z:5][Y:10][X:5] in 24 bits big-endian
        packed = ((z & 0x1F) << 15) | ((y & 0x3FF) << 5) | (x & 0x1F)
        return f"{packed:06X}"

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        # Handled by _send_loop via the asyncio thread
        pass

    def _do_close(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._ws = None
        self._bound = False

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def is_bound(self) -> bool:
        return self._bound

    def get_qr_url(self, server_url: str = "wss://ws.dungeon-lab.cn/") -> str:
        """Generate the QR code URL for the DG-Lab APP to scan."""
        if not self._client_id:
            return ""
        return (f"https://www.dungeon-lab.com/app-download.php"
                f"#DGLAB-SOCKET#{server_url}{self._client_id}")


# ===========================================================================
# Buttplug.io / Intiface Central (WebSocket client -> Intiface)
# ===========================================================================

class ButtplugBackend(DeviceBackend):
    """Buttplug.io device via Intiface Central WebSocket.

    Connects to the Intiface Central server, scans for the first
    available device, and maps routing axes to Buttplug commands:
    - vibrate -> VibrateCmd  (0.0-1.0)
    - rotate  -> RotateCmd   (0.0-1.0, clockwise)
    - linear  -> LinearCmd   (0.0-1.0, 500ms duration)
    """

    def __init__(self, instance_id: str, model_id: str = "buttplug_generic",
                 name: str = "Buttplug.io") -> None:
        super().__init__(instance_id, model_id, name)
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._msg_id = 1
        self._device_idx: Optional[int] = None
        self._device_name: str = ""
        self._features: Dict[str, int] = {}  # "vibrate"->count, "rotate"->count, "linear"->count

    def connect(self, server: str = "ws://127.0.0.1:12345", **kwargs) -> bool:
        try:
            import websockets  # noqa: F401
        except ImportError:
            self._error = "websockets not installed"
            return False

        self._loop = asyncio.new_event_loop()
        self._stop.clear()
        self._server_url = server
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"Buttplug-{self.name}")
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self._connected:
            time.sleep(0.05)
        return self._connected

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._ws_task())

    async def _ws_task(self) -> None:
        import websockets
        try:
            async with websockets.connect(self._server_url) as ws:
                self._ws = ws

                # Handshake
                await self._bp_send(ws, {
                    "RequestServerInfo": {
                        "Id": self._next_id(),
                        "ClientName": "OFS-PyQt",
                        "MessageVersion": 3,
                    }
                })
                resp = await self._bp_recv(ws)

                # Start scanning
                await self._bp_send(ws, {
                    "StartScanning": {"Id": self._next_id()}
                })

                # Wait for DeviceAdded
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msgs = json.loads(resp)
                    for msg in msgs:
                        if "DeviceAdded" in msg:
                            da = msg["DeviceAdded"]
                            self._device_idx = da["DeviceIndex"]
                            self._device_name = da.get("DeviceName", "Unknown")
                            # Parse features
                            for attr in da.get("DeviceMessages", {}).keys():
                                if attr == "VibrateCmd":
                                    self._features["vibrate"] = da["DeviceMessages"][attr].get("FeatureCount", 1)
                                elif attr == "RotateCmd":
                                    self._features["rotate"] = da["DeviceMessages"][attr].get("FeatureCount", 1)
                                elif attr == "LinearCmd":
                                    self._features["linear"] = da["DeviceMessages"][attr].get("FeatureCount", 1)
                            break
                    if self._device_idx is not None:
                        break

                if self._device_idx is None:
                    self._error = "No device found"
                    return

                await self._bp_send(ws, {
                    "StopScanning": {"Id": self._next_id()}
                })

                self._connected = True
                log.info(f"[{self.name}] connected to {self._device_name}")

                # Send loop
                while not self._stop.is_set():
                    if self._queue:
                        vals = self._queue.pop()
                        self._queue.clear()
                        await self._send_commands(ws, vals)
                    await asyncio.sleep(0.020)  # 50 Hz

        except Exception as exc:
            self._error = str(exc)
            log.error(f"[{self.name}] error: {exc}")
        finally:
            self._connected = False
            self._ws = None

    async def _send_commands(self, ws, axis_values: Dict[str, float]) -> None:
        vib = axis_values.get("vibrate", 0) / 100.0
        rot = axis_values.get("rotate", 0) / 100.0
        lin = axis_values.get("linear", 0) / 100.0

        if "vibrate" in self._features and vib >= 0:
            n = self._features["vibrate"]
            speeds = [{"Index": i, "Speed": max(0.0, min(1.0, vib))} for i in range(n)]
            await self._bp_send(ws, {
                "VibrateCmd": {
                    "Id": self._next_id(),
                    "DeviceIndex": self._device_idx,
                    "Speeds": speeds,
                }
            })
        if "rotate" in self._features and rot > 0:
            n = self._features["rotate"]
            rotations = [{"Index": i, "Speed": max(0.0, min(1.0, rot)),
                         "Clockwise": True} for i in range(n)]
            await self._bp_send(ws, {
                "RotateCmd": {
                    "Id": self._next_id(),
                    "DeviceIndex": self._device_idx,
                    "Rotations": rotations,
                }
            })
        if "linear" in self._features and lin > 0:
            n = self._features["linear"]
            vectors = [{"Index": i, "Duration": 500,
                        "Position": max(0.0, min(1.0, lin))} for i in range(n)]
            await self._bp_send(ws, {
                "LinearCmd": {
                    "Id": self._next_id(),
                    "DeviceIndex": self._device_idx,
                    "Vectors": vectors,
                }
            })

    async def _bp_send(self, ws, msg: dict) -> None:
        await ws.send(json.dumps([msg]))

    async def _bp_recv(self, ws) -> list:
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        return json.loads(raw)

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        pass  # handled by async send loop

    def _do_close(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._ws = None


# ===========================================================================
# OSC output  --  generic UDP
# ===========================================================================

class OSCOutputBackend(DeviceBackend):
    """Generic OSC output via UDP (python-osc).

    Sends each axis as ``/{prefix}/{axis_name}`` with float 0.0-1.0.
    """

    def __init__(self, instance_id: str, model_id: str = "osc_output",
                 name: str = "OSC Output") -> None:
        super().__init__(instance_id, model_id, name)
        self._client = None
        self._prefix = "/ofs"

    def connect(self, host: str = "127.0.0.1", port: int = 8001,
                prefix: str = "/ofs", **kwargs) -> bool:
        try:
            from pythonosc.udp_client import SimpleUDPClient
        except ImportError:
            self._error = "python-osc not installed"
            return False

        try:
            self._client = SimpleUDPClient(host, port)
            self._prefix = prefix.rstrip("/")
            self._connected = True
            self._start_writer(interval_s=0.010)
            log.info(f"[{self.name}] sending OSC to {host}:{port}")
            return True
        except Exception as exc:
            self._error = str(exc)
            return False

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        if not self._client:
            return
        for axis_name, val_100 in axis_values.items():
            osc_val = max(0.0, min(1.0, val_100 / 100.0))
            try:
                self._client.send_message(
                    f"{self._prefix}/{axis_name}", osc_val)
            except Exception:
                pass

    def _do_close(self) -> None:
        self._client = None


# ===========================================================================
# Custom WebSocket output  --  axis broadcast
# ===========================================================================

class WSOutputBackend(DeviceBackend):
    """Custom WebSocket output  --  broadcasts axis values to connected clients.

    Runs a WebSocket server on a configurable port. Clients connect and
    receive JSON messages: ``{"type":"axis","axes":{"stroke":50.0,...}}``.
    Also supports the zHappy format: ``A06260 B10000`` etc.
    """

    def __init__(self, instance_id: str, model_id: str = "ws_output",
                 name: str = "WS Output") -> None:
        super().__init__(instance_id, model_id, name)
        self._host = "localhost"
        self._port = 8082
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._clients: set = set()
        self._format = "json"  # "json" or "tcode"
        self._latest: Dict[str, float] = {}

    def connect(self, host: str = "localhost", port: int = 8082,
                format: str = "json", **kwargs) -> bool:
        try:
            import websockets  # noqa: F401
        except ImportError:
            self._error = "websockets not installed"
            return False

        self._host = host
        self._port = port
        self._format = format
        self._loop = asyncio.new_event_loop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"WSOut-{self.name}")
        self._thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not self._connected:
            time.sleep(0.05)
        return self._connected

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        import websockets
        async with websockets.serve(self._handler, self._host, self._port):
            self._connected = True
            log.info(f"[{self.name}] WS output server on ws://{self._host}:{self._port}")
            while not self._stop.is_set():
                # Drain queue and broadcast
                if self._queue:
                    vals = self._queue.pop()
                    self._queue.clear()
                    self._latest = vals
                    await self._broadcast(vals)
                await asyncio.sleep(0.016)  # ~60 Hz

    async def _handler(self, ws, path=None) -> None:
        self._clients.add(ws)
        try:
            # Send current state on connect
            if self._latest:
                msg = self._format_msg(self._latest)
                await ws.send(msg)
            async for _ in ws:
                pass  # we only send, ignore incoming
        finally:
            self._clients.discard(ws)

    async def _broadcast(self, vals: Dict[str, float]) -> None:
        if not self._clients:
            return
        msg = self._format_msg(vals)
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    def _format_msg(self, vals: Dict[str, float]) -> str:
        if self._format == "tcode":
            # zHappy-compatible: "A06260 B10000"
            parts = []
            for axis, val in vals.items():
                tcode = _TCODE_AXES.get(axis, axis[:2].upper())
                ival = int(max(0, min(9999, val * 99.99)))
                parts.append(f"{tcode}{ival:04d}")
            return " ".join(parts)
        else:
            return json.dumps({"type": "axis", "axes": {
                k: round(v, 2) for k, v in vals.items()
            }})

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        pass  # handled by async _serve loop

    def _do_close(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._server = None
        self._clients.clear()


# ===========================================================================
# DG-Lab Coyote V3  --  direct BLE via bleak
# ===========================================================================

# V3 BLE UUIDs  (standard 128-bit base: 0000xxxx-0000-1000-8000-00805f9b34fb)
_DG3_SVC         = "0000180c-0000-1000-8000-00805f9b34fb"
_DG3_CHAR_WRITE  = "0000150a-0000-1000-8000-00805f9b34fb"   # 20-byte write
_DG3_CHAR_NOTIFY = "0000150b-0000-1000-8000-00805f9b34fb"   # 20-byte notify
_DG3_CHAR_BATT   = "00001500-0000-1000-8000-00805f9b34fb"   # 1-byte battery

# V2 BLE UUIDs  (custom base: 955Axxxx-0FE2-F5AA-A094-84B8D4F3E8AD)
_DG2_SVC         = "955a180b-0fe2-f5aa-a094-84b8d4f3e8ad"
_DG2_CHAR_AB     = "955a1504-0fe2-f5aa-a094-84b8d4f3e8ad"   # PWM_AB2 (3 bytes)
_DG2_CHAR_A34    = "955a1505-0fe2-f5aa-a094-84b8d4f3e8ad"   # PWM_A34 (3 bytes)
_DG2_CHAR_B34    = "955a1506-0fe2-f5aa-a094-84b8d4f3e8ad"   # PWM_B34 (3 bytes)
_DG2_CHAR_BATT   = "955a1500-0fe2-f5aa-a094-84b8d4f3e8ad"   # battery


class DGLabBLEBackend(DeviceBackend):
    """DG-Lab Coyote V3 / V2 via direct BLE using *bleak*.

    V3 protocol (Coyote 3.0, name prefix "47L121000"):
    - Service 0x180C, Write 0x150A, Notify 0x150B
    - B0 command (20 bytes) every 100ms:
        HEAD(0xB0) | seq(4b)+strength_method(4b) | A_strength(1B) | B_strength(1B)
        | A_freqx4(4B) | A_intx4(4B) | B_freqx4(4B) | B_intx4(4B)
    - BF safety command (7 bytes): HEAD(0xBF) | limit_A(1B) | limit_B(1B)
        | freq_balance_A(1B) | freq_balance_B(1B) | int_balance_A(1B) | int_balance_B(1B)
    - B1 notify response: HEAD(0xB1) | seq(1B) | A_strength(1B) | B_strength(1B)

    V2 protocol (Coyote 2.0, name prefix "D-LAB ESTIM01"):
    - Custom UUID base: 955Axxxx-0FE2-F5AA-A094-84B8D4F3E8AD
    - PWM_AB2: 3 bytes, bits [21:11]=A strength, [10:0]=B strength (0-2047)
    - PWM_A34: 3 bytes, bits [19:15]=Z, [14:5]=Y, [4:0]=X
    - PWM_B34: same as A34 for channel B
    - Waveform must be resent every 100ms
    """

    def __init__(self, instance_id: str, model_id: str = "dg_lab_coyote3",
                 name: str = "DG-Lab Coyote BLE") -> None:
        super().__init__(instance_id, model_id, name)
        self._client = None          # bleak.BleakClient
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._device_addr: str = ""  # BLE MAC or name
        self._v3: bool = (model_id == "dg_lab_coyote3")
        self._seq: int = 0
        self._strength_a: int = 0
        self._strength_b: int = 0
        self._limit_a: int = 200
        self._limit_b: int = 200
        self._battery: int = -1
        self._strength_ack_pending: bool = False

    def connect(self, address: str = "",
                limit_a: int = 200, limit_b: int = 200,
                **kwargs) -> bool:
        """Connect via BLE. *address* is a MAC or device name."""
        try:
            import bleak  # noqa: F401
        except ImportError:
            self._error = "bleak not installed (pip install bleak)"
            return False

        self._device_addr = address
        self._limit_a = max(0, min(200, limit_a))
        self._limit_b = max(0, min(200, limit_b))

        self._loop = asyncio.new_event_loop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True,
            name=f"DGBLE-{self.name}")
        self._thread.start()
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not self._connected:
            time.sleep(0.05)
        return self._connected

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._ble_task())

    async def _ble_task(self) -> None:
        import bleak

        # Scan if no address given
        addr = self._device_addr
        if not addr:
            prefix = "47L121" if self._v3 else "D-LAB ESTIM"
            log.info(f"[{self.name}] scanning for BLE device ({prefix}...)")
            devices = await bleak.BleakScanner.discover(timeout=5.0)
            for d in devices:
                if d.name and d.name.startswith(prefix):
                    addr = d.address
                    log.info(f"[{self.name}] found {d.name} at {addr}")
                    break
            if not addr:
                self._error = f"No DG-Lab device found (scan for {prefix}*)"
                log.warning(self._error)
                return

        try:
            client = bleak.BleakClient(addr, timeout=10.0)
            await client.connect()
            self._client = client
            self._connected = True
            log.info(f"[{self.name}] BLE connected to {addr}")

            if self._v3:
                # Subscribe to B1 notify
                await client.start_notify(
                    _DG3_CHAR_NOTIFY, self._on_v3_notify)
                # Send BF safety limits
                await self._send_bf(client)
                # Main send loop
                while not self._stop.is_set():
                    if self._queue:
                        vals = self._queue.pop()
                        self._queue.clear()
                        await self._send_b0(client, vals)
                    else:
                        # Keep-alive: send idle waveform
                        await self._send_b0(client, {})
                    await asyncio.sleep(0.100)  # 100ms cycle
            else:
                # V2 send loop
                while not self._stop.is_set():
                    if self._queue:
                        vals = self._queue.pop()
                        self._queue.clear()
                        await self._send_v2(client, vals)
                    else:
                        await self._send_v2(client, {})
                    await asyncio.sleep(0.100)

        except Exception as exc:
            self._error = str(exc)
            log.error(f"[{self.name}] BLE error: {exc}")
        finally:
            self._connected = False
            if self._client and self._client.is_connected:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
            self._client = None

    # -- V3 protocol helpers -------------------------------------------

    async def _send_bf(self, client) -> None:
        """Send BF safety-limit command (7 bytes). Must resend after reconnect."""
        data = bytes([
            0xBF,
            self._limit_a & 0xFF,
            self._limit_b & 0xFF,
            128,  # freq balance A (default mid)
            128,  # freq balance B (default mid)
            128,  # intensity balance A
            128,  # intensity balance B
        ])
        await client.write_gatt_char(_DG3_CHAR_WRITE, data, response=False)
        log.debug(f"[{self.name}] BF sent: limit_a={self._limit_a}, limit_b={self._limit_b}")

    async def _send_b0(self, client, axis_values: Dict[str, float]) -> None:
        """Build and send one 20-byte B0 command."""
        int_a = max(0.0, min(100.0, axis_values.get("channel_a", 0)))
        int_b = max(0.0, min(100.0, axis_values.get("channel_b", 0)))
        freq_a = max(0.0, min(100.0, axis_values.get("freq_a", 50.0)))
        freq_b = max(0.0, min(100.0, axis_values.get("freq_b", 50.0)))

        # Strength: 0-100% -> 0-200
        str_a = int(int_a * 2.0)
        str_b = int(int_b * 2.0)

        # Determine strength change method
        if not self._strength_ack_pending and (
                str_a != self._strength_a or str_b != self._strength_b):
            self._seq = (self._seq % 15) + 1  # 1-15
            # Absolute set for both: A=0b11, B=0b11 -> 0b1111 = 0x0F
            strength_method = 0x0F
            self._strength_a = str_a
            self._strength_b = str_b
            self._strength_ack_pending = True
        else:
            strength_method = 0x00  # no change
            str_a = 0
            str_b = 0

        seq_method = ((self._seq if strength_method else 0) << 4) | strength_method

        # Frequency: 0-100% -> 10-1000 Hz -> V3 byte encoding
        fb_a = self._freq_to_v3_byte(freq_a)
        fb_b = self._freq_to_v3_byte(freq_b)

        # Intensity: 0-100% -> 0-100 byte
        ib_a = max(0, min(100, int(int_a)))
        ib_b = max(0, min(100, int(int_b)))

        data = bytes([
            0xB0,
            seq_method & 0xFF,
            str_a & 0xFF,
            str_b & 0xFF,
            fb_a, fb_a, fb_a, fb_a,  # A freq x 4 sub-frames
            ib_a, ib_a, ib_a, ib_a,  # A intensity x 4
            fb_b, fb_b, fb_b, fb_b,  # B freq x 4
            ib_b, ib_b, ib_b, ib_b,  # B intensity x 4
        ])
        await client.write_gatt_char(_DG3_CHAR_WRITE, data, response=False)

    @staticmethod
    def _freq_to_v3_byte(freq_pct: float) -> int:
        """Map 0-100% -> frequency byte (10-240)."""
        freq_hz = 10 + freq_pct * 9.9
        if freq_hz <= 100:
            b = int(freq_hz)
        elif freq_hz <= 600:
            b = int((freq_hz - 100) / 5 + 100)
        else:
            b = int((freq_hz - 600) / 10 + 200)
        return max(10, min(240, b))

    def _on_v3_notify(self, _sender, data: bytearray) -> None:
        """Handle B1 strength feedback notify."""
        if len(data) >= 4 and data[0] == 0xB1:
            ret_seq = data[1]
            self._strength_a = data[2]
            self._strength_b = data[3]
            if ret_seq == self._seq:
                self._strength_ack_pending = False

    # -- V2 protocol helpers -------------------------------------------

    async def _send_v2(self, client, axis_values: Dict[str, float]) -> None:
        """Send V2 strength + waveform via BLE characteristics."""
        import math
        int_a = max(0.0, min(100.0, axis_values.get("channel_a", 0)))
        int_b = max(0.0, min(100.0, axis_values.get("channel_b", 0)))
        freq_a = max(0.0, min(100.0, axis_values.get("freq_a", 50.0)))
        freq_b = max(0.0, min(100.0, axis_values.get("freq_b", 50.0)))

        # Strength: 0-100% -> 0-2047 (APP uses x7 per notch, we map linearly)
        sa = int(int_a * 20.47)
        sb = int(int_b * 20.47)
        sa = max(0, min(2047, sa))
        sb = max(0, min(2047, sb))
        # Pack PWM_AB2: 3 bytes, bits [21:11]=A, [10:0]=B
        ab_val = ((sa & 0x7FF) << 11) | (sb & 0x7FF)
        ab_bytes = ab_val.to_bytes(3, "big")
        await client.write_gatt_char(_DG2_CHAR_AB, ab_bytes, response=False)

        # Waveform A: compute X,Y,Z from freq/intensity
        def encode_xyz(freq_pct: float, int_pct: float) -> bytes:
            freq_hz = max(10, 10 + freq_pct * 9.9)
            frequency = int(freq_hz)  # X+Y total
            x = int(math.sqrt(frequency / 1000) * 15)
            x = max(1, min(31, x))
            y = max(0, min(1023, frequency - x))
            z = max(0, min(20, int(int_pct * 0.2)))
            packed = ((z & 0x1F) << 15) | ((y & 0x3FF) << 5) | (x & 0x1F)
            return packed.to_bytes(3, "big")

        a34 = encode_xyz(freq_a, int_a)
        b34 = encode_xyz(freq_b, int_b)
        await client.write_gatt_char(_DG2_CHAR_A34, a34, response=False)
        await client.write_gatt_char(_DG2_CHAR_B34, b34, response=False)

    def _do_write(self, axis_values: Dict[str, float]) -> None:
        pass  # handled by async BLE task

    def _do_close(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._client = None

    @property
    def battery_level(self) -> int:
        return self._battery


# ===========================================================================
# Backend factory
# ===========================================================================

# Maps model_id -> default backend class.
# DG-Lab models use Socket relay by default; the user can switch to BLE
# by choosing the _ble variant in the device config UI.
_BACKEND_MAP: Dict[str, type] = {
    "mk312bt":         MK312Backend,
    "et312b":          MK312Backend,
    "2b":              MK312Backend,   # same serial protocol as ET-312
    "osr_sr6":         TCodeBackend,
    "dg_lab_coyote":   DGLabSocketBackend,
    "dg_lab_coyote3":  DGLabSocketBackend,
    "buttplug_generic": ButtplugBackend,
}

# Alternate backend classes selectable per-instance
BACKEND_ALTERNATIVES: Dict[str, List[Tuple[str, type]]] = {
    "dg_lab_coyote":  [("WebSocket Relay", DGLabSocketBackend), ("Direct BLE", DGLabBLEBackend)],
    "dg_lab_coyote3": [("WebSocket Relay", DGLabSocketBackend), ("Direct BLE", DGLabBLEBackend)],
}


def create_backend(instance_id: str, model_id: str,
                   name: str = "",
                   backend_class: Optional[type] = None) -> Optional[DeviceBackend]:
    """Factory: create the appropriate backend for a device model.

    If *backend_class* is given it overrides the default from ``_BACKEND_MAP``.
    """
    cls = backend_class or _BACKEND_MAP.get(model_id)
    if cls is None:
        log.warning(f"No backend for model: {model_id}")
        return None
    return cls(instance_id, model_id, name)
