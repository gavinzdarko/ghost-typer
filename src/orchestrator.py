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

from .ai_planner import AIPlanner, AIRewriter
from .clipboard_monitor import ClipboardContent, ClipboardMonitor
from .models import (
    ApplyFormatting,
    MakeMistake,
    Pause,
    PressKey,
    Rewrite,
    Settings,
    TextSegment,
    TypeText,
    TypingAction,
    TypingPlan,
)
from .keystroke_simulator import KeystrokeSimulator
from .notification_service import NotificationService
from .settings_ui import DEFAULTS, load_settings_dict, save_settings_dict
from .text_parser import TextParser
from .typing_engine import TypingEngine
from .typing_planner import TypingPlanner
from .visual_verifier import VisualVerifier

logger = logging.getLogger(__name__)


class OrchestratorState(Enum):
    IDLE = auto()
    PLANNING = auto()
    TYPING = auto()
    VERIFYING = auto()
    PAUSED = auto()


class Orchestrator:
    """Ties together all Ghost Typer components with AI-powered planning."""

    def __init__(self) -> None:
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

        # AI components
        self.ai_planner = AIPlanner(self._settings)
        self.ai_rewriter = AIRewriter()
        self.visual_verifier = VisualVerifier(
            enabled=self._settings_dict.get("verify_after_typing", False),
        )

        # Fallback planner (rule-based)
        self.fallback_planner = TypingPlanner(self._settings)

        # Typing state
        self._state = OrchestratorState.IDLE
        self._state_lock = threading.Lock()
        self._typing_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._simulator: Optional[KeystrokeSimulator] = None

        # Stats
        self._current_word_count = 0
        self._typing_start_time = 0.0

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
            # Clear progress callback first so the dying thread can't enqueue
            # more GUI work after we start tearing down
            self.on_progress = None
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
        logger.info("Settings updated")

    def _on_clipboard_change(self, content: ClipboardContent) -> None:
        """Callback from clipboard monitor when new content is detected."""
        # Wait for any previous thread to finish before starting a new one
        old_thread = self._typing_thread
        if old_thread and old_thread.is_alive():
            old_thread.join(timeout=5.0)

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
            self._typing_start_time = time.time()

            # ── Step 2: Build typing plan (AI-powered or rule-based fallback) ──
            use_ai = self._settings_dict.get("ai_enabled", True)
            if use_ai and self.ai_planner.is_enabled:
                logger.info("Generating AI typing plan for %d words...", self._current_word_count)
                plan = self.ai_planner.plan(segments)
                if plan.metadata.get("ai_generated"):
                    logger.info(
                        "AI plan ready: %d actions, strategy: %s",
                        len(plan),
                        plan.metadata.get("strategy", "N/A"),
                    )
                else:
                    logger.info("Fell back to rule-based plan: %d actions", len(plan))
            else:
                logger.info("Using rule-based planner")
                plan = self.fallback_planner.plan(segments)

            if self._cancel_event.is_set():
                return

            # ── Step 3: Execute the plan ──
            self.state = OrchestratorState.TYPING
            simulator = KeystrokeSimulator()
            self._simulator = simulator
            engine = TypingEngine(self._settings)

            self._total_chars = plan.total_characters
            self._chars_typed = 0
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
                simulator.hotkey(*action.shortcut)
                simulator.wait(0.1)

            elif isinstance(action, Pause):
                simulator.wait(action.duration)

            elif isinstance(action, MakeMistake):
                prev_char = self._execute_mistake(action, engine, simulator, prev_char)

            elif isinstance(action, Rewrite):
                self._execute_rewrite(action, engine, simulator)
                prev_char = action.new_text[-1] if action.new_text else prev_char

            elif isinstance(action, PressKey):
                simulator.press_key(action.key)
                delay = engine.delay_for_keystroke("\n", prev_char)
                simulator.wait(delay)
                prev_char = ""

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

            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char

            # Report progress every few characters
            self._chars_typed += 1
            progress_cb = self.on_progress  # snapshot to avoid TOCTOU
            if self._chars_typed % 5 == 0 and progress_cb:
                try:
                    progress_cb(self._chars_typed, self._total_chars)
                except Exception:
                    pass

        return prev_char

    def _execute_mistake(
        self, action: MakeMistake, engine: TypingEngine, simulator: KeystrokeSimulator, prev_char: str
    ) -> str:
        """Execute a mistake: type wrong text, pause, backspace, type correct text."""
        # Type the wrong text
        for char in action.wrong_text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            prev_char = char

        # Pause as if noticing the mistake
        correction_pause = engine.correction_pause_duration()
        simulator.wait(correction_pause)

        # Backspace to delete the wrong text (accelerating)
        for i in range(len(action.wrong_text)):
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            simulator.wait(engine.backspace_delay(nth_backspace=i))
            simulator.press_key("backspace")

        # Small pause before retyping
        simulator.wait(engine.correction_pause_duration() * 0.5)

        # Type the correct text (with post-error slowdown)
        engine.on_error_corrected()
        for char in action.correct_text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return prev_char
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char

        return prev_char

    def _execute_rewrite(
        self, action: Rewrite, engine: TypingEngine, simulator: KeystrokeSimulator
    ) -> None:
        """Execute a rewrite: backspace delete_count chars, then type new_text."""
        # Pause as if reconsidering
        simulator.wait(engine.correction_pause_duration())

        # Delete back (accelerating)
        for i in range(action.delete_count):
            if self._cancel_event.is_set() or not simulator.is_active:
                return
            simulator.wait(engine.backspace_delay(nth_backspace=i))
            simulator.press_key("backspace")

        # Small pause before retyping
        simulator.wait(engine.correction_pause_duration() * 0.3)

        # Retype
        prev_char = ""
        for char in action.new_text:
            if self._cancel_event.is_set() or not simulator.is_active:
                return
            delay = engine.delay_for_keystroke(char, prev_char)
            simulator.wait(delay)
            simulator.type_char(char)
            engine.on_char_typed(char)
            prev_char = char

    @staticmethod
    def _build_settings(d: dict) -> Settings:
        """Construct a Settings object from a plain dict, ignoring unknown keys."""
        return Settings.from_dict(d)
