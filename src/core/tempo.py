"""
Tempo / beat subdivision constants — shared between ScriptTimeline and ScriptingMode.

Mirrors ``OFS::beatMultiples[]`` / ``OFS::beatMultipleColor[]`` from ``BaseOverlayState.h``.
"""

from __future__ import annotations

# Beat subdivisions (fraction of a whole note = 4 beats).
# Index 0 = whole measures, index 9 = 64ths.
BEAT_MULTIPLES: list[float] = [
    4.0,                # whole measures
    4.0 * (1 / 2),     # 2nds
    4.0 * (1 / 4),     # 4ths
    4.0 * (1 / 8),     # 8ths
    4.0 * (1 / 12),    # 12ths
    4.0 * (1 / 16),    # 16ths
    4.0 * (1 / 24),    # 24ths
    4.0 * (1 / 32),    # 32nds
    4.0 * (1 / 48),    # 48ths
    4.0 * (1 / 64),    # 64ths
]

BEAT_NAMES: list[str] = [
    "Whole measures", "2nds", "4ths", "8ths",
    "12ths", "16ths", "24ths", "32nds", "48ths", "64ths",
]

# Colours per subdivision (RGBA 0–1 tuples, OFS beatMultipleColor[]).
# Converted to imgui u32 by consumers as needed.
BEAT_COLORS_RGBA: list[tuple[float, float, float, float]] = [
    (0xBB / 255, 0xBE / 255, 0xBC / 255, 1.0),  # whole measures
    (0x53 / 255, 0xD3 / 255, 0xDF / 255, 1.0),  # 2nds
    (0xC1 / 255, 0x65 / 255, 0x77 / 255, 1.0),  # 4ths
    (0x24 / 255, 0x54 / 255, 0x99 / 255, 1.0),  # 8ths
    (0xC8 / 255, 0x86 / 255, 0xEE / 255, 1.0),  # 12ths
    (0xD2 / 255, 0xCC / 255, 0x23 / 255, 1.0),  # 16ths
    (0xEA / 255, 0x8D / 255, 0xE0 / 255, 1.0),  # 24ths
    (0xE7 / 255, 0x97 / 255, 0x5C / 255, 1.0),  # 32nds
    (0xEB / 255, 0x38 / 255, 0x99 / 255, 1.0),  # 48ths
    (0x23 / 255, 0xD2 / 255, 0x54 / 255, 1.0),  # 64ths
]


def tempo_beat_time(bpm: float, measure_idx: int) -> float:
    """Seconds per subdivided beat for given BPM and subdivision index."""
    return (60.0 / max(1.0, bpm)) * BEAT_MULTIPLES[measure_idx]
