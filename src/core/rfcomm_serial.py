"""
RFCOMM Serial Port for macOS  --  drop-in ``serial.Serial`` replacement.

On macOS, paired Bluetooth Classic devices (like the DFRobot BT401 module on
the MK-312BT) create virtual serial ports (``/dev/cu.<name>``), but opening
them with ``serial.Serial`` **does not** establish the RFCOMM data channel  -- 
the macOS IOUserBluetoothSerialDriver keeps the A2DP/AVRCP audio profiles
connected and silently ignores the serial path.

This module bypasses the kernel driver entirely by using **PyObjC IOBluetooth**
to open an RFCOMM channel directly.  The resulting ``RFCOMMSerialPort`` object
exposes the same interface as ``serial.Serial`` so it can be injected into the
MK-312 protocol code with zero changes.

Cross-platform note
-------------------
``is_rfcomm_available()`` returns ``False`` on non-macOS platforms, so the
rest of the app can always call it without guards.  On Windows / Linux the
standard ``serial.Serial`` path is used.
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from collections import deque
from typing import Optional

log = logging.getLogger(__name__)

IS_MACOS = platform.system() == "Darwin"

# ---------------------------------------------------------------------------
# Conditional PyObjC imports (macOS only)
# ---------------------------------------------------------------------------
if IS_MACOS:
    try:
        import objc  # noqa: F401
        from Foundation import (  # type: ignore[attr-defined]
            NSDate,
            NSDefaultRunLoopMode,
            NSObject,
            NSRunLoop,
        )
        from IOBluetooth import (  # type: ignore[attr-defined]
            IOBluetoothDevice,
            IOBluetoothRFCOMMChannel,  # noqa: F401
        )

        PYOBJC_AVAILABLE = True
    except ImportError:
        PYOBJC_AVAILABLE = False
        NSObject = object  # type: ignore[assignment,misc]
        log.warning("[RFCOMMPort] PyObjC IOBluetooth not available - "
                    "install pyobjc-framework-IOBluetooth")
else:
    PYOBJC_AVAILABLE = False
    NSObject = object  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_loop(seconds: float) -> None:
    """Tick the Cocoa RunLoop so IOBluetooth can process events."""
    iterations = max(1, int(seconds * 10))
    for _ in range(iterations):
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode,
            NSDate.dateWithTimeIntervalSinceNow_(0.1),
        )


# ---------------------------------------------------------------------------
# ObjC delegate
# ---------------------------------------------------------------------------

class _RFCOMMDelegate(NSObject):  # type: ignore[misc]
    """Objective-C delegate receiving IOBluetoothRFCOMMChannel callbacks."""

    def initWithPort_(self, port: "RFCOMMSerialPort"):
        self = objc.super(_RFCOMMDelegate, self).init()
        if self is None:
            return None
        self._port = port
        return self

    # -- delegate methods --------------------------------------------------

    def rfcommChannelOpenComplete_status_(self, channel, status):  # type: ignore[override]
        if status == 0:
            log.debug("[RFCOMMPort] channel open complete")
        else:
            log.error(f"[RFCOMMPort] channel open FAILED: "
                      f"0x{status & 0xFFFFFFFF:08X}")

    def rfcommChannelData_data_length_(self, channel, data_ptr, length):  # type: ignore[override]
        try:
            data = bytes(data_ptr[:length])
        except Exception:
            import ctypes
            buf = (ctypes.c_uint8 * length).from_address(data_ptr)
            data = bytes(buf)
        log.debug(f"[RFCOMMPort] RX {length} bytes: {data.hex()}")
        self._port._on_data_received(data)

    def rfcommChannelClosed_(self, channel):  # type: ignore[override]
        log.info("[RFCOMMPort] channel closed by remote")
        self._port._on_channel_closed()


# ---------------------------------------------------------------------------
# Public serial-compatible port
# ---------------------------------------------------------------------------

class RFCOMMSerialPort:
    """Drop-in replacement for ``serial.Serial`` using IOBluetooth RFCOMM.

    Parameters
    ----------
    device : str
        Either a macOS serial path (``/dev/cu.micro``) whose basename is
        matched against paired Bluetooth device names, or a BT MAC address.
    baudrate : int
        Ignored (RFCOMM negotiates its own link speed).  Accepted for API
        compatibility with ``serial.Serial``.
    timeout : float
        Read timeout in seconds.
    rfcomm_channel : int
        RFCOMM channel ID (default **2**  --  correct for JieLi / BT401 chips).
    """

    def __init__(
        self,
        device: str,
        baudrate: int = 19200,
        timeout: float = 1.0,
        rfcomm_channel: int = 2,
        **kwargs,
    ) -> None:
        if not PYOBJC_AVAILABLE:
            raise RuntimeError(
                "PyObjC IOBluetooth not available - "
                "pip install pyobjc-framework-IOBluetooth"
            )

        self._mac = self._resolve_mac(device)
        self._rfcomm_channel_id = rfcomm_channel
        self._timeout = timeout
        self._baudrate = baudrate
        self._device_obj: Optional[IOBluetoothDevice] = None  # type: ignore[assignment]
        self._channel = None
        self._delegate = None
        self._is_open = False
        self._rx_buffer: deque = deque()
        self._rx_lock = threading.Lock()
        self._rx_event = threading.Event()

        log.info(f"[RFCOMMPort] resolved MAC={self._mac} "
                 f"(rfcomm_ch={rfcomm_channel})")
        self.open()

    # -- MAC resolution ----------------------------------------------------

    @staticmethod
    def _resolve_mac(device: str) -> str:
        """Resolve ``/dev/cu.<name>`` -> Bluetooth MAC via paired-device list."""
        import os

        if device.startswith("/dev/"):
            name = os.path.basename(device)
            # strip cu. / tty. prefix
            for prefix in ("cu.", "tty."):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            devices = IOBluetoothDevice.pairedDevices()
            if devices:
                for d in devices:
                    if (d.name() or "").lower() == name.lower():
                        mac = d.addressString()
                        log.info(f"[RFCOMMPort] '{device}' -> "
                                 f"paired device '{d.name()}' ({mac})")
                        return mac
            raise ValueError(
                f"No paired Bluetooth device matching '{name}' - "
                f"check System Settings -> Bluetooth"
            )
        # Already a MAC string  --  normalise separators
        return device.lower().replace(":", "-")

    # -- serial.Serial-compatible properties --------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def isOpen(self) -> bool:  # noqa: N802  --  match pyserial API
        return self._is_open

    @property
    def in_waiting(self) -> int:
        with self._rx_lock:
            return len(self._rx_buffer)

    @property
    def name(self) -> str:
        return f"RFCOMM:{self._mac}"

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        self._baudrate = value  # no-op for RFCOMM

    # DTR / modem lines  --  no-ops for RFCOMM, needed for serial compat

    @property
    def dtr(self) -> bool:
        return self._is_open

    @dtr.setter
    def dtr(self, value: bool) -> None:
        pass  # no-op  --  RFCOMM has no DTR

    @property
    def cd(self) -> bool:
        return self._is_open

    @property
    def cts(self) -> bool:
        return self._is_open

    @property
    def dsr(self) -> bool:
        return self._is_open

    # -- open / close -------------------------------------------------------

    def open(self) -> None:
        """Establish RFCOMM connection.

        The sequence is **critical** (see BLUETOOTH_RFCOMM_MACOS_GUIDE.md):

        1. ``closeConnection()``  --  drop existing audio/ACL
        2. ``time.sleep(2)``      --  **must** be ``time.sleep``, NOT RunLoop
        3. ``openConnection()``   --  reconnect ACL (our conn gets priority)
        4. ``time.sleep(3)``      --  wait for ACL to stabilise
        5. ``openRFCOMMChannelSync``  --  open the data channel
        6. ``_run_loop(2)``       --  process Cocoa events to finalise
        """
        if self._is_open:
            return

        self._device_obj = IOBluetoothDevice.deviceWithAddressString_(self._mac)
        if self._device_obj is None:
            raise ConnectionError(f"Bluetooth device not found: {self._mac}")

        # Step 1  --  always disconnect first (drops audio + ACL)
        # MUST use time.sleep  --  NOT _run_loop  --  to prevent macOS from
        # auto-reconnecting A2DP during the wait.
        if self._device_obj.isConnected():
            log.info(f"[RFCOMMPort] disconnecting existing ACL to {self._mac}")
            self._device_obj.closeConnection()
        time.sleep(2)

        # Step 2  --  reconnect ACL (our connection gets priority over audio)
        log.info(f"[RFCOMMPort] opening ACL to {self._mac}")
        self._device_obj.openConnection()
        time.sleep(3)
        if not self._device_obj.isConnected():
            raise ConnectionError(
                f"Failed to establish ACL link to {self._mac}"
            )
        log.info(f"[RFCOMMPort] ACL link established")

        # Step 3  --  open RFCOMM channel (here we DO tick the RunLoop)
        self._delegate = _RFCOMMDelegate.alloc().initWithPort_(self)
        result, channel = (
            self._device_obj.openRFCOMMChannelSync_withChannelID_delegate_(
                None, self._rfcomm_channel_id, self._delegate
            )
        )
        _run_loop(2.0)

        if result != 0:
            raise ConnectionError(
                f"RFCOMM open failed on channel {self._rfcomm_channel_id}: "
                f"0x{result & 0xFFFFFFFF:08X}"
            )

        self._channel = channel
        self._is_open = True
        log.info(f"[RFCOMMPort] RFCOMM channel {self._rfcomm_channel_id} "
                 f"open to {self._mac}")

    def close(self) -> None:
        if not self._is_open:
            return
        self._is_open = False
        if self._channel:
            try:
                self._channel.closeChannel()
            except Exception:
                pass
            self._channel = None
        self._delegate = None
        log.info(f"[RFCOMMPort] closed")

    # -- read / write -------------------------------------------------------

    def write(self, data: bytes) -> int:
        if not self._is_open or not self._channel:
            raise IOError("RFCOMM port not open")
        result = self._channel.writeSync_length_(data, len(data))
        if result != 0:
            raise IOError(
                f"RFCOMM write failed: 0x{result & 0xFFFFFFFF:08X}"
            )
        _run_loop(0.05)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self._is_open:
            return b""
        deadline = time.time() + self._timeout
        result = bytearray()
        while len(result) < size:
            with self._rx_lock:
                while self._rx_buffer and len(result) < size:
                    result.append(self._rx_buffer.popleft())
            if len(result) >= size:
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            _run_loop(min(0.1, remaining))
        return bytes(result)

    def reset_input_buffer(self) -> None:
        with self._rx_lock:
            self._rx_buffer.clear()
        self._rx_event.clear()

    def reset_output_buffer(self) -> None:
        pass  # RFCOMM has no output buffer we can flush

    # -- delegate callbacks (called from ObjC) ------------------------------

    def _on_data_received(self, data: bytes) -> None:
        with self._rx_lock:
            self._rx_buffer.extend(data)
        self._rx_event.set()

    def _on_channel_closed(self) -> None:
        self._is_open = False
        self._channel = None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_rfcomm_available() -> bool:
    """``True`` if running on macOS with PyObjC IOBluetooth installed."""
    return IS_MACOS and PYOBJC_AVAILABLE


def is_bt_serial_port(device: str) -> bool:
    """``True`` if *device* is a macOS BT serial path matching a paired device.

    Returns ``False`` immediately on non-macOS or if PyObjC is missing.
    """
    if not IS_MACOS or not PYOBJC_AVAILABLE:
        return False
    import os

    if not device.startswith("/dev/"):
        return False
    name = os.path.basename(device)
    for prefix in ("cu.", "tty."):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    # Skip things that are clearly USB or debug ports
    if name.startswith("usb") or name == "debug-console":
        return False
    devices = IOBluetoothDevice.pairedDevices()
    if devices:
        for d in devices:
            if (d.name() or "").lower() == name.lower():
                return True
    return False
