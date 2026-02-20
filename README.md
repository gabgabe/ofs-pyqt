# OpenFunscripter — Python Port

A complete Python port of [OpenFunscripter](https://github.com/OpenFunscripter/OpenFunscripter) using **Dear ImGui** (via imgui-bundle), **mpv**, and **PyOpenGL**.

## Overview

This is a faithful recreation of the full OFS scripting interface in Python, including:
- **Video playback** with frame-perfect control via mpv
- **Multi-track funscript editing** (load multiple .funscript files)
- **Scripting modes**: Normal, Recording, **Alternating** (auto top/bottom)
- **Special functions**: RDP simplification, range extension, scaling, limiting
- **Undo/Redo system** with 23+ operation types (mirrors OFS exactly)
- **Timeline** with action interaction (click to seek, click dots to select/move)
- **Panels**: Statistics, Undo History, Project manager, Preferences, WebSocket API
- **Project save/load** (.ofsp format) with auto-backup
- **Heatmap visualization** showing action density over time

## Quick Start

### Prerequisites
- Python 3.11+
- macOS, Linux, or Windows

### Installation

1. **Clone & setup**:
   ```bash
   git clone https://github.com/yourusername/ofs-pyqt.git
   cd ofs-pyqt
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run**:
   ```bash
   python main.py [video_path]
   ```

   Or via the shell wrapper:
   ```bash
   ./run.sh
   ```

## Architecture

```
src/
├── core/
│   ├── funscript.py          # Funscript data model + editing API
│   ├── undo_system.py        # 23 StateType operations
│   ├── project.py            # Project load/save, multi-track management
│   ├── video_player.py       # mpv wrapper with frame control
│   ├── events.py             # Event bus (ACTION_CLICKED, etc.)
│   ├── keybindings.py        # Keyboard shortcuts
│   └── websocket_api.py      # WebSocket server for external control
├── cueing/
│   └── cue_manager.py        # Chapter/cue management
├── rendering/
│   ├── funscript_overlay.py  # Timeline rendering (action dots, lines)
│   ├── funscript_viewport.py # Video viewport + heatmap gradient
│   └── [GL rendering helpers]
└── ui/
    ├── app.py                # Main application (hello_imgui runner)
    ├── script_timeline.py    # Interactive timeline widget
    ├── videoplayer_controls.py
    ├── widgets/
    │   ├── timeline_widget.py
    │   ├── heatmap_widget.py
    │   └── ...
    └── panels/
        ├── special_functions.py    # RDP, range extend, scale, limit
        ├── scripting_mode.py       # Normal/Recording/Alternating modes
        ├── simulator.py            # 2D interpolation simulator
        ├── statistics.py           # Action distribution stats
        ├── undo_history.py         # Undo/Redo browser
        ├── preferences.py          # Settings with JSON persistence
        ├── chapter_manager.py
        ├── metadata_editor.py
        └── action_editor.py        # Single-action editor
```

## Key Features

### Scripting Modes
- **Normal**: Click to place actions, auto-frame-advance
- **Recording**: Record continuously while playing
- **Alternating**: Auto-toggle between top (100) and bottom (0), with context-sensitivity and fixed ranges
- **Dynamic**: (placeholder for advanced dynamics)

### Special Functions
- **RDP Simplify**: Reduce point count while preserving shape
- **Range Extender**: Stretch or compress positions (stroke-aware)
- **Limit Range**: Clamp positions to min/max
- **Scale**: Multiply all positions by a percentage
- **Remove every Nth**: Thin out selections

### Timeline Interaction
- **Click**: Seek to position
- **Click action dot**: Select or seek to action
- **Ctrl+click**: Select time range or create action at cursor
- **Drag action dot**: Move action to new time/position
- **Middle-drag**: Scroll timeline (non-follow mode)
- **Scroll + Ctrl**: Zoom timeline

### Project Management
- Load/save `.ofsp` project files
- Import from video files (auto-creates default script)
- Import from existing `.funscript` files
- Multiple scripts per project (mix of axes: surge, sway, suck, twist, roll, pitch, vib, pump, raw)
- Per-script enable/disable, repath
- Auto-backup to `~/.openFunscripter/backup/`
- Quick export to `.funscript` or all scripts

### Advanced
- **WebSocket API**: Control playback, speed, time from external tools
- **Undo/Redo**: 23 StateType operations (ADD_ACTION, MOVE, SIMPLIFY, RANGE_EXTEND, etc.)
- **Heatmap**: Density visualization (darker = more actions)
- **Preferences**: JSON-persisted settings (keybinds, window geometry, player FPS)
- **Close-without-saving dialog**: Protects unsaved work

## Configuration

Edit preferences in the UI or directly in `~/.openFunscripter/`:
- `preferences.json` — keyboard bindings, player settings, geometry
- `OpenFunscripter.ini` — state across sessions

## Development

### Adding a Scripting Mode
1. Add enum to `ScriptingModeEnum` in `scripting_mode.py`
2. Implement mode class with `add_edit_action()`, `Undo()`, `Redo()`, `Show()`
3. Register in the mode selector combo

### Adding a Panel
1. Create `src/ui/panels/my_panel.py` with a class `MyPanel()`
2. Add `show_my_panel: bool` to `OpenFunscripter.__init__`
3. Call `self.my_panel.Show()` in `_show_gui()`
4. Add File/View menu item to toggle visibility

### Extending Undo/Redo
1. Add new `StateType` to `undo_system.py`
2. Call `undo.snapshot(StateType.MY_OP, script)` before edits
3. Implement undo handler if custom logic needed (most use default serialization)

## Testing

All 19 core modules import cleanly. To verify:
```bash
python -c "
import sys
sys.path.insert(0, '.')
for m in ['src.core.funscript', 'src.core.project', 'src.ui.app']:
    __import__(m)
    print(f'{m}: OK')
"
```

## Known Limitations

- **Spline interpolation**: Simulator uses linear interpolation (OFS uses Catmull-Rom spline). Low priority.
- **Lua extensions**: `CUSTOM_LUA` StateType exists but no Lua interpreter integrated. Can be added if needed.
- **Drag-and-drop**: No SDL DragNDrop handler yet. Use File → Open instead.
- **TempoOverlay**: Beat-based frame stepping not implemented. Easy to add if needed.

## Comparison to OFS (C++)

| Feature | Status |
|---------|--------|
| Multi-track scripts | ✅ Full |
| Undo/Redo (23 ops) | ✅ Complete |
| Scripting modes | ✅ Normal, Recording, Alternating |
| Special functions | ✅ All except Lua |
| Timeline interaction | ✅ Click/drag/create/move |
| Project save/load | ✅ Full |
| Panels (Stats, History, etc.) | ✅ All implemented |
| Preferences persistence | ✅ JSON-based |
| WebSocket API | ✅ 3 commands |
| Heatmap | ✅ Yes |
| Spline interpolation | ⚠️ Linear only |
| Lua extensions | ❌ Not yet |
| Drag-and-drop file open | ⚠️ Menu only |

## License

This is a fan port inspired by [OpenFunscripter](https://github.com/OpenFunscripter/OpenFunscripter). Refer to OFS's original license for terms.

## Contributing

Pull requests welcome! Areas for contribution:
- Spline interpolation for simulator
- Lua extension system
- Drag-and-drop file opening
- Performance optimizations
- Additional scripting modes

## References

- [OpenFunscripter GitHub](https://github.com/OpenFunscripter/OpenFunscripter)
- [Dear ImGui](https://github.com/ocornut/imgui)
- [imgui-bundle](https://github.com/pthom/imgui_bundle)
- [python-mpv](https://github.com/jaseg/python-mpv)
# ofs-pyqt
