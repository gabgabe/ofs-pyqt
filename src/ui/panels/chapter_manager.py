"""
ChapterManagerWindow — Python port of OFS_ChapterManager.h / .cpp

Manages named chapters / bookmarks attached to the project.
Stored in project state dict under key "chapters".

A chapter has:  { "name": str, "start": float (s), "end": float (s) }
A bookmark has: { "name": str, "time": float (s) }
"""

from __future__ import annotations

import logging
from typing import List, Optional

from imgui_bundle import imgui, ImVec2, ImVec4

from src.core.video_player import OFS_Videoplayer
from src.core.project      import OFS_Project

log = logging.getLogger(__name__)


class Chapter:
    def __init__(self, name: str, start: float, end: float) -> None:
        self.name  = name
        self.start = start
        self.end   = end

    def to_dict(self):
        return {"name": self.name, "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d.get("name", ""), d.get("start", 0.0), d.get("end", 0.0))


class Bookmark:
    def __init__(self, name: str, time: float) -> None:
        self.name = name
        self.time = time

    def to_dict(self):
        return {"name": self.name, "time": self.time}

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d.get("name", ""), d.get("time", 0.0))


class ChapterManagerWindow:
    """OFS Chapter Manager panel."""

    WindowId = "Chapters###ChapterManager"

    def __init__(self) -> None:
        self._chapters:  List[Chapter]  = []
        self._bookmarks: List[Bookmark] = []
        self._new_name:  str            = ""
        self._edit_idx:  int            = -1
        self._edit_buf:  str            = ""

    # ──────────────────────────────────────────────────────────────────────
    # API called by app keybindings
    # ──────────────────────────────────────────────────────────────────────

    def add_chapter(self, start: float, duration: float) -> None:
        name = f"Chapter {len(self._chapters) + 1}"
        end  = min(start + 30.0, duration)
        self._chapters.append(Chapter(name, start, end))
        log.info(f"Added chapter '{name}' @ {start:.2f}s")

    def add_bookmark(self, time: float) -> None:
        name = f"Bookmark {len(self._bookmarks) + 1}"
        self._bookmarks.append(Bookmark(name, time))
        log.info(f"Added bookmark '{name}' @ {time:.2f}s")

    # ──────────────────────────────────────────────────────────────────────

    def Show(
        self,
        player:  OFS_Videoplayer,
        project: OFS_Project,
        visible: bool,
    ) -> bool:
        """Returns updated visible flag."""
        if not visible:
            return False
        is_open = True
        imgui.set_next_window_size(ImVec2(380, 300), imgui.Cond_.first_use_ever)
        opened, is_open = imgui.begin("Chapters###ChapterManager", is_open)
        if opened:
            self._draw(player, project)
        imgui.end()
        return is_open

    def _draw(self, player: OFS_Videoplayer, project: OFS_Project) -> None:
        cur = player.CurrentTime() if player.VideoLoaded() else 0.0

        # ── Chapters ──────────────────────────────────────────────────
        if imgui.collapsing_header("Chapters", imgui.TreeNodeFlags_.default_open):
            if imgui.button("+ Chapter"):
                self.add_chapter(cur, player.Duration())
            imgui.same_line()
            imgui.set_next_item_width(140)
            _, self._new_name = imgui.input_text("##cname", self._new_name)

            for i, ch in enumerate(self._chapters):
                imgui.push_id(i)
                imgui.text(f"{ch.name:<20} {ch.start:.2f}s → {ch.end:.2f}s")
                imgui.same_line()
                if imgui.small_button("Seek"):
                    player.SetPositionExact(ch.start)
                imgui.same_line()
                if imgui.small_button("X"):
                    self._chapters.pop(i)
                    imgui.pop_id()
                    break
                imgui.pop_id()

        imgui.spacing()

        # ── Bookmarks ─────────────────────────────────────────────────
        if imgui.collapsing_header("Bookmarks", imgui.TreeNodeFlags_.default_open):
            if imgui.button("+ Bookmark"):
                self.add_bookmark(cur)

            for i, bm in enumerate(self._bookmarks):
                imgui.push_id(i + 1000)
                imgui.text(f"{bm.name:<24} {bm.time:.2f}s")
                imgui.same_line()
                if imgui.small_button("Seek"):
                    player.SetPositionExact(bm.time)
                imgui.same_line()
                if imgui.small_button("X"):
                    self._bookmarks.pop(i)
                    imgui.pop_id()
                    break
                imgui.pop_id()
