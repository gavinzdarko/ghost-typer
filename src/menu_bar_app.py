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
from urllib.parse import urlsplit
from typing import Optional

import AppKit
import objc
import rumps

from .hotkey_listener import HotkeyListener
from .orchestrator import Orchestrator, OrchestratorState
from .progress_overlay import ProgressOverlay
from .settings_ui import load_settings_dict, save_settings_dict, parse_numeric_setting

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
    ("verify_after_typing", "Verify After Typing (OCR)"),
]


class _MenuDelegate(AppKit.NSObject):
    """NSMenuDelegate that pauses typing while the dropdown is open."""

    _app_ref = None  # set after init

    def menuWillOpen_(self, menu) -> None:
        app = self._app_ref
        if app and not app._shutting_down:
            # A new paste can become ready even if the menu opened while idle.
            # Capture pause ownership before a ready worker sees the menu flag.
            app._menu_auto_paused = app.orchestrator.set_menu_open(True)
            if app._menu_auto_paused:
                app.orchestrator.pause()
                logger.info("Auto-paused typing (menu opened)")

    def menuDidClose_(self, menu) -> None:
        app = self._app_ref
        if app and not app._shutting_down:
            app.orchestrator.set_menu_open(False)
            if getattr(app, '_menu_auto_paused', False):
                app._menu_auto_paused = False
                if (app.orchestrator.state == OrchestratorState.PAUSED
                        and not getattr(app, '_settings_modal_active', False)):
                    app.orchestrator.resume()
                    logger.info("Auto-resumed typing (menu closed)")


class GhostTyperApp(rumps.App):
    """Menu bar application for Ghost Typer."""

    def __init__(self, orchestrator: Orchestrator):
        super().__init__(name="Ghost Typer", title=None, icon=ICON_OFF, template=True, quit_button=None)

        self._state_effects_lock = threading.Lock()
        self._state_effects_revision = -1
        self.orchestrator = orchestrator
        self.orchestrator.on_state_change = self._on_state_change
        self.orchestrator.on_progress = self._on_progress

        # Auto-pause tracking
        self._menu_auto_paused = False
        self._settings_modal_active = False

        # Set up menu delegate to pause typing while dropdown is open
        self._menu_delegate = _MenuDelegate.alloc().init()
        self._menu_delegate._app_ref = self
        # Wire it up after rumps creates the NSMenu (deferred to after super().__init__)
        self._wire_menu_delegate()

        # Floating progress overlay
        self._progress_overlay = ProgressOverlay()

        # Global hotkey listener
        self._hotkey_listener = HotkeyListener(
            on_toggle_pause=self._hotkey_toggle_pause,
            on_emergency_stop=self._hotkey_emergency_stop,
            on_toggle_enabled=self._hotkey_toggle_enabled,
            on_paste=self._hotkey_paste,
        )

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

        # Table fill mode
        self._table_fill_item = rumps.MenuItem("Table Fill Mode", callback=self._toggle_table_fill)
        self._table_run_item = rumps.MenuItem("Run Table (0 items)", callback=self._run_table_fill)
        self.orchestrator.on_table_queue_change = self._on_table_queue_change

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
            self._table_fill_item,
            self._table_run_item,
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
        self._gui_update_lock = threading.Lock()
        self._gui_updates = {}
        self._gui_timer = rumps.Timer(self._process_gui_queue, 0.1)
        self._gui_timer.start()

        # Callbacks may fire immediately when the global listener starts.
        # Publish it only after every callback dependency and GUI queue exists.
        self._hotkey_listener.start()

    def _wire_menu_delegate(self) -> None:
        """Attach the NSMenuDelegate to the status bar menu."""
        try:
            ns_menu = self._menu._menu  # rumps internal NSMenu
            ns_menu.setDelegate_(self._menu_delegate)
            logger.info("Menu delegate attached")
        except Exception:
            logger.exception("Failed to set up menu delegate")

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

        for key, name in (("anthropic_api_key", "Anthropic API Key"),
                          ("webhook_url", "Notification Webhook")):
            self._settings_menu[key] = rumps.MenuItem(
                name, callback=self._make_connection_callback(key, name)
            )

    def _make_connection_callback(self, key: str, name: str):
        """Edit connection secrets through native, masked input fields."""
        def callback(_sender):
            window = rumps.Window(
                message=("Enter a replacement value. Leave blank to clear the saved value. "
                         "A cleared API key uses ANTHROPIC_API_KEY from the environment."),
                title=f"Ghost Typer — {name}", default_text="", secure=True,
                ok="Save", cancel="Cancel", dimensions=(320, 24),
            )
            response = self._run_settings_window(window)
            if response is None or not response.clicked:
                return
            value = response.text.strip()
            if key == "webhook_url" and value:
                try:
                    parsed = urlsplit(value)
                    valid_url = parsed.scheme in ("http", "https") and bool(parsed.hostname)
                except ValueError:
                    valid_url = False
                if not valid_url:
                    self.orchestrator.notification_service.notify_error(
                        "Webhook must be an HTTP or HTTPS URL."
                    )
                    return
            candidate = {**self._settings_dict, key: value}
            try:
                save_settings_dict(candidate)
            except (OSError, ValueError, TypeError):
                logger.exception("Failed to save connection setting %s", key)
                self.orchestrator.notification_service.notify_error(
                    "Could not save settings. The setting was not changed."
                )
                return
            self._settings_dict = candidate
            self.orchestrator.update_settings(candidate)
            logger.info("Connection setting %s updated", key)
        return callback

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
            response = self._run_settings_window(window)
            if response is None:
                return
            if response.clicked:
                try:
                    new_val = parse_numeric_setting(key, response.text)
                    candidate = {**self._settings_dict, key: new_val}
                    if candidate.get("pause_duration_min", 0.3) > candidate.get("pause_duration_max", 4.0):
                        raise ValueError("Pause minimum must not exceed maximum")
                    save_settings_dict(candidate)
                    self._settings_dict = candidate
                    self.orchestrator.update_settings(candidate)

                    # Update menu item title
                    item, fn, display_name = self._setting_items[key]
                    item.title = f"{display_name}: {fn(new_val)}"
                    logger.info("Setting %s changed to %s", key, new_val)
                except (ValueError, TypeError):
                    self.orchestrator.notification_service.notify_error(
                        f"Invalid {name} value; enter a valid {typ.__name__}."
                    )
                except OSError:
                    logger.exception("Failed to save numeric setting %s", key)
                    self.orchestrator.notification_service.notify_error(
                        "Could not save settings. The setting was not changed."
                    )
        return callback

    def _run_settings_window(self, window):
        """Keep synthetic keys and clipboard capture outside modal settings."""
        # Capture the state after excluding clipboard callbacks: a paste that
        # won this lock may already have launched planning and must be noticed.
        self._settings_modal_active = True
        try:
            with self.orchestrator.clipboard_monitor.suspended(blocking=False):
                state = self.orchestrator.state
                if state in (OrchestratorState.PLANNING, OrchestratorState.VERIFYING):
                    self.orchestrator.notification_service.notify_error(
                        "Wait for planning or verification to finish before opening settings."
                    )
                    return None
                simulator = self.orchestrator._simulator
                if state == OrchestratorState.TYPING and simulator is None:
                    self.orchestrator.notification_service.notify_error(
                        "Wait for the typing session to become ready before opening settings."
                    )
                    return None
                menu_pause = getattr(self, '_menu_auto_paused', False)
                resume_after = simulator is not None and (
                    state == OrchestratorState.TYPING
                    or state == OrchestratorState.PAUSED and menu_pause
                )
                if menu_pause:
                    self._menu_auto_paused = False
                if state == OrchestratorState.TYPING and resume_after:
                    self.orchestrator.pause()
                try:
                    return window.run()
                finally:
                    if (resume_after and self.orchestrator._simulator is simulator
                            and self.orchestrator.state == OrchestratorState.PAUSED):
                        self.orchestrator.resume()

        except BlockingIOError:
            self.orchestrator.notification_service.notify_error(
                "Clipboard is busy; finish or stop the current operation before opening settings."
            )
            return None
        finally:
            self._settings_modal_active = False

    def _make_toggle_callback(self, key: str):
        """Create a callback that toggles a boolean setting."""
        def callback(sender):
            new_val = sender.state == 0  # flip
            candidate = {**self._settings_dict, key: new_val}
            try:
                save_settings_dict(candidate)
            except (OSError, ValueError, TypeError):
                logger.exception("Failed to save toggle setting %s", key)
                self.orchestrator.notification_service.notify_error(
                    "Could not save settings. The setting was not changed."
                )
                return
            self.orchestrator.update_settings(candidate)
            self._settings_dict = candidate
            sender.state = 1 if new_val else 0
            logger.info("Setting %s toggled to %s", key, new_val)
        return callback

    # ── Main-thread GUI dispatch ──

    def _run_on_main(self, fn) -> None:
        """Enqueue a callable to run on the main thread via the GUI timer."""
        self._gui_queue.put(fn)

    def _queue_gui_update(self, key: str, fn) -> None:
        """Keep only the newest replaceable update while the UI is occupied."""
        with self._gui_update_lock:
            if self._shutting_down:
                return
            pending = key in self._gui_updates
            self._gui_updates[key] = fn
            if pending:
                return

        def deliver():
            with self._gui_update_lock:
                latest = self._gui_updates.pop(key, None)
            if latest is not None:
                latest()
        self._run_on_main(deliver)

    def _process_gui_queue(self, _timer) -> None:
        """Drain the GUI queue on the main thread (called by rumps.Timer)."""
        # Producers may enqueue while this timer runs. Bound each turn so the
        # AppKit loop can service menus, redraws and the emergency-stop controls.
        for _ in range(100):
            if self._shutting_down:
                return
            try:
                fn = self._gui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                logger.exception("Error in GUI queue callback")

    # ── Menu callbacks ──

    def _toggle(self, sender: rumps.MenuItem) -> None:
        """Toggle the app ON/OFF."""
        if self.orchestrator.is_enabled:
            self.orchestrator.disable(blocking=False)
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
        if self._shutting_down or getattr(self, '_settings_modal_active', False):
            return
        state = self.orchestrator.state
        if state == OrchestratorState.TYPING:
            self.orchestrator.pause()
        elif state == OrchestratorState.PAUSED:
            if getattr(self.orchestrator, "_menu_open", False):
                # The menu itself paused an active session. A user's Pause
                # click takes ownership; a Resume click on an existing manual
                # pause schedules resume after the menu stops receiving keys.
                self._menu_auto_paused = not getattr(self, "_menu_auto_paused", False)
                self._pause_item.title = "Pause" if self._menu_auto_paused else "Resume"
            else:
                self.orchestrator.resume()

    def _cancel(self, _sender: rumps.MenuItem) -> None:
        """Cancel current typing."""
        self.orchestrator.cancel(blocking=False)

    def _toggle_table_fill(self, sender: rumps.MenuItem) -> None:
        """Toggle table fill mode on/off."""
        if self.orchestrator.table_fill_mode:
            # Turn off
            self.orchestrator.disable_table_fill()
            sender.state = 0
            self._table_run_item.title = "Run Table (0 items)"
            self._status_item.title = "Status: Idle" if self.orchestrator.is_enabled else "Status: Off"
        else:
            # Turn on — also enable the app if it's off
            if not self.orchestrator.is_enabled:
                self.orchestrator.enable()
                self._toggle_item.title = "Turn OFF"
                self.icon = ICON_IDLE
            self.orchestrator.enable_table_fill()
            sender.state = 1
            self._status_item.title = f"Table Fill: {self.orchestrator.table_queue_count()} items queued"

    def _run_table_fill(self, _sender: rumps.MenuItem) -> None:
        """Execute the table fill queue."""
        count = self.orchestrator.table_queue_count()
        if count == 0:
            return

        if self.orchestrator.run_table_fill(skip_columns=1):
            self._table_fill_item.state = 0
            self._table_run_item.title = "Run Table (0 items)"

    def _on_table_queue_change(self, count: int) -> None:
        """Update menu when table queue changes."""
        def _update():
            self._table_run_item.title = f"Run Table ({count} item{'s' if count != 1 else ''})" if count > 0 else "Run Table (0 items)"
            if count > 0:
                self._status_item.title = f"Table Fill: {count} item{'s' if count != 1 else ''} queued"
            elif not self.orchestrator.table_fill_mode:
                self._table_fill_item.state = 0
        self._run_on_main(_update)

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
        if self._shutting_down or getattr(self, '_settings_modal_active', False):
            return
        # Menu delegates and menu actions run on AppKit's main thread. Apply
        # hotkey intent there too so menu dismissal cannot race ownership edits.
        with self.orchestrator._session_lock:
            if self.orchestrator.state not in (OrchestratorState.TYPING, OrchestratorState.PAUSED):
                return
            simulator = self.orchestrator._simulator
            if simulator is None:
                return

        def toggle_current_session():
            with self.orchestrator._session_lock:
                if self.orchestrator._simulator is simulator:
                    self._pause_resume(None)

        self._run_on_main(toggle_current_session)

    def _hotkey_emergency_stop(self) -> None:
        """Shift+F6 pressed — cancel current typing immediately."""
        if self._shutting_down:
            return
        self.orchestrator.cancel(blocking=False)
        logger.info("Emergency stop via hotkey")

    def _hotkey_paste(self) -> None:
        """Cmd+V pressed — trigger typing of staged clipboard content."""
        if self._shutting_down or getattr(self, '_settings_modal_active', False):
            return
        # In table fill mode, content is already queued on copy — Cmd+V is a no-op
        if self.orchestrator.table_fill_mode:
            return
        self.orchestrator.clipboard_monitor.trigger_paste()

    def _hotkey_toggle_enabled(self) -> None:
        """Ctrl+F6 pressed — toggle on/off."""
        if self._shutting_down or getattr(self, '_settings_modal_active', False):
            return
        if self.orchestrator.is_enabled:
            self.orchestrator.disable(blocking=False)
        else:
            self.orchestrator.enable()

        def _update():
            # A newer menu command or hotkey can win before this GUI turn.
            # Render current ownership instead of replaying the old intent.
            enabled = self.orchestrator.is_enabled
            self._toggle_item.title = "Turn OFF" if enabled else "Turn ON"
            if not enabled:
                self._status_item.title = "Status: Off"
                self.icon = ICON_OFF
                self._stop_animation()
                self._progress_overlay.hide()
            elif self.orchestrator.state == OrchestratorState.IDLE:
                self._status_item.title = "Status: Idle"
                self.icon = ICON_IDLE
        self._run_on_main(_update)

    # ── State change handler ──

    def _on_state_change(self, new_state: OrchestratorState) -> None:
        """Update menu bar, progress overlay, and hotkey suppression when state changes."""
        # State callbacks run outside the orchestrator's locks and may arrive
        # after a later transition. Serialize only these immediate hotkey effects
        # so an old resume cannot suppress controls after completion unsuppressed
        # them. Never hold this lock while dispatching or running GUI callbacks.
        with self._state_effects_lock:
            state, revision = self.orchestrator.state_snapshot
            if new_state != state or revision <= self._state_effects_revision:
                return
            self._state_effects_revision = revision
            if new_state == OrchestratorState.TYPING:
                self._hotkey_listener.suppress()
            elif new_state in (OrchestratorState.IDLE, OrchestratorState.PAUSED):
                self._hotkey_listener.unsuppress()

        def _update_gui():
            if self.orchestrator.state_snapshot != (new_state, revision):
                return
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
                self._start_animation()
                self._progress_overlay.show_planning()

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
                self._pause_item.title = "Pause" if self._menu_auto_paused else "Resume"
                self._pause_item.set_callback(self._pause_resume)
                self._cancel_item.set_callback(self._cancel)
                self._stop_animation()
                self._progress_overlay.pause()

        self._run_on_main(_update_gui)

    def _on_progress(self, chars_typed: int, total_chars: int, start_time: float = 0.0, estimated_total: float = 0.0) -> None:
        """Update menu bar status and floating progress overlay."""
        if total_chars <= 0:
            return
        snapshot = self.orchestrator.state_snapshot
        if snapshot[0] != OrchestratorState.TYPING:
            return
        pct = min(100, int(chars_typed / total_chars * 100))
        remaining = max(0, total_chars - chars_typed)

        def _update():
            # GUI callbacks can wait behind a modal menu/dialog. Do not let
            # progress from an earlier transition overwrite idle or a new session.
            if self.orchestrator.state_snapshot != snapshot:
                return
            self._status_item.title = f"Status: Typing... {pct}% ({remaining} left)"
            self._progress_overlay.update(chars_typed, total_chars, start_time, estimated_total)
        # Preserve the initial ETA message; later progress is replaceable.
        if estimated_total > 0:
            self._run_on_main(_update)
        else:
            # A pending delivery from an older transition precedes this
            # transition's initial ETA in the queue. Do not reuse its slot.
            self._queue_gui_update(f"progress:{snapshot[1]}", _update)

    # ── Animation ──

    def _start_animation(self) -> None:
        """Start animating the menu bar icon."""
        if (self._animation_thread is not None and self._animation_thread.is_alive()
                and not self._animation_stop.is_set()):
            return
        # A stopped worker can still be exiting. Its event must stay set so it
        # and its queued frames cannot become active again after a restart.
        self._animation_stop = threading.Event()
        self._animation_thread = threading.Thread(target=self._animate, args=(self._animation_stop,),
                                                  daemon=True, name="MenuBarAnim")
        self._animation_thread.start()

    def _stop_animation(self) -> None:
        """Signal the animation thread to stop."""
        self._animation_stop.set()

    def _animate(self, stop: threading.Event) -> None:
        """Cycle the menu bar icon to indicate typing activity."""
        frames = [ICON_TYPING, ICON_TYPING2, ICON_TYPING3]
        idx = 0
        while not stop.is_set():
            frame = frames[idx % len(frames)]
            # Check stop flag inside the lambda to avoid overwriting the icon
            # if _stop_animation() was called between enqueue and execution.
            self._queue_gui_update("animation", lambda f=frame: (
                setattr(self, 'icon', f) if not stop.is_set() else None
            ))
            idx += 1
            stop.wait(timeout=0.5)
