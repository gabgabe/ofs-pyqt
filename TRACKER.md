# OFS-PyQt Implementation Tracker

Last updated: 2026-02-21 (session 6)

Legend: ✅ Done · 🔄 Partial · ⬜ Not started · ❌ Won't do

---

## src/ui/script_timeline.py

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-track lane rendering | ✅ | One lane per enabled Funscript |
| Gradient track backgrounds (purple/dark-blue) | ✅ | OFS-accurate colours |
| Per-track border (green=active, blue-grey=has-sel, white=default) | ✅ | |
| Hover highlight (white 10/255) | ✅ | |
| Clip rect per track | ✅ | |
| Height guide lines (0/25/50/75/100%) | ✅ | |
| Action dots (dynamic size + opacity) | ✅ | |
| Speed-based line colours (High/Mid/Low) | ✅ | |
| Selection highlight (bright green segment) | ✅ | |
| Playhead triangle + thick vertical line per track | ✅ | |
| Selection box only on active track | ✅ | |
| Seconds label on ruler | ✅ | |
| Smooth zoom animation (easeOutExpo 150 ms) | ✅ | |
| Hand cursor on dot hover | ✅ | |
| Active-script-only hit-testing | ✅ | |
| Plain-drag = selection (no modifier needed) | ✅ | |
| Shift modifier = add/move selection | ✅ | |
| Ctrl = additive selection on release | ✅ | |
| Middle-click-double = clear selection | ✅ | |
| Auto-scroll with OFS 3% margin | ✅ | |
| Track-switch on click of inactive track | ✅ | Dispatches CHANGE_ACTIVE_SCRIPT |
| Context menu (enable/disable with auto-switch) | ✅ | |
| `_get_track_y()` helper | ✅ | |
| Line rendering for off-screen actions (edge actions) | ✅ | Fixed: prev_edge / next_edge |
| Waveform / audio overlay | ⬜ | OFS_Waveform.cpp not ported |
| Scrubbing via playhead drag | ⬜ | Click on ruler seeks, drag not yet |

---

## src/ui/videoplayer_controls.py

| Feature | Status | Notes |
|---------|--------|-------|
| Heatmap pre-computation (speed-based colours) | ✅ | 256 segments |
| Play/Pause, PrevFrame, NextFrame buttons | ✅ | |
| Mute / Volume slider | ✅ | |
| Speed input field | ✅ | |
| ±3 s seek buttons | ✅ | |
| 1× / −10% / +10% speed buttons | ✅ | |
| Seek-pause-resume on slider drag | ✅ | `_drag_was_paused` flag |
| Custom DrawList timeline widget | ✅ | invisible_button + full DrawList rendering |
| Progress fill + background | ✅ | Filled bar shows progress |
| Heatmap overlay on timeline bar | ✅ | Drawn on top of progress fill |
| Chapters drawn on timeline bar | ✅ | Coloured strips (top 28%) + names |
| Active-chapter white border on timeline | ✅ | |
| Bookmarks drawn on timeline bar | ✅ | White circles at bottom |
| Chapter context menus on timeline bar | ✅ | Seek to start/end via right-click |
| Hover tooltip with time + delta | ✅ | mm:ss.xx + ±delta |
| Hover cursor vertical line | ✅ | Semi-transparent white |
| Time label below bar | ✅ | |
| Measured playback speed display | ⬜ | Would need mpv `speed` observable |
| Video thumbnail preview on hover | ⬜ | Needs VideoPreview FBO (complex) |

---

## src/ui/panels/metadata_editor.py

| Feature | Status | Notes |
|---------|--------|-------|
| Modal popup (blocks input) | ✅ | `begin_popup_modal` centered |
| title, creator, description, type, video_url | ✅ | |
| script_url field | ✅ | |
| notes multiline field | ✅ | |
| Duration read-only label | ✅ | |
| License combo (None/Free/Paid/CC…) | ✅ | |
| Tags chips (click × to remove, + to add) | ✅ | |
| Performers chips | ✅ | |
| Save template / Load template buttons | ✅ | ~/.ofs-pyqt/metadata_template.json |
| Save project button | ✅ | |

---

## src/ui/panels/preferences.py

| Feature | Status | Notes |
|---------|--------|-------|
| Tab bar (Application / Videoplayer / Scripting) | ✅ | |
| Language selector combo (auto-discovers CSVs) | ✅ | |
| Font size | ✅ | |
| Font override file picker + Clear | ✅ | |
| Light/dark theme toggle | ✅ | |
| FPS limit + VSync | ✅ | |
| Show metadata on new project checkbox | ✅ | Now wired to auto-open MetadataEditor |
| Hardware decoding | ✅ | |
| Fast step amount | ✅ | |
| Default speed | ✅ | |
| Auto-backup interval | ✅ | |
| Show heatmap | ✅ | |
| Action dot radius | ✅ | |
| Max-speed highlight threshold | ✅ | |
| Hot-reload font on change | ⬜ | Needs imgui rebuild after change |

---

## src/ui/panels/chapter_manager.py

| Feature | Status | Notes |
|---------|--------|-------|
| 4-column resizable table (Name/Begin/End/Controls) | ✅ | `imgui.begin_table` |
| Inline double-click name editing | ✅ | |
| Per-chapter color swatch + color_picker4 | ✅ | |
| Bookmarks table | ✅ | |
| Persistence to project `_extra_state` | ✅ | |
| Load/save on project change | ✅ | |
| Export Clip via FFmpeg | ⬜ | Needs subprocess + ffmpeg |
| Chapter resize (SetChapterSize) | ⬜ | OFS right-click context menu feature |

---

## src/ui/panels/special_functions.py

| Feature | Status | Notes |
|---------|--------|-------|
| Combo selector (Range Extender / Simplify RDP) | ✅ | |
| RDP epsilon scaled by avg inter-action distance | ✅ | |
| Range Extender live-drag (undo-collapse) | ✅ | undo→re-snapshot per tick |
| Range Extender Reset button | ✅ | |

---

## src/ui/panels/simulator.py  ← FULL REWRITE THIS SESSION

| Feature | Status | Notes |
|---------|--------|-------|
| Basic position indicator bar | ✅ | |
| Draggable P1 / P2 endpoints | ✅ | Hand cursor, drag detection |
| Center-drag to move entire bar | ✅ | Resize-all cursor |
| Lock checkbox | ✅ | Freezes drag |
| Center / Invert / Load / Save config buttons | ✅ | |
| Collapsing configuration section | ✅ | `collapsing_header` |
| 6 color editors (Text/Border/Front/Back/Indicator/ExtraLines) | ✅ | `color_edit4` |
| Width / BorderWidth / LineWidth sliders | ✅ | |
| Opacity slider | ✅ | Applied globally to all draw calls |
| ExtraLinesCount + ExtraLineWidth | ✅ | |
| Height tick marks at 10% intervals | ✅ | Perpendicular lines i=1..9 |
| Extra lines above/below range | ✅ | |
| EnableHeightLines / EnableIndicators / EnablePosition toggles | ✅ | |
| Prev/next action indicators + numeric labels | ✅ | Uses `script.get_*` proxies |
| Center position text | ✅ | Drawn at bar midpoint |
| Background + front-fill line drawing via foreground DrawList | ✅ | |
| Border quad | ✅ | `add_quad` |
| Vanilla mode (read-only VSlider fallback) | ✅ | `begin_disabled` + `v_slider_float` |
| Reset to defaults button | ✅ | |
| Config persistence (~/.ofs-pyqt/sim_config.json) | ✅ | |
| Mouse-to-position mapping (`mouse_value` / `mouse_on_sim`) | ✅ | |
| Spline-mode position evaluation | ⬜ | FunscriptSpline.h not ported |

---

## src/ui/panels/statistics.py

| Feature | Status | Notes |
|---------|--------|-------|
| Total / selected action count | ✅ | |
| Average / max / min speed | ✅ | |
| Median speed | ✅ | Added this session |
| Average / max / min position | ✅ | |
| Actions per minute | ✅ | |
| Selection duration | ✅ | |
| Reactive cache (hash-based) | ✅ | |

---

## src/ui/panels/scripting_mode.py

| Feature | Status | Notes |
|---------|--------|-------|
| Normal mode (add/edit on spacebar) | ✅ | |
| Action offset delay slider (ms) | ✅ | |
| Recording mode stub | 🔄 | UI stub only |
| Dynamic / Fixed step modes | 🔄 | Basic switching |

---

## src/ui/panels/action_editor.py

| Feature | Status | Notes |
|---------|--------|-------|
| Button grid (0–100 in configurable steps) | ✅ | |
| Current position highlighting | ✅ | |
| Nearest action display | ✅ | |
| Step selector | ✅ | |

---

## src/ui/panels/undo_history.py

| Feature | Status | Notes |
|---------|--------|-------|
| Scrollable undo/redo list | ✅ | |
| Current position marker | ✅ | |
| Redo entries greyed out | ✅ | |
| Click to jump to undo state | ✅ | Added this session via `UndoSystem.jump_to()` |
| Auto-scroll | ✅ | |

---

## src/core/project.py

| Feature | Status | Notes |
|---------|--------|-------|
| Load / save .ofsp JSON | ✅ | |
| Funscript import + multi-axis detection | ✅ | |
| Media path resolution (relative/absolute) | ✅ | |
| Metadata persistence | ✅ | |
| `_extra_state` (chapters/bookmarks) | ✅ | |
| Auto-backup | ✅ | |
| "Show metadata on new project" hook | ✅ | Added this session |

---

## src/core/undo_system.py

| Feature | Status | Notes |
|---------|--------|-------|
| Per-script FunscriptUndoSystem | ✅ | |
| Global UndoSystem (multi-script contexts) | ✅ | |
| Undo / Redo | ✅ | |
| `jump_to(idx)` — jump to arbitrary history position | ✅ | Added this session |

---

## src/core/funscript.py

| Feature | Status | Notes |
|---------|--------|-------|
| Load / save .funscript | ✅ | |
| Action array (sorted, binary search) | ✅ | |
| Selection (add/remove/clear/has) | ✅ | |
| Range extend selection | ✅ | |
| Spline interpolation | ⬜ | FunscriptSpline.h not ported |

---

## Outstanding

| # | File | Feature | Complexity |
|---|------|---------|-----------|
| 1 | videoplayer_controls | Video thumbnail preview on hover (VideoPreview FBO) | Large |
| 2 | chapter_manager | Export Clip via subprocess + ffmpeg | Large |
| 3 | script_timeline | Waveform audio overlay (OFS_Waveform) | Large |
| 4 | funscript.py | Spline interpolation (FunscriptSpline) | Medium |
| 5 | scripting_mode | Recording mode (full) | Medium |
| 6 | simulator | Spline-mode position eval | Medium |
| 7 | preferences | Hot-reload font | Medium |
| 8 | script_timeline | Playhead drag to scrub | Small |
| 9 | chapter_manager | Chapter resize (SetChapterSize context menu) | Small |


Legend: ✅ Done · 🔄 Partial · ⬜ Not started · ❌ Won't do

---

## src/ui/script_timeline.py

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-track lane rendering | ✅ | One lane per enabled Funscript |
| Gradient track backgrounds (purple/dark-blue) | ✅ | OFS-accurate colours |
| Per-track border (green=active, blue-grey=has-sel, white=default) | ✅ | |
| Hover highlight (white 10/255) | ✅ | |
| Clip rect per track | ✅ | |
| Height guide lines (0/25/50/75/100%) | ✅ | |
| Action dots (dynamic size + opacity) | ✅ | |
| Speed-based line colours (High/Mid/Low) | ✅ | |
| Selection highlight (bright green segment) | ✅ | |
| Playhead triangle + thick vertical line per track | ✅ | |
| Selection box only on active track | ✅ | |
| Seconds label on ruler | ✅ | |
| Smooth zoom animation (easeOutExpo 150 ms) | ✅ | |
| Hand cursor on dot hover | ✅ | |
| Active-script-only hit-testing | ✅ | |
| Plain-drag = selection (no modifier needed) | ✅ | |
| Shift modifier = add/move selection | ✅ | |
| Ctrl = additive selection on release | ✅ | |
| Middle-click-double = clear selection | ✅ | |
| Auto-scroll with OFS 3% margin | ✅ | |
| Track-switch on click of inactive track | ✅ | Dispatches CHANGE_ACTIVE_SCRIPT |
| Context menu (enable/disable with auto-switch) | ✅ | |
| `_get_track_y()` helper | ✅ | |
| Line rendering for off-screen actions (edge actions) | ✅ | Fixed: prev_edge / next_edge |
| Waveform / audio overlay | ⬜ | OFS_Waveform.cpp not ported |
| Scrubbing via playhead drag | ⬜ | Click on ruler seeks, drag not yet |

---

## src/ui/videoplayer_controls.py

| Feature | Status | Notes |
|---------|--------|-------|
| Heatmap pre-computation (speed-based colours) | ✅ | 256 segments |
| Play/Pause, PrevFrame, NextFrame buttons | ✅ | |
| Mute / Volume slider | ✅ | |
| Speed input field | ✅ | |
| ±3 s seek buttons | ✅ | |
| 1× / −10% / +10% speed buttons | ✅ | |
| Seek-pause-resume on slider drag | ✅ | `_drag_was_paused` flag |
| Custom DrawList timeline widget | ✅ | Filled bar + heatmap + cursor line |
| Chapters drawn on timeline bar | ✅ | Coloured strips at top + names |
| Bookmarks drawn on timeline bar | ✅ | White circles at bottom |
| Chapter context menus on timeline bar | ✅ | Seek to start/end |
| Hover tooltip with time + delta | ✅ | |
| Hover cursor vertical line | ✅ | |
| Measured playback speed display | ⬜ | Would need mpv `speed` observable |
| Video thumbnail preview on hover | ⬜ | Needs VideoPreview FBO (complex) |

---

## src/ui/panels/metadata_editor.py

| Feature | Status | Notes |
|---------|--------|-------|
| Modal popup (blocks input) | ✅ | `begin_popup_modal` centered |
| title, creator, description, type, video_url | ✅ | |
| script_url field | ✅ | |
| notes multiline field | ✅ | |
| Duration read-only label | ✅ | |
| License combo (None/Free/Paid/CC…) | ✅ | |
| Tags chips (click × to remove, + to add) | ✅ | |
| Performers chips | ✅ | |
| Save template / Load template buttons | ✅ | ~/.ofs-pyqt/metadata_template.json |
| Save project button | ✅ | |

---

## src/ui/panels/preferences.py

| Feature | Status | Notes |
|---------|--------|-------|
| Tab bar (Application / Videoplayer / Scripting) | ✅ | |
| Language selector combo (auto-discovers CSVs) | ✅ | |
| Font size | ✅ | |
| Font override file picker + Clear | ✅ | |
| Light/dark theme toggle | ✅ | |
| FPS limit + VSync | ✅ | |
| Show metadata on new project checkbox | ✅ | |
| Hardware decoding | ✅ | |
| Fast step amount | ✅ | |
| Default speed | ✅ | |
| Auto-backup interval | ✅ | |
| Show heatmap | ✅ | |
| Action dot radius | ✅ | |
| Max-speed highlight threshold | ✅ | |
| Hot-reload font on change | ⬜ | Needs imgui rebuild after change |

---

## src/ui/panels/chapter_manager.py

| Feature | Status | Notes |
|---------|--------|-------|
| 4-column resizable table (Name/Begin/End/Controls) | ✅ | `imgui.begin_table` |
| Inline double-click name editing | ✅ | |
| Per-chapter color swatch + color_picker4 | ✅ | |
| Bookmarks table | ✅ | |
| Persistence to project `_extra_state` | ✅ | |
| Load/save on project change | ✅ | |
| Export Clip via FFmpeg | ⬜ | Needs subprocess + ffmpeg |
| Chapter resize (SetChapterSize) | ⬜ | OFS right-click context menu feature |

---

## src/ui/panels/special_functions.py

| Feature | Status | Notes |
|---------|--------|-------|
| Combo selector (Range Extender / Simplify RDP) | ✅ | |
| RDP epsilon scaled by avg inter-action distance | ✅ | |
| Range Extender live-drag (undo-collapse) | ✅ | undo→re-snapshot per tick |
| Range Extender Reset button | ✅ | |

---

## src/ui/panels/simulator.py

| Feature | Status | Notes |
|---------|--------|-------|
| Basic position indicator bar | ✅ | |
| Draggable P1 / P2 endpoints | ✅ | Hand cursor, drag detection |
| Center-drag to move entire bar | ✅ | Resize-all cursor |
| Lock checkbox | ✅ | |
| Center / Invert / Load / Save config buttons | ✅ | |
| Collapsing configuration section | ✅ | |
| 6 color editors (Text/Border/Front/Back/Indicator/ExtraLines) | ✅ | |
| Width / BorderWidth / LineWidth / Opacity sliders | ✅ | |
| ExtraLinesCount + ExtraLineWidth | ✅ | |
| Height tick marks at 10% intervals | ✅ | |
| Extra lines above/below range | ✅ | |
| EnableHeightLines / EnableIndicators / EnablePosition toggles | ✅ | |
| Prev/next action indicators + numeric labels | ✅ | |
| Center position text | ✅ | |
| Vanilla mode (VSliderFloat fallback) | ✅ | |
| Reset to defaults button | ✅ | |
| Config persistence (~/.ofs-pyqt/sim_config.json) | ✅ | |
| Mouse-to-position mapping (MouseOnSimulator) | ✅ | |
| Spline-mode position evaluation | ⬜ | FunscriptSpline.h not ported |

---

## src/ui/panels/statistics.py

| Feature | Status | Notes |
|---------|--------|-------|
| Total / selected action count | ✅ | |
| Average / max / min speed | ✅ | |
| Average / max / min position | ✅ | |
| Actions per minute | ✅ | |
| Selection duration | ✅ | |
| Reactive cache (hash-based) | ✅ | |
| Median speed | ⬜ | Nice-to-have |

---

## src/ui/panels/scripting_mode.py

| Feature | Status | Notes |
|---------|--------|-------|
| Normal mode (add/edit on spacebar) | ✅ | |
| Action offset delay slider (ms) | ✅ | |
| Recording mode stub | 🔄 | UI stub only |
| Dynamic / Fixed step modes | 🔄 | Basic switching |

---

## src/ui/panels/action_editor.py

| Feature | Status | Notes |
|---------|--------|-------|
| Button grid (0–100 in configurable steps) | ✅ | |
| Current position highlighting | ✅ | |
| Nearest action display | ✅ | |
| Step selector | ✅ | |

---

## src/ui/panels/undo_history.py

| Feature | Status | Notes |
|---------|--------|-------|
| Scrollable undo/redo list | ✅ | |
| Current position marker | ✅ | |
| Redo entries greyed out | ✅ | |
| Click to jump to state | ⬜ | Core doesn't yet support jump-to |
| Auto-scroll | ✅ | |

---

## src/core/project.py

| Feature | Status | Notes |
|---------|--------|-------|
| Load / save .ofsp JSON | ✅ | |
| Funscript import + multi-axis detection | ✅ | |
| Media path resolution (relative/absolute) | ✅ | |
| Metadata persistence | ✅ | |
| `_extra_state` (chapters/bookmarks) | ✅ | |
| Auto-backup | ✅ | |
| "Show metadata on new project" hook | ⬜ | preference exists, not wired |

---

## src/core/funscript.py

| Feature | Status | Notes |
|---------|--------|-------|
| Load / save .funscript | ✅ | |
| Action array (sorted, binary search) | ✅ | |
| Selection (add/remove/clear/has) | ✅ | |
| Range extend selection | ✅ | |
| Spline interpolation | ⬜ | FunscriptSpline.h not ported |

---

## Outstanding — High Priority

| # | File | Feature | Complexity |
|---|------|---------|-----------|
| 1 | videoplayer_controls | Video thumbnail preview on hover (VideoPreview FBO) | Large |
| 2 | project.py | Wire `show_metadata_on_new` pref when opening new project | Small |
| 3 | chapter_manager | Export Clip via subprocess + ffmpeg | Large |
| 4 | undo_history | Click-to-jump to undo state | Medium |
| 5 | funscript.py | Spline interpolation (FunscriptSpline) | Medium |
| 6 | script_timeline | Playhead drag to scrub | Small |
| 7 | script_timeline | Waveform audio overlay | Large |

---

## Outstanding — Lower Priority

| # | File | Feature | Complexity |
|---|------|---------|-----------|
| 8 | statistics | Median speed | Small |
| 9 | preferences | Hot-reload font | Medium |
| 10 | scripting_mode | Recording mode (full) | Medium |
| 11 | simulator | Spline-mode position eval | Medium |
