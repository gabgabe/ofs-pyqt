"""
OFS_Project — Python port of OFS_Project.h / OFS_Project.cpp

Manages:
  - A list of Funscript objects (multi-axis support)
  - Media path resolution (relative / absolute)
  - Project state persistence as a JSON-based .ofsp file
  - Import from .funscript file or media file
  - Export individual or all funscripts
  - Auto-detection of related multi-axis scripts
  - Unsaved-edit tracking
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable

from .funscript import Funscript, FunscriptMetadata
from .undo_system import UndoSystem

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extension constants
# ---------------------------------------------------------------------------

PROJECT_EXTENSION = ".ofsp"

# Formats supported by mpv (via libav/ffmpeg) on macOS and Linux.
# .wmv/.wma/.asf excluded — Windows Media formats rarely used outside Windows.
VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    # Common containers
    ".mp4", ".mkv", ".webm", ".avi",
    # Apple / macOS native
    ".mov", ".m4v",
    # Streaming / broadcast
    ".ts", ".m2ts", ".mts", ".flv",
    # MPEG legacy
    ".mpg", ".mpeg", ".vob",
    # Ogg / open formats
    ".ogv",
    # Mobile
    ".3gp", ".3g2",
    # Raw / other
    ".rm", ".rmvb",
})

AUDIO_EXTENSIONS: frozenset[str] = frozenset({
    # Lossy
    ".mp3", ".aac", ".ogg", ".opus", ".m4a",
    # Lossless
    ".flac", ".wav", ".aiff", ".aif",
    # macOS native
    ".caf", ".alac",
    # Other
    ".wv", ".ape",
})

MEDIA_EXTENSIONS: frozenset[str] = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Multi-axis axes reordering (OFS preference — roll/pitch/twist last → first)
_MULTIAXIS_ORDER = [".twist.funscript", ".pitch.funscript", ".roll.funscript"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _has_media_extension(path: str) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def _find_media_for_script(script_path: str) -> Optional[str]:
    """Find a media file next to script_path with the same stem."""
    p = Path(script_path)
    stem = p.stem  # remove .funscript
    parent = p.parent
    for entry in parent.iterdir():
        if entry.stem == stem and entry.suffix.lower() in MEDIA_EXTENSIONS:
            return str(entry)
    return None


def _find_related_scripts(root_path: str) -> List[str]:
    """
    Discover multi-axis funscripts adjacent to root_path.
    E.g. video.funscript → video.twist.funscript, video.pitch.funscript …

    Returns paths sorted to place roll/pitch/twist at the front (OFS convention).
    """
    root = Path(root_path)
    stem = root.stem  # e.g. "myvideo"
    prefix = stem + "."
    parent = root.parent

    related: List[Path] = []
    try:
        for entry in parent.iterdir():
            name = entry.name
            if (
                entry.suffix.lower() == ".funscript"
                and name.startswith(prefix)
                and str(entry) != root_path
            ):
                related.append(entry)
    except OSError as e:
        log.warning(f"Could not scan directory {parent}: {e}")

    # Sort: preferred order first
    def sort_key(p: Path) -> int:
        for i, ending in enumerate(_MULTIAXIS_ORDER):
            if str(p).endswith(ending):
                return len(_MULTIAXIS_ORDER) - i  # higher = earlier
        return 0

    return [str(p) for p in sorted(related, key=sort_key, reverse=True)]


# ---------------------------------------------------------------------------
# ProjectState — mirrors OFS ProjectState struct
# ---------------------------------------------------------------------------

class ProjectState:
    """Persistent project state embedded in the .ofsp file. Mirrors ``OFS_Project::ProjectState``."""

    def __init__(self):
        self.relative_media_path: str = ""
        self.active_timer: float = 0.0
        self.last_player_position: float = 0.0
        self.active_script_idx: int = 0
        self.nudge_metadata: bool = True

    def to_dict(self) -> dict:
        return {
            "relativeMediaPath": self.relative_media_path,
            "activeTimer": self.active_timer,
            "lastPlayerPosition": self.last_player_position,
            "activeScriptIdx": self.active_script_idx,
            "nudgeMetadata": self.nudge_metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectState":
        ps = cls()
        ps.relative_media_path = d.get("relativeMediaPath", "")
        ps.active_timer = float(d.get("activeTimer", 0.0))
        ps.last_player_position = float(d.get("lastPlayerPosition", 0.0))
        ps.active_script_idx = int(d.get("activeScriptIdx", 0))
        ps.nudge_metadata = bool(d.get("nudgeMetadata", True))
        return ps


# ---------------------------------------------------------------------------
# OFS_Project
# ---------------------------------------------------------------------------

class OFS_Project:
    """
    Manages the loaded project — a collection of Funscripts associated with
    one media file.  Mirrors OFS OFS_Project class.

    Typical workflow::

        # Open via funscript
        project = OFS_Project()
        project.ImportFromFunscript("/path/to/script.funscript")

        # Open via media
        project = OFS_Project()
        project.ImportFromMedia("/path/to/video.mp4")

        # Load existing project file
        project = OFS_Project()
        project.Load("/path/to/project.ofsp")

        # Save
        project.Save()

        # Export all funscripts
        project.ExportFunscripts()
    """

    def __init__(self) -> None:
        self._path: str = ""           # absolute path to the .ofsp file
        self._valid: bool = False
        self._errors: List[str] = []

        self.funscripts: List[Funscript] = []
        self.state: ProjectState = ProjectState()
        self.undo_system: UndoSystem = UndoSystem()

        # Shared metadata (from first funscript, OFS convention)
        self.metadata: FunscriptMetadata = FunscriptMetadata()

        # Extra state (chapters, bookmarks, etc.) — arbitrary JSON dict
        self._extra_state: dict = {}

        # Change-notification callbacks
        self._changed_callbacks: List[Callable] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    @property
    def is_valid(self) -> bool:
        return self._valid

    @property
    def errors(self) -> str:
        return "\n".join(self._errors)

    @property
    def active_idx(self) -> int:
        return self.state.active_script_idx

    @active_idx.setter
    def active_idx(self, idx: int) -> None:
        if 0 <= idx < len(self.funscripts):
            self.state.active_script_idx = idx

    @property
    def active_script(self) -> Optional[Funscript]:
        if not self.funscripts:
            return None
        idx = min(self.state.active_script_idx, len(self.funscripts) - 1)
        return self.funscripts[idx]

    @property
    def media_path(self) -> str:
        """Absolute path to the media file."""
        return self._make_path_absolute(self.state.relative_media_path)

    # ------------------------------------------------------------------
    # Load / Import
    # ------------------------------------------------------------------

    def Load(self, path: str) -> bool:
        """Load a .ofsp project file. Mirrors ``OFS_Project::Load``."""
        if self._valid:
            log.warning("Project already loaded; call reset() first.")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except Exception as e:
            self._add_error(f"Failed to read project file: {e}")
            return False

        self._path = path

        # Restore project state
        self.state = ProjectState.from_dict(doc.get("projectState", {}))

        # Restore metadata
        meta_d = doc.get("metadata", {})
        self.metadata = FunscriptMetadata(
            type=meta_d.get("type", "basic"),
            title=meta_d.get("title", ""),
            creator=meta_d.get("creator", ""),
            script_url=meta_d.get("script_url", ""),
            video_url=meta_d.get("video_url", ""),
            tags=meta_d.get("tags", []),
            performers=meta_d.get("performers", []),
            description=meta_d.get("description", ""),
            license=meta_d.get("license", ""),
            notes=meta_d.get("notes", ""),
            duration=meta_d.get("duration", 0),
        )

        # Restore funscripts (stored as relative paths in the ofsp file)
        self.funscripts.clear()
        for rel_path in doc.get("scripts", []):
            abs_path = self._make_path_absolute(rel_path)
            self._load_funscript(abs_path)

        if not self.funscripts:
            # Ensure at least one empty script slot
            self.funscripts.append(self._make_empty_script(""))

        # Extra state (chapters, bookmarks, …)
        self._extra_state = doc.get("extraState", {})

        self._valid = True
        log.info(f"Loaded project: {path} ({len(self.funscripts)} scripts)")
        return True

    def ImportFromFunscript(self, path: str) -> bool:
        """Create a project from an existing .funscript file. Mirrors ``OFS_Project::ImportFromFunscript``."""
        if self._valid:
            log.warning("Project already loaded.")
            return False

        if not os.path.isfile(path):
            self._add_error(f"File not found: {path}")
            return False

        base = Path(path)
        self._path = str(base.with_suffix(PROJECT_EXTENSION))

        self.funscripts.clear()
        self._load_funscript(path)

        # Load related multi-axis scripts
        for rel_path in _find_related_scripts(path):
            if rel_path != path:
                self._load_funscript(rel_path)

        # Use metadata from first funscript
        if self.funscripts:
            self.metadata = self.funscripts[0].metadata

        # Try to auto-detect media
        media = _find_media_for_script(path)
        if media:
            self.state.relative_media_path = self._make_path_relative(media)
            self._valid = True
            log.info(f"Imported from funscript: {path}, media: {media}")
        else:
            self._add_error("Could not auto-detect media file.")
            # Still allow the project to be used — media can be set later
            self._valid = True
            log.warning(f"No media found for {path}; project partially valid.")

        return self._valid

    def ImportFromMedia(self, path: str) -> bool:
        """Create a project from a media file.

        Only loads *existing* funscripts that live alongside the media.
        Does **not** auto-create an empty funscript — the user adds scripts
        manually via the DAW timeline (right-click → Add axis).
        """
        if self._valid:
            log.warning("Project already loaded.")
            return False

        if not _has_media_extension(path):
            self._add_error(f"Unsupported media extension: {Path(path).suffix}")
            return False

        if not os.path.isfile(path):
            self._add_error(f"Media file not found: {path}")
            return False

        base = Path(path)
        self._path = str(base.with_suffix(PROJECT_EXTENSION))
        self.state.relative_media_path = self._make_path_relative(path)

        # Load only existing funscripts (do NOT create empty ones)
        funscript_path = str(base.with_suffix(".funscript"))
        self.funscripts.clear()
        if os.path.isfile(funscript_path):
            self._load_funscript(funscript_path)

        # Load any existing multi-axis scripts
        for rel_path in _find_related_scripts(funscript_path):
            self._load_funscript(rel_path)

        self._valid = True
        log.info(f"Imported from media: {path}")
        return True

    def set_media_path(self, abs_path: str) -> bool:
        """Assign a media file to an existing project (Pick Different Media)."""
        if not _has_media_extension(abs_path):
            log.warning(f"Unsupported media extension: {abs_path}")
            return False
        self.state.relative_media_path = self._make_path_relative(abs_path)
        self._notify_changed()
        return True

    # ------------------------------------------------------------------
    # Save / Export
    # ------------------------------------------------------------------

    def Save(self, path: Optional[str] = None, clear_unsaved: bool = True) -> bool:
        """Save project to .ofsp file (JSON). Mirrors ``OFS_Project::Save``."""
        save_path = path or self._path
        if not save_path:
            log.error("No project path set.")
            return False

        self._path = save_path
        doc = {
            "version": "1.0",
            "projectState": self.state.to_dict(),
            "metadata": {
                "type": self.metadata.type,
                "title": self.metadata.title,
                "creator": self.metadata.creator,
                "script_url": self.metadata.script_url,
                "video_url": self.metadata.video_url,
                "tags": self.metadata.tags,
                "performers": self.metadata.performers,
                "description": self.metadata.description,
                "license": self.metadata.license,
                "notes": self.metadata.notes,
                "duration": self.metadata.duration,
            },
            "scripts": [
                self._make_path_relative(self._make_path_absolute(s.relative_path))
                if s.relative_path else ""
                for s in self.funscripts
            ],
            "extraState": self._extra_state,
        }

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2)
            log.info(f"Saved project: {save_path}")
        except Exception as e:
            log.error(f"Failed to save project: {e}")
            return False

        if clear_unsaved:
            for s in self.funscripts:
                s.unsaved_edits = False

        return True

    def ExportFunscripts(self, output_dir: Optional[str] = None) -> int:
        """
        Export all funscripts as .funscript files. Mirrors ``OFS_Project::ExportFunscripts``.

        Parameters
        ----------
        output_dir:
            If None, export next to the project file (original paths).
            Otherwise write into the given directory.

        Returns
        -------
        Number of successfully exported scripts.
        """
        count = 0
        for i, script in enumerate(self.funscripts):
            if output_dir:
                filename = Path(self._make_path_absolute(script.relative_path)).name
                out_path = str(Path(output_dir) / filename)
            else:
                out_path = self._make_path_absolute(script.relative_path)

            if not out_path:
                log.warning(f"Script {i} has no path — skipping export.")
                continue

            if script.Save(out_path):
                count += 1
        return count

    def ExportFunscript(self, output_path: str, idx: int) -> bool:
        """Export a single funscript by index. Mirrors ``OFS_Project::ExportFunscript``."""
        if not 0 <= idx < len(self.funscripts):
            log.error(f"Script index {idx} out of range.")
            return False
        script = self.funscripts[idx]
        if script.Save(output_path):
            script.relative_path = self._make_path_relative(output_path)
            return True
        return False

    def QuickExport(self) -> bool:
        """Export ALL funscripts to their stored paths.

        Mirrors ``OFS_Project::quickExport`` which calls ExportFunscripts() (no args),
        writing every script to its original path next to the project file.
        """
        count = self.ExportFunscripts(output_dir=None)
        return count > 0

    # ------------------------------------------------------------------
    # Script management
    # ------------------------------------------------------------------

    def AddFunscript(self, path: str) -> bool:
        """
        Add an existing or new funscript to the project. Mirrors ``OFS_Project::AddFunscript``.

        If path does not exist an empty script is created at that path.
        """
        return self._load_funscript(path)

    def RemoveFunscript(self, idx: int) -> None:
        """Remove a funscript from the project by index. Mirrors ``OFS_Project::RemoveFunscript``."""
        if 0 <= idx < len(self.funscripts):
            removed = self.funscripts.pop(idx)
            log.info(f"Removed script: {removed.title}")
            # Keep active index in bounds
            if self.state.active_script_idx >= len(self.funscripts):
                self.state.active_script_idx = max(0, len(self.funscripts) - 1)
            self._notify_changed()
            try:
                from .events import EV, OFS_Events
                EV.dispatch(OFS_Events.FUNSCRIPT_REMOVED,
                            title=removed.title, path=removed._path)
            except Exception:
                pass

    def cycle_active_script(self, direction: int = 1) -> None:
        """Cycle active script forwards (+1) or backwards (-1)."""
        if not self.funscripts:
            return
        n = len(self.funscripts)
        self.state.active_script_idx = (self.state.active_script_idx + direction) % n

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def HasUnsavedEdits(self) -> bool:
        """Return True if any loaded funscript has unsaved changes. Mirrors ``OFS_Project::HasUnsavedEdits``."""
        return any(s.unsaved_edits for s in self.funscripts)

    def reset(self) -> None:
        """Clear all data so the project can be reused for a new load."""
        self.funscripts.clear()
        self.state = ProjectState()
        self.metadata = FunscriptMetadata()
        self.undo_system.Clear()
        self._path = ""
        self._valid = False
        self._errors.clear()

    def update(self, delta: float, idle: bool = False) -> None:
        """Called every frame to advance timers (mirrors OFS_Project::Update)."""
        if not idle:
            self.state.active_timer += delta

    def create_backup(self, backup_dir: Optional[str] = None) -> Optional[str]:
        """
        Write a timestamped backup of the project file.

        Returns the backup file path on success, or None.
        """
        if not self._path or not os.path.isfile(self._path):
            return None
        bdir = backup_dir or str(Path(self._path).parent / "Backup")
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = Path(self._path).stem
        backup_name = f"{stem}_{ts}{PROJECT_EXTENSION}"
        dest = str(Path(bdir) / backup_name)
        try:
            shutil.copy2(self._path, dest)
            log.info(f"Backup written: {dest}")
            return dest
        except Exception as e:
            log.error(f"Backup failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Change notification
    # ------------------------------------------------------------------

    def connect_changed(self, callback: Callable) -> None:
        if callback not in self._changed_callbacks:
            self._changed_callbacks.append(callback)

    def disconnect_changed(self, callback: Callable) -> None:
        try:
            self._changed_callbacks.remove(callback)
        except ValueError:
            pass

    def _notify_changed(self) -> None:
        for cb in list(self._changed_callbacks):
            try:
                cb(self)
            except Exception as e:
                log.warning(f"Project changed callback error: {e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_error(self, msg: str) -> None:
        self._valid = False
        self._errors.append(msg)
        log.error(msg)

    def _load_funscript(self, path: str) -> bool:
        """Load (or create empty) a Funscript and append it to self.funscripts."""
        if os.path.isfile(path):
            script = Funscript.Load(path)
        else:
            script = self._make_empty_script(path)

        script.relative_path = self._make_path_relative(path)
        script.InitUndoSystem()
        self.funscripts.append(script)
        return True

    @staticmethod
    def _make_empty_script(path: str) -> Funscript:
        script = Funscript(path)
        script.title = Path(path).stem if path else "Untitled"
        return script

    def _make_path_relative(self, abs_path: str) -> str:
        if not abs_path or not self._path:
            return abs_path
        try:
            project_dir = Path(self._path).parent
            return str(Path(abs_path).relative_to(project_dir))
        except ValueError:
            return abs_path  # different drive / not relative — keep absolute

    def _make_path_absolute(self, rel_path: str) -> str:
        if not rel_path:
            return ""
        p = Path(rel_path)
        if p.is_absolute():
            return str(p)
        if not self._path:
            return str(p)
        project_dir = Path(self._path).parent
        # Use normpath instead of resolve() to avoid symlink expansion
        # (macOS: /tmp is a symlink to /private/tmp; resolve() would change the path)
        return os.path.normpath(str(project_dir / p))

    def __repr__(self) -> str:
        return (
            f"OFS_Project('{self._path}', "
            f"{len(self.funscripts)} scripts, "
            f"valid={self._valid})"
        )
