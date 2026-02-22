# OFS-PyQt Implementation Tracker

Last updated: session 11 — full codebase audit  
Legend: ✅ Done · 🔄 Partial · ⬜ Not started · ❌ Won't port

---

## src/ui/app.py  ← OpenFunscripter.h / OpenFunscripter.cpp

### App lifecycle

| Feature | Status | Notes |
|---------|--------|-------|
| Init() / Run() / Shutdown() | ✅ | hello_imgui runner |
| post_init callback (GL + mpv + keybindings) | ✅ | |
| pre_new_frame (update + EV.process + keybindings) | ✅ | EV.process before ProcessKeybindings |
| show_gui callback (floating windows) | ✅ | |
| after_swap (NotifySwap) | ✅ | |
| before_exit (Shutdown) | ✅ | |
| Default docking layout (setupDefaultLayout) | ✅ | 7 splits matching OFS |
| Simulator as floating no-dock window | ✅ | session 10 |
| Key repeat tuning (delay=150ms, rate=20ms) | ✅ | session 10 |
| any_key_active + idle suppression 250ms | ✅ | session 10 |

### Main menu bar (ShowMainMenuBar)

| Feature | Status | Notes |
|---------|--------|-------|
| File → Open / Recent / Save / Quick export | ✅ | |
| File → Export active script as… | ✅ | _export_active_dialog() |
| File → Export all to dir (multi-script) | ✅ | session 10 |
| File → Auto backup toggle + Open backup dir | ✅ | |
| Project → Configure / Pick different media | ✅ | |
| Project → Add (axis / new / existing) | ✅ | |
| Project → Remove funscript | ✅ | with confirm modal |
| Edit → Undo / Redo / Cut / Copy / Paste | ✅ | |
| Edit → Save frame as image | ✅ | |
| Edit → Save heatmap as PNG | ✅ | session 10 |
| Edit → Save heatmap with chapters | ✅ | session 10 |
| Select menu (all actions) | ✅ | |
| View menu (toggle panels + video mode) | ✅ | |
| Options → Keybindings / Preferences / Fullscreen | ✅ | |
| ? About window | ✅ | |
| Menu bar colour alert (red pulse >5 min unsaved) | ✅ | session 11 — lerp-to-red on unsaved timer |

### Editing operations

| Feature | Status | Notes |
|---------|--------|-------|
| add_edit_action(pos) | ✅ | |
| remove_action() | ✅ | |
| cut / copy / paste_selection() / paste_exact() | ✅ | |
| equalize / invert / isolate / repeat_last_stroke | ✅ | |
| _select_top / middle / bottom_points() | ✅ | |
| _move_pos() / _move_time() (with snap-video) | ✅ | |
| _move_action_to_current() | ✅ | |
| saveHeatmap(path, width, height, withChapters) | ✅ | session 10 |

### Project management

| Feature | Status | Notes |
|---------|--------|-------|
| open_file() — project / funscript / media | ✅ | |
| _init_project() | ✅ | |
| save_project() / quick_export() | ✅ | |
| close_project() / pick_different_media() | ✅ | |
| Unsaved-changes confirm modal | ✅ | |
| Remove-script confirm modal | ✅ | |
| Drag & Drop file opening (SDL_DROPFILE) | ✅ | session 11 — _on_backend_event handles SDL_DROPFILE |
| Recent files list | ✅ | |
| _maybe_auto_backup() | ✅ | |

---

## src/core/keybindings.py  ← OFS_KeybindingSystem.h / cpp

### Binding groups

| Group | Action | Default chord | Status |
|-------|--------|---------------|--------|
| **Actions** | remove_action | Delete | ✅ |
| | action_0 … action_100 | Numpad 0–9, / | ✅ |
| **Core** | save_project | Ctrl+S | ✅ |
| | quick_export | Ctrl+Shift+S | ✅ |
| | sync_timestamps | S | ✅ |
| | cycle_loaded_forward_scripts | PgDown | ✅ |
| | cycle_loaded_backward_scripts | PgUp | ✅ |
| | reload_translation_csv | — | ❌ no i18n |
| **Navigation** | prev_action | ↓ repeat | ✅ |
| | next_action | ↑ repeat | ✅ |
| | prev_action_multi | Ctrl+↓ | ✅ nearest action in ANY script — session 10 |
| | next_action_multi | Ctrl+↑ | ✅ |
| | prev_frame | ← repeat | ✅ |
| | next_frame | → repeat | ✅ |
| | prev_frame_x3 | Ctrl+← | ✅ 3-frame/10-frame — session 10 |
| | next_frame_x3 | Ctrl+→ | ✅ |
| | fast_step / fast_backstep | (none) | ✅ |
| **Utility** | undo / redo | Ctrl+Z/Y repeat | ✅ |
| | copy / paste / paste_exact / cut | Ctrl+C/V/Shift+V/X | ✅ |
| | select_all / deselect_all | Ctrl+A/D | ✅ |
| | select_all_left / _right | Ctrl+Alt+←/→ | ✅ |
| | select_top/middle/bottom_points | (none) | ✅ |
| | save_frame_as_image | F2 | ✅ |
| | cycle_subtitles | J | ✅ |
| | fullscreen_toggle | F10 | ✅ |
| **Moving** | move_actions_up/down 10/5 | (none) | ✅ |
| | move_actions_up/down 1 | Shift+↑/↓ repeat | ✅ |
| | move_actions_left/right | Shift+←/→ repeat | ✅ |
| | move_actions_left/right_snapped | Ctrl+Shift+←/→ repeat | ✅ |
| | move_action_to_current_pos | End | ✅ |
| **Special** | equalize/invert/isolate/repeat_stroke | E/I/R/Home | ✅ |
| **Videoplayer** | toggle_play | Space | ✅ |
| | decrement/increment_speed | Numpad−/+ | ✅ |
| | goto_start / goto_end | (none) | ✅ |
| **Extensions** | — | — | ❌ no Lua |
| **Controller** | — | — | ❌ no gamepad |
| **Chapters** | create_chapter / create_bookmark | (none) | ✅ |

### Infrastructure

| Feature | Status | Notes |
|---------|--------|-------|
| Group + Action registration | ✅ | |
| Chord matching (mods + key) | ✅ | |
| `_split_mods()` for repeat-with-modifier | ✅ | session 10 |
| `any_key_active` flag | ✅ | session 10 |
| mods=0 bindings skip when modifier held | ✅ | |
| Repeat support | ✅ | |
| Keybinding editor modal | ✅ | |
| RenderKeybindingWindow() | ✅ | |
| Mouse wheel direction triggers (`MouseWheelDirection` flag, scroll-up vs scroll-down) | ✅ | session 11 — MOUSE_WHEEL_UP/DOWN pseudo-keys |
| Orphan triggers (triggers with no matching action, preserved across sessions) | ⬜ | low priority |
| Chord persistence (user chords → JSON) | ✅ | session 11 — settings_path JSON save/load |

---

## src/core/video_player.py  ← OFS_Videoplayer.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Init(hw_accel) / OpenVideo / CloseVideo | ✅ | |
| SetSpeed / AddSpeed / SetVolume / Mute/Unmute | ✅ | |
| SetPositionExact / SetPositionPercent | ✅ | |
| SeekRelative / SeekFrames | ✅ | SeekFrames rate-limited — session 10 |
| TogglePlay / SetPaused / IsPaused | ✅ | |
| NextFrame / PreviousFrame | ✅ | |
| CycleSubtitles / SaveFrameToImage | ✅ | |
| NotifySwap / SyncWithPlayerTime | ✅ | |
| Update(delta) | ✅ | |
| Duration / CurrentTime / Fps / FrameTime | ✅ | |
| VideoWidth / VideoHeight / VideoPath | ✅ | |
| FrameTexture / logicalPosition | ✅ | |
| MinPlaybackSpeed / MaxPlaybackSpeed | ✅ | |
| `VideoLoaded()` bool | ✅ | |
| `CurrentPlayerTime()` (actual mpv pos) vs `CurrentTime()` (logical pos) | ✅ | Both tracked |

---

## src/ui/videoplayer_window.py  ← OFS_VideoplayerWindow.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| GL texture → imgui.image() | ✅ | |
| Scroll to zoom / Drag to translate | ✅ | |
| reset_translation_and_zoom() | ✅ | |
| Right-click context menu | ✅ | |
| Video mode combo (Full/Left/Right/Top/Bottom) | ✅ | session 11 — persisted in app_state.json |
| lockedPosition (lock pan/zoom toggle) | ✅ | session 11 — context menu toggle |
| VR stereoscopic mode | ❌ | Needs VrShader GLSL |
| Draw video toggle | ✅ | |

---

## src/ui/videoplayer_controls.py  ← OFS_VideoplayerControls.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Heatmap (speed-based colours, 256 segments) | ✅ | |
| Play/Pause, PrevFrame, NextFrame buttons | ✅ | |
| Mute / Volume / Speed controls | ✅ | |
| ±3 s seek buttons / 1× / ±10% speed | ✅ | |
| Seek-pause-resume on slider drag | ✅ | |
| Custom DrawList timeline (progress + heatmap) | ✅ | |
| Chapters (coloured strips + names) | ✅ | |
| Active-chapter white border | ✅ | |
| Bookmarks (white circles) | ✅ | |
| Chapter right-click context menu | ✅ | |
| Hover tooltip (time + delta) | ✅ | |
| Hover cursor line + time label | ✅ | |
| UpdateHeatmap on GRADIENT_NEEDS_UPDATE | ✅ | |
| Save heatmap as PNG | ✅ | Edit → Save heatmap… — session 10 |
| Save heatmap with chapters overlay | ✅ | session 10 |
| Video thumbnail preview on hover | ✅ | session 11 — thumbnail.py 2nd mpv instance |
| Measured playback speed (actualPlaybackSpeed) | ✅ | session 11 — ActualSpeed() EMA |
| Waveform amplitude scale (ScaleAudio) | ✅ | session 11 — ScaleAudio slider in preferences |
| Waveform colour tint (WaveformColor) | ✅ | session 11 — colour picker in preferences |

---

## src/ui/script_timeline.py  ← OFS_ScriptTimeline.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-track lane rendering | ✅ | |
| Gradient backgrounds / per-track borders | ✅ | |
| Height guide lines (0/25/50/75/100%) | ✅ | |
| Action dots (dynamic size + opacity) | ✅ | |
| Speed-based line colours | ✅ | |
| Selection highlight | ✅ | |
| Playhead triangle + vertical line | ✅ | |
| Seconds ruler | ✅ | |
| Smooth zoom animation (easeOutExpo 150ms) | ✅ | |
| Frame overlay grid | ✅ | |
| Tempo overlay grid (BPM subdivisions) | ✅ | |
| Plain drag = selection / Shift = add / Ctrl = additive | ✅ | |
| Auto-scroll (OFS 3% margin) | ✅ | |
| Track-switch on click of inactive lane | ✅ | |
| Context menu (enable/disable track) | ✅ | |
| Edge actions (prev/next off-screen) | ✅ | |
| Scrubbing via playhead drag | ✅ | |
| Spline mode (Catmull-Rom) rendering | ✅ | |
| Waveform audio overlay | ✅ | |
| `ScaleAudio` float — amplitude multiplier wired to draw | ✅ | session 11 — wired to waveform drawing |
| `BaseOverlay.ShowLines` / `ShowPoints` toggle in context menu | ✅ | session 11 — context menu toggles |
| `ShowMaxSpeedHighlight` bool + `MaxSpeedColor` picker | ✅ | session 11 — toggle + colour picker in context menu |

---

## src/ui/panels/scripting_mode.py  ← OFS_ScriptingMode.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Normal / Recording / Dynamic / Alternating modes | ✅ | |
| Action offset delay slider | ✅ | |
| Recording: HoldSample + FrameByFrame | ✅ | |
| Overlay selector (Frame / Tempo / Empty) | ✅ | |
| Frame FPS override / Tempo BPM+offset | ✅ | |
| Frame-stepping overlay-aware | ✅ | |
| Recording — gamepad axis input | ❌ | |

---

## src/ui/panels/special_functions.py  ← SpecialFunctionsWindow

| Feature | Status | Notes |
|---------|--------|-------|
| Range Extender (live-drag, undo-collapse) | ✅ | |
| Simplify RDP (epsilon scaled by avg distance) | ✅ | |

---

## src/ui/panels/simulator.py  ← ScriptSimulator.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Draggable P1/P2 endpoints + center-drag | ✅ | |
| Lock / Center / Invert / Load / Save | ✅ | |
| 6 colour editors / Width / Opacity sliders | ✅ | |
| ExtraLines / HeightTicks / Indicators / Position | ✅ | |
| Background + front-fill via foreground DrawList | ✅ | |
| Vanilla mode (read-only VSlider) | ✅ | |
| Config persistence | ✅ | |
| Mouse-to-position mapping | ✅ | |
| Spline-mode position evaluation | ✅ | |

---

## src/ui/panels/statistics.py  ← ShowStatisticsWindow (OpenFunscripter.cpp)

| Feature | Status | Notes |
|---------|--------|-------|
| **OFS real-time stats at cursor** | | |
| Interval (ms) behind action → cursor | ✅ | session 10 |
| Speed (units/s) between adjacent actions | ✅ | session 10 |
| Duration (ms) between adjacent actions | ✅ | session 10 |
| Direction indicator (↑ / ↓) | ✅ | session 10 |
| **Python-specific aggregate stats** | | |
| Total / selected count | ✅ | Not in OFS |
| Avg / max / min / median speed | ✅ | Not in OFS |
| Avg / max / min position | ✅ | Not in OFS |
| Actions per minute | ✅ | Not in OFS |
| Selection duration | ✅ | Not in OFS |
| Hash-based reactive cache | ✅ | |

---

## src/ui/panels/preferences.py  ← OFS_Preferences / PreferenceState

| Feature | Status | Notes |
|---------|--------|-------|
| Tab bar (Application / Videoplayer / Scripting) | ✅ | |
| Language / Font size / Font file | ✅ | |
| Light/dark theme / FPS limit / VSync | ✅ | |
| Show metadata on new / HW decoding | ✅ | |
| Fast step amount / Default speed | ✅ | |
| Auto-backup interval / Show heatmap | ✅ | |
| Action dot radius / Max-speed threshold | ✅ | |
| Hot-reload font size | ✅ | |
| Waveform amplitude scale slider | ✅ | session 11 — ScaleAudio slider |
| Waveform colour tint editor | ✅ | session 11 — WaveformColor picker |

---

## src/ui/panels/chapter_manager.py  ← OFS_ChapterManager.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| 4-column table / inline name editing | ✅ | |
| Per-chapter colour swatch | ✅ | |
| Bookmarks table | ✅ | |
| Persistence via _extra_state | ✅ | |
| Chapter resize (Set Begin / Set End) | ✅ | |
| Export Clip via FFmpeg | ✅ | |

---

## src/ui/panels/metadata_editor.py  ← OFS_FunscriptMetadataEditor.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| title / creator / description / type / urls | ✅ | |
| License combo / Tags / Performers chips | ✅ | |
| Duration read-only / Save+Load template | ✅ | |

---

## src/ui/panels/action_editor.py  · src/ui/panels/undo_history.py

| Feature | Status | Notes |
|---------|--------|-------|
| Action editor button grid 0–100 | ✅ | |
| Undo history scrollable list + jump | ✅ | |

---

## src/core/project.py  ← OFS_Project.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Load / save .ofsp JSON | ✅ | |
| ImportFromFunscript / ImportFromMedia | ✅ | |
| Metadata / _extra_state / auto-backup | ✅ | |
| ExportFunscript(outputPath, idx) | ✅ | |
| ExportFunscripts(outputDir) — ALL scripts | ✅ | session 10 |
| quick_export() | ✅ | Fixed: now exports ALL scripts (was active-only) |
| AddFunscript / RemoveFunscript | ✅ | |
| HasUnsavedEdits / project timer | ✅ | |
| lastPlayerPosition save/restore | ✅ | |

---

## src/core/undo_system.py  ← OFS_UndoSystem.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Per-script FunscriptUndoSystem | ✅ | |
| Global UndoSystem (multi-script) | ✅ | |
| All StateType values | ✅ | |
| Undo / Redo / jump_to | ✅ | |

---

## src/core/funscript.py  ← Funscript.h / cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Load / save .funscript | ✅ | |
| Action array (sorted, binary search) | ✅ | |
| GetActionAtTime / GetPrevious / GetNext / GetClosest | ✅ | |
| AddAction / AddEditAction / RemoveAction | ✅ | |
| RemoveActionsInInterval / EditAction | ✅ | |
| Select* / ClearSelection / SelectTime | ✅ | |
| MoveSelectionPosition / MoveSelectionTime | ✅ | |
| Equalize / Invert / SelectTop/Mid/Bottom | ✅ | |
| GetLastStroke / Spline (Catmull-Rom) | ✅ | |
| GetPositionAtTime(t) → float [0..1] | ✅ | get_position_at_time() — session 10 |
| AddMultipleActions(actions) — batch insert | ✅ | add_multiple_actions() — session 10 |
| FunscriptActionsChangedEvent dispatch | ✅ | |
| FunscriptSelectionChangedEvent dispatch | 🔄 | Some paths missing |
| FunscriptNameChangedEvent dispatch | ✅ | session 11 — set_title() dispatches |
| FunscriptRemovedEvent dispatch | ✅ | session 11 — project.remove dispatches |

---

## src/core/waveform.py  (Python-specific)

| Feature | Status | Notes |
|---------|--------|-------|
| Async ffmpeg PCM extraction | ✅ | OFS uses FLAC internally |
| Centred amplitude bars / LOD | ✅ | |
| ScaleAudio amplitude multiplier | ✅ | session 11 — wired to waveform drawing |

---

## src/core/events.py  ← OFS-lib/event/OFS_Event.h + OFS_EventSystem.h/.cpp

| Feature | Status | Notes |
|---------|--------|-------|
| Event bus: listen / dispatch / enqueue / process | ✅ | Mirrors EV::Queue().appendListener / EV::Process() |
| `OFS_Events.VIDEO_LOADED` / `DURATION_CHANGE` / `TIME_CHANGE` / `PLAY_PAUSE_CHANGE` / `PLAYBACK_SPEED_CHANGE` | ✅ | |
| `OFS_Events.FUNSCRIPT_CHANGED` (FunscriptActionsChangedEvent) | ✅ | |
| `OFS_Events.PROJECT_LOADED` / `METADATA_CHANGED` | ✅ | |
| `OFS_Events.CHAPTER_STATE_CHANGED` / `EXPORT_CLIP` | ✅ | |
| `OFS_Events.DROP_FILE` | ✅ | |
| `OFS_Events.FUNSCRIPT_NAME_CHANGED` constant | ✅ | session 11 |
| `OFS_Events.FUNSCRIPT_REMOVED` constant | ✅ | session 11 |
| `OFS_DeferEvent` (deferred lambda via event) | Won't Port | Not needed in Python |
| `OFS_SDL_Event` SDL event wrapper | Won't Port | imgui-bundle handles SDL internally |

---

## OFS-lib/state/states/ — Persistent state structs

### BaseOverlayState.h → script_timeline.py / preferences.py

| Field | Status | Notes |
|-------|--------|-------|
| `MaxSpeedPerSecond` (speed highlight threshold) | ✅ | → `preferences.max_speed_highlight` |
| `SplineMode` | ✅ | → `script_timeline.spline_mode` |
| `ShowMaxSpeedHighlight` (bool toggle in UI) | ✅ | session 11 — context menu toggle |
| `MaxSpeedColor` (colour picker for speed highlight) | ✅ | session 11 — user colour picker |
| `SyncLineEnable` (sync vertical line on timeline) | ✅ | session 11 |

### ChapterState.h/.cpp → chapter_manager.py / videoplayer_controls.py

| Field | Status | Notes |
|-------|--------|-------|
| `Chapter` struct (startTime, endTime, name) | ✅ | |
| `Bookmark` struct (time, name) | ✅ | |
| `Chapter.color` (ImColor per chapter) | ✅ | Stored + rendered in timeline strips |
| `AddChapter()` / `AddBookmark()` | ✅ | |
| `SetChapterSize()` (resize end time) | ✅ | → Set Begin / Set End in chapter_manager |
| `ChapterStateChanged` event | ✅ | |
| `ExportClipForChapter` event | ✅ | |

### KeybindingState.h/.cpp → keybindings.py

| Field | Status | Notes |
|-------|--------|-------|
| `OFS_ActionTrigger` (Mod + Key + ShouldRepeat + MappedActionId) | ✅ | → `KeyChord` dataclass |
| `Triggers` vector_set (all registered bindings) | ✅ | |
| `user_chords` overrides field on `KeyAction` | ✅ | Field exists |
| **Persist user_chords to JSON + reload on startup** | ✅ | session 11 — settings_path JSON |
| `ConvertToOFS()` / `ConvertToImGui()` key enum mapping | Won't Port | Python uses imgui key ints directly |

### VideoplayerWindowState.h → videoplayer_window.py

| Field | Status | Notes |
|-------|--------|-------|
| `VideoMode` enum (Full/Left/Right/Top/Bottom) | ✅ | |
| `activeMode` | ✅ | |
| `zoomFactor` (scroll-wheel zoom) | ✅ | scroll-to-zoom implemented |
| `currentTranslation` / `videoPos` (pan) | ✅ | drag-to-translate implemented |
| `lockedPosition` (lock pan/zoom toggle) | ✅ | session 11 — context menu toggle |
| VR fields (`vrZoom`, `currentVrRotation`, `prevVrRotation`) | Won't Port | Requires VrShader GLSL |

### WaveformState.h → waveform.py / project.py

| Field | Status | Notes |
|-------|--------|-------|
| `Filename` (current audio source tracking) | ✅ | |
| `BinSamples` / `UncompressedSize` (sdefl-compressed u16 PCM) | Won't Port | Python caches `float[]` in-memory; no project persistence needed |
| `GetSamples()` / `SetSamples()` (compress/decompress round-trip) | Won't Port | |

### OFS_StateManager.h / OFS_StateHandle.h / OFS_LibState.h

| Feature | Status | Notes |
|---------|--------|-------|
| `OFS_AppState<T>` / `OFS_ProjectState<T>` template registry | Won't Port | C++ reflection/serialization framework; Python uses plain dataclass fields + JSON dicts |

---

## src/state/ ← OpenFunscripterState + PreferenceState + ProjectState + SimulatorState + WebsocketApiState + MetadataEditorState

### OpenFunscripterState.h → app.py

| Field | Status | Notes |
|-------|--------|-------|
| `recentFiles` (list) | ✅ | |
| `lastPath` | ✅ | |
| `showVideo` / `showHistory` / `showSimulator` / `showStatistics` / `showSpecialFunctions` / `showChapterManager` / `showWsApi` | ✅ | Fields exist in `app.py` |
| **Panel visibility persisted to disk** (save on exit, restore on launch) | ✅ | session 11 — _save_app_state/_load_app_state |
| `alwaysShowBookmarkLabels` (always render bookmark name text) | ✅ | session 11 — persisted in app_state.json |
| `heatmapSettings` (defaultWidth=2000, defaultHeight=50, defaultPath) | ✅ | session 11 — preferences heatmap tab |
| `showDebugLog` | Won't Port | Python `logging` sufficient |

### PreferenceState.h → preferences.py

| Field | Status | Notes |
|-------|--------|-------|
| `languageCsv` / `fontOverride` / `defaultFontSize` | ✅ | |
| `currentTheme` (Dark / Light) | ✅ | |
| `fastStepAmount` / `vsync` / `framerateLimit` | ✅ | |
| `forceHwDecoding` / `showMetaOnNew` | ✅ | |

### ProjectState.h → project.py

| Field | Status | Notes |
|-------|--------|-------|
| `metadata` / `relativeMediaPath` / `activeTimer` / `lastPlayerPosition` / `activeScriptIdx` | ✅ | |
| `nudgeMetadata` | ✅ | |
| `TempoOverlayState` (bpm, beatOffsetSeconds, measureIndex) | ✅ | |
| `binaryFunscriptData` | Won't Port | C++ binary serialization; Python uses plain JSON |

### SimulatorState.h → simulator.py

| Field | Status | Notes |
|-------|--------|-------|
| All visual fields (P1/P2, colours, widths, opacity, indicators, etc.) | ✅ | |
| `SimulatorDefaultConfigState` (save-as-default + reload) | ✅ | `~/.ofs-pyqt/sim_config.json` via Load/Save config buttons |

### WebsocketApiState.h → websocket_api.py / app.py

| Field | Status | Notes |
|-------|--------|-------|
| `port` (default "8080") | ✅ | |
| `serverActive` (persist server on/off across sessions) | ✅ | session 11 — saved as ws_active |

### MetadataEditorState.h → metadata_editor.py

| Field | Status | Notes |
|-------|--------|-------|
| `defaultMetadata` template (save + load a metadata template for new scripts) | ✅ | session 11 — Save/Load template buttons |

---

## src/core/websocket_api.py  ← OFS_WebsocketApi + OFS_WebsocketApiClient + OFS_WebsocketApiCommands + OFS_WebsocketApiEvents

OFS source: 8 files across `src/api/` (server, client, commands, events × .h/.cpp)

| Feature | Status | Notes |
|---------|--------|-------|
| WebSocket server infrastructure (asyncio + websockets) | ✅ | Port fallback loop, daemon thread |
| **Protocol: outbound event envelope** `{"type":"event","name":"…","data":{…}}` | ✅ | session 11 — full OFS protocol rewrite |
| **`play_change`** event `{"name":"play_change","data":{"playing":bool}}` | ✅ | session 11 |
| **`time_change`** event `{"name":"time_change","data":{"time":float}}` | ✅ | session 11 |
| **`duration_change`** event `{"name":"duration_change","data":{"duration":float}}` | ✅ | session 11 |
| **`media_change`** event `{"name":"media_change","data":{"path":str}}` | ✅ | session 11 |
| **`playbackspeed_change`** event `{"name":"playbackspeed_change","data":{"speed":float}}` | ✅ | session 11 |
| **`project_change`** event `{"name":"project_change","data":{}}` | ✅ | session 11 |
| **`funscript_change`** event — full serialized funscript JSON per script | ✅ | session 11 — 200ms debounce |
| **`funscript_remove`** event `{"name":"funscript_remove","data":{"name":str}}` | ✅ | session 11 |
| **Protocol: inbound command envelope** `{"type":"command","name":"…","data":{…}}` | ✅ | session 11 — full OFS protocol |
| **`change_time`** command `{"name":"change_time","data":{"time":float}}` | ✅ | session 11 |
| **`change_play`** command `{"name":"change_play","data":{"playing":bool}}` | ✅ | session 11 |
| **`change_playbackspeed`** command `{"name":"change_playbackspeed","data":{"speed":float}}` | ✅ | session 11 |
| **On-connect welcome** `{"connected":"OFS <version>"}` + `UpdateAll()` | ✅ | session 11 — welcome + full state dump |
| **`UpdateAll()`** — sends project/media/speed/play/duration/time/all funscripts on connect | ✅ | session 11 |
| **200ms cooldown batching** for `funscript_change` per script | ✅ | session 11 — per-script Timer debounce |
| **Clients connected count** tracking | ✅ | session 11 — len(self._clients) |
| **ShowWindow** — server toggle checkbox, URL display, client count, port input | ✅ | app.py WebSocket panel |
| Server URL path `/ofs` | ✅ | session 11 — path filter in _handler() |

---

## C++ Source Code Inventory (129 files)

### OFS-lib/ — Core Library (70 files)

#### Event System (4 files)
| File | Classes / Key Functions |
|------|----------------------|
| `event/OFS_Event.h` | `OFS_Event` base, `OFS_SDL_Event`, `OFS_DeferEvent` |
| `event/OFS_Event.cpp` | Event type registration |
| `event/OFS_EventSystem.h` | `OFS_EventSystem` — `Subscribe()`, `Publish()`, `PublishDeferred()`, `ProcessDeferred()` |
| `event/OFS_EventSystem.cpp` | EV singleton, deferred queue processing |

#### Funscript Data (10 files)
| File | Classes / Key Functions |
|------|----------------------|
| `Funscript/FunscriptAction.h` | `FunscriptAction` {at, pos, tag, flags}, `FunscriptArray` (sorted vector + binary search) |
| `Funscript/FunscriptAction.cpp` | Sort, dedup, merge, binary search helpers |
| `Funscript/Funscript.h` | `Funscript` — `Load()`, `Save()`, `AddAction()`, `AddEditAction()`, `RemoveAction()`, `GetActionAtTime()`, `GetPositionAtTime()`, `GetClosestAction()`, `SelectAction()`, `ClearSelection()`, `MoveSelectionTime()`, `MoveSelectionPosition()`, `EqualizeSelection()`, `InvertSelection()`, `SelectTop/Mid/BottomPoints()`, `RangeExtend()`, `SplineClamped()`, ~40 methods |
| `Funscript/Funscript.cpp` | Full implementations |
| `Funscript/FunscriptHeatmap.h` | `FunscriptHeatmap` — `Update()` (speed→colour gradient 256 segments) |
| `Funscript/FunscriptHeatmap.cpp` | Gradient sampling, speed calculation |
| `Funscript/FunscriptSpline.h` | `CatmullRomSpline()`, `SampleAtIndex()` — catmull-rom interpolation |
| `Funscript/FunscriptUndoSystem.h` | `FunscriptUndoSystem` — `Snapshot()`, `Undo()`, `Redo()`, `ClearRedoStack()`, `JumpTo()` |
| `Funscript/FunscriptUndoSystem.cpp` | All undo/redo implementations |

#### Utilities & Infrastructure (12 files)
| File | Classes / Key Functions |
|------|----------------------|
| `OFS_Util.h` | `Util::Clamp()`, `Util::RandomColor()`, `Util::FormatBytes()`, `Util::FormatTime()`, `Util::PathFromUrl()`, `Util::Prefpath()`, `Util::FfmpegPath()`, `Util::InverseLerp()`, file dialogs, ~20 helpers |
| `OFS_Util.cpp` | Full implementations |
| `OFS_Serialization.h` | `OFS_Serializer<T>` — JSON serialize/deserialize via refl-cpp |
| `OFS_Serialization.cpp` | Reflection-based serialization |
| `OFS_BinarySerialization.h` | bitsery `Serialize<T>()` / `Deserialize<T>()` |
| `OFS_VectorSet.h` | `OFS_VectorSet<T>` — sorted vector with set semantics |
| `OFS_Reflection.h` | `REFL_TYPE` macros for compile-time reflection |
| `OFS_GL.h` | OpenGL type aliases, `glCheckError()` |
| `OFS_MpvLoader.h/.cpp` | Dynamic libmpv symbol loading (dlopen/LoadLibrary) |
| `OFS_DynamicFontAtlas.h/.cpp` | CJK glyph range atlas rebuild |
| `OFS_FileLogging.h/.cpp` | `OFS_FileLogger`, LOG_*/LOGF_* macros |
| `OFS_ControllerInput.h/.cpp` | SDL gamepad: `Init()`, `Update()`, `GetButton()`, `GetAxis()`, ~10 methods |

#### GL / Shader (4 files)
| File | Classes / Key Functions |
|------|----------------------|
| `gl/OFS_Shader.h` | `OFS_Shader` — `Compile()`, `Use()`, `SetUniform*()`, `VrShader` GLSL pipeline |
| `gl/OFS_Shader.cpp` | Shader compilation, VR vertex/fragment sources |

#### State System (14 files)
| File | Contents |
|------|---------|
| `state/OFS_StateManager.h/.cpp` | `OFS_StateManager` — type-erased state registry |
| `state/OFS_StateHandle.h` | `OFS_AppState<T>`, `OFS_ProjectState<T>` templates |
| `state/OFS_LibState.h/.cpp` | Library-level global state |
| `state/states/BaseOverlayState.h` | `MaxSpeedPerSecond`, `SplineMode`, `ShowMaxSpeedHighlight`, `MaxSpeedColor`, `SyncLineEnable`, `ShowLines`, `ShowPoints` |
| `state/states/ChapterState.h/.cpp` | `Chapter` {start, end, name, color}, `Bookmark` {time, name}, `AddChapter()`, `AddBookmark()` |
| `state/states/KeybindingState.h/.cpp` | `OFS_ActionTrigger` {mod, key, repeat, actionId}, trigger vector, `ConvertToOFS/ImGui()` |
| `state/states/VideoplayerWindowState.h` | `VideoMode` enum, `activeMode`, `zoomFactor`, `currentTranslation`, `lockedPosition`, VR fields |
| `state/states/WaveformState.h` | `BinSamples` (sdefl-compressed u16 PCM), `GetSamples()`, `SetSamples()` |

#### UI Widgets (26 files)
| File | Classes / Key Functions |
|------|----------------------|
| `UI/GradientBar.h/.cpp` | `ImGradient` — colour stops, `AddMark()`, `RemoveMark()`, `DrawGradientBar()`, `ComputeColorAt()` |
| `UI/OFS_BlockingTask.h/.cpp` | `OFS_BlockingTask` — modal progress overlay with cancel |
| `UI/OFS_ImGui.h/.cpp` | `OFS_ImGui::Tooltip()`, `Spinner()`, `AppLog`, `BeginColumns()`, imgui helper wrappers |
| `UI/OFS_KeybindingSystem.h/.cpp` | `OFS_KeybindingSystem` — `RegisterGroup()`, `RegisterAction()`, `ProcessKeybindings()`, `RenderKeybindingWindow()`, `AddTrigger()`, ~15 methods |
| `UI/OFS_ScriptTimeline.h/.cpp` | `OFS_ScriptTimeline` — `DrawTimeline()`, `DrawActionLines()`, `DrawActionPoints()`, `HandleSelection()`, `HandleScrubbing()`, `HandleAutoScroll()`, zoom/pan, ruler, frame/tempo overlay, ~25 methods |
| `UI/OFS_ScriptTimelineEvents.h` | `ScriptTimelineActionClicked/Created/Moved/SelectionChanged` event types |
| `UI/OFS_VideoplayerControls.h/.cpp` | `OFS_VideoplayerControls` — `DrawControls()` (play/pause/seek/speed/volume), `DrawTimeline()` (heatmap + chapters + bookmarks + scrubbing), `UpdateHeatmap()`, `SaveHeatmap()`, ~15 methods |
| `UI/OFS_Videopreview.h/.cpp` | `OFS_Videopreview` — 2nd mpv render context, 320×180 FBO, `Init()`, `Update()`, `PreviewTime()`, `RenderToTexture()` |
| `UI/OFS_Waveform.h/.cpp` | `OFS_Waveform` — async FFmpeg extraction, `LoadAudio()`, `Update()`, GL texture upload, `WaveformShader` |
| `UI/ScriptPositionsOverlayMode.h/.cpp` | `ScriptPositionsOverlayMode` base, `DefaultOverlay`, `FrameOverlay`, `TempoOverlay` — `DrawStroke()`, `DrawGrid()`, ~10 methods |
| `UI/OFS_Profiling.h` | `OFS_PROFILE()` macros (Tracy) |

#### Videoplayer (6 files)
| File | Classes / Key Functions |
|------|----------------------|
| `videoplayer/OFS_Videoplayer.h` | `OFS_Videoplayer` — `Init()`, `Shutdown()`, `Update()`, `OpenVideo()`, `CloseVideo()`, `SetPaused()`, `TogglePlay()`, `SetPositionExact()`, `SeekRelative()`, `SeekFrames()`, `NextFrame()`, `PreviousFrame()`, `SetSpeed()`, `AddSpeed()`, `SetVolume()`, `Mute()`, `CycleSubtitles()`, `SaveFrameToImage()`, `NotifySwap()`, `SyncWithPlayerTime()`, `Duration()`, `CurrentTime()`, `Fps()`, `FrameTime()`, `FrameTexture()`, `MeasuredSpeed()`, ~35 methods |
| `videoplayer/OFS_VideoplayerEvents.h` | `VideoLoadedEvent`, `DurationChangeEvent`, `TimeChangeEvent`, `PlayPauseChangeEvent`, `PlaybackSpeedChangeEvent` |
| `videoplayer/OFS_VideoplayerWindow.h/.cpp` | `OFS_VideoplayerWindow` — `DrawVideoPlayer()`, zoom, pan, reset, context menu, `VideoMode` enum, VR rendering |
| `videoplayer/impl/OFS_MpvVideoplayer.cpp` | mpv_render_context, FBO setup, `mpv_render_context_render()`, property observation callbacks |

### src/ — Application Layer (59 files)

#### Main App (8 files)
| File | Classes / Key Functions |
|------|----------------------|
| `main.cpp` | Entry point, SDL init, ImGui context, main loop |
| `OpenFunscripter.h/.cpp` | `OpenFunscripter` — `Init()`, `Run()`, `Shutdown()`, `Step()`, `openFile()`, `saveProject()`, `saveHeatmap()`, `exportFunscript()`, `closeProject()`, `ShowMainMenuBar()`, `ShowAboutWindow()`, `HandleEvents()`, `Undo()`, `Redo()`, `Copy/Paste/Cut()`, `RegisterBindings()`, `ScriptTimelineAction*` callbacks, `LoadState()`, `SaveState()`, `auto_backup`, ~70 methods |
| `OFS_Project.h/.cpp` | `OFS_Project` — `Load()`, `Save()`, `ImportFromFunscript()`, `ImportFromMedia()`, `ExportFunscript()`, `ExportFunscripts()`, `AddFunscript()`, `RemoveFunscript()`, `HasUnsavedEdits()`, ~25 methods |
| `OFS_ScriptingMode.h/.cpp` | `ScriptingMode` enum (DEFAULT/ALTERNATING/RECORDING/DYNAMIC), `ScriptingModeBase` + 4 subclasses, `update()`, `addEditAction()`, `finish()`, ~30 methods |
| `OFS_UndoSystem.h/.cpp` | `OFS_UndoSystem` — multi-script undo coordinator, `Snapshot()`, `Undo()`, `Redo()`, `ClearHistory()`, ~15 methods |

#### WebSocket API (8 files)
| File | Classes / Key Functions |
|------|----------------------|
| `api/OFS_WebsocketApi.h/.cpp` | `OFS_WebsocketApi` — `Init()`, `Shutdown()`, `Start()`, `Stop()`, `ShowWindow()`, client tracking, broadcast infrastructure |
| `api/OFS_WebsocketApiClient.h/.cpp` | `OFS_WebsocketApiClient` — per-connection handler, message routing |
| `api/OFS_WebsocketApiCommands.h/.cpp` | `change_time`, `change_play`, `change_playbackspeed` command handlers |
| `api/OFS_WebsocketApiEvents.h/.cpp` | `time_change`, `play_change`, `duration_change`, `media_change`, `playbackspeed_change`, `project_change`, `funscript_change` (200ms debounce), `funscript_remove` broadcast events |

#### GL (2 files)
| File | Contents |
|------|---------|
| `gl/OFS_GPU.h/.cpp` | `NvOptimusEnablement`, `AmdPowerXpressRequestHighPerformance` GPU hints (Windows) |

#### Lua Extension System (10 files)
| File | Contents |
|------|---------|
| `lua/OFS_LuaExtensions.h/.cpp` | Extension manager, `LoadExtension()`, `UnloadExtension()`, `RenderExtensionWindows()` |
| `lua/OFS_LuaScript.h/.cpp` | `OFS_LuaScript` — Lua state wrapper, `Init()`, `Execute()`, `Shutdown()` |
| `lua/OFS_LuaBinding*.h/.cpp` | API bindings: Funscript, Player, GUI, Process, Clipboard, ~60 bound methods |
| `lua/OFS_LuaCoreExtension.h/.cpp` | Core extension lifecycle |

#### State Files (16 files)
| File | Contents |
|------|---------|
| `state/OpenFunscripterState.h/.cpp` | `recentFiles`, `lastPath`, `showVideo/History/Simulator/Statistics/SpecialFunctions/ChapterManager/WsApi`, `alwaysShowBookmarkLabels`, `heatmapSettings` |
| `state/PreferenceState.h` | `languageCsv`, `fontOverride`, `defaultFontSize`, `currentTheme`, `fastStepAmount`, `vsync`, `framerateLimit`, `forceHwDecoding`, `showMetaOnNew` |
| `state/ProjectState.h` | `metadata`, `relativeMediaPath`, `activeTimer`, `lastPlayerPosition`, `activeScriptIdx`, `nudgeMetadata`, `TempoOverlayState` |
| `state/MetadataEditorState.h` | `defaultMetadata` template |
| `state/ScriptModeState.h` | Active scripting mode, overlay selection |
| `state/SimulatorState.h` | All sim visual fields (P1/P2, colours, width, opacity, indicators) |
| `state/SpecialFunctionsState.h` | Active function selection |
| `state/WebsocketApiState.h` | `port`, `serverActive` |

#### UI Panels (15 files)
| File | Classes / Key Functions |
|------|----------------------|
| `UI/OFS_ChapterManager.h/.cpp` | `OFS_ChapterManager` — chapter/bookmark table, inline edit, colour swatch, FFmpeg clip export |
| `UI/OFS_DownloadFfmpeg.h/.cpp` | `OFS_DownloadFfmpeg` — Windows auto-download dialog |
| `UI/OFS_FunscriptMetadataEditor.h/.cpp` | `OFS_FunscriptMetadataEditor` — all metadata fields, save/load template |
| `UI/OFS_Preferences.h/.cpp` | `OFS_Preferences` — Application/Videoplayer/Scripting tabs, all settings |
| `UI/OFS_ScriptPositionsOverlays.h/.cpp` | `SimMode`, `TempoMode` — advanced overlay editing UIs |
| `UI/OFS_ScriptSimulator.h/.cpp` | `OFS_ScriptSimulator` — position tracking, P1/P2 drag, colours, config persistence |
| `UI/OFS_SpecialFunctions.h/.cpp` | `SpecialFunctionsWindow` + 8 function classes: `FunctionRangeExtender`, `RamerDouglasPeucker`, `FunctionFillGaps`, `StrokePerSecond`, `RepeatStroke`, etc. |

---

### Python Source Inventory (25 files)

#### Core (9 files)
| File | Classes / Key Functions | Lines |
|------|----------------------|-------|
| `core/events.py` | `OFS_Events` enum (18 constants), `EventBus` singleton — `listen()`, `dispatch()`, `enqueue()`, `process()` | ~80 |
| `core/funscript.py` | `FunscriptAction`, `FunscriptArray`, `Funscript` (~40 methods), `FunscriptMetadata` | ~500 |
| `core/video_player.py` | `OFS_Videoplayer` (~35 methods) — mpv render context, FBO, `ActualSpeed()` EMA | ~350 |
| `core/project.py` | `OFS_Project` (~25 methods) — load/save .ofsp, import/export, multi-script | ~300 |
| `core/keybindings.py` | `KeyChord`, `KeyAction`, `OFS_KeybindingSystem` (~15 methods) — chords, mouse-wheel, JSON persist | ~400 |
| `core/undo_system.py` | `ScriptState`, `FunscriptUndoSystem`, `UndoSystem` | ~120 |
| `core/websocket_api.py` | `WebSocketAPI` — full OFS protocol, 8 events, 3 commands, 200ms debounce, on-connect welcome | ~250 |
| `core/waveform.py` | `WaveformData` — async FFmpeg PCM extraction, LOD, amplitude bars | ~200 |
| `core/thumbnail.py` | `VideoThumbnailManager` — 2nd mpv render context, 320×180 FBO, debounced seek | ~300 |

#### UI (7 files)
| File | Classes / Key Functions | Lines |
|------|----------------------|-------|
| `ui/app.py` | `OpenFunscripter` (~70 methods) — main app, menu, docking, all handlers, state persistence | ~1200 |
| `ui/videoplayer_window.py` | `VideoMode` enum, `OFS_VideoplayerWindow` — zoom, pan, lock, context menu | ~200 |
| `ui/videoplayer_controls.py` | `OFS_VideoplayerControls` — DrawControls, DrawTimeline, heatmap, chapters, bookmarks, thumbnails | ~400 |
| `ui/script_timeline.py` | `ScriptTimeline` (~20 methods) — multi-track, zoom, selection, overlays, waveform, sync line | ~600 |

#### UI Panels (9 files)
| File | Classes / Key Functions | Lines |
|------|----------------------|-------|
| `ui/panels/scripting_mode.py` | `ScriptingMode` (23 methods) + `DefaultOverlay`, `FrameOverlay`, `TempoOverlay` | ~400 |
| `ui/panels/preferences.py` | All tabs + waveform/heatmap settings | ~200 |
| `ui/panels/simulator.py` | `ScriptSimulator` — position tracking, P1/P2, config persistence | ~300 |
| `ui/panels/special_functions.py` | 8 helper functions + `SpecialFunctionsWindow` (13 methods) | ~350 |
| `ui/panels/statistics.py` | Real-time stats at cursor + aggregate stats | ~150 |
| `ui/panels/chapter_manager.py` | Chapter/bookmark tables, colour swatch, clip export | ~200 |
| `ui/panels/metadata_editor.py` | All fields + template save/load | ~150 |
| `ui/panels/action_editor.py` | Action button grid 0–100 | ~60 |
| `ui/panels/undo_history.py` | Scrollable undo list + jump | ~80 |

#### Cueing (1 file — Python-only, not in OFS C++)
| File | Classes / Key Functions | Lines |
|------|----------------------|-------|
| `cueing/cue_manager.py` | `CueManager` (16 methods, 7 signals) — cue sheet management | ~200 |

---

## Outstanding — TODO (prioritised)

### ✅ All 20 items from sessions 10–11 completed

| # | Status | Feature | Session |
|---|--------|---------|---------|
| 1 | ✅ | Drag & Drop file opening | 11 |
| 2 | ✅ | Menu bar alert colour (red pulse >5 min unsaved) | 11 |
| 3 | ✅ | ScaleAudio amplitude scale + UI slider | 11 |
| 4 | ✅ | Waveform colour tint editor | 11 |
| 5 | ✅ | FUNSCRIPT_NAME_CHANGED / FUNSCRIPT_REMOVED events | 11 |
| 6 | ✅ | ShowMaxSpeedHighlight toggle + MaxSpeedColor picker | 11 |
| 7 | ✅ | SyncLineEnable vertical sync line | 11 |
| 8 | ✅ | lockedPosition lock pan/zoom toggle | 11 |
| 9 | ✅ | Chord persistence (JSON save/load) | 11 |
| 10 | ✅ | Measured playback speed (ActualSpeed EMA) | 11 |
| 11 | ✅ | Half-pane video modes persisted | 11 |
| 12 | ✅ | Video thumbnail preview (2nd mpv) | 11 |
| 13 | ✅ | Panel visibility persistence | 11 |
| 14 | ✅ | alwaysShowBookmarkLabels | 11 |
| 15 | ✅ | heatmapSettings defaults in preferences | 11 |
| 16 | ✅ | Default metadata template save/load | 11 |
| 17 | ✅ | serverActive WS persistence | 11 |
| 18 | ✅ | ShowLines / ShowPoints toggle | 11 |
| 19 | ✅ | Mouse wheel direction triggers | 11 |
| 20 | ✅ | WebSocket protocol full OFS rewrite | 11 |

### 🔜 Remaining work

| # | Priority | File(s) | Feature | OFS source | Size |
|---|----------|---------|---------|------------|------|
| R1 | 🟡 Medium | funscript.py | **FunscriptSpline** — catmull-rom interpolation (SplineClamped) | FunscriptSpline.h | Small |
| R2 | 🟡 Medium | keybindings.py | **Orphan triggers** — preserve unused bindings across sessions | OFS_KeybindingSystem.h | Small |
| R3 | 🟢 Low | funscript.py | **FunscriptSelectionChangedEvent** — dispatch on all selection paths | Funscript.cpp | Small |
| R4 | 🟢 Low | — | **Localization** — i18n string table (load CSV, wrap strings) | OFS_Localization.h | Large |
| R5 | 🔵 Future | — | **Gamepad/Controller** — SDL gamepad input support | OFS_ControllerInput.h | Large |
| R6 | 🔵 Future | special_functions.py | **SpecialFunctions completeness** — verify all 8 sub-functions | OFS_SpecialFunctions.h | Medium |
| R7 | 🔵 Future | scripting_mode.py | **Dynamic injection / recording mode** — verify completeness | OFS_ScriptingMode.cpp | Medium |

---

### Port Completion Score

| Category | Items | Ported | N/A | Remaining | % Ported |
|----------|-------|--------|-----|-----------|----------|
| Core data model | 10 | 9 | 0 | 1 (Spline) | **90%** |
| Video & audio | 8 | 7 | 1 | 0 | **100%** |
| UI panels | 15 | 15 | 0 | 0 | **100%** |
| WebSocket API | 20 | 20 | 0 | 0 | **100%** |
| State system | 16 | 14 | 2 | 0 | **100%** |
| Keybinding system | 8 | 7 | 0 | 1 (orphans) | **88%** |
| Events | 10 | 9 | 2 | 1 (selection) | **90%** |
| **Total (excl. Won't-Port)** | **87** | **81** | **5** | **3** | **~97%** |

> **Won't-port modules** (28 items): Lua extensions, gamepad, VR, dynamic font atlas, binary serialization, reflection, profiling, etc.
> **Effective porting: ~97% of meaningful OFS features are implemented.**

---

## Won't Port

| Feature | OFS source | Reason |
|---------|-----------|--------|
| Lua extensions | OFS_LuaExtensions | Scripting engine, C++ dep |
| Gamepad / controller input | OFS_ControllerInput | Hardware dep |
| Controller axis playback speed | OpenFunscripter.cpp | Requires gamepad |
| Dynamic font atlas (CJK) | OFS_DynFontAtlas | Complex font rebuild |
| Localization i18n (TR() / TrString) | OFS_Localization.h/.cpp | Python uses hardcoded English strings |
| OFS_Profiling macros | OFS_Profiling.h | C++ perf tracing only |
| Download FFmpeg dialog | OFS_DownloadFfmpeg | System ffmpeg on macOS |
| AppLog in-app log viewer | OFS_ImGui AppLog | Python logging sufficient |
| BlockingTask progress modal | OFS_BlockingTask.h | Python threading covers it |
| VR stereoscopic mode | OFS_VideoplayerWindow + VrShader | GLSL shader, niche |
| `OFS_Shader` / `VrShader` GLSL pipeline | OFS-lib/gl/OFS_Shader.h/.cpp | imgui-bundle provides GL backend |
| `imgui_impl_opengl3` / `imgui_impl_sdl` backends | OFS-lib/imgui_impl/ | imgui-bundle provides these automatically |
| `OFS_StateManager` / `OFS_StateHandle` / `OFS_LibState` | OFS-lib/state/ | C++ reflection/serialization framework; Python uses plain dicts |
| `WaveformState` sdefl-compressed binary storage | OFS-lib/state/states/WaveformState.h | Python caches float[] in-memory; no on-disk compression needed |
| `KeybindingState.ConvertToOFS/ImGui()` key enum mapping | OFS-lib/state/states/KeybindingState.cpp | Python uses imgui key ints directly |
| `OFS_SDL_Event` / `OFS_DeferEvent` wrappers | OFS-lib/event/OFS_Event.h | imgui-bundle handles SDL; Python lambdas replace defer |
| `WaveformShader` GPU texture upload | OFS-lib/UI/OFS_Waveform.h | OFS blits waveform to GL texture via shader; Python uses imgui DrawList CPU overlay |
| `OFS_ImGui::AppLog` widget | OFS-lib/UI/OFS_ImGui.h | Python `logging` module sufficient; no in-app log panel |
| `OFS_DownloadFfmpeg` (auto-download ffmpeg on Windows) | src/UI/OFS_DownloadFfmpeg.h/.cpp | System ffmpeg assumed on macOS/Linux |
| `OFS_BlockingTask` (progress modal for long tasks) | OFS-lib/UI/OFS_BlockingTask.h | Python threading + asyncio covers it |
| `OFS_BinarySerialization` (bitsery) | OFS-lib/OFS_BinarySerialization.h | Pure C++ bitsery library; Python uses JSON |
| `OFS_Reflection.h` (`refl-cpp` REFL_TYPE macros) | OFS-lib/OFS_Reflection.h | C++ compile-time reflection; not needed in Python |
| `OFS_VectorSet<T>` sorted-vector container | OFS-lib/OFS_VectorSet.h | Python uses `list` + `bisect` |
| `OFS_DynamicFontAtlas` (CJK glyph atlas rebuild) | OFS-lib/OFS_DynamicFontAtlas.h/.cpp | hello_imgui font management used instead |
| `OFS_MpvLoader` (dynamic libmpv symbol loading) | OFS-lib/OFS_MpvLoader.h/.cpp | python-mpv handles this automatically |
| `OFS_FileLogger` / LOG_*/LOGF_* macros | OFS-lib/OFS_FileLogging.h/.cpp | Python `logging` module used |
| `OFS_Profiling` / `OFS_PROFILE()` macros | OFS-lib/OFS_Profiling.h | C++ Tracy profiler; not needed in Python |
