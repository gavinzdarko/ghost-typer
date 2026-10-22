"""
Main controller that connects clipboard monitoring, text parsing, AI planner,
typing engine, visual verification, and notifications.

This is the brain of Ghost Typer — it orchestrates the full pipeline:
clipboard → parse → AI plan → type → verify → notify
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy
import threading
import time
from enum import Enum, auto
from typing import Optional

from .ai_planner import AIPlanner, AIProfileGenerator, AIRewriter
from .clipboard_monitor import ClipboardContent, ClipboardMonitor
from .models import (
    AbandonWord,
    ApplyFormatting,
    DistractionPause,
    MakeMistake,
    Pause,
    PressKey,
    Rewrite,
    Settings,
    TextSegment,
    TypeText,
    TypingAction,
    TypingPlan,
    TypingProfile,
)
from .keystroke_simulator import KeystrokeSimulator
from .notification_service import NotificationService
from .settings_ui import DEFAULTS, load_settings_dict, save_settings_dict
from .text_parser import TextParser
from .typing_engine import TypingEngine
from .typing_planner import PlanningCancelled, TypingPlanner
from .visual_verifier import VisualVerifier

logger = logging.getLogger(__name__)

# Sentinel value used in the table queue to mark row boundaries
_ROW_BREAK = "\x00__ROW_BREAK__"


class OrchestratorState(Enum):
    IDLE = auto()
    PLANNING = auto()
    TYPING = auto()
    VERIFYING = auto()
    PAUSED = auto()


class Orchestrator:
    """Ties together all Ghost Typer components with AI-powered planning."""

    def __init__(self, profile: TypingProfile | None = None) -> None:
        # Typing profile (AI-generated or defaults)
        self._profile = profile or TypingProfile.defaults()
        self._baseline_profile = deepcopy(self._profile)

        # Load persisted settings (flat dict with both Settings fields and app-level fields)
        self._settings_dict = load_settings_dict()
        self._settings = self._build_settings(self._settings_dict)

        # Core components
        self.text_parser = TextParser()
        self.notification_service = NotificationService(
            webhook_url=self._settings_dict.get("webhook_url") or None,
            sound_enabled=self._settings_dict.get("sound_enabled", True),
        )
        self.clipboard_monitor = ClipboardMonitor(
            on_clipboard_change=self._on_clipboard_change,
            start_delay=self._settings_dict.get("start_delay", 3.0),
        )

        # AI components — use settings API key if available
        _api_key = self._resolve_api_key(self._settings_dict)
        ai_enabled = self._settings_dict.get("ai_enabled", True)
        self.ai_planner = AIPlanner(self._settings, api_key=_api_key, enabled=ai_enabled)
        self.ai_rewriter = AIRewriter(api_key=_api_key, enabled=ai_enabled)
        self.ai_profile_generator = AIProfileGenerator(self._settings, api_key=_api_key, enabled=ai_enabled)
        self.visual_verifier = VisualVerifier(
            enabled=self._settings_dict.get("verify_after_typing", False),
        )

        # Fallback planner (rule-based, with AI rewriter for drafts)
        self.fallback_planner = TypingPlanner(self._settings, ai_rewriter=self.ai_rewriter, ai_enabled=ai_enabled, api_key=_api_key)

        # Typing state
        self._state = OrchestratorState.IDLE
        self._state_revision = 0
        self._state_lock = threading.Lock()
        self._session_lock = threading.RLock()
        self._typing_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._simulator: Optional[KeystrokeSimulator] = None
        self._menu_open = False

        # Behavioral content (AI-generated, or empty dict)
        self._behavioral_content: dict = {}
        self._profile_executor = None
        self._profile_futures = set()

        # Stats
        self._current_word_count = 0
        self._typing_start_time = 0.0
        self._total_chars = 0
        self._chars_typed = 0

        # Table fill mode
        self._table_fill_mode = False
        self._table_queue: list[ClipboardContent] = []
        self._table_queue_lock = threading.RLock()
        self.on_table_queue_change: Optional[callable] = None  # (count)

        # Callbacks for UI updates
        self.on_state_change: Optional[callable] = None
        self.on_progress: Optional[callable] = None  # (chars_typed, total_chars)

        # Log AI status
        if self.ai_planner.is_enabled:
            logger.info("AI planner ENABLED — Claude will generate typing plans")
        else:
            logger.info("AI planner DISABLED — using rule-based planner")

    @property
    def state(self) -> OrchestratorState:
        with self._state_lock:
            return self._state

    @property
    def state_snapshot(self) -> tuple[OrchestratorState, int]:
        """Identify a transition even when a later session reuses its state."""
        with self._state_lock:
            return self._state, self._state_revision

    @state.setter
    def state(self, new_state: OrchestratorState) -> None:
        self._set_state(new_state)

    def _set_state(self, new_state: OrchestratorState, *, expected: OrchestratorState | None = None) -> bool:
        """Transition atomically, optionally only from an expected state."""
        with self._state_lock:
            old = self._state
            if expected is not None and old != expected:
                return False
            self._state = new_state
            self._state_revision += 1
        logger.info("State: %s -> %s", old.name, new_state.name)
        cb = self.on_state_change  # snapshot to avoid TOCTOU
        if cb:
            try:
                cb(new_state)
            except Exception:
                logger.exception("Error in state change callback")
        return True

    def start(self) -> None:
        """Start the orchestrator and clipboard monitor."""
        self.clipboard_monitor.start()
        logger.info("Orchestrator started")

    def stop(self) -> None:
        """Shut down everything gracefully."""
        self.cancel()
        self.clipboard_monitor.stop()
        if self._profile_executor is not None:
            self._profile_executor.shutdown(wait=False, cancel_futures=True)
            self._profile_executor = None
        logger.info("Orchestrator stopped")

    def enable(self) -> None:
        """Enable clipboard monitoring (app ON)."""
        self.clipboard_monitor.enabled = True
        with self._session_lock:
            self._sessions_disabled = False
        logger.info("Ghost Typer enabled")

    def disable(self, blocking: bool = True) -> None:
        """Disable clipboard monitoring (app OFF)."""
        # A paused table probe owns the clipboard transaction lock while it
        # waits for its simulator. Stop that simulator before waiting to restore
        # the clipboard, otherwise turning OFF can never reach cancellation.
        with self._session_lock:
            # A clipboard callback may already own its transaction lock. Fence
            # its later launch before cancellation can observe an idle session.
            self._sessions_disabled = True
        self.cancel(blocking=blocking)
        self.clipboard_monitor.enabled = False
        logger.info("Ghost Typer disabled")

    @property
    def is_enabled(self) -> bool:
        return self.clipboard_monitor.enabled

    def set_menu_open(self, value: bool) -> bool:
        """Fence keyboard sessions and atomically identify menu pause ownership."""
        with self._session_lock:
            auto_pause = value and self.state != OrchestratorState.PAUSED
            self._menu_open = value
            return auto_pause

    def _activate_simulator(self) -> KeystrokeSimulator:
        """Publish a ready simulator and honor a menu opened during planning."""
        with self._session_lock:
            simulator = KeystrokeSimulator()
            self._simulator = simulator
            if getattr(self, "_menu_open", False):
                simulator.pause()
                self.state = OrchestratorState.PAUSED
            else:
                self.state = OrchestratorState.TYPING
            return simulator

    def pause(self) -> None:
        """Pause the current typing session without reviving a finished worker."""
        with self._session_lock:
            if self.state != OrchestratorState.TYPING:
                return
            sim = self._simulator
            if sim is None:
                return
            sim.pause()
            if self._set_state(OrchestratorState.PAUSED, expected=OrchestratorState.TYPING):
                self.notification_service.notify_paused()
            else:
                # Completion may have won while the simulator was pausing.
                sim.resume()

    def resume(self) -> None:
        """Resume only a session that still owns its paused simulator."""
        with self._session_lock:
            if self.state != OrchestratorState.PAUSED or getattr(self, "_menu_open", False):
                return
            sim = self._simulator
            if sim is None:
                return
            sim.resume()
            if self._set_state(OrchestratorState.TYPING, expected=OrchestratorState.PAUSED):
                self.notification_service.notify_resumed()

    def cancel(self, blocking: bool = True) -> None:
        """Cancel the current typing session.

        Args:
            blocking: If True, wait for the typing thread to finish.
                      Set to False when calling from the main/GUI thread
                      to avoid blocking the AppKit event loop.
        """
        with self._session_lock:
            if self.state == OrchestratorState.IDLE and not (
                self._typing_thread and self._typing_thread.is_alive()
            ):
                return
            self._cancel_event.set()
            sim = self._simulator
            worker = self._typing_thread
        if sim:
            sim.resume()
            sim.stop()
        if blocking and worker and worker is not threading.current_thread() and worker.ident is not None:
            worker.join(timeout=5.0)
        with self._session_lock:
            # A timed-out worker still owns its cancellation event and session.
            # Never advertise IDLE or allow a new launch to clear its event.
            if blocking and (not worker or not worker.is_alive()) and self._typing_thread is worker:
                self._typing_thread = None
                self.state = OrchestratorState.IDLE
        self.notification_service.notify_cancelled()

    # ------------------------------------------------------------------
    # Table fill mode
    # ------------------------------------------------------------------

    @property
    def table_fill_mode(self) -> bool:
        return self._table_fill_mode

    def enable_table_fill(self) -> None:
        """Enter table fill mode — pastes queue up instead of typing."""
        self._table_fill_mode = True
        self.clipboard_monitor._immediate_mode = True
        self._notify_table_queue_change(self.table_queue_count())
        logger.info("Table fill mode ON")

    def disable_table_fill(self) -> None:
        """Exit table fill mode and clear the queue."""
        self._table_fill_mode = False
        self.clipboard_monitor._immediate_mode = False
        with self._table_queue_lock:
            self._table_queue.clear()
        self._notify_table_queue_change(0)
        logger.info("Table fill mode OFF")

    def table_queue_count(self) -> int:
        with self._table_queue_lock:
            return sum(1 for item in self._table_queue if item.text != _ROW_BREAK)

    def _add_to_table_queue(self, content: ClipboardContent) -> None:
        """Add clipboard content to the table fill queue.

        Supports two formats:
        - Multiple lines with blank-line separators: each group of lines is a
          row, each line within a group is a cell. A ROW_BREAK marker is
          inserted between groups.
        - Single line or lines with no blank separator: each line is one cell.
        """
        raw_lines = content.text.splitlines()

        # Check if there are blank-line separators (row breaks)
        has_row_breaks = any(line.strip() == "" for line in raw_lines)

        items_added = 0
        with self._table_queue_lock:
            if has_row_breaks:
                # Split into row groups by blank lines.
                # Insert a ROW_BREAK between groups (not for leading/trailing
                # blanks or consecutive blanks).
                in_row_break = False
                for line in raw_lines:
                    if line.strip() == "":
                        if not in_row_break and self._table_queue:
                            self._table_queue.append(ClipboardContent(text=_ROW_BREAK))
                        in_row_break = True
                    else:
                        self._table_queue.append(ClipboardContent(text=line.strip()))
                        in_row_break = False
                        items_added += 1
                # Remove trailing row break if present
                if self._table_queue and self._table_queue[-1].text == _ROW_BREAK:
                    self._table_queue.pop()
            elif len(raw_lines) > 1:
                for line in raw_lines:
                    stripped = line.strip()
                    if stripped:
                        self._table_queue.append(ClipboardContent(text=stripped))
                        items_added += 1
            else:
                self._table_queue.append(content)
                items_added = 1
            count = sum(1 for item in self._table_queue if item.text != _ROW_BREAK)
        logger.info("Table queue: added %d cell(s), total %d", items_added, count)
        self._notify_table_queue_change(count)

    def _notify_table_queue_change(self, count: int) -> None:
        cb = self.on_table_queue_change
        if cb:
            try:
                cb(count)
            except Exception:
                logger.exception("Error in table queue change callback")

    def run_table_fill(self, skip_columns: int = 1) -> bool:
        """Execute all queued table items — type each one, TAB between them.

        Args:
            skip_columns: Number of pre-filled columns to skip at the start
                          of each new row (e.g. 1 if column A has labels).
        """
        with self._session_lock:
            if getattr(self, "_sessions_disabled", False):
                logger.info("Ignoring launch while Ghost Typer is disabled")
                return False
            worker = self._typing_thread
            if self.state != OrchestratorState.IDLE or (worker and worker.is_alive()):
                logger.info("Can't run table fill while a session is active")
                return False
            with self._table_queue_lock:
                items = list(self._table_queue)
                if not items:
                    logger.warning("Table fill: nothing in queue")
                    return False
                # Keep the queue and mode intact unless the worker actually starts.
                if not self._launch_pipeline(self._table_fill_pipeline, (items, skip_columns), "TableFillPipeline"):
                    return False
                self._table_queue.clear()
                self._table_fill_mode = False
                self.clipboard_monitor._immediate_mode = False
        self._notify_table_queue_change(0)
        return True

    _CLIPBOARD_SENTINEL = "\x00__GHOST_TYPER_EMPTY__"

    def _cell_has_content(self, simulator: KeystrokeSimulator) -> bool:
        """Probe a cell while preserving every pasteboard representation.

        Restoration is conditional on the observed revision still belonging to
        this probe. NSPasteboard has no compare-and-swap write: revision checks
        reduce competing-writer races but cannot make this transaction atomic.
        """
        import AppKit
        pb = AppKit.NSPasteboard.generalPasteboard()
        with self.clipboard_monitor.suspended():
            snapshot_revision = pb.changeCount()
            saved_items = []
            for item in pb.pasteboardItems() or []:
                saved = AppKit.NSPasteboardItem.alloc().init()
                for pasteboard_type in item.types():
                    data = item.dataForType_(pasteboard_type)
                    if data is None or not saved.setData_forType_(data, pasteboard_type):
                        raise RuntimeError("Could not preserve the clipboard for a cell check")
                saved_items.append(saved)

            if pb.changeCount() != snapshot_revision:
                raise RuntimeError("Clipboard changed during a cell check; retry table fill")
            owned_revision = None
            try:
                cleared_revision = pb.clearContents()
                owned_revision = int(cleared_revision) if cleared_revision is not None else pb.changeCount()
                if pb.changeCount() != owned_revision:
                    raise RuntimeError("Clipboard changed during a cell check; retry table fill")
                if not pb.setString_forType_(self._CLIPBOARD_SENTINEL, AppKit.NSPasteboardTypeString):
                    raise RuntimeError("Could not prepare clipboard for a cell check")
                prepared_revision = pb.changeCount()
                if (pb.stringForType_(AppKit.NSPasteboardTypeString) != self._CLIPBOARD_SENTINEL
                        or pb.changeCount() != prepared_revision):
                    raise RuntimeError("Clipboard changed during a cell check; retry table fill")
                owned_revision = prepared_revision
                simulator.wait(0.05)
                simulator.hotkey("command", "left")
                simulator.wait(0.1)
                simulator.hotkey("command", "shift", "right")
                simulator.wait(0.15)
                if pb.changeCount() != owned_revision:
                    raise RuntimeError("Clipboard changed during a cell check; retry table fill")
                simulator.hotkey("command", "c")
                # Capture the copy response as soon as it arrives. Any subsequent
                # revision belongs to another writer and is preserved in finally.
                for _ in range(7):
                    simulator.wait(0.05)
                    revision = pb.changeCount()
                    if revision != owned_revision:
                        owned_revision = revision
                        break
                text = pb.stringForType_(AppKit.NSPasteboardTypeString) or ""
                if pb.changeCount() != owned_revision:
                    raise RuntimeError("Clipboard changed during a cell check; retry table fill")
                return text != self._CLIPBOARD_SENTINEL and bool(text.strip())
            finally:
                if owned_revision is not None and pb.changeCount() == owned_revision:
                    pb.clearContents()
                    if saved_items and not pb.writeObjects_(saved_items):
                        raise RuntimeError("Could not restore clipboard after a cell check")
                    self.clipboard_monitor.acknowledge_change(pb.changeCount())

    def _table_fill_pipeline(self, items: list[ClipboardContent], skip_columns: int = 1) -> None:
        """Type each queued item with TAB between them, auto-skipping filled cells."""
        consumed_items = 0
        incomplete = False
        try:
            total_word_count = 0
            cell_count = 0
            skipped_count = 0

            # Plan every cell once so progress describes the complete table,
            # including temporary typo/correction characters in simple plans.
            type_queue = []
            for original_index, entry in enumerate(items):
                if entry.text == _ROW_BREAK:
                    continue
                if self._cancel_event.is_set():
                    return
                segments = self.text_parser.parse(entry.content, is_html=entry.is_html)
                if not segments or not segments[0].text.strip():
                    raise ValueError("Table item did not contain typable text")
                cell_plan = self.fallback_planner.plan(
                    segments, simple=True, cancelled=self._cancel_event.is_set)
                word_count = sum(len(seg.text.split()) for seg in segments if seg.text.strip())
                type_queue.append((entry, original_index, cell_plan, word_count))
            self.notification_service.notify_start(sum(entry[3] for entry in type_queue))

            # Give the user time to focus the target before sending any keys.
            if self._wait_for_start():
                return

            # ── Execute live: Tab through cells, type items into empty ones ──
            simulator = self._activate_simulator()
            engine = TypingEngine(self._settings, profile=self._profile)

            self._typing_start_time = time.time()
            self._total_chars = sum(self._count_typed_chars(entry[2].actions) for entry in type_queue)
            self._chars_typed = 0
            chars_per_sec = ((self._settings.wpm or 60) * 5.0) / 60.0
            self._estimated_total_time = (self._total_chars / chars_per_sec) * 1.4
            if self.on_progress:
                try:
                    self.on_progress(0, self._total_chars, self._typing_start_time, self._estimated_total_time)
                except Exception:
                    logger.debug("Progress callback failed", exc_info=True)
            # Keep original indices so row boundaries and unfinished items survive.
            queue_index = 0
            is_first_cell = True
            row_skip_applied = False
            max_cells = len(type_queue) + 20  # safety limit to avoid infinite loop

            cells_visited = 0
            while queue_index < len(type_queue) and cells_visited < max_cells:
                if self._cancel_event.is_set() or not simulator.is_active:
                    return

                cells_visited += 1

                entry, original_index, cell_plan, word_count = type_queue[queue_index]
                # A blank-line row separator means the next ordinary TAB crosses
                # the row boundary, followed by the configured label columns.
                has_row_break = any(item.text == _ROW_BREAK for item in items[consumed_items:original_index])
                tabs = 0 if is_first_cell else 1
                if has_row_break and not row_skip_applied:
                    tabs += max(0, int(skip_columns))
                    row_skip_applied = True
                for _ in range(tabs):
                    if self._cancel_event.is_set() or not simulator.is_active:
                        return
                    simulator.press_key("tab")
                    simulator.wait(0.5)
                is_first_cell = False

                # Check if this cell already has content
                if self._cell_has_content(simulator):
                    logger.info("Cell already has content — skipping cell (keeping item %d)", queue_index)
                    skipped_count += 1
                    simulator.press_key("right")
                    simulator.wait(0.1)
                    # DON'T advance queue_index — save this item for the next empty cell
                    continue

                # Cell is empty — execute its prepared plan without resetting
                # the complete session's character counters or elapsed time.
                engine.reset_word_context()
                self._execute_plan(cell_plan, engine, simulator)
                if self._cancel_event.is_set() or not simulator.is_active:
                    return
                total_word_count += word_count
                queue_index += 1
                consumed_items = original_index + 1
                row_skip_applied = False
                cell_count += 1

            if self._cancel_event.is_set():
                logger.info("Table fill cancelled")
                return

            if queue_index < len(type_queue):
                incomplete = True
                self.notification_service.notify_error(
                    "Table fill stopped at its cell safety limit; remaining items are queued."
                )
                return

            consumed_items = len(items)
            self._current_word_count = total_word_count
            elapsed = time.time() - self._typing_start_time
            self.notification_service.notify_complete(self._current_word_count, elapsed)
            logger.info(
                "Table fill complete: %d cells typed, %d skipped, %d words in %.1f seconds",
                cell_count, skipped_count, self._current_word_count, elapsed,
            )

        except PlanningCancelled:
            logger.info("Table fill planning cancelled")
        except Exception as e:
            logger.exception("Error in table fill pipeline")
            self.notification_service.notify_error(str(e))
        finally:
            self._simulator = None
            remaining = items[consumed_items:]
            with self._table_queue_lock:
                # Prepend unfinished work ahead of any newly queued cells.
                self._table_queue[0:0] = remaining
                count = sum(item.text != _ROW_BREAK for item in self._table_queue)
            self._notify_table_queue_change(count)
            if remaining and not incomplete:
                logger.warning("Table fill incomplete: %d items remain; the current cell may be partially typed", count)
            if self.state != OrchestratorState.IDLE:
                self.state = OrchestratorState.IDLE

    @staticmethod
    def _resolve_api_key(settings_dict: dict) -> str:
        """Use current UI settings before environment (including loaded .env)."""
        return settings_dict.get("anthropic_api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "").strip()

    def update_settings(self, settings_dict: dict) -> None:
        """Apply settings between sessions so active plans retain their context."""
        with self._session_lock:
            worker = self._typing_thread
            if self.state != OrchestratorState.IDLE or (worker and worker.is_alive()):
                # Own a copy: UI dictionaries may be edited again while a plan
                # or a paused simulator still relies on the current settings.
                self._pending_settings = dict(settings_dict)
                logger.info("Settings saved for the next typing session")
                return
            self._apply_settings(dict(settings_dict))
            self._pending_settings = None

    def _apply_settings(self, settings_dict: dict) -> None:
        """Replace components only while the session lock excludes a launch."""
        self._settings_dict = settings_dict
        self._settings = self._build_settings(settings_dict)

        # Update all component settings
        self.clipboard_monitor.start_delay = settings_dict.get("start_delay", 3.0)
        self.notification_service.update_settings(
            webhook_url=settings_dict.get("webhook_url") or None,
            sound_enabled=settings_dict.get("sound_enabled", True),
        )
        self.visual_verifier.enabled = settings_dict.get("verify_after_typing", False)

        # Rebuild every planning component even offline: rates and cleared keys
        # must take effect without retaining a previous session's paid client.
        ai_enabled = settings_dict.get("ai_enabled", True)
        new_key = self._resolve_api_key(settings_dict)
        self.ai_planner = AIPlanner(self._settings, api_key=new_key, enabled=ai_enabled)
        self.ai_rewriter = AIRewriter(api_key=new_key, enabled=ai_enabled)
        self.ai_profile_generator = AIProfileGenerator(self._settings, api_key=new_key, enabled=ai_enabled)
        self.fallback_planner = TypingPlanner(
            self._settings, ai_rewriter=self.ai_rewriter, ai_enabled=ai_enabled, api_key=new_key,
        )

        logger.info("Settings updated")

    def _on_clipboard_change(self, content: ClipboardContent) -> bool:
        """Callback from clipboard monitor when new content is detected."""
        # Table fill mode: queue instead of typing
        if self._table_fill_mode:
            self._add_to_table_queue(content)
            return True

        return self._launch_pipeline(self._typing_pipeline, (content,), "TypingPipeline")

    def _launch_pipeline(self, target, args: tuple, name: str) -> bool:
        """Reserve a session atomically; a live previous worker retains ownership."""
        with self._session_lock:
            if getattr(self, "_sessions_disabled", False):
                logger.info("Ignoring launch while Ghost Typer is disabled")
                return False
            worker = self._typing_thread
            if (worker and worker.is_alive()) or self.state != OrchestratorState.IDLE:
                logger.info("Ignoring launch while a previous session is active")
                return False
            pending = getattr(self, "_pending_settings", None)
            if pending is not None:
                self._apply_settings(pending)
                self._pending_settings = None
            self._cancel_event.clear()
            self.state = OrchestratorState.PLANNING
            try:
                worker = threading.Thread(target=target, args=args, daemon=True, name=name)
                self._typing_thread = worker
                worker.start()
            except Exception:
                logger.exception("Failed to start typing thread")
                self._typing_thread = None
                self.state = OrchestratorState.IDLE
                return False
            return True

    def _typing_pipeline(self, content: ClipboardContent) -> None:
        """Run the full AI-powered typing pipeline in a background thread."""
        try:
            if self._cancel_event.is_set():
                return
            # State already set to PLANNING in _on_clipboard_change
            self.notification_service.notify_planning()

            # ── Step 1: Parse content into segments ──
            segments = self.text_parser.parse(
                content.content,
                is_html=content.is_html,
            )
            if not segments:
                logger.warning("No segments parsed from clipboard content")
                self.state = OrchestratorState.IDLE
                return

            # Count words for stats
            self._current_word_count = sum(
                len(seg.text.split()) for seg in segments if seg.text.strip()
            )

            # Build the full intended text for verification later
            intended_text = "".join(seg.text for seg in segments)

            # Notify start
            self.notification_service.notify_start(self._current_word_count)

            # ── Step 1.5: Generate AI typing profile ──
            full_text = "".join(seg.text for seg in segments)
            self._profile, self._behavioral_content = self._generate_session_behaviors(full_text)
            if self._cancel_event.is_set():
                return

            # ── Step 2: Build typing plan ──
            # Always use rule-based planner — it handles rewrites, human errors,
            # and misspellings reliably. AI planner is available but its rewrite
            # generation is inconsistent.
            logger.info("Using rule-based planner")
            self.fallback_planner.profile = self._profile
            plan = self.fallback_planner.plan(segments, behavioral_content=self._behavioral_content,
                                              cancelled=self._cancel_event.is_set)

            if self._cancel_event.is_set():
                return

            # ── Step 3: Execute the plan ──
            if self._wait_for_start():
                return
            simulator = self._activate_simulator()
            engine = TypingEngine(self._settings, profile=self._profile)

            # Count ALL characters that will actually be typed (including
            # drafts in rewrites, corrections in mistakes, proofreading fixes)
            self._total_chars = self._count_typed_chars(plan.actions)
            self._chars_typed = 0
            self._typing_start_time = time.time()

            # Calculate upfront ETA so the user knows immediately how long it'll take.
            # Average word = 5 chars; WPM → chars per second, plus overhead for
            # pauses, mistakes, rewrites (~40% overhead).
            wpm = self._settings.wpm or 60
            chars_per_sec = (wpm * 5.0) / 60.0
            self._estimated_total_time = (self._total_chars / chars_per_sec) * 1.4

            # Send initial progress so overlay shows ETA from the start
            progress_cb = self.on_progress
            if progress_cb:
                try:
                    progress_cb(0, self._total_chars, self._typing_start_time, self._estimated_total_time)
                except Exception:
                    pass

            self._execute_plan(plan, engine, simulator)

            if self._cancel_event.is_set():
                logger.info("Typing pipeline cancelled")
                return

            # ── Step 4: Visual verification (optional) ──
            if self.visual_verifier.enabled:
                self.state = OrchestratorState.VERIFYING
                logger.info("Running visual verification...")
                result = self.visual_verifier.verify(intended_text, cancel_event=self._cancel_event)
                if self._cancel_event.is_set():
                    return
                logger.info("Verification: %s", result)
                if not result.success:
                    self.notification_service.notify_error(
                        f"Verification: {result.message}"
                    )

            # ── Step 5: Notify completion ──
            if self._cancel_event.is_set():
                logger.info("Typing pipeline cancelled")
                return

            elapsed = time.time() - self._typing_start_time
            ai_tag = " (AI-planned)" if plan.metadata.get("ai_generated") else ""
            self.notification_service.notify_complete(self._current_word_count, elapsed)
            logger.info(
                "Typing complete%s: %d words in %.1f seconds",
                ai_tag,
                self._current_word_count,
                elapsed,
            )

        except PlanningCancelled:
            logger.info("Typing planning cancelled")
        except Exception as e:
            logger.exception("Error in typing pipeline")
            self.notification_service.notify_error(str(e))
        finally:
            self._simulator = None
            if self.state != OrchestratorState.IDLE:
                self.state = OrchestratorState.IDLE

    def _generate_session_behaviors(self, text: str) -> tuple[TypingProfile, dict]:
        """Fall back independently on failure and release cancelled sessions promptly.

        At most two calls stay in flight, including calls abandoned by a cancelled
        session. Their late results never mutate a subsequent session's profile.
        """
        from concurrent.futures import ThreadPoolExecutor

        generator = self.ai_profile_generator
        defaults = (deepcopy(self._baseline_profile), {})
        if (not generator.is_enabled or self._cancel_event.is_set()
                or any(not future.done() for future in self._profile_futures)):
            return defaults
        if self._profile_executor is None:
            self._profile_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Profile")
        started = time.monotonic()
        profile = self._profile_executor.submit(generator.generate_profile, text)
        behavior = self._profile_executor.submit(generator.generate_behavioral_content, text)
        self._profile_futures = {profile, behavior}
        pending = {profile: (0, 35.0), behavior: (1, 50.0)}
        results = list(defaults)
        try:
            while pending and not self._cancel_event.is_set():
                elapsed = time.monotonic() - started
                for future, (index, limit) in list(pending.items()):
                    if future.done():
                        try:
                            value = future.result()
                            if isinstance(value, TypingProfile if index == 0 else dict):
                                results[index] = value
                        except Exception:
                            logger.warning("AI session behavior failed; using defaults", exc_info=True)
                        del pending[future]
                    elif elapsed >= limit:
                        future.cancel()
                        del pending[future]
                        logger.warning("AI session behavior timed out; using defaults")
                if pending:
                    self._cancel_event.wait(0.05)
        finally:
            for future in pending:
                future.cancel()
        return tuple(results)

    def _wait_for_start(self) -> bool:
        """Wait the configured focus delay; True means the session was cancelled."""
        delay = max(0.0, float(self.clipboard_monitor.start_delay))
        return self._cancel_event.wait(delay)

    def _execute_plan(
        self, plan: TypingPlan, engine: TypingEngine, simulator: KeystrokeSimulator
    ) -> None:
        """Execute a TypingPlan action-by-action using the engine for timing and simulator for keystrokes."""
        prev_char = ""

        for action in plan.actions:
            if self._cancel_event.is_set() or not simulator.is_active:
                return

            if isinstance(action, TypeText):
                prev_char = self._execute_type_text(action, engine, simulator, prev_char)

            elif isinstance(action, ApplyFormatting):
                p = self._profile
                simulator.hotkey(*action.shortcut)
                if action.shortcut[-1] in ("left", "right", "up", "down", "home", "end"):
                    engine.reset_word_context()
                    prev_char = ""
                # Navigation hotkeys (word jump) are faster than formatting toggles
                if action.shortcut[-1] in ("left", "right"):
                    simulator.wait(engine._rng.uniform(
                        p.orchestration.navigation_hotkey_pause.min,
                        p.orchestration.navigation_hotkey_pause.max,
                    ))
                else:
                    simulator.wait(p.orchestration.formatting_hotkey_pause)

            elif isinstance(action, Pause):
                self._execute_pause(action.duration, engine, simulator)

            elif isinstance(action, MakeMistake):
                prev_char = self._execute_mistake(action, engine, simulator, prev_char)

            elif isinstance(action, Rewrite):
                prev_char = self._execute_rewrite(action, engine, simulator)

            elif isinstance(action, PressKey):
                prev_char = self._execute_press_key(action, engine, simulator, prev_char)

            elif isinstance(action, DistractionPause):
                self._execute_pause(action.duration, engine, simulator)

            elif isinstance(action, AbandonWord):
                prev_char = self._execute_abandon_word(action, engine, simulator, prev_char)

    def _execute_pause(self, duration: float, engine: TypingEngine, simulator: KeystrokeSimulator) -> None:
        """Apply rest to runtime timing state after a completed planned pause."""
        simulator.wait(duration)
        if not self._cancel_event.is_set() and simulator.is_active:
            engine.on_pause()
            engine.recover_fatigue_during_pause(duration)

    def _execute_type_text(
        self, action: TypeText, engine: TypingEngine, simulator: KeystrokeSimulator, prev_char: str
    ) -> str:
        """Type text character by character with realistic delays."""
        for char in action.text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char

            # Peek pause: peeker looks up at screen periodically to check output
            if engine.should_peek_pause():
                simulator.wait(engine.peek_pause_duration())
                engine.on_peek()

            delay = engine.delay_for_keystroke(char, prev_char) / action.speed_multiplier
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char

            self._record_typed_character()

        return prev_char

    def _execute_mistake(
        self, action: MakeMistake, engine: TypingEngine, simulator: KeystrokeSimulator, prev_char: str
    ) -> str:
        """Execute a mistake: type wrong text, pause, backspace, type correct text."""
        is_quick = len(action.wrong_text) <= 2  # quick reflex correction
        preceding_char = prev_char

        # Type the wrong text
        for char in action.wrong_text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char
            self._record_typed_character()

        # Pause as if noticing the mistake
        p = self._profile
        if is_quick:
            simulator.wait(engine._rng.uniform(
                p.correction.quick_correction_pause.min,
                p.correction.quick_correction_pause.max,
            ))
        else:
            simulator.wait(engine.correction_pause_duration())

        # Backspace to delete the wrong text
        for i in range(len(action.wrong_text)):
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            if is_quick:
                simulator.wait(engine._rng.uniform(
                    p.correction.quick_backspace_delay.min,
                    p.correction.quick_backspace_delay.max,
                ))
            else:
                simulator.wait(engine.backspace_delay(nth_backspace=i))
            simulator.press_key("backspace")
            engine.on_backspace()

        # Brief pause before retyping
        if is_quick:
            simulator.wait(engine._rng.uniform(
                p.correction.quick_pre_retype_pause.min,
                p.correction.quick_pre_retype_pause.max,
            ))
        else:
            simulator.wait(engine.correction_pause_duration() * 0.5)

        # Type the correct text from the context before the deleted mistake.
        prev_char = preceding_char
        engine.on_error_corrected()
        for char in action.correct_text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            if is_quick:
                simulator.wait(engine._rng.uniform(
                    p.correction.quick_retype_delay.min,
                    p.correction.quick_retype_delay.max,
                ))
            else:
                delay = engine.delay_for_keystroke(char, prev_char)
                simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char
            self._record_typed_character()

        return prev_char

    def _execute_rewrite(
        self, action: Rewrite, engine: TypingEngine, simulator: KeystrokeSimulator
    ) -> str:
        """Execute a rewrite: backspace delete_count chars, then execute new_actions.

        Returns the last character typed (for prev_char tracking).
        """
        # Pause as if reconsidering
        simulator.wait(engine.correction_pause_duration())

        # Delete back (accelerating)
        for i in range(action.delete_count):
            if self._cancel_event.is_set() or not simulator.is_active:
                return ""
            simulator.wait(engine.backspace_delay(nth_backspace=i))
            simulator.press_key("backspace")
            engine.on_backspace()

        # Small pause before retyping
        simulator.wait(engine.correction_pause_duration() * 0.3)

        # Execute new_actions (which may contain nested Rewrites)
        prev_char = engine.previous_visible_char
        for sub_action in action.new_actions:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            prev_char = self._execute_action(sub_action, engine, simulator, prev_char)

        return prev_char

    def _execute_action(
        self, action: TypingAction, engine: TypingEngine,
        simulator: KeystrokeSimulator, prev_char: str,
    ) -> str:
        """Execute a single action and return the last character typed."""
        if isinstance(action, TypeText):
            return self._execute_type_text(action, engine, simulator, prev_char)
        elif isinstance(action, Rewrite):
            return self._execute_rewrite(action, engine, simulator)
        elif isinstance(action, Pause):
            self._execute_pause(action.duration, engine, simulator)
            return prev_char
        elif isinstance(action, MakeMistake):
            return self._execute_mistake(action, engine, simulator, prev_char)
        elif isinstance(action, ApplyFormatting):
            p = self._profile
            simulator.hotkey(*action.shortcut)
            if action.shortcut[-1] in ("left", "right", "up", "down", "home", "end"):
                engine.reset_word_context()
                prev_char = ""
            if action.shortcut[-1] in ("left", "right"):
                simulator.wait(engine._rng.uniform(
                    p.orchestration.navigation_hotkey_pause.min,
                    p.orchestration.navigation_hotkey_pause.max,
                ))
            else:
                simulator.wait(p.orchestration.formatting_hotkey_pause)
            return prev_char
        elif isinstance(action, PressKey):
            return self._execute_press_key(action, engine, simulator, prev_char)
        elif isinstance(action, DistractionPause):
            self._execute_pause(action.duration, engine, simulator)
            return prev_char
        elif isinstance(action, AbandonWord):
            return self._execute_abandon_word(action, engine, simulator, prev_char)
        return prev_char

    def _execute_press_key(self, action: PressKey, engine: TypingEngine,
                           simulator: KeystrokeSimulator, prev_char: str) -> str:
        """Keep word timing in sync with structural keys in every action list."""
        p = self._profile
        structural = {"enter": "\n", "return": "\n", "tab": "\t", "space": " "}
        char = structural.get(action.key)
        if char is not None:
            simulator.wait(engine.delay_for_keystroke(char, prev_char))
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            simulator.press_key(action.key)
            engine.on_char_typed(char)
            return ""
        simulator.press_key(action.key)
        if action.key == "backspace":
            engine.on_backspace()
            return engine.previous_visible_char
        if action.key in ("left", "right", "up", "down", "home", "end"):
            engine.reset_word_context()
            prev_char = ""
        if action.key in ("left", "right", "up", "down"):
            simulator.wait(engine._rng.uniform(
                p.orchestration.arrow_key_pause.min,
                p.orchestration.arrow_key_pause.max,
            ))
        return prev_char

    def _execute_abandon_word(
        self, action: AbandonWord, engine: TypingEngine,
        simulator: KeystrokeSimulator, prev_char: str,
    ) -> str:
        """Type partial word, pause, delete it, type replacement."""
        # Type partial word
        for char in action.partial_text:
            if self._cancel_event.is_set():
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char
            self._record_typed_character()

        # Pause (reconsidering)
        p = self._profile
        simulator.wait(engine._rng.uniform(
            p.behaviors.abandonment.pause_before_delete.min,
            p.behaviors.abandonment.pause_before_delete.max,
        ))

        # Backspace
        for i in range(len(action.partial_text)):
            if self._cancel_event.is_set():
                return prev_char
            simulator.wait(engine.backspace_delay(nth_backspace=i))
            simulator.press_key("backspace")
            engine.on_backspace()

        # Brief pause before replacement
        simulator.wait(engine._rng.uniform(
            p.behaviors.abandonment.pause_before_replacement.min,
            p.behaviors.abandonment.pause_before_replacement.max,
        ))

        # Type replacement
        prev_char = engine.previous_visible_char
        for char in action.replacement_text:
            if self._cancel_event.is_set():
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char
            self._record_typed_character()

        return prev_char

    def _record_typed_character(self) -> None:
        """Report every emitted text path, including corrections and short tails."""
        self._chars_typed += 1
        progress_cb = getattr(self, "on_progress", None)
        if (progress_cb and not self._cancel_event.is_set()
                and (self._chars_typed % self._profile.orchestration.progress_report_frequency == 0
                     or self._chars_typed == self._total_chars)):
            try:
                progress_cb(self._chars_typed, self._total_chars, self._typing_start_time)
            except Exception:
                logger.debug("Progress callback failed", exc_info=True)

    def _count_typed_chars(self, actions: list) -> int:
        """Recursively count all characters that will be typed in a list of actions."""
        total = 0
        for a in actions:
            if isinstance(a, TypeText):
                total += len(a.text)
            elif isinstance(a, MakeMistake):
                total += len(a.wrong_text) + len(a.correct_text)
            elif isinstance(a, Rewrite):
                total += self._count_typed_chars(a.new_actions)
            elif isinstance(a, AbandonWord):
                total += len(a.partial_text) + len(a.replacement_text)
            elif isinstance(a, DistractionPause):
                pass  # No characters typed
        return total

    @staticmethod
    def _build_settings(d: dict) -> Settings:
        """Construct a Settings object from a plain dict, ignoring unknown keys."""
        return Settings.from_dict(d)
