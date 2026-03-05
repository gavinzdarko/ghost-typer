"""
macOS menu bar application using rumps.
Provides ON/OFF toggle, status display, pause/resume, cancel, settings submenu, and quit.
Global hotkeys: F6=pause, Shift+F6=stop, Ctrl+F6=on/off.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Optional

import rumps

from .hotkey_listener import HotkeyListener
from .orchestrator import Orchestrator, OrchestratorState
from .progress_overlay import ProgressOverlay
from .settings_ui import load_settings_dict, save_settings_dict

logger = logging.getLogger(__name__)

# Icon paths (32x32 black-on-transparent PNGs for macOS menu bar)
_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons")
ICON_OFF = os.path.join(_ICON_DIR, "ghost_off.png")
ICON_IDLE = os.path.join(_ICON_DIR, "ghost_idle.png")
ICON_TYPING = os.path.join(_ICON_DIR, "ghost_typing.png")
ICON_TYPING2 = os.path.join(_ICON_DIR, "ghost_typing2.png")
ICON_TYPING3 = os.path.join(_ICON_DIR, "ghost_typing3.png")
ICON_PAUSED = os.path.join(_ICON_DIR, "ghost_paused.png")
ICON_PLANNING = os.path.join(_ICON_DIR, "ghost_planning.png")
ICON_VERIFYING = os.path.join(_ICON_DIR, "ghost_verifying.png")

# Settings config: (key, display_name, type, format_fn)
_NUMERIC_SETTINGS = [
    ("wpm", "WPM", int, lambda v: str(v)),
    ("error_rate", "Error Rate", float, lambda v: f"{v:.0%}"),
    ("start_delay", "Start Delay", float, lambda v: f"{v:.1f}s"),
    ("pause_frequency", "Pause Frequency", float, lambda v: f"{v:.0%}"),
    ("pause_duration_min", "Pause Min", float, lambda v: f"{v:.1f}s"),
    ("pause_duration_max", "Pause Max", float, lambda v: f"{v:.1f}s"),
]

_TOGGLE_SETTINGS = [
    ("fatigue_enabled", "Fatigue"),
    ("burst_typing_enabled", "Burst Typing"),
    ("ai_enabled", "AI Planning"),
    ("sound_enabled", "Sound"),
]


class GhostTyperApp(rumps.App):
    """Menu bar application for Ghost Typer."""

    def __init__(self, orchestrator: Orchestrator):
        super().__init__(name="Ghost Typer", title=None, icon=ICON_OFF, template=True, quit_button=None)

        self.orchestrator = orchestrator
        self.orchestrator.on_state_change = self._on_state_change
        self.orchestrator.on_progress = self._on_progress

        # Floating progress overlay
        self._progress_overlay = ProgressOverlay()

        # Global hotkey listener
        self._hotkey_listener = HotkeyListener(
            on_toggle_pause=self._hotkey_toggle_pause,
            on_emergency_stop=self._hotkey_emergency_stop,
            on_toggle_enabled=self._hotkey_toggle_enabled,
            on_paste=self._hotkey_paste,
        )
        self._hotkey_listener.start()

        # Load current settings
        self._settings_dict = load_settings_dict()

        # Menu items
        self._toggle_item = rumps.MenuItem("Turn ON", callback=self._toggle)
        self._status_item = rumps.MenuItem("Status: Off")
        self._status_item.set_callback(None)
        self._pause_item = rumps.MenuItem("Pause", callback=self._pause_resume)
        self._cancel_item = rumps.MenuItem("Cancel Current", callback=self._cancel)
        self._hotkeys_item = rumps.MenuItem("F6=Pause  Shift+F6=Stop  Ctrl+F6=On/Off")
        self._hotkeys_item.set_callback(None)
        self._quit_item = rumps.MenuItem("Quit", callback=self._quit)

        # Settings submenu
        self._settings_menu = rumps.MenuItem("Settings")
        self._setting_items = {}
        self._build_settings_menu()

        # Disable pause/cancel when idle
        self._pause_item.set_callback(None)
        self._cancel_item.set_callback(None)

        self.menu = [
            self._toggle_item,
            None,
            self._status_item,
            None,
            self._pause_item,
            self._cancel_item,
            None,
            self._settings_menu,
            None,
            self._hotkeys_item,
            None,
            self._quit_item,
        ]

        self._animation_thread: Optional[threading.Thread] = None
        self._animation_stop = threading.Event()
        self._animation_stop.set()

        # Shutdown guard — when True, _process_gui_queue discards all work
        self._shutting_down = False

        # Queue for dispatching GUI updates to the main thread
        self._gui_queue: queue.Queue = queue.Queue()
        self._gui_timer = rumps.Timer(self._process_gui_queue, 0.1)
        self._gui_timer.start()

    # ── Settings submenu ──

    def _build_settings_menu(self) -> None:
        """Build the Settings submenu from current settings."""
        for key, name, typ, fmt_fn in _NUMERIC_SETTINGS:
            val = self._settings_dict.get(key, 0)
            title = f"{name}: {fmt_fn(val)}"
            item = rumps.MenuItem(title, callback=self._make_numeric_callback(key, name, typ, fmt_fn))
            self._settings_menu[key] = item
            self._setting_items[key] = (item, fmt_fn, name)

        # Separator before toggles
        self._settings_menu["_sep"] = None

        for key, name in _TOGGLE_SETTINGS:
            val = self._settings_dict.get(key, False)
            item = rumps.MenuItem(name, callback=self._make_toggle_callback(key))
            item.state = 1 if val else 0
            self._settings_menu[key] = item
            self._setting_items[key] = (item, None, name)

    def _make_numeric_callback(self, key: str, name: str, typ: type, fmt_fn):
        """Create a callback that opens a dialog to edit a numeric setting."""
        def callback(_sender):
            current = self._settings_dict.get(key, 0)
            # Show as raw number for editing
            if typ == float:
                default_text = f"{current}"
            else:
                default_text = str(current)

            window = rumps.Window(
                message=f"Enter new value for {name}:",
                title=f"Ghost Typer — {name}",
                default_text=default_text,
                ok="Save",
                cancel="Cancel",
                dimensions=(200, 24),
            )
            response = window.run()
            if response.clicked:
                try:
                    new_val = typ(response.text.strip().rstrip('%').rstrip('s'))
                    self._settings_dict[key] = new_val
                    save_settings_dict(self._settings_dict)
                    self.orchestrator.update_settings(self._settings_dict)

                    # Update menu item title
                    item, fn, display_name = self._setting_items[key]
                    item.title = f"{display_name}: {fn(new_val)}"
                    logger.info("Setting %s changed to %s", key, new_val)
                except (ValueError, TypeError):
                    rumps.alert("Invalid value", f"Could not parse '{response.text}' as {typ.__name__}")
        return callback

    def _make_toggle_callback(self, key: str):
        """Create a callback that toggles a boolean setting."""
        def callback(sender):
            new_val = sender.state == 0  # flip
            sender.state = 1 if new_val else 0
            self._settings_dict[key] = new_val
            save_settings_dict(self._settings_dict)
            self.orchestrator.update_settings(self._settings_dict)
            logger.info("Setting %s toggled to %s", key, new_val)
        return callback

    # ── Main-thread GUI dispatch ──

    def _run_on_main(self, fn) -> None:
        """Enqueue a callable to run on the main thread via the GUI timer."""
        self._gui_queue.put(fn)

    def _process_gui_queue(self, _timer) -> None:
        """Drain the GUI queue on the main thread (called by rumps.Timer)."""
        if self._shutting_down:
            return
        while not self._gui_queue.empty():
            try:
                fn = self._gui_queue.get_nowait()
                fn()
            except Exception:
                logger.exception("Error in GUI queue callback")

    # ── Menu callbacks ──

    def _toggle(self, sender: rumps.MenuItem) -> None:
        """Toggle the app ON/OFF."""
        if self.orchestrator.is_enabled:
            self.orchestrator.disable(blocking=False)
            # Re-wire progress callback (cancel clears it)
            self.orchestrator.on_progress = self._on_progress
            sender.title = "Turn ON"
            self._status_item.title = "Status: Off"
            self.icon = ICON_OFF
            self._stop_animation()
            self._progress_overlay.hide()
        else:
            self.orchestrator.enable()
            sender.title = "Turn OFF"
            self._status_item.title = "Status: Idle"
            self.icon = ICON_IDLE

    def _pause_resume(self, sender: rumps.MenuItem) -> None:
        """Pause or resume current typing."""
        state = self.orchestrator.state
        if state == OrchestratorState.TYPING:
            self.orchestrator.pause()
        elif state == OrchestratorState.PAUSED:
            self.orchestrator.resume()

    def _cancel(self, _sender: rumps.MenuItem) -> None:
        """Cancel current typing."""
        self.orchestrator.cancel(blocking=False)
        self.orchestrator.on_progress = self._on_progress

    def _quit(self, _sender: rumps.MenuItem) -> None:
        """Quit the application."""
        logger.info("Quitting Ghost Typer")
        self._shutting_down = True
        self._stop_animation()
        if self._animation_thread is not None:
            self._animation_thread.join(timeout=1.0)
            self._animation_thread = None
        # Stop hotkey listener FIRST so no new hotkey callbacks fire into
        # stopped components. Then stop orchestrator.
        self.orchestrator.on_state_change = None
        self.orchestrator.on_progress = None
        self._hotkey_listener.stop()
        self.orchestrator.stop()
        # Hide overlay directly (we're on main thread) — don't enqueue
        self._progress_overlay.destroy()
        # Stop the GUI timer and drain remaining queue
        self._gui_timer.stop()
        rumps.quit_application()

    # ── Hotkey callbacks ──

    def _hotkey_toggle_pause(self) -> None:
        """F6 pressed — toggle pause/resume."""
        if self._shutting_down:
            return
        state = self.orchestrator.state
        if state == OrchestratorState.TYPING:
            self.orchestrator.pause()
        elif state == OrchestratorState.PAUSED:
            self.orchestrator.resume()

    def _hotkey_emergency_stop(self) -> None:
        """Shift+F6 pressed — cancel current typing immediately."""
        if self._shutting_down:
            return
        self.orchestrator.cancel(blocking=False)
        self.orchestrator.on_progress = self._on_progress
        logger.info("Emergency stop via hotkey")

    def _hotkey_paste(self) -> None:
        """Cmd+V pressed — trigger typing of staged clipboard content."""
        if self._shutting_down:
            return
        self.orchestrator.clipboard_monitor.trigger_paste()

    def _hotkey_toggle_enabled(self) -> None:
        """Ctrl+F6 pressed — toggle on/off."""
        if self._shutting_down:
            return
        if self.orchestrator.is_enabled:
            self.orchestrator.disable(blocking=False)
            self.orchestrator.on_progress = self._on_progress
            def _off():
                self._toggle_item.title = "Turn ON"
                self._status_item.title = "Status: Off"
                self.icon = ICON_OFF
                self._stop_animation()
                self._progress_overlay.hide()
            self._run_on_main(_off)
        else:
            self.orchestrator.enable()
            def _on():
                self._toggle_item.title = "Turn OFF"
                self._status_item.title = "Status: Idle"
                self.icon = ICON_IDLE
            self._run_on_main(_on)

    # ── State change handler ──

    def _on_state_change(self, new_state: OrchestratorState) -> None:
        """Update menu bar, progress overlay, and hotkey suppression when state changes."""
        # Suppress hotkey modifier tracking during typing
        if new_state == OrchestratorState.TYPING:
            self._hotkey_listener.suppress()
        elif new_state in (OrchestratorState.IDLE, OrchestratorState.PAUSED):
            self._hotkey_listener.unsuppress()

        def _update_gui():
            if new_state == OrchestratorState.IDLE:
                if self.orchestrator.is_enabled:
                    self.icon = ICON_IDLE
                    self._status_item.title = "Status: Idle"
                else:
                    self.icon = ICON_OFF
                    self._status_item.title = "Status: Off"
                self._pause_item.title = "Pause"
                self._pause_item.set_callback(None)
                self._cancel_item.set_callback(None)
                self._stop_animation()
                self._progress_overlay.hide()

            elif new_state == OrchestratorState.PLANNING:
                self._status_item.title = "Status: AI Planning..."
                self._cancel_item.set_callback(self._cancel)
                self.icon = ICON_PLANNING

            elif new_state == OrchestratorState.TYPING:
                self._status_item.title = "Status: Typing..."
                self._pause_item.title = "Pause"
                self._pause_item.set_callback(self._pause_resume)
                self._cancel_item.set_callback(self._cancel)
                self._start_animation()
                self._progress_overlay.show()

            elif new_state == OrchestratorState.VERIFYING:
                self._status_item.title = "Status: Verifying..."
                self._stop_animation()
                self.icon = ICON_VERIFYING
                self._progress_overlay.hide()

            elif new_state == OrchestratorState.PAUSED:
                self.icon = ICON_PAUSED
                self._status_item.title = "Status: Paused"
                self._pause_item.title = "Resume"
                self._pause_item.set_callback(self._pause_resume)
                self._cancel_item.set_callback(self._cancel)
                self._stop_animation()
                self._progress_overlay.hide()

        self._run_on_main(_update_gui)

    def _on_progress(self, chars_typed: int, total_chars: int) -> None:
        """Update menu bar status and floating progress overlay."""
        if total_chars <= 0:
            return
        pct = min(100, int(chars_typed / total_chars * 100))
        remaining = total_chars - chars_typed
        wpm = self._settings_dict.get("wpm", 57)

        def _update():
            self._status_item.title = f"Status: Typing... {pct}% ({remaining} left)"
            self._progress_overlay.update(chars_typed, total_chars, wpm)
        self._run_on_main(_update)

    # ── Animation ──

    def _start_animation(self) -> None:
        """Start animating the menu bar icon."""
        if self._animation_thread is not None and self._animation_thread.is_alive():
            return
        self._animation_stop.clear()
        self._animation_thread = threading.Thread(target=self._animate, daemon=True, name="MenuBarAnim")
        self._animation_thread.start()

    def _stop_animation(self) -> None:
        """Signal the animation thread to stop."""
        self._animation_stop.set()

    def _animate(self) -> None:
        """Cycle the menu bar icon to indicate typing activity."""
        frames = [ICON_TYPING, ICON_TYPING2, ICON_TYPING3]
        idx = 0
        while not self._animation_stop.is_set():
            frame = frames[idx % len(frames)]
            self._run_on_main(lambda f=frame: setattr(self, 'icon', f))
            idx += 1
            self._animation_stop.wait(timeout=0.5)
