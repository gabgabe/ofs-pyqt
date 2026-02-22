"""Shared constants for OpenFunscripter UI layer.

Extracted so that both ``app.py`` and mixin modules can import them
without circular-import issues.
"""

# ── Status flags (mirrors OFS_Status) ─────────────────────────────────────
class OFS_Status:
    """Bit-flag constants for application status. Mirrors ``OFS_Status`` in OpenFunscripter.h."""

    NONE                  = 0x0
    SHOULD_EXIT           = 0x1
    FULLSCREEN            = 0x1 << 1
    GRADIENT_NEEDS_UPDATE = 0x1 << 2
    AUTO_BACKUP           = 0x1 << 4


AUTO_BACKUP_INTERVAL = 60  # seconds

# Mirrors Funscript::AxisNames from OFS
FUNSCRIPT_AXIS_NAMES = (
    "surge", "sway", "suck", "twist", "roll",
    "pitch", "vib", "pump", "raw",
)
