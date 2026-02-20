"""
OpenFunscripter — Python port
Entry point.  No Qt.  Uses Dear ImGui (imgui-bundle) + SDL2 + mpv render context.

Usage:
    python main.py [<media_or_project_file>]
"""

import sys
import logging
from pathlib import Path

# Add project root to path so `src.*` imports work
root_path = Path(__file__).resolve().parent
sys.path.insert(0, str(root_path))

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ofs")


def main():
    cli_file = sys.argv[1] if len(sys.argv) > 1 else None

    from src.ui.app import OpenFunscripter

    ofs = OpenFunscripter()
    if not ofs.Init(cli_file):
        log.error("Init failed — aborting")
        sys.exit(1)

    ofs.Run()


if __name__ == "__main__":
    main()
