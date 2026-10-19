"""
Global hotkey listener for emergency stop and pause/resume.

Listens for keyboard shortcuts system-wide so you can stop Ghost Typer
even when it's actively typing into another app.

Default hotkeys:
  F6          = Toggle pause/resume
  Shift+F6    = Emergency stop (cancel current typing)
  Ctrl+F6     = Toggle ON/OFF
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from pynput import keyboard

logger = logging.getLogger(__name__)

# Virtual key code for 'V' on macOS (used when Cmd is held and key.char is None)
_VK_V = 9


class HotkeyListener:
    """Listens for global hotkeys to control Ghost Typer."""

    def __init__(
        self,
        on_toggle_pause: Optional[Callable[[], None]] = None,
        on_emergency_stop: Optional[Callable[[], None]] = None,
        on_toggle_enabled: Optional[Callable[[], None]] = None,
        on_paste: Optional[Callable[[], None]] = None,
    ):
        self._on_toggle_pause = on_toggle_pause
        self._on_emergency_stop = on_emergency_stop
        self._on_toggle_enabled = on_toggle_enabled
        self._on_paste = on_paste
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._shift_pressed = False
        self._ctrl_pressed = False
        self._cmd_pressed = False
        self._key_listener: Optional[keyboard.Listener] = None
        self._suppressed = False  # True while typing engine is active
        self._pressed_modifiers = {name: set() for name in ("shift", "ctrl", "cmd")}
        self._f6_down = False
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        """Start exactly one listener, including when startup is called twice."""
        with self._lifecycle_lock:
            if self._key_listener is not None and self._key_listener.is_alive():
                return
            self._reset_state()
            listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            listener.daemon = True
            try:
                listener.start()
            except Exception:
                listener.stop()
                raise
            self._key_listener = listener
        logger.info("Hotkey listener started (F6=pause, Shift+F6=stop, Ctrl+F6=on/off)")

    def stop(self) -> None:
        """Stop the owned listener and discard state before a later restart."""
        with self._lifecycle_lock:
            if self._key_listener:
                self._key_listener.stop()
                self._key_listener = None
            self._reset_state()
        logger.info("Hotkey listener stopped")

    def _reset_state(self) -> None:
        for keys in self._pressed_modifiers.values():
            keys.clear()
        self._shift_pressed = self._ctrl_pressed = self._cmd_pressed = False
        self._f6_down = False
        self._suppressed = False

    def suppress(self) -> None:
        """Suppress action triggers while typing engine sends synthetic keystrokes.

        Modifier tracking continues so we don't get stale state.
        """
        self._suppressed = True

    def unsuppress(self) -> None:
        """Re-enable action triggers after typing engine finishes."""
        self._suppressed = False

    @staticmethod
    def _is_modifier(key) -> str | None:
        """Return 'shift', 'ctrl', 'cmd', or None."""
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            return "shift"
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return "ctrl"
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            return "cmd"
        return None

    @staticmethod
    def _is_v_key(key) -> bool:
        """Check if key is 'V' — works even when Cmd is held (key.char is None on macOS)."""
        if isinstance(key, keyboard.KeyCode):
            # key.char works when no modifier is held
            if key.char == "v":
                return True
            # When Cmd is held, key.char is None but vk (virtual key code) is still set
            if hasattr(key, "vk") and key.vk == _VK_V:
                return True
        return False

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        """Handle key press events.

        Modifier tracking ALWAYS runs (even when suppressed) to avoid stale state.
        Action triggers only fire when not suppressed.
        """
        # Always track modifier state, even during suppression
        mod = self._is_modifier(key)
        if mod:
            self._pressed_modifiers[mod].add(key)
            setattr(self, f"_{mod}_pressed", True)
            return

        if key == keyboard.Key.f6:
            # Key auto-repeat must not rapidly toggle pause or ON/OFF.
            if self._f6_down:
                return
            self._f6_down = True
        elif self._suppressed:
            return

        # Cmd+V = paste trigger
        if self._cmd_pressed and self._is_v_key(key):
            if self._on_paste:
                logger.info("HOTKEY: Cmd+V — Paste trigger")
                threading.Thread(target=self._on_paste, daemon=True).start()
        elif key == keyboard.Key.f6:
            if self._shift_pressed:
                logger.info("HOTKEY: Shift+F6 — Emergency Stop")
                if self._on_emergency_stop:
                    threading.Thread(target=self._on_emergency_stop, daemon=True).start()
            elif self._ctrl_pressed:
                logger.info("HOTKEY: Ctrl+F6 — Toggle ON/OFF")
                if self._on_toggle_enabled:
                    threading.Thread(target=self._on_toggle_enabled, daemon=True).start()
            else:
                logger.info("HOTKEY: F6 — Toggle Pause/Resume")
                if self._on_toggle_pause:
                    threading.Thread(target=self._on_toggle_pause, daemon=True).start()

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        """Handle key release events. Always tracks modifiers, even when suppressed."""
        mod = self._is_modifier(key)
        if mod:
            self._pressed_modifiers[mod].discard(key)
            setattr(self, f"_{mod}_pressed", bool(self._pressed_modifiers[mod]))
        if key == keyboard.Key.f6:
            self._f6_down = False
