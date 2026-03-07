"""
Device definitions  --  electrostim and generic haptic output devices.

Each device model declares its axis map (channel name -> value range/type).
This module is pure data  --  no I/O, no UI.  The RoutingMatrix and output
backends consume these definitions at runtime.

Axis value convention (matching funscript):
    0-100 integer   (position / intensity percentage)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple


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


# ---------------------------------------------------------------------------
# Channel tree -- hierarchical menu structure for adding channels
# ---------------------------------------------------------------------------
# Each entry is (label, axis_name | None, children | None).
# If axis_name is set it's a leaf.  If children is set it's a sub-menu.

ChannelTreeNode = Tuple[str, Optional[str], Optional[List[Any]]]


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
    channel_tree: List[Any] = field(default_factory=list)
    # Hierarchical tree for the "add channel" menu.
    # List of ChannelTreeNode: (label, axis_name|None, children|None)
    # Leaf: ("A Level", "channel_a", None)
    # Branch: ("Channel A", None, [leaf, leaf, ...])

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


# -- DG-Lab Coyote (2 independent channels) ----------------------------
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

# -- DG-Lab Coyote 3 (3 channels) -------------------------------------
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

# -- MK-312BT (ErosTek clone  --  2 channels) ----------------------------
# All axis names MUST match keys in backends._MK312_AXIS_MAP so that
# the routing matrix can drive any parameter via funscript tracks.
_register(DeviceModel(
    model_id="mk312bt",
    label="MK-312BT",
    manufacturer="Community",
    protocol="serial",
    description="ErosTek ET-312 clone, serial protocol, 2 channels + full register map",
    axes=[
        # -- Core levels --------------------------------------------
        AxisDef("channel_a",        "Channel A Level",      AxisKind.INTENSITY),
        AxisDef("channel_b",        "Channel B Level",      AxisKind.INTENSITY),
        AxisDef("ma",               "Multi-Adjust",         AxisKind.INTENSITY),
        AxisDef("current_mode",     "Current Mode",         AxisKind.PATTERN),
        # -- Channel A: Ramp ----------------------------------------
        AxisDef("a_ramp_value",     "A Ramp Value",         AxisKind.INTENSITY),
        AxisDef("a_ramp_min",       "A Ramp Min",           AxisKind.INTENSITY),
        AxisDef("a_ramp_max",       "A Ramp Max",           AxisKind.INTENSITY),
        AxisDef("a_ramp_rate",      "A Ramp Rate",          AxisKind.INTENSITY),
        # -- Channel A: Gate ----------------------------------------
        AxisDef("a_gate_value",     "A Gate Value",         AxisKind.INTENSITY),
        AxisDef("a_gate_ontime",    "A Gate On Time",       AxisKind.INTENSITY),
        AxisDef("a_gate_offtime",   "A Gate Off Time",      AxisKind.INTENSITY),
        AxisDef("a_gate_select",    "A Gate Select",        AxisKind.INTENSITY),
        # -- Channel A: Frequency -----------------------------------
        AxisDef("a_freq_value",     "A Freq Value",         AxisKind.FREQUENCY),
        AxisDef("a_freq_min",       "A Freq Min",           AxisKind.FREQUENCY),
        AxisDef("a_freq_max",       "A Freq Max",           AxisKind.FREQUENCY),
        AxisDef("a_freq_rate",      "A Freq Rate",          AxisKind.INTENSITY),
        # -- Channel A: Width --------------------------------------
        AxisDef("a_width_value",    "A Width Value",        AxisKind.INTENSITY),
        AxisDef("a_width_min",      "A Width Min",          AxisKind.INTENSITY),
        AxisDef("a_width_max",      "A Width Max",          AxisKind.INTENSITY),
        AxisDef("a_width_rate",     "A Width Rate",         AxisKind.INTENSITY),
        # -- Channel A: Intensity ----------------------------------
        AxisDef("a_intensity",      "A Intensity Value",    AxisKind.INTENSITY),
        AxisDef("a_intensity_min",  "A Intensity Min",      AxisKind.INTENSITY),
        AxisDef("a_intensity_max",  "A Intensity Max",      AxisKind.INTENSITY),
        AxisDef("a_intensity_rate", "A Intensity Rate",     AxisKind.INTENSITY),
        # -- Channel B: Ramp ----------------------------------------
        AxisDef("b_ramp_value",     "B Ramp Value",         AxisKind.INTENSITY),
        AxisDef("b_ramp_min",       "B Ramp Min",           AxisKind.INTENSITY),
        AxisDef("b_ramp_max",       "B Ramp Max",           AxisKind.INTENSITY),
        AxisDef("b_ramp_rate",      "B Ramp Rate",          AxisKind.INTENSITY),
        # -- Channel B: Gate ----------------------------------------
        AxisDef("b_gate_value",     "B Gate Value",         AxisKind.INTENSITY),
        AxisDef("b_gate_ontime",    "B Gate On Time",       AxisKind.INTENSITY),
        AxisDef("b_gate_offtime",   "B Gate Off Time",      AxisKind.INTENSITY),
        AxisDef("b_gate_select",    "B Gate Select",        AxisKind.INTENSITY),
        # -- Channel B: Frequency -----------------------------------
        AxisDef("b_freq_value",     "B Freq Value",         AxisKind.FREQUENCY),
        AxisDef("b_freq_min",       "B Freq Min",           AxisKind.FREQUENCY),
        AxisDef("b_freq_max",       "B Freq Max",           AxisKind.FREQUENCY),
        AxisDef("b_freq_rate",      "B Freq Rate",          AxisKind.INTENSITY),
        # -- Channel B: Width --------------------------------------
        AxisDef("b_width_value",    "B Width Value",        AxisKind.INTENSITY),
        AxisDef("b_width_min",      "B Width Min",          AxisKind.INTENSITY),
        AxisDef("b_width_max",      "B Width Max",          AxisKind.INTENSITY),
        AxisDef("b_width_rate",     "B Width Rate",         AxisKind.INTENSITY),
        # -- Channel B: Intensity ----------------------------------
        AxisDef("b_intensity",      "B Intensity Value",    AxisKind.INTENSITY),
        AxisDef("b_intensity_min",  "B Intensity Min",      AxisKind.INTENSITY),
        AxisDef("b_intensity_max",  "B Intensity Max",      AxisKind.INTENSITY),
        AxisDef("b_intensity_rate", "B Intensity Rate",     AxisKind.INTENSITY),
        # -- Advanced / Panel --------------------------------------
        AxisDef("ramp_select",      "Ramp Select",          AxisKind.INTENSITY),
        AxisDef("ramp_level",       "Ramp Level",           AxisKind.INTENSITY),
        AxisDef("power_level",      "Power Level",          AxisKind.INTENSITY),
    ],
    channel_tree=[
        # Top-level categories
        ("Core", None, [
            ("Channel A Level",  "channel_a",    None),
            ("Channel B Level",  "channel_b",    None),
            ("Multi-Adjust",     "ma",           None),
            ("Current Mode",     "current_mode", None),
        ]),
        ("Channel A", None, [
            ("Ramp", None, [
                ("A Ramp Value", "a_ramp_value", None),
                ("A Ramp Min",   "a_ramp_min",   None),
                ("A Ramp Max",   "a_ramp_max",   None),
                ("A Ramp Rate",  "a_ramp_rate",  None),
            ]),
            ("Gate", None, [
                ("A Gate Value",    "a_gate_value",   None),
                ("A Gate On Time",  "a_gate_ontime",  None),
                ("A Gate Off Time", "a_gate_offtime", None),
                ("A Gate Select",   "a_gate_select",  None),
            ]),
            ("Frequency", None, [
                ("A Freq Value", "a_freq_value", None),
                ("A Freq Min",   "a_freq_min",   None),
                ("A Freq Max",   "a_freq_max",   None),
                ("A Freq Rate",  "a_freq_rate",  None),
            ]),
            ("Width", None, [
                ("A Width Value", "a_width_value", None),
                ("A Width Min",   "a_width_min",   None),
                ("A Width Max",   "a_width_max",   None),
                ("A Width Rate",  "a_width_rate",  None),
            ]),
            ("Intensity", None, [
                ("A Intensity Value", "a_intensity",      None),
                ("A Intensity Min",   "a_intensity_min",  None),
                ("A Intensity Max",   "a_intensity_max",  None),
                ("A Intensity Rate",  "a_intensity_rate", None),
            ]),
        ]),
        ("Channel B", None, [
            ("Ramp", None, [
                ("B Ramp Value", "b_ramp_value", None),
                ("B Ramp Min",   "b_ramp_min",   None),
                ("B Ramp Max",   "b_ramp_max",   None),
                ("B Ramp Rate",  "b_ramp_rate",  None),
            ]),
            ("Gate", None, [
                ("B Gate Value",    "b_gate_value",   None),
                ("B Gate On Time",  "b_gate_ontime",  None),
                ("B Gate Off Time", "b_gate_offtime", None),
                ("B Gate Select",   "b_gate_select",  None),
            ]),
            ("Frequency", None, [
                ("B Freq Value", "b_freq_value", None),
                ("B Freq Min",   "b_freq_min",   None),
                ("B Freq Max",   "b_freq_max",   None),
                ("B Freq Rate",  "b_freq_rate",  None),
            ]),
            ("Width", None, [
                ("B Width Value", "b_width_value", None),
                ("B Width Min",   "b_width_min",   None),
                ("B Width Max",   "b_width_max",   None),
                ("B Width Rate",  "b_width_rate",  None),
            ]),
            ("Intensity", None, [
                ("B Intensity Value", "b_intensity",      None),
                ("B Intensity Min",   "b_intensity_min",  None),
                ("B Intensity Max",   "b_intensity_max",  None),
                ("B Intensity Rate",  "b_intensity_rate", None),
            ]),
        ]),
        ("Advanced", None, [
            ("Ramp Select", "ramp_select",  None),
            ("Ramp Level",  "ramp_level",   None),
            ("Power Level", "power_level",  None),
        ]),
    ],
))

# -- ErosTek ET-312B ---------------------------------------------------
# Same register map as MK-312BT
_mk312_ref = DEVICE_CATALOGUE["mk312bt"]
_register(DeviceModel(
    model_id="et312b",
    label="ErosTek ET-312B",
    manufacturer="ErosTek",
    protocol="serial",
    description="ET-312B estim box, serial/link, 2 channels + full register map",
    axes=_mk312_ref.axes[:],
    channel_tree=_mk312_ref.channel_tree[:],
))

# -- 2B (SmartStim) ---------------------------------------------------
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

# -- Generic Buttplug.io device ----------------------------------------
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

# -- OSR / SR6 (TCode stroker) ----------------------------------------
_register(DeviceModel(
    model_id="osr_sr6",
    label="OSR / SR6",
    manufacturer="Community",
    protocol="serial",
    description="Open-Source Stroker / SR6 - TCode over serial, 6+ axes",
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


# -- PiShock / OpenShock (RF shock collar controller) ----------------------
_register(DeviceModel(
    model_id="pishock",
    label="PiShock / OpenShock",
    manufacturer="OpenShock",
    protocol="serial",
    description="RF shock collar controller (shock, vibrate, beep) via serial or WiFi bridge",
    axes=[
        AxisDef("shock_intensity",   "Shock Intensity",   AxisKind.INTENSITY,
                range_min=0, range_max=100, default=0),
        AxisDef("vibrate_intensity", "Vibrate Intensity", AxisKind.INTENSITY,
                range_min=0, range_max=100, default=0),
        AxisDef("beep",              "Beep",              AxisKind.TOGGLE,
                range_min=0, range_max=100, default=0),
    ],
    channel_tree=[
        ("Shock",   "shock_intensity",   None),
        ("Vibrate", "vibrate_intensity", None),
        ("Beep",    "beep",              None),
    ],
))

# -- OSSM (Open Source Sex Machine) ----------------------------------------
_register(DeviceModel(
    model_id="ossm",
    label="OSSM (Stroker)",
    manufacturer="KinkyMakers / R&D",
    protocol="ble",
    description="Open Source Sex Machine — real-time position streaming via BLE or WiFi bridge",
    axes=[
        AxisDef("stroke",    "Stroke Position", AxisKind.POSITION,
                range_min=0, range_max=100, default=50),
        AxisDef("speed",     "Speed",           AxisKind.INTENSITY,
                range_min=0, range_max=100, default=0),
        AxisDef("depth",     "Depth",           AxisKind.INTENSITY,
                range_min=0, range_max=100, default=50),
        AxisDef("sensation", "Sensation",       AxisKind.INTENSITY,
                range_min=0, range_max=100, default=50),
    ],
    channel_tree=[
        ("Stroke Position", "stroke",    None),
        ("Speed",           "speed",     None),
        ("Depth",           "depth",     None),
        ("Sensation",       "sensation", None),
    ],
))

# -- ESP GPIO Bridge (generic WiFi-controlled outputs) ---------------------
_register(DeviceModel(
    model_id="esp_gpio",
    label="ESP GPIO Bridge",
    manufacturer="Custom",
    protocol="ws_bridge",
    description="ESP8266/32 over WiFi — servo, MOSFET PWM, relay outputs via WebSocket",
    axes=[
        AxisDef("servo_1",  "Servo 1",  AxisKind.POSITION),
        AxisDef("servo_2",  "Servo 2",  AxisKind.POSITION),
        AxisDef("pwm_1",    "PWM 1",    AxisKind.INTENSITY),
        AxisDef("pwm_2",    "PWM 2",    AxisKind.INTENSITY),
        AxisDef("relay_1",  "Relay 1",  AxisKind.TOGGLE),
        AxisDef("relay_2",  "Relay 2",  AxisKind.TOGGLE),
    ],
    channel_tree=[
        ("Servos", None, [
            ("Servo 1", "servo_1", None),
            ("Servo 2", "servo_2", None),
        ]),
        ("PWM", None, [
            ("PWM 1", "pwm_1", None),
            ("PWM 2", "pwm_2", None),
        ]),
        ("Relays", None, [
            ("Relay 1", "relay_1", None),
            ("Relay 2", "relay_2", None),
        ]),
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
