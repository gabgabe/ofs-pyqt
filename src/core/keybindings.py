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
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from imgui_bundle import imgui, ImVec2

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mouse wheel pseudo-keys (not real ImGui keys — negative sentinels)
# ---------------------------------------------------------------------------

MOUSE_WHEEL_UP   = -1   # pseudo-key for scroll-up bindings
MOUSE_WHEEL_DOWN = -2   # pseudo-key for scroll-down bindings

# ---------------------------------------------------------------------------
# Modifier decomposition helper
# ---------------------------------------------------------------------------

def _split_mods(mods: int) -> List[int]:
    """Return the individual imgui.Key.mod_* values present in a mods bitmask."""
    result = []
    for m in (imgui.Key.mod_ctrl, imgui.Key.mod_shift,
              imgui.Key.mod_alt, imgui.Key.mod_super):
        if mods & m:
            result.append(m)
    return result

# ---------------------------------------------------------------------------
# Key chord: (mods, key, repeat)
# ---------------------------------------------------------------------------

@dataclass
class KeyChord:
    """A key combination (modifier mask + key + optional repeat). Mirrors ``OFS::KeyChord``."""

    mods: int       = 0        # imgui.Key.mod_ctrl | imgui.Key.mod_shift, etc.
    key:  int       = 0        # imgui.Key.*
    repeat: bool    = False    # held-down repeat


# ---------------------------------------------------------------------------
# Binding definition
# ---------------------------------------------------------------------------

@dataclass
class KeyBinding:
    """A registered action with its key chords and callback. Mirrors ``OFS::KeyBinding``."""

    id:          str                   # unique snake_case id (OFS-exact)
    description: str                   # human-readable label
    fn:          Callable              # callback
    group:       str                   # group id
    chords:      List[KeyChord]        # default key chords
    repeat:      bool       = False    # if True, fires while held
    user_chords: List[KeyChord] = field(default_factory=list)  # user overrides


@dataclass
class BindingGroup:
    """Named group of related key bindings. Mirrors ``OFS::BindingGroup``."""

    id:    str
    label: str
    bindings: List[str] = field(default_factory=list)  # list of binding ids


# ---------------------------------------------------------------------------
# OFS_KeybindingSystem
# ---------------------------------------------------------------------------

class OFS_KeybindingSystem:
    """
    Keybinding manager. Mirrors ``OFS_KeybindingSystem`` (OFS_KeybindingSystem.h).

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
        """Register a named binding group. Mirrors ``OFS_KeybindingSystem::RegisterGroup``."""
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
        Register an action with default key chords. Mirrors ``OFS_KeybindingSystem::RegisterAction``.

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
        Poll ImGui input and fire matching binding callbacks. Mirrors ``OFS_KeybindingSystem::ProcessKeybindings``.

        Call once per frame. Sets ``self.any_key_active = True`` if any binding fired.
        """
        self.any_key_active = False
        # Don't fire bindings when a text input widget actually has focus.
        # ``want_capture_keyboard`` alone is not reliable — ImGui can leave
        # it True even after the user clicks away from an input widget
        # (the nav system keeps the last-focused window's state).  We
        # combine it with ``is_any_item_active()`` which is True only when
        # an actual input widget (InputText, InputInt, etc.) holds focus.
        if imgui.get_io().want_capture_keyboard and imgui.is_any_item_active():
            return

        for binding in self._bindings.values():
            active_chords = binding.user_chords if binding.user_chords else binding.chords
            for chord in active_chords:
                if chord.key == 0:
                    continue
                fired = False
                if chord.mods != 0:
                    if chord.repeat:
                        # is_key_chord_pressed has no repeat support — fires only
                        # on initial press.  For held-key repeat we check mods are
                        # all down and use is_key_pressed(repeat=True) for the key.
                        mods_down = all(
                            imgui.is_key_down(m)
                            for m in _split_mods(chord.mods)
                        )
                        if mods_down:
                            fired = imgui.is_key_pressed(chord.key, repeat=True)
                    else:
                        fired = imgui.is_key_chord_pressed(chord.mods | chord.key)
                else:
                    # mods=0 means "no modifiers" — don't fire when Ctrl/Shift/Alt/Cmd
                    # is held (prevents prev_frame firing alongside fast_backstep,
                    # move_actions_left, prev_frame_x3, etc. that use the same base key).
                    if not (imgui.is_key_down(imgui.Key.mod_ctrl)
                            or imgui.is_key_down(imgui.Key.mod_shift)
                            or imgui.is_key_down(imgui.Key.mod_alt)
                            or imgui.is_key_down(imgui.Key.mod_super)):
                        fired = imgui.is_key_pressed(
                            chord.key,
                            repeat=chord.repeat
                        )
                if fired:
                    self.any_key_active = True
                    try:
                        binding.fn()
                    except Exception as e:
                        log.error(f"Binding '{binding.id}' error: {e}")
                    break  # only fire once per binding per frame

        # Mouse wheel pseudo-key bindings — fire when scroll is not consumed
        # by any imgui widget (want_capture_mouse is False).
        scroll = imgui.get_io().mouse_wheel
        if scroll != 0 and not imgui.get_io().want_capture_mouse:
            pseudo = MOUSE_WHEEL_UP if scroll > 0 else MOUSE_WHEEL_DOWN
            for binding in self._bindings.values():
                active_chords = binding.user_chords if binding.user_chords else binding.chords
                for chord in active_chords:
                    if chord.key == pseudo:
                        self.any_key_active = True
                        try:
                            binding.fn()
                        except Exception as e:
                            log.error(f"Binding '{binding.id}' scroll error: {e}")
                        break

    # ------------------------------------------------------------------
    # ImGui window

    def ShowModal(self) -> None:
        """Open the keybinding editor window. Mirrors ``OFS_KeybindingSystem::ShowModal``."""
        self._show_window = True

    def RenderKeybindingWindow(self) -> None:
        """Render the keybinding editor ImGui window. Mirrors ``OFS_KeybindingSystem::RenderKeybindingWindow``."""
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
        # Handle mouse wheel pseudo-keys
        if chord.key == MOUSE_WHEEL_UP:
            return "Scroll Up"
        if chord.key == MOUSE_WHEEL_DOWN:
            return "Scroll Down"
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
        """Persist user key overrides to a JSON file. Mirrors ``OFS_KeybindingSystem::Save``."""
        data: dict = {}
        for bid, binding in self._bindings.items():
            if binding.user_chords:
                data[bid] = [
                    {"mods": c.mods, "key": c.key, "repeat": c.repeat}
                    for c in binding.user_chords
                ]
        path.write_text(json.dumps(data, indent=2))
