"""Keystroke simulation layer for macOS using pynput.

Sends real keyboard events so the target application (e.g. Google Docs)
sees them as human typing.
"""

from __future__ import annotations

import logging
import time
from threading import Event, Lock

from pynput.keyboard import Controller, Key, KeyCode

logger = logging.getLogger(__name__)

# Map from friendly names to pynput Key objects
SPECIAL_KEYS: dict[str, Key] = {
    "enter": Key.enter,
    "return": Key.enter,
    "tab": Key.tab,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "escape": Key.esc,
    "esc": Key.esc,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "shift": Key.shift,
    "shift_l": Key.shift_l,
    "shift_r": Key.shift_r,
    "ctrl": Key.ctrl,
    "ctrl_l": Key.ctrl_l,
    "ctrl_r": Key.ctrl_r,
    "alt": Key.alt,
    "alt_l": Key.alt_l,
    "alt_r": Key.alt_r,
    "option": Key.alt,
    "opt": Key.alt,
    "cmd": Key.cmd,
    "command": Key.cmd,
    "cmd_l": Key.cmd_l,
    "cmd_r": Key.cmd_r,
    "caps_lock": Key.caps_lock,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}

MODIFIER_NAMES: set[str] = {
    "shift", "shift_l", "shift_r",
    "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r", "option", "opt",
    "cmd", "command", "cmd_l", "cmd_r",
}


class KeystrokeSimulator:
    """Sends real keystrokes to macOS via pynput."""

    def __init__(self) -> None:
        self._controller = Controller()
        self._active = Event()
        self._active.set()  # active by default
        self._paused = Event()
        self._paused.clear()  # not paused by default
        # Lock to prevent stop() from racing with in-flight CGEvent calls
        self._cg_lock = Lock()

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active.is_set()

    def stop(self) -> None:
        """Signal the simulator to stop all activity.

        Acquires _cg_lock so that any in-flight CGEvent call finishes
        before the active flag is cleared.
        """
        with self._cg_lock:
            self._active.clear()

    def start(self) -> None:
        """Re-activate after a stop."""
        self._active.set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def pause(self) -> None:
        """Pause typing — blocks until resumed."""
        self._paused.set()

    def resume(self) -> None:
        """Resume after pause."""
        self._paused.clear()

    def _check_state(self) -> bool:
        """Wait if paused, return False if stopped."""
        while self._paused.is_set():
            if not self._active.is_set():
                return False
            time.sleep(0.05)
        return self._active.is_set()

    def _safe_cg_call(self, fn, *args) -> bool:
        """Execute a CGEvent-producing call under the lock.

        Returns True if the call was made, False if stopped.
        """
        with self._cg_lock:
            if not self._active.is_set():
                return False
            try:
                fn(*args)
            except Exception:
                logger.debug("CGEvent call failed (likely shutdown)", exc_info=True)
                return False
        return True

    # ------------------------------------------------------------------
    # Primitive actions
    # ------------------------------------------------------------------

    def type_char(self, char: str) -> None:
        """Type a single character. Handles uppercase/shift automatically."""
        if not self._check_state():
            return
        self._safe_cg_call(self._controller.type, char)

    def press_key(self, key_name: str) -> None:
        """Press and release a special key by name (e.g. 'enter', 'tab')."""
        if not self._check_state():
            return
        key = self._resolve_key(key_name)
        self._safe_cg_call(self._do_press_release, key)

    def _do_press_release(self, key) -> None:
        """Press and release a key (called under _cg_lock)."""
        try:
            self._controller.press(key)
        finally:
            self._controller.release(key)

    def type_backspace(self, count: int = 1) -> None:
        """Press backspace `count` times with a small inter-press delay."""
        for _ in range(count):
            if not self._check_state():
                return
            self._safe_cg_call(self._do_press_release, Key.backspace)
            time.sleep(0.04)

    def hotkey(self, *keys: str) -> None:
        """Press a key combination. Last key is the main key, rest are modifiers.

        Example: hotkey("cmd", "b") sends Cmd+B for bold.
                 hotkey("cmd", "opt", "1") sends Cmd+Opt+1 for heading 1.
        """
        if not keys or not self._check_state():
            return

        resolved = [self._resolve_key(k) for k in keys]
        modifiers = resolved[:-1]
        main_key = resolved[-1]

        # Execute entire hotkey sequence under the lock to prevent
        # stop() from leaving modifiers stuck
        def _do_hotkey():
            pressed = []
            try:
                for mod in modifiers:
                    # A backend may raise after posting the key-down event.
                    pressed.append(mod)
                    self._controller.press(mod)
                time.sleep(0.02)
                pressed.append(main_key)
                self._controller.press(main_key)
            finally:
                release_error = None
                for key in reversed(pressed):
                    try:
                        self._controller.release(key)
                    except Exception as exc:
                        # One failed release must not skip the other modifiers.
                        release_error = exc
                if release_error is not None:
                    raise release_error

        self._safe_cg_call(_do_hotkey)
        time.sleep(0.05)

    def type_string_raw(self, text: str, delay: float = 0.02) -> None:
        """Type a string with a fixed delay between characters.

        This is a simpler utility — for realistic typing, use TypingEngine
        to get per-character delays and call type_char in a loop.
        """
        for char in text:
            if not self._check_state():
                return
            if not self._safe_cg_call(self._controller.type, char):
                return
            time.sleep(delay)

    def wait(self, seconds: float) -> None:
        """Wait for active time, preserving the remaining delay across pauses."""
        remaining = seconds
        while remaining > 0:
            if not self._check_state():
                return
            # _check_state may wait for a long manual pause. Do not count that
            # time toward a planned thinking pause or keystroke delay.
            started = time.monotonic()
            time.sleep(min(0.05, remaining))
            remaining -= time.monotonic() - started

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_key(self, name: str) -> Key | KeyCode:
        """Resolve a key name string to a pynput Key or KeyCode."""
        lower = name.lower().strip()

        # Check special keys map
        if lower in SPECIAL_KEYS:
            return SPECIAL_KEYS[lower]

        # Single character — return a KeyCode
        if len(name) == 1:
            return KeyCode.from_char(name)

        # Try as a character (e.g. "1", "a")
        if len(lower) == 1:
            return KeyCode.from_char(lower)

        raise ValueError(f"Unknown key name: {name!r}")
