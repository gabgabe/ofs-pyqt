# Feature Tracker

All changes from this point forward are tracked here.

---

## Session 22 — Multi-media architecture overhaul

### ✅ Dead code analysis
- **Files affected**: all `src/` files
- **Description**: Identified all single-media patterns: `project.media_path`, `PickDifferentMedia()`, `AddOrUpdateVideoTrack()` hardcoded to `vtracks[0]`, single `_player` reference in `TimelineManager`.

### ~~✅ New project → empty video track~~ *(superseded by Session 23: empty timeline)*
- **Files**: `src/ui/app.py`
- **Description**: ~~`_do_new_project()` now creates a Video layer + empty placeholder video track.~~ Replaced in Session 23 — new projects are now completely empty.

### ✅ Fix crash on second media scroll (color format)
- **Files**: `src/ui/app.py`
- **Description**: `_add_media_to_timeline()` was passing 0-255 integer color `(100, 150, 220, 200)` to `_col32()` which expects 0-1 floats. Fixed to `(0.39, 0.59, 0.86, 0.78)`.

### ✅ Remove dead single-media code
- **Files**: `src/ui/app.py`, `src/ui/app_menu.py`
- **Description**: Deleted `PickDifferentMedia()` method and "Pick different media" menu item. Updated `_init_project()` to load video from per-track `VideoTrackData.media_path` instead of `project.media_path` (with legacy fallback).

### ✅ Multi-video player pool
- **Files**: `src/core/timeline_manager.py`, `src/ui/app.py`, `src/ui/videoplayer_window.py`
- **Description**: Complete multi-video architecture:
  - `TimelineManager` now has `_players: Dict[str, OFS_Videoplayer]` — per-track player pool.
  - New methods: `RegisterPlayer()`, `UnregisterPlayer()`, `GetPlayerForTrack()`, `ActivePlayer()`, `AnyPlayerLoaded()`, `AnyPlayerPlaying()`.
  - `Tick()` syncs ALL video players to their respective tracks (not just `vtracks[0]`).
  - `AddOrUpdateVideoTrack(track_id=None)` updates specific or all tracks from their players.
  - `SyncFromPlayer()` uses the active player under the transport cursor.
  - `app.py`: `_create_player_for_track()` / `_destroy_player_for_track()` manage player lifecycle.
  - `_init_project()` creates players for all video tracks (primary + pool).
  - `_pre_new_frame()` calls `Update()` for ALL players.
  - `_after_swap()` calls `NotifySwap()` for ALL players.
  - `_add_media_to_timeline()` creates a pool player for the new track.
  - `videoplayer_window.py`: `Draw()` resolves `ActivePlayer()` from pool and renders the correct texture.

### ✅ Color palettes in Track Info panel
- **Files**: `src/ui/panels/track_info.py`
- **Description**: Added 12-color swatch palette (same as Add Track wizard) below the RGB color mixer in the Track Info panel. Clicking a swatch sets the track color. The currently matching palette entry gets a white border highlight.

---

## Session 23 — Layer logic, empty projects, color picker popup

### ✅ Empty timeline on new project
- **Files**: `src/ui/app.py`, `src/core/timeline_manager.py`
- **Description**: New projects now create a completely empty timeline (no Video layer, no tracks). Video tracks are added manually by the user via drag-and-drop or menu. `_build_default_layout()` only creates a Video layer+track when `media_path` is non-empty. `_reconcile_funscripts()` no longer force-creates a Video layer.

### ✅ Layer management UI
- **Files**: `src/ui/script_timeline.py`, `src/core/events.py`
- **Description**: Full layer management system:
  - **Layer label column** (100px) now visible on the left of the DAW timeline, with layer name + interactive Mute (M) and Lock (L) toggle buttons.
  - **Context menu → Layers**: Add Layer, per-layer submenu with Mute, Lock, Rename, Move Up/Down, Remove Layer.
  - **Rename popup**: Opens a text input popup to rename a layer.
  - **Lock overlay**: Locked layers show a subtle amber overlay. Actions on locked layers are blocked (no clip drag, no action creation, no selection rect).
  - **New events**: `TIMELINE_LAYER_ADDED`, `TIMELINE_LAYER_REMOVED`, `TIMELINE_LAYER_RENAMED`.

### ✅ Color palette moved into picker popup
- **Files**: `src/ui/panels/track_info.py`
- **Description**: The 12-color palette swatches are now inside the color picker popup (opened by clicking the color button), not below the RGB mixer. The popup contains a full `color_picker3` widget plus a "Palette" section with the swatches arranged in a 6×2 grid.

---

## Backlog / Future

### ⏳ Save pattern redesign
- **Status**: Not yet designed — awaiting instructions.
- **Description**: The project save format needs rethinking for multi-media timelines. Currently `.ofsp` stores a single `media_path` globally.

### ⏳ Deprecate `project.media_path`
- **Status**: Low priority — legacy fallback still works for old `.ofsp` files.
- **Description**: `OFS_Project.media_path` should eventually be removed in favor of per-track `VideoTrackData.media_path`. Currently kept for backward compatibility.

### ⏳ Per-track waveform support
- **Status**: Not started.
- **Description**: Currently waveform data is global (`self.waveform`). For multi-video, each video track should have its own waveform data displayed in its DAW clip.
