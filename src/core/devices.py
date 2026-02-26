"""
Device definitions — electrostim and generic haptic output devices.

Each device model declares its axis map (channel name → value range/type).
This module is pure data — no I/O, no UI.  The RoutingMatrix and output
backends consume these definitions at runtime.

Axis value convention (matching funscript):
    0–100 integer   (position / intensity percentage)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Axis descriptor
# ---------------------------------------------------------------------------

class AxisKind(Enum):
    """How a single device axis is driven."""
    POSITION  = auto()   # 0-100 linear position (default funscript mapping)
    INTENSITY = auto()   # 0-100 intensity / level
    FREQUENCY = auto()   # 0-100 mapped to device-specific Hz range
    PATTERN   = auto()   # 0-100 mapped to pattern index
    TOGGLE    = auto()   # 0 = off, >0 = on


@dataclass
class AxisDef:
    """Description of a single axis on a device."""
    name: str               # e.g. "channel_a", "vibrate"
    label: str = ""         # human-readable, e.g. "Channel A"
    kind: AxisKind = AxisKind.INTENSITY
    range_min: int = 0
    range_max: int = 100
    default: int = 0

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Device model
# ---------------------------------------------------------------------------

@dataclass
class DeviceModel:
    """Static description of a device model (not an instance)."""
    model_id: str              # unique key, e.g. "mk312bt"
    label: str                 # human display name
    manufacturer: str = ""
    axes: List[AxisDef] = field(default_factory=list)
    protocol: str = ""         # "serial", "ble", "buttplug", "dg-lab"
    description: str = ""

    @property
    def axis_names(self) -> List[str]:
        return [a.name for a in self.axes]


# ---------------------------------------------------------------------------
# OFS standard WebSocket output axes
# ---------------------------------------------------------------------------
# These mirror the TCode / OSR / OFS multi-axis naming convention
# as seen in Funscript.AXIS_NAMES and the OFS WebSocket protocol.

OFS_WS_OUTPUT_AXES: List[AxisDef] = [
    AxisDef("stroke",  "Stroke (L0)",  AxisKind.POSITION),
    AxisDef("surge",   "Surge (L1)",   AxisKind.POSITION),
    AxisDef("sway",    "Sway (L2)",    AxisKind.POSITION),
    AxisDef("twist",   "Twist (R0)",   AxisKind.POSITION),
    AxisDef("roll",    "Roll (R1)",    AxisKind.POSITION),
    AxisDef("pitch",   "Pitch (R2)",   AxisKind.POSITION),
    AxisDef("vib",     "Vib (V0)",     AxisKind.INTENSITY),
    AxisDef("pump",    "Pump (A0)",    AxisKind.POSITION),
    AxisDef("suck",    "Suck (A1)",    AxisKind.INTENSITY),
    AxisDef("raw",     "Raw (A2)",     AxisKind.POSITION),
]


# ---------------------------------------------------------------------------
# Built-in device catalogue
# ---------------------------------------------------------------------------

DEVICE_CATALOGUE: Dict[str, DeviceModel] = {}


def _register(dev: DeviceModel) -> DeviceModel:
    DEVICE_CATALOGUE[dev.model_id] = dev
    return dev


# ── DG-Lab Coyote (2 independent channels) ────────────────────────────
_register(DeviceModel(
    model_id="dg_lab_coyote",
    label="DG-Lab Coyote",
    manufacturer="DG-Lab",
    protocol="dg-lab",
    description="Dual-channel electrostim via BLE / WebSocket",
    axes=[
        AxisDef("channel_a", "Channel A", AxisKind.INTENSITY),
        AxisDef("channel_b", "Channel B", AxisKind.INTENSITY),
        AxisDef("freq_a",    "Freq A",    AxisKind.FREQUENCY),
        AxisDef("freq_b",    "Freq B",    AxisKind.FREQUENCY),
    ],
))

# ── DG-Lab Coyote 3 (3 channels) ─────────────────────────────────────
_register(DeviceModel(
    model_id="dg_lab_coyote3",
    label="DG-Lab Coyote 3",
    manufacturer="DG-Lab",
    protocol="dg-lab",
    description="Three-channel electrostim (BLE 5.0)",
    axes=[
        AxisDef("channel_a", "Channel A", AxisKind.INTENSITY),
        AxisDef("channel_b", "Channel B", AxisKind.INTENSITY),
        AxisDef("channel_c", "Channel C", AxisKind.INTENSITY),
        AxisDef("freq_a",    "Freq A",    AxisKind.FREQUENCY),
        AxisDef("freq_b",    "Freq B",    AxisKind.FREQUENCY),
        AxisDef("freq_c",    "Freq C",    AxisKind.FREQUENCY),
    ],
))

# ── MK-312BT (ErosTek clone — 2 channels) ────────────────────────────
_register(DeviceModel(
    model_id="mk312bt",
    label="MK-312BT",
    manufacturer="Community",
    protocol="serial",
    description="ErosTek ET-312 clone, serial protocol, 2 channels",
    axes=[
        AxisDef("channel_a", "Channel A",  AxisKind.INTENSITY),
        AxisDef("channel_b", "Channel B",  AxisKind.INTENSITY),
        AxisDef("ma",        "Multi-Adjust", AxisKind.INTENSITY),
    ],
))

# ── ErosTek ET-312B ───────────────────────────────────────────────────
_register(DeviceModel(
    model_id="et312b",
    label="ErosTek ET-312B",
    manufacturer="ErosTek",
    protocol="serial",
    description="ET-312B estim box, serial/link, 2 channels",
    axes=[
        AxisDef("channel_a", "Channel A",  AxisKind.INTENSITY),
        AxisDef("channel_b", "Channel B",  AxisKind.INTENSITY),
        AxisDef("ma",        "Multi-Adjust", AxisKind.INTENSITY),
    ],
))

# ── 2B (SmartStim) ───────────────────────────────────────────────────
_register(DeviceModel(
    model_id="2b",
    label="2B",
    manufacturer="SmartStim / E-Stim Systems",
    protocol="serial",
    description="2B estim power box, 2 channels",
    axes=[
        AxisDef("channel_a", "Channel A", AxisKind.INTENSITY),
        AxisDef("channel_b", "Channel B", AxisKind.INTENSITY),
    ],
))

# ── Generic Buttplug.io device ────────────────────────────────────────
_register(DeviceModel(
    model_id="buttplug_generic",
    label="Buttplug.io (Generic)",
    manufacturer="Various",
    protocol="buttplug",
    description="Any device reachable via Buttplug.io / Intiface Central",
    axes=[
        AxisDef("vibrate",   "Vibrate",   AxisKind.INTENSITY),
        AxisDef("rotate",    "Rotate",    AxisKind.POSITION),
        AxisDef("linear",    "Linear",    AxisKind.POSITION),
    ],
))

# ── OSR / SR6 (TCode stroker) ────────────────────────────────────────
_register(DeviceModel(
    model_id="osr_sr6",
    label="OSR / SR6",
    manufacturer="Community",
    protocol="serial",
    description="Open-Source Stroker / SR6 — TCode over serial, 6+ axes",
    axes=[
        AxisDef("stroke", "Stroke (L0)", AxisKind.POSITION),
        AxisDef("surge",  "Surge (L1)",  AxisKind.POSITION),
        AxisDef("sway",   "Sway (L2)",   AxisKind.POSITION),
        AxisDef("twist",  "Twist (R0)",  AxisKind.POSITION),
        AxisDef("roll",   "Roll (R1)",   AxisKind.POSITION),
        AxisDef("pitch",  "Pitch (R2)",  AxisKind.POSITION),
        AxisDef("vib",    "Vib (V0)",    AxisKind.INTENSITY),
        AxisDef("pump",   "Pump (A0)",   AxisKind.POSITION),
    ],
))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_device_model(model_id: str) -> DeviceModel | None:
    """Look up a device model by ID."""
    return DEVICE_CATALOGUE.get(model_id)


def list_device_models() -> List[DeviceModel]:
    """Return all registered device models, sorted by label."""
    return sorted(DEVICE_CATALOGUE.values(), key=lambda d: d.label)
