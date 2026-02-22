"""
ChapterManagerWindow — Python port of OFS_ChapterManager.h / .cpp

Manages named chapters / bookmarks attached to the project.
Chapters are persisted inside the .ofsp project file under "chapters".

A Chapter has:  { name, start (s), end (s), color [r,g,b,a] }
A Bookmark has: { name, time (s) }
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from typing import List, Optional, Tuple

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.project      import OFS_Project

log = logging.getLogger(__name__)

# Default chapter colour (OFS uses a light blue)
_DEFAULT_COLOR = (0.30, 0.60, 0.90, 1.0)


class Chapter:
    """A named time-range chapter. Mirrors the chapter struct in ``OFS_ChapterManager``."""

    def __init__(
        self,
        name:  str,
        start: float,
        end:   float,
        color: Tuple[float, float, float, float] = _DEFAULT_COLOR,
    ) -> None:
        self.name  = name
        self.start = start
        self.end   = end
        self.color = color   # (r,g,b,a) 0-1

    def to_dict(self):
        return {
            "name":  self.name,
            "start": self.start,
            "end":   self.end,
            "color": list(self.color),
        }

    @classmethod
    def from_dict(cls, d: dict):
        color = tuple(d.get("color", list(_DEFAULT_COLOR)))
        return cls(d.get("name", ""), d.get("start", 0.0), d.get("end", 0.0), color)


class Bookmark:
    """A named time bookmark. Mirrors the bookmark struct in ``OFS_ChapterManager``."""

    def __init__(self, name: str, time: float) -> None:
        self.name = name
        self.time = time

    def to_dict(self):
        return {"name": self.name, "time": self.time}

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d.get("name", ""), d.get("time", 0.0))


class ChapterManagerWindow:
    """OFS Chapter Manager panel. Mirrors ``OFS_ChapterManager`` (OFS_ChapterManager.h / .cpp)."""

    WindowId = "Chapters###ChapterManager"

    def __init__(self) -> None:
        self._chapters:  List[Chapter]  = []
        self._bookmarks: List[Bookmark] = []
        self._new_name:  str            = ""
        # inline name-edit state
        self._edit_ch_idx:  int = -1
        self._edit_ch_buf:  str = ""
        self._edit_bm_idx:  int = -1
        self._edit_bm_buf:  str = ""
        # color-picker state
        self._color_ch_idx: int        = -1
        self._color_buf:    List[float] = list(_DEFAULT_COLOR)
        # last project we synced to/from (by id)
        self._synced_project_id: int = -1
        # export clip state
        self._export_status: str  = ""   # last status message
        self._export_busy:   bool = False

    # ──────────────────────────────────────────────────────────────────────
    # API called by app keybindings
    # ──────────────────────────────────────────────────────────────────────

    def AddChapter(self, start: float, duration: float) -> None:
        """Create a new chapter at the given time. Mirrors ``OFS_ChapterManager::AddChapter``."""
        name = self._new_name.strip() or f"Chapter {len(self._chapters) + 1}"
        end  = min(start + 30.0, duration)
        self._chapters.append(Chapter(name, start, end))
        log.info(f"Added chapter '{name}' @ {start:.2f}s")

    def AddBookmark(self, time: float) -> None:
        """Create a new bookmark at the given time. Mirrors ``OFS_ChapterManager::AddBookmark``."""
        name = f"Bookmark {len(self._bookmarks) + 1}"
        self._bookmarks.append(Bookmark(name, time))
        log.info(f"Added bookmark '{name}' @ {time:.2f}s")

    def _export_chapter(
        self,
        ch: "Chapter",
        video_path: str,
    ) -> None:
        """Export chapter as a clip using ffmpeg (-c copy, lossless)."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self._export_status = "\u26a0 ffmpeg not found in PATH"
            self._export_busy = False
            return
        out_dir  = os.path.dirname(video_path)
        base     = os.path.splitext(os.path.basename(video_path))[0]
        safe     = ch.name.replace(" ", "_")[:40]
        for ch_bad in r'\/:*?"<>|':
            safe = safe.replace(ch_bad, "_")
        out_path = os.path.join(out_dir, f"{base}__{safe}.mp4")
        cmd = [
            ffmpeg, "-y",
            "-loglevel", "quiet",
            "-ss", str(ch.start),
            "-to", str(ch.end),
            "-i", video_path,
            "-c", "copy",
            out_path,
        ]
        log.info("Exporting clip: %s", out_path)
        try:
            result = subprocess.run(cmd, timeout=3600, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                self._export_status = f"\u2705 {os.path.basename(out_path)}"
            else:
                self._export_status = f"\u274c ffmpeg exited {result.returncode}"
        except subprocess.TimeoutExpired:
            self._export_status = "\u274c Timed out"
        except Exception as exc:
            self._export_status = f"\u274c {exc}"
        finally:
            self._export_busy = False

    # ──────────────────────────────────────────────────────────────────────
    # Persistence helpers (called by app on load/save)
    # ──────────────────────────────────────────────────────────────────────

    def LoadFromProject(self, project: OFS_Project) -> None:
        """Restore chapters/bookmarks from project state dict. Mirrors ``OFS_ChapterManager::LoadFromProject``."""
        pid = id(project)
        if pid == self._synced_project_id:
            return
        self._synced_project_id = pid
        pstate = getattr(project, "_extra_state", {})
        self._chapters  = [Chapter.from_dict(d) for d in pstate.get("chapters", [])]
        self._bookmarks = [Bookmark.from_dict(d) for d in pstate.get("bookmarks", [])]

    def SaveToProject(self, project: OFS_Project) -> None:
        """Persist chapters/bookmarks into project extra state. Mirrors ``OFS_ChapterManager::SaveToProject``."""
        if not hasattr(project, "_extra_state"):
            project._extra_state = {}
        project._extra_state["chapters"]  = [c.to_dict() for c in self._chapters]
        project._extra_state["bookmarks"] = [b.to_dict() for b in self._bookmarks]

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player:  OFS_Videoplayer,
        project: OFS_Project,
        visible: bool,
    ) -> bool:
        """Render the chapter manager window. Mirrors ``OFS_ChapterManager::ShowChapterManagerWindow``."""
        if not visible:
            return False

        # Sync from project whenever a new project is active
        if project.is_valid:
            self.LoadFromProject(project)

        is_open = True
        imgui.set_next_window_size(ImVec2(480, 360), imgui.Cond_.first_use_ever)
        opened, is_open = imgui.begin("Chapters###ChapterManager", is_open)
        if opened:
            self._draw(player, project)
        imgui.end()

        # Persist every frame (cheap dict update)
        if project.is_valid:
            self.SaveToProject(project)

        return is_open

    # ──────────────────────────────────────────────────────────────────────

    def _draw(self, player: OFS_Videoplayer, project: OFS_Project) -> None:
        cur      = player.CurrentTime() if player.VideoLoaded() else 0.0
        duration = player.Duration()    if player.VideoLoaded() else 0.0

        # ── Add controls ──────────────────────────────────────────────
        if imgui.button("+ Chapter"):
            self.AddChapter(cur, duration)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Add chapter at current playback position")
        imgui.same_line(spacing=4)
        imgui.set_next_item_width(140)
        _, self._new_name = imgui.input_text("##cname", self._new_name)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Name for next chapter (leave blank for auto)")
        imgui.same_line(spacing=8)
        if imgui.button("+ Bookmark"):
            self.AddBookmark(cur)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Add bookmark at current playback position")

        imgui.separator()
        imgui.spacing()

        # ── Chapters table ─────────────────────────────────────────────
        table_flags = (
            imgui.TableFlags_.borders_inner_v
            | imgui.TableFlags_.row_bg
            | imgui.TableFlags_.resizable
            | imgui.TableFlags_.scroll_y
        )
        table_h = min(200, max(60, len(self._chapters) * 24 + 28))

        if imgui.begin_table("##chtable", 4, table_flags, ImVec2(-1, table_h)):
            imgui.table_setup_column("Name",      imgui.TableColumnFlags_.width_stretch)
            imgui.table_setup_column("Begin",     imgui.TableColumnFlags_.width_fixed, 70)
            imgui.table_setup_column("End",       imgui.TableColumnFlags_.width_fixed, 70)
            imgui.table_setup_column("",          imgui.TableColumnFlags_.width_fixed, 90)
            imgui.table_headers_row()

            del_idx = -1
            for i, ch in enumerate(self._chapters):
                imgui.table_next_row()
                imgui.push_id(i)

                # Col 0: name + color swatch
                imgui.table_set_column_index(0)
                # color swatch button
                swatch_col = ImVec4(ch.color[0], ch.color[1], ch.color[2], ch.color[3])
                imgui.push_style_color(imgui.Col_.button,         swatch_col)
                imgui.push_style_color(imgui.Col_.button_hovered, swatch_col)
                imgui.push_style_color(imgui.Col_.button_active,  swatch_col)
                if imgui.button("  ##col", ImVec2(14, 14)):
                    self._color_ch_idx = i
                    self._color_buf    = list(ch.color)
                imgui.pop_style_color(3)
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Click to change chapter colour")
                imgui.same_line(spacing=4)
                # inline name editing
                if self._edit_ch_idx == i:
                    imgui.set_next_item_width(-1)
                    enter, self._edit_ch_buf = imgui.input_text(
                        "##chname", self._edit_ch_buf,
                        imgui.InputTextFlags_.enter_returns_true,
                    )
                    if enter or (not imgui.is_item_active() and not imgui.is_item_focused()):
                        ch.name = self._edit_ch_buf
                        self._edit_ch_idx = -1
                else:
                    imgui.text(ch.name)
                    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                        self._edit_ch_idx = i
                        self._edit_ch_buf = ch.name

                # Col 1: begin time
                imgui.table_set_column_index(1)
                imgui.text(self._ts(ch.start))
                if imgui.is_item_hovered():
                    imgui.set_tooltip(f"{ch.start:.3f} s")

                # Col 2: end time
                imgui.table_set_column_index(2)
                imgui.text(self._ts(ch.end))
                if imgui.is_item_hovered():
                    imgui.set_tooltip(f"{ch.end:.3f} s")

                # Col 3: actions
                imgui.table_set_column_index(3)
                if imgui.small_button("Seek##ch"):
                    player.SetPositionExact(ch.start)
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Seek to chapter start")
                imgui.same_line(spacing=2)
                if imgui.small_button("▶##chsetbegin"):
                    ch.start = player.CurrentTime()
                    if ch.start > ch.end:
                        ch.end = ch.start
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Set Begin to current time")
                imgui.same_line(spacing=2)
                if imgui.small_button("◀##chsetend"):
                    ch.end = player.CurrentTime()
                    if ch.end < ch.start:
                        ch.start = ch.end
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Set End to current time")
                imgui.same_line(spacing=2)
                if imgui.small_button("X##ch"):
                    del_idx = i

                # Right-click context menu on the entire row for export
                if imgui.begin_popup_context_item(f"##ctx{i}"):
                    if imgui.menu_item("Export Clip")[0]:
                        vp = player.VideoPath() if player.VideoLoaded() else ""
                        if vp and not self._export_busy:
                            self._export_busy = True
                            self._export_status = "Exporting\u2026"
                            threading.Thread(
                                target=self._export_chapter,
                                args=(ch, vp),
                                daemon=True,
                            ).start()
                        elif not vp:
                            self._export_status = "\u26a0 No video loaded"
                    imgui.end_popup()

                imgui.pop_id()

            imgui.end_table()
            if del_idx >= 0:
                self._chapters.pop(del_idx)
                if self._color_ch_idx == del_idx:
                    self._color_ch_idx = -1

        # Export status line
        if self._export_status:
            if "\u2705" in self._export_status:
                imgui.push_style_color(imgui.Col_.text, ImVec4(0.3, 1.0, 0.3, 1.0))
            elif "\u274c" in self._export_status or "\u26a0" in self._export_status:
                imgui.push_style_color(imgui.Col_.text, ImVec4(1.0, 0.4, 0.3, 1.0))
            else:
                imgui.push_style_color(imgui.Col_.text, ImVec4(1.0, 0.85, 0.2, 1.0))
            imgui.text_small(self._export_status)
            imgui.pop_style_color()

        # ── Inline color picker popup ──────────────────────────────────
        if self._color_ch_idx >= 0:
            imgui.open_popup("##chcolor")
        if imgui.begin_popup("##chcolor"):
            changed, new_col = imgui.color_picker4(
                "##cp", self._color_buf,
                imgui.ColorEditFlags_.alpha_bar,
            )
            if changed:
                self._color_buf = list(new_col)
                if 0 <= self._color_ch_idx < len(self._chapters):
                    self._chapters[self._color_ch_idx].color = tuple(new_col)
            if imgui.button("OK##colok", ImVec2(60, 0)):
                self._color_ch_idx = -1
                imgui.close_current_popup()
            imgui.end_popup()

        imgui.spacing()
        imgui.separator()

        # ── Bookmarks table ────────────────────────────────────────────
        imgui.text("Bookmarks")
        bm_table_h = min(120, max(30, len(self._bookmarks) * 22 + 28))
        if imgui.begin_table("##bmtable", 3, table_flags, ImVec2(-1, bm_table_h)):
            imgui.table_setup_column("Name",  imgui.TableColumnFlags_.width_stretch)
            imgui.table_setup_column("Time",  imgui.TableColumnFlags_.width_fixed, 70)
            imgui.table_setup_column("",      imgui.TableColumnFlags_.width_fixed, 70)
            imgui.table_headers_row()

            del_bm = -1
            for i, bm in enumerate(self._bookmarks):
                imgui.table_next_row()
                imgui.push_id(i + 2000)

                imgui.table_set_column_index(0)
                if self._edit_bm_idx == i:
                    imgui.set_next_item_width(-1)
                    enter, self._edit_bm_buf = imgui.input_text(
                        "##bmname", self._edit_bm_buf,
                        imgui.InputTextFlags_.enter_returns_true,
                    )
                    if enter or (not imgui.is_item_active() and not imgui.is_item_focused()):
                        bm.name = self._edit_bm_buf
                        self._edit_bm_idx = -1
                else:
                    imgui.text(bm.name)
                    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
                        self._edit_bm_idx = i
                        self._edit_bm_buf = bm.name

                imgui.table_set_column_index(1)
                imgui.text(self._ts(bm.time))

                imgui.table_set_column_index(2)
                if imgui.small_button("Seek##bm"):
                    player.SetPositionExact(bm.time)
                imgui.same_line(spacing=4)
                if imgui.small_button("X##bm"):
                    del_bm = i

                imgui.pop_id()

            imgui.end_table()
            if del_bm >= 0:
                self._bookmarks.pop(del_bm)

    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _ts(t: float) -> str:
        m = int(t) // 60
        s = t % 60
        return f"{m:02d}:{s:05.2f}"
