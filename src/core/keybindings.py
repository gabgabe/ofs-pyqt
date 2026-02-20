"""
OFS_KeybindingSystem — Python port of OFS_KeybindingSystem.h

Uses ImGui's IsKeyPressed / IsKeyChordPressed directly.
No Qt. Registered actions are called from the main loop via ProcessKeybindings().

Architecture mirrors OFS exactly:
  - RegisterGroup(id, label)
  - RegisterAction({id, fn, repeat}, label, group, [{mods, key, repeat}])
  - ProcessKeybindings() — call once per frame from update()
  - ShowModal() / RenderKeybindingWindow() — ImGui UI

Key format uses imgui.Key_* and imgui.Mod_* constants.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from imgui_bundle import imgui, ImVec2

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key chord: (mods, key, repeat)
# ---------------------------------------------------------------------------

@dataclass
class KeyChord:
    mods: int       = 0        # imgui.Key.mod_ctrl | imgui.Key.mod_shift, etc.
    key:  int       = 0        # imgui.Key.*
    repeat: bool    = False    # held-down repeat


# ---------------------------------------------------------------------------
# Binding definition
# ---------------------------------------------------------------------------

@dataclass
class KeyBinding:
    id:          str                   # unique snake_case id (OFS-exact)
    description: str                   # human-readable label
    fn:          Callable              # callback
    group:       str                   # group id
    chords:      List[KeyChord]        # default key chords
    repeat:      bool       = False    # if True, fires while held
    user_chords: List[KeyChord] = field(default_factory=list)  # user overrides


@dataclass
class BindingGroup:
    id:    str
    label: str
    bindings: List[str] = field(default_factory=list)  # list of binding ids


# ---------------------------------------------------------------------------
# OFS_KeybindingSystem
# ---------------------------------------------------------------------------

class OFS_KeybindingSystem:
    """
    Python port of OFS_KeybindingSystem.
    RegisterGroup / RegisterAction / ProcessKeybindings / ShowModal.
    """

    def __init__(self, settings_path: Optional[Path] = None) -> None:
        self._groups:   Dict[str, BindingGroup] = {}
        self._bindings: Dict[str, KeyBinding]   = {}
        self._group_order: List[str]            = []
        self._show_window: bool                 = False
        self._settings_path = settings_path
        self._filter_buf: str = ""

        if settings_path and settings_path.exists():
            self._load(settings_path)

    # ------------------------------------------------------------------

    def RegisterGroup(self, id_: str, label: str) -> None:
        if id_ not in self._groups:
            self._groups[id_] = BindingGroup(id=id_, label=label)
            self._group_order.append(id_)

    def RegisterAction(
        self,
        id_: str,
        fn: Callable,
        label: str,
        group: str,
        chords: Optional[List[Tuple]] = None,  # list of (mods, key[, repeat])
        repeat: bool = False,
    ) -> None:
        """
        Register an action.

        chords format: list of (mods, key) or (mods, key, repeat)
        """
        parsed: List[KeyChord] = []
        for chord in (chords or []):
            if len(chord) == 2:
                parsed.append(KeyChord(mods=chord[0], key=chord[1], repeat=repeat))
            else:
                parsed.append(KeyChord(mods=chord[0], key=chord[1], repeat=chord[2]))

        binding = KeyBinding(
            id=id_, description=label, fn=fn,
            group=group, chords=parsed, repeat=repeat,
        )
        self._bindings[id_] = binding
        if group in self._groups:
            self._groups[group].bindings.append(id_)

    # ------------------------------------------------------------------

    def ProcessKeybindings(self) -> None:
        """
        Call once per frame from the main update loop.
        Fires callbacks for pressed key chords.
        ImGui must have processed input before this is called.
        """
        # Don't fire bindings when a text input widget has focus
        if imgui.get_io().want_capture_keyboard:
            # Allow some bindings even when text is focused? OFS doesn't.
            return

        for binding in self._bindings.values():
            active_chords = binding.user_chords if binding.user_chords else binding.chords
            for chord in active_chords:
                if chord.key == 0:
                    continue
                fired = False
                if chord.mods != 0:
                    fired = imgui.is_key_chord_pressed(chord.mods | chord.key)
                else:
                    fired = imgui.is_key_pressed(
                        chord.key,
                        repeat=chord.repeat
                    )
                if fired:
                    try:
                        binding.fn()
                    except Exception as e:
                        log.error(f"Binding '{binding.id}' error: {e}")
                    break  # only fire once per binding per frame

    # ------------------------------------------------------------------
    # ImGui window

    def ShowModal(self) -> None:
        self._show_window = True

    def RenderKeybindingWindow(self) -> None:
        if not self._show_window:
            return

        imgui.set_next_window_size(ImVec2(700, 500), imgui.Cond_.first_use_ever)
        opened, self._show_window = imgui.begin(
            "Keybindings###keybindings_win", self._show_window
        )
        if not opened:
            imgui.end()
            return

        imgui.text("Filter:")
        imgui.same_line()
        imgui.set_next_item_width(-1)
        changed, self._filter_buf = imgui.input_text("##filter", self._filter_buf)

        imgui.separator()

        if imgui.begin_table("##kbtable", 3,
                             imgui.TableFlags_.borders_inner_h |
                             imgui.TableFlags_.row_bg |
                             imgui.TableFlags_.scroll_y,
                             (0, -30)):
            imgui.table_setup_column("Action",  imgui.TableColumnFlags_.width_stretch)
            imgui.table_setup_column("Key",     imgui.TableColumnFlags_.width_fixed, 150)
            imgui.table_setup_column("Group",   imgui.TableColumnFlags_.width_fixed, 100)
            imgui.table_headers_row()

            flt = self._filter_buf.lower()
            for bid, binding in self._bindings.items():
                if flt and flt not in binding.description.lower() and flt not in bid.lower():
                    continue
                imgui.table_next_row()
                imgui.table_set_column_index(0)
                imgui.text_unformatted(binding.description)
                imgui.table_set_column_index(1)
                chords = binding.user_chords if binding.user_chords else binding.chords
                key_str = self._chord_str(chords[0]) if chords else "(none)"
                imgui.text_unformatted(key_str)
                imgui.table_set_column_index(2)
                grp = self._groups.get(binding.group)
                imgui.text_unformatted(grp.label if grp else binding.group)

            imgui.end_table()

        if imgui.button("Close", ImVec2(-1, 0)):
            self._show_window = False

        imgui.end()

    # ------------------------------------------------------------------
    # Persistence

    def _chord_str(self, chord: KeyChord) -> str:
        parts = []
        if chord.mods & imgui.Key.mod_ctrl:  parts.append("Ctrl")
        if chord.mods & imgui.Key.mod_shift: parts.append("Shift")
        if chord.mods & imgui.Key.mod_alt:   parts.append("Alt")
        key_name = imgui.get_key_name(chord.key)
        parts.append(key_name)
        return "+".join(parts)

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text())
            for bid, chords in data.items():
                if bid in self._bindings:
                    self._bindings[bid].user_chords = [
                        KeyChord(mods=c["mods"], key=c["key"], repeat=c.get("repeat", False))
                        for c in chords
                    ]
        except Exception as e:
            log.warning(f"Failed to load keybindings: {e}")

    def Save(self, path: Path) -> None:
        data: dict = {}
        for bid, binding in self._bindings.items():
            if binding.user_chords:
                data[bid] = [
                    {"mods": c.mods, "key": c.key, "repeat": c.repeat}
                    for c in binding.user_chords
                ]
        path.write_text(json.dumps(data, indent=2))
