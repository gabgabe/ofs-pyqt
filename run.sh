#!/bin/bash
# Script di avvio per OFS-PyQt
# Nota: non usare DYLD_LIBRARY_PATH (causa conflitti di librerie con mpv su macOS).
# libmpv è caricata direttamente dal path Homebrew via patch in mpv.py.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
