# OFS-PyQt Implementation Tracker

Last updated: session 10  
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
| Menu bar colour alert (red pulse >5 min unsaved) | ⬜ | OFS alertCol lerp |

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
| Drag & Drop file opening (SDL_DROPFILE) | ⬜ | |
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
| Mouse wheel direction triggers (`MouseWheelDirection` flag, scroll-up vs scroll-down) | ⬜ | OFS_KeybindingSystem.cpp |
| Orphan triggers (triggers with no matching action, preserved across sessions) | ⬜ | OFS_KeybindingSystem.h |
| Chord persistence (user chords → JSON) | ⬜ | OFS persists modifications |

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
| Video mode combo (Full/Left/Right/Top/Bottom) | 🔄 | Stored; only Full rendered |
| lockedPosition (lock pan/zoom toggle) | ⬜ | VideoplayerWindowState.lockedPosition |
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
| Video thumbnail preview on hover | ⬜ | Needs 2nd mpv instance |
| Measured playback speed (actualPlaybackSpeed) | ⬜ | Position-delta calc |
| Waveform amplitude scale (ScaleAudio) | ⬜ | |
| Waveform colour tint (WaveformColor) | ⬜ | |

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
| `ScaleAudio` float — amplitude multiplier wired to draw | ⬜ | Field exists but not wired to waveform drawing |
| `BaseOverlay.ShowLines` / `ShowPoints` toggle in context menu | ⬜ | Python always renders both; no toggle exposed |
| `ShowMaxSpeedHighlight` bool + `MaxSpeedColor` picker | ⬜ | Highlight always on when speed exceeded; no toggle or colour picker |

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
| Waveform amplitude scale slider | ⬜ | ScaleAudio |
| Waveform colour tint editor | ⬜ | WaveformColor |

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
| FunscriptNameChangedEvent dispatch | ⬜ | On title/path change |
| FunscriptRemovedEvent dispatch | ⬜ | On project.remove_funscript() |

---

## src/core/waveform.py  (Python-specific)

| Feature | Status | Notes |
|---------|--------|-------|
| Async ffmpeg PCM extraction | ✅ | OFS uses FLAC internally |
| Centred amplitude bars / LOD | ✅ | |
| ScaleAudio amplitude multiplier | ⬜ | |

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
| `OFS_Events.FUNSCRIPT_NAME_CHANGED` constant | ⬜ | Missing — needed by websocket + project |
| `OFS_Events.FUNSCRIPT_REMOVED` constant | ⬜ | Missing — needed by websocket + project |
| `OFS_DeferEvent` (deferred lambda via event) | Won't Port | Not needed in Python |
| `OFS_SDL_Event` SDL event wrapper | Won't Port | imgui-bundle handles SDL internally |

---

## OFS-lib/state/states/ — Persistent state structs

### BaseOverlayState.h → script_timeline.py / preferences.py

| Field | Status | Notes |
|-------|--------|-------|
| `MaxSpeedPerSecond` (speed highlight threshold) | ✅ | → `preferences.max_speed_highlight` |
| `SplineMode` | ✅ | → `script_timeline.spline_mode` |
| `ShowMaxSpeedHighlight` (bool toggle in UI) | ⬜ | No toggle exposed; highlight always on if threshold exceeded |
| `MaxSpeedColor` (colour picker for speed highlight) | ⬜ | Hard-coded red; no user colour picker |
| `SyncLineEnable` (sync vertical line on timeline) | ⬜ | Not implemented |

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
| **Persist user_chords to JSON + reload on startup** | ⬜ | Not saved to disk; resets every launch |
| `ConvertToOFS()` / `ConvertToImGui()` key enum mapping | Won't Port | Python uses imgui key ints directly |

### VideoplayerWindowState.h → videoplayer_window.py

| Field | Status | Notes |
|-------|--------|-------|
| `VideoMode` enum (Full/Left/Right/Top/Bottom) | ✅ | |
| `activeMode` | ✅ | |
| `zoomFactor` (scroll-wheel zoom) | ✅ | scroll-to-zoom implemented |
| `currentTranslation` / `videoPos` (pan) | ✅ | drag-to-translate implemented |
| `lockedPosition` (lock pan/zoom toggle) | ⬜ | Not implemented |
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
| **Panel visibility persisted to disk** (save on exit, restore on launch) | ⬜ | `_before_exit` doesn't write these to JSON — resets to defaults every launch |
| `alwaysShowBookmarkLabels` (always render bookmark name text) | ⬜ | Not implemented |
| `heatmapSettings` (defaultWidth=2000, defaultHeight=50, defaultPath) | ⬜ | Python hardcodes 1280×100; no UI to change defaults |
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
| `serverActive` (persist server on/off across sessions) | ⬜ | Python doesn't persist this — server always starts disabled |

### MetadataEditorState.h → metadata_editor.py

| Field | Status | Notes |
|-------|--------|-------|
| `defaultMetadata` template (save + load a metadata template for new scripts) | ⬜ | Python metadata editor has no Save-as-template / Load-template feature |

---

## src/core/websocket_api.py  ← OFS_WebsocketApi + OFS_WebsocketApiClient + OFS_WebsocketApiCommands + OFS_WebsocketApiEvents

OFS source: 8 files across `src/api/` (server, client, commands, events × .h/.cpp)

| Feature | Status | Notes |
|---------|--------|-------|
| WebSocket server infrastructure (asyncio + websockets) | ✅ | Port fallback loop, daemon thread |
| **Protocol: outbound event envelope** `{"type":"event","name":"…","data":{…}}` | ❌ | Port uses flat `{"type":"position",…}` — wrong format |
| **`play_change`** event `{"name":"play_change","data":{"playing":bool}}` | ❌ | Port sends `{"type":"playing",…}` |
| **`time_change`** event `{"name":"time_change","data":{"time":float}}` | ❌ | Merged into non-OFS `position` message |
| **`duration_change`** event `{"name":"duration_change","data":{"duration":float}}` | ❌ | Port sends `{"type":"duration",…}` — wrong envelope |
| **`media_change`** event `{"name":"media_change","data":{"path":str}}` | ❌ | Not implemented |
| **`playbackspeed_change`** event `{"name":"playbackspeed_change","data":{"speed":float}}` | ❌ | Not implemented |
| **`project_change`** event `{"name":"project_change","data":{}}` | ❌ | Not implemented |
| **`funscript_change`** event — full serialized funscript JSON per script | ❌ | Not implemented |
| **`funscript_remove`** event `{"name":"funscript_remove","data":{"name":str}}` | ❌ | Not implemented |
| **Protocol: inbound command envelope** `{"type":"command","name":"…","data":{…}}` | ❌ | Port uses flat `{"type":"seek",…}` — wrong format |
| **`change_time`** command `{"name":"change_time","data":{"time":float}}` | ❌ | Port uses `{"type":"seek"}` |
| **`change_play`** command `{"name":"change_play","data":{"playing":bool}}` | ❌ | Port uses separate `play`/`pause` types |
| **`change_playbackspeed`** command `{"name":"change_playbackspeed","data":{"speed":float}}` | ❌ | Port uses `{"type":"speed"}` |
| **On-connect welcome** `{"connected":"OFS <version>"}` + `UpdateAll()` | ❌ | Not implemented — clients get no state on connect |
| **`UpdateAll()`** — sends project/media/speed/play/duration/time/all funscripts on connect | ❌ | Not implemented |
| **200ms cooldown batching** for `funscript_change` per script | ❌ | Not implemented |
| **Clients connected count** tracking | ❌ | Not tracked |
| **ShowWindow** — server toggle checkbox, URL display, client count, port input | ⬜ | UI panel for WebSocket settings |
| Server URL path `/ofs` | ⬜ | Port uses any path; OFS uses `/ws://host:port/ofs` |

---

## Outstanding — TODO (prioritised)

| # | Priority | File(s) | Feature | OFS source | Size |
|---|----------|---------|---------|------------|------|
| 1 | � Medium | app.py | Drag & Drop file opening | OFS cpp:DragNDrop | Small |
| 2 | 🟡 Medium | app.py | Menu bar alert colour (red pulse >5 min unsaved) | OFS cpp:ShowMainMenuBar | Small |
| 3 | 🟢 Low | waveform.py + preferences.py | ScaleAudio amplitude scale + UI slider | OFS_ScriptTimeline.h | Small |
| 4 | 🟢 Low | waveform.py + preferences.py | Waveform colour tint editor | OFS_Waveform.h | Small |
| 5 | 🟢 Low | core/events.py + core/funscript.py + core/project.py | `FUNSCRIPT_NAME_CHANGED` / `FUNSCRIPT_REMOVED` — add constants + dispatch on title change / remove | Funscript.h + OFS_Event.h | Small |
| 6 | 🟢 Low | script_timeline.py + preferences.py | `ShowMaxSpeedHighlight` bool toggle + `MaxSpeedColor` picker | BaseOverlayState.h | Small |
| 7 | 🟢 Low | script_timeline.py | `SyncLineEnable` — vertical sync line drawn on timeline | BaseOverlayState.h | Small |
| 8 | 🟢 Low | videoplayer_window.py | `lockedPosition` — lock pan/zoom toggle in context menu | VideoplayerWindowState.h | Small |
| 9 | 🔵 Future | core/keybindings.py + app.py | Chord persistence (save user_chords → JSON, reload on startup) | KeybindingState.h | Medium |
| 10 | 🔵 Future | videoplayer_controls.py | Measured playback speed (actualPlaybackSpeed) | OFS_VideoplayerControls.cpp | Medium |
| 11 | 🔵 Future | videoplayer_window.py | Half-pane video modes (Left/Right/Top/Bottom rendering) | OFS_VideoplayerWindow.cpp | Medium |
| 12 | 🔵 Future | videoplayer_controls.py | Video thumbnail preview on hover | OFS_Videopreview.h (2nd mpv) | Large |
| 13 | 🟢 Low | app.py | Panel visibility persisted on exit + restored on launch | OpenFunscripterState.h | Small |
| 14 | 🟢 Low | app.py | `alwaysShowBookmarkLabels` — always render bookmark name text on timeline | OpenFunscripterState.h | Small |
| 15 | 🟢 Low | app.py + preferences.py | `heatmapSettings` — configurable default heatmap width/height/path | OpenFunscripterState.h | Small |
| 16 | 🟢 Low | metadata_editor.py | Default metadata template (Save as template / Load template) | MetadataEditorState.h | Small |
| 17 | 🟢 Low | websocket_api.py + app.py | `serverActive` persistence — auto-restart WS server on launch if was active | WebsocketApiState.h | Small |
| 18 | 🟢 Low | script_timeline.py | `ShowLines` / `ShowPoints` toggle in timeline context menu | ScriptPositionsOverlayMode.h | Small |
| 19 | 🟢 Low | core/keybindings.py | Mouse wheel direction triggers (scroll-up vs scroll-down as separate bindings) | OFS_KeybindingSystem.cpp | Small |

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
