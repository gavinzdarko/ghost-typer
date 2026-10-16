"""
Main controller that connects clipboard monitoring, text parsing, AI planner,
typing engine, visual verification, and notifications.

This is the brain of Ghost Typer — it orchestrates the full pipeline:
clipboard → parse → AI plan → type → verify → notify
"""

from __future__ import annotations

import logging
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
from .typing_planner import TypingPlanner
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
        from .settings_ui import get_api_key
        _api_key = get_api_key() or None
        self.ai_planner = AIPlanner(self._settings, api_key=_api_key)
        self.ai_rewriter = AIRewriter(api_key=_api_key)
        self.ai_profile_generator = AIProfileGenerator(self._settings, api_key=_api_key)
        self.visual_verifier = VisualVerifier(
            enabled=self._settings_dict.get("verify_after_typing", False),
        )

        # Fallback planner (rule-based, with AI rewriter for drafts)
        self.fallback_planner = TypingPlanner(self._settings, ai_rewriter=self.ai_rewriter)

        # Typing state
        self._state = OrchestratorState.IDLE
        self._state_lock = threading.Lock()
        self._typing_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._simulator: Optional[KeystrokeSimulator] = None

        # Behavioral content (AI-generated, or empty dict)
        self._behavioral_content: dict = {}

        # Stats
        self._current_word_count = 0
        self._typing_start_time = 0.0
        self._total_chars = 0
        self._chars_typed = 0

        # Table fill mode
        self._table_fill_mode = False
        self._table_queue: list[ClipboardContent] = []
        self._table_queue_lock = threading.Lock()
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

    @state.setter
    def state(self, new_state: OrchestratorState) -> None:
        with self._state_lock:
            old = self._state
            self._state = new_state
        logger.info("State: %s -> %s", old.name, new_state.name)
        cb = self.on_state_change  # snapshot to avoid TOCTOU
        if cb:
            try:
                cb(new_state)
            except Exception:
                logger.exception("Error in state change callback")

    def start(self) -> None:
        """Start the orchestrator and clipboard monitor."""
        self.clipboard_monitor.start()
        logger.info("Orchestrator started")

    def stop(self) -> None:
        """Shut down everything gracefully."""
        self.cancel()
        self.clipboard_monitor.stop()
        logger.info("Orchestrator stopped")

    def enable(self) -> None:
        """Enable clipboard monitoring (app ON)."""
        self.clipboard_monitor.enabled = True
        logger.info("Ghost Typer enabled")

    def disable(self, blocking: bool = True) -> None:
        """Disable clipboard monitoring (app OFF)."""
        self.clipboard_monitor.enabled = False
        self.cancel(blocking=blocking)
        logger.info("Ghost Typer disabled")

    @property
    def is_enabled(self) -> bool:
        return self.clipboard_monitor.enabled

    def pause(self) -> None:
        """Pause the current typing session."""
        if self.state == OrchestratorState.TYPING:
            sim = self._simulator  # snapshot to avoid TOCTOU
            if sim:
                sim.pause()
            self.state = OrchestratorState.PAUSED
            self.notification_service.notify_paused()

    def resume(self) -> None:
        """Resume a paused typing session."""
        if self.state == OrchestratorState.PAUSED:
            sim = self._simulator  # snapshot to avoid TOCTOU
            if sim:
                sim.resume()
            self.state = OrchestratorState.TYPING
            self.notification_service.notify_resumed()

    def cancel(self, blocking: bool = True) -> None:
        """Cancel the current typing session.

        Args:
            blocking: If True, wait for the typing thread to finish.
                      Set to False when calling from the main/GUI thread
                      to avoid blocking the AppKit event loop.
        """
        if self.state in (OrchestratorState.TYPING, OrchestratorState.PAUSED, OrchestratorState.PLANNING):
            self._cancel_event.set()
            sim = self._simulator
            if sim:
                sim.resume()  # unblock if paused so thread can exit
                sim.stop()    # blocks until any in-flight CGEvent call finishes
            if blocking and self._typing_thread:
                self._typing_thread.join(timeout=5.0)
                self._typing_thread = None
            # Only force IDLE when blocking (thread is dead). When non-blocking,
            # let the thread's finally block set IDLE to avoid two concurrent
            # typing threads (new clipboard event sees IDLE, starts new thread
            # while old one is still winding down).
            if blocking:
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
        with self._table_queue_lock:
            self._table_queue.clear()
        self._table_fill_mode = True
        self.clipboard_monitor._immediate_mode = True
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

    def run_table_fill(self, skip_columns: int = 1) -> None:
        """Execute all queued table items — type each one, TAB between them.

        Args:
            skip_columns: Number of pre-filled columns to skip at the start
                          of each new row (e.g. 1 if column A has labels).
        """
        with self._table_queue_lock:
            items = list(self._table_queue)
            self._table_queue.clear()

        if not items:
            logger.warning("Table fill: nothing in queue")
            return

        self._table_fill_mode = False
        self.clipboard_monitor._immediate_mode = False

        with self._state_lock:
            if self._state != OrchestratorState.IDLE:
                logger.info("Can't run table fill — currently %s", self._state.name)
                return
            self._state = OrchestratorState.PLANNING

        self._cancel_event.clear()
        logger.info("Running table fill with %d items", len(items))

        cb = self.on_state_change
        if cb:
            try:
                cb(OrchestratorState.PLANNING)
            except Exception:
                logger.exception("Error in state change callback")

        try:
            self._typing_thread = threading.Thread(
                target=self._table_fill_pipeline,
                args=(items, skip_columns),
                daemon=True,
                name="TableFillPipeline",
            )
            self._typing_thread.start()
        except Exception:
            logger.exception("Failed to start table fill thread")
            self.state = OrchestratorState.IDLE

    _CLIPBOARD_SENTINEL = "\x00__GHOST_TYPER_EMPTY__"

    def _cell_has_content(self, simulator: KeystrokeSimulator) -> bool:
        """Check if the current cell has content by copying and reading clipboard.

        Tab in Google Docs selects cell content automatically.
        We set a sentinel on the clipboard, then Cmd+C. If clipboard
        changes from the sentinel, the cell had content.
        """
        import AppKit
        pb = AppKit.NSPasteboard.generalPasteboard()

        # Pause clipboard monitor so it doesn't interfere
        old_enabled = self.clipboard_monitor.enabled
        self.clipboard_monitor.enabled = False

        # Set sentinel
        pb.clearContents()
        pb.setString_forType_(self._CLIPBOARD_SENTINEL, AppKit.NSPasteboardTypeString)
        time.sleep(0.05)

        # Select all text in the cell: Home then Shift+End
        simulator.press_key("home")
        time.sleep(0.1)
        simulator.hotkey("shift", "end")
        time.sleep(0.15)

        # Copy whatever is selected
        simulator.hotkey("command", "c")
        time.sleep(0.35)

        # Read back
        text = pb.stringForType_(AppKit.NSPasteboardTypeString) or ""
        has_content = text != self._CLIPBOARD_SENTINEL and len(text.strip()) > 0

        logger.info("Cell check: clipboard=%r, sentinel=%r, has_content=%s",
                     text[:50] if text else "", self._CLIPBOARD_SENTINEL[:20], has_content)

        # Restore clipboard monitor
        self.clipboard_monitor.enabled = old_enabled

        return has_content

        content = self._read_clipboard().strip()
        return len(content) > 0

    def _table_fill_pipeline(self, items: list[ClipboardContent], skip_columns: int = 1) -> None:
        """Type each queued item with TAB between them, auto-skipping filled cells."""
        try:
            # ── Separate items into cells and row breaks ──
            cell_items: list[ClipboardContent | None] = []  # None = row break
            for item in items:
                if item.text == _ROW_BREAK:
                    cell_items.append(None)
                else:
                    cell_items.append(item)

            total_word_count = 0
            cell_count = 0
            skipped_count = 0

            self._typing_start_time = time.time()
            self.notification_service.notify_start(0)

            # ── Execute live: Tab through cells, type items into empty ones ──
            self.state = OrchestratorState.TYPING
            simulator = KeystrokeSimulator()
            self._simulator = simulator
            engine = TypingEngine(self._settings, profile=self._profile)

            # Build a queue of items to type (skip row breaks for now)
            type_queue = [e for e in cell_items if e is not None]
            queue_index = 0
            is_first_cell = True
            max_cells = len(type_queue) + 20  # safety limit to avoid infinite loop

            cells_visited = 0
            while queue_index < len(type_queue) and cells_visited < max_cells:
                if self._cancel_event.is_set() or not simulator.is_active:
                    return

                cells_visited += 1

                # TAB to next cell (except the very first)
                if not is_first_cell:
                    simulator.press_key("tab")
                    time.sleep(0.5)
                is_first_cell = False

                # Check if this cell already has content
                if self._cell_has_content(simulator):
                    logger.info("Cell already has content — skipping cell (keeping item %d)", queue_index)
                    skipped_count += 1
                    simulator.press_key("right")
                    simulator.wait(0.1)
                    # DON'T advance queue_index — save this item for the next empty cell
                    continue

                # Cell is empty — type the next queued item into it
                entry = type_queue[queue_index]
                queue_index += 1

                segments = self.text_parser.parse(entry.content, is_html=entry.is_html)
                if segments and segments[0].text.strip():
                    cell_plan = self.fallback_planner.plan(segments, simple=True)

                    self._total_chars = self._count_typed_chars(cell_plan.actions)
                    self._chars_typed = 0
                    self._execute_plan(cell_plan, engine, simulator)

                    total_word_count += sum(
                        len(seg.text.split()) for seg in segments if seg.text.strip()
                    )
                cell_count += 1

            if self._cancel_event.is_set():
                logger.info("Table fill cancelled")
                return

            self._current_word_count = total_word_count
            elapsed = time.time() - self._typing_start_time
            self.notification_service.notify_complete(self._current_word_count, elapsed)
            logger.info(
                "Table fill complete: %d cells typed, %d skipped, %d words in %.1f seconds",
                cell_count, skipped_count, self._current_word_count, elapsed,
            )

        except Exception as e:
            logger.exception("Error in table fill pipeline")
            self.notification_service.notify_error(str(e))
        finally:
            self._simulator = None
            self._notify_table_queue_change(0)
            if self.state != OrchestratorState.IDLE:
                self.state = OrchestratorState.IDLE

    def update_settings(self, settings_dict: dict) -> None:
        """Apply new settings from the UI."""
        self._settings_dict = settings_dict
        self._settings = self._build_settings(settings_dict)

        # Update all component settings
        self.clipboard_monitor.start_delay = settings_dict.get("start_delay", 3.0)
        self.notification_service.update_settings(
            webhook_url=settings_dict.get("webhook_url") or None,
            sound_enabled=settings_dict.get("sound_enabled", True),
        )
        self.ai_planner.update_settings(self._settings)
        self.visual_verifier.enabled = settings_dict.get("verify_after_typing", False)

        # Re-init AI components if API key changed
        from .settings_ui import get_api_key
        new_key = get_api_key() or None
        if new_key:
            self.ai_planner = AIPlanner(self._settings, api_key=new_key)
            self.ai_rewriter = AIRewriter(api_key=new_key)
            self.ai_profile_generator = AIProfileGenerator(self._settings, api_key=new_key)
            self.fallback_planner = TypingPlanner(self._settings, ai_rewriter=self.ai_rewriter)

        logger.info("Settings updated")

    def _on_clipboard_change(self, content: ClipboardContent) -> None:
        """Callback from clipboard monitor when new content is detected."""
        # Table fill mode: queue instead of typing
        if self._table_fill_mode:
            self._add_to_table_queue(content)
            return

        # Wait for any previous thread to finish before starting a new one
        old_thread = self._typing_thread
        if old_thread and old_thread.is_alive():
            old_thread.join(timeout=5.0)

        # If cancel was requested, the thread may still be winding down.
        # Wait outside the lock to avoid unsafe release/acquire.
        if self._cancel_event.is_set() and old_thread and old_thread.is_alive():
            old_thread.join(timeout=3.0)

        with self._state_lock:
            if self._state != OrchestratorState.IDLE:
                logger.info("Ignoring clipboard change — currently %s", self._state.name)
                return
            self._state = OrchestratorState.PLANNING
        # Clear cancel event before starting new pipeline
        self._cancel_event.clear()

        logger.info("Processing clipboard content: %s", content)
        cb = self.on_state_change  # snapshot
        if cb:
            try:
                cb(OrchestratorState.PLANNING)
            except Exception:
                logger.exception("Error in state change callback")

        try:
            self._typing_thread = threading.Thread(
                target=self._typing_pipeline,
                args=(content,),
                daemon=True,
                name="TypingPipeline",
            )
            self._typing_thread.start()
        except Exception:
            logger.exception("Failed to start typing thread")
            self.state = OrchestratorState.IDLE

    def _typing_pipeline(self, content: ClipboardContent) -> None:
        """Run the full AI-powered typing pipeline in a background thread."""
        try:
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
            intended_text = " ".join(seg.text for seg in segments if seg.text.strip())

            # Notify start
            self.notification_service.notify_start(self._current_word_count)

            # ── Step 1.5: Generate AI typing profile ──
            full_text = "".join(seg.text for seg in segments)
            if self.ai_profile_generator.is_enabled:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    profile_future = pool.submit(
                        self.ai_profile_generator.generate_profile, full_text
                    )
                    behavioral_future = pool.submit(
                        self.ai_profile_generator.generate_behavioral_content, full_text
                    )
                    self._profile = profile_future.result(timeout=35)
                    self._behavioral_content = behavioral_future.result(timeout=50)
                logger.info("AI profile generated: %s", self._profile.persona_description)
            else:
                self._profile = TypingProfile.defaults()
                self._behavioral_content = {}

            if self._cancel_event.is_set():
                return

            # ── Step 2: Build typing plan ──
            # Always use rule-based planner — it handles rewrites, human errors,
            # and misspellings reliably. AI planner is available but its rewrite
            # generation is inconsistent.
            logger.info("Using rule-based planner")
            self.fallback_planner.profile = self._profile
            plan = self.fallback_planner.plan(segments, behavioral_content=self._behavioral_content)

            if self._cancel_event.is_set():
                return

            # ── Step 3: Execute the plan ──
            self.state = OrchestratorState.TYPING
            simulator = KeystrokeSimulator()
            self._simulator = simulator
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
                result = self.visual_verifier.verify(intended_text)
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

        except Exception as e:
            logger.exception("Error in typing pipeline")
            self.notification_service.notify_error(str(e))
        finally:
            self._simulator = None
            if self.state != OrchestratorState.IDLE:
                self.state = OrchestratorState.IDLE

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
                # Navigation hotkeys (word jump) are faster than formatting toggles
                if action.shortcut[-1] in ("left", "right"):
                    simulator.wait(engine._rng.uniform(
                        p.orchestration.navigation_hotkey_pause.min,
                        p.orchestration.navigation_hotkey_pause.max,
                    ))
                else:
                    simulator.wait(p.orchestration.formatting_hotkey_pause)

            elif isinstance(action, Pause):
                simulator.wait(action.duration)

            elif isinstance(action, MakeMistake):
                prev_char = self._execute_mistake(action, engine, simulator, prev_char)

            elif isinstance(action, Rewrite):
                prev_char = self._execute_rewrite(action, engine, simulator)

            elif isinstance(action, PressKey):
                p = self._profile
                simulator.press_key(action.key)
                if action.key in ("left", "right", "up", "down"):
                    # Arrow keys are pressed rapidly when navigating
                    simulator.wait(engine._rng.uniform(
                        p.orchestration.arrow_key_pause.min,
                        p.orchestration.arrow_key_pause.max,
                    ))
                else:
                    delay = engine.delay_for_keystroke("\n", prev_char)
                    simulator.wait(delay)
                    prev_char = ""

            elif isinstance(action, DistractionPause):
                simulator.wait(action.duration)
                engine.recover_fatigue_during_pause(action.duration)

            elif isinstance(action, AbandonWord):
                prev_char = self._execute_abandon_word(action, engine, simulator, prev_char)

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

            # Report progress every few characters
            self._chars_typed += 1
            p = self._profile
            progress_cb = self.on_progress  # snapshot to avoid TOCTOU
            if self._chars_typed % p.orchestration.progress_report_frequency == 0 and progress_cb and not self._cancel_event.is_set():
                try:
                    progress_cb(self._chars_typed, self._total_chars, self._typing_start_time)
                except Exception:
                    pass

        return prev_char

    def _execute_mistake(
        self, action: MakeMistake, engine: TypingEngine, simulator: KeystrokeSimulator, prev_char: str
    ) -> str:
        """Execute a mistake: type wrong text, pause, backspace, type correct text."""
        is_quick = len(action.wrong_text) <= 2  # quick reflex correction

        # Type the wrong text
        for char in action.wrong_text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char
            self._chars_typed += 1

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

        # Brief pause before retyping
        if is_quick:
            simulator.wait(engine._rng.uniform(
                p.correction.quick_pre_retype_pause.min,
                p.correction.quick_pre_retype_pause.max,
            ))
        else:
            simulator.wait(engine.correction_pause_duration() * 0.5)

        # Type the correct text
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
            self._chars_typed += 1

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

        # Small pause before retyping
        simulator.wait(engine.correction_pause_duration() * 0.3)

        # Execute new_actions (which may contain nested Rewrites)
        prev_char = ""
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
            simulator.wait(action.duration)
            return prev_char
        elif isinstance(action, MakeMistake):
            return self._execute_mistake(action, engine, simulator, prev_char)
        elif isinstance(action, ApplyFormatting):
            p = self._profile
            simulator.hotkey(*action.shortcut)
            if action.shortcut[-1] in ("left", "right"):
                simulator.wait(engine._rng.uniform(
                    p.orchestration.navigation_hotkey_pause.min,
                    p.orchestration.navigation_hotkey_pause.max,
                ))
            else:
                simulator.wait(p.orchestration.formatting_hotkey_pause)
            return prev_char
        elif isinstance(action, PressKey):
            p = self._profile
            simulator.press_key(action.key)
            if action.key in ("left", "right", "up", "down"):
                simulator.wait(engine._rng.uniform(
                    p.orchestration.arrow_key_pause.min,
                    p.orchestration.arrow_key_pause.max,
                ))
            else:
                delay = engine.delay_for_keystroke("\n", prev_char)
                simulator.wait(delay)
            return "" if action.key not in ("left", "right", "up", "down") else prev_char
        elif isinstance(action, DistractionPause):
            simulator.wait(action.duration)
            engine.recover_fatigue_during_pause(action.duration)
            return prev_char
        elif isinstance(action, AbandonWord):
            return self._execute_abandon_word(action, engine, simulator, prev_char)
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
            self._chars_typed += 1

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

        # Brief pause before replacement
        simulator.wait(engine._rng.uniform(
            p.behaviors.abandonment.pause_before_replacement.min,
            p.behaviors.abandonment.pause_before_replacement.max,
        ))

        # Type replacement
        for char in action.replacement_text:
            if self._cancel_event.is_set():
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char
            self._chars_typed += 1

        return prev_char

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
