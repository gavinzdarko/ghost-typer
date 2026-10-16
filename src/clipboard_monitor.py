"""
Background thread that watches the macOS clipboard for changes and triggers the typing pipeline.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Attempt AppKit import for native pasteboard access
try:
    from AppKit import NSPasteboard, NSPasteboardTypeHTML, NSPasteboardTypeString
except ImportError:
    NSPasteboard = None
    NSPasteboardTypeHTML = None
    NSPasteboardTypeString = None
    logger.warning("AppKit not available — clipboard HTML detection will be limited")


class ClipboardContent:
    """Holds clipboard content with metadata about its type."""

    def __init__(self, text: str, html: Optional[str] = None):
        self.text = text
        self.html = html

    @property
    def is_html(self) -> bool:
        return self.html is not None and len(self.html.strip()) > 0

    @property
    def content(self) -> str:
        """Return HTML if available, otherwise plain text."""
        return self.html if self.is_html else self.text

    def __repr__(self) -> str:
        kind = "HTML" if self.is_html else "Plain"
        preview = (self.text[:50] + "...") if len(self.text) > 50 else self.text
        return f"ClipboardContent({kind}, {preview!r})"


class ClipboardMonitor:
    """Monitors the macOS clipboard for changes in a background thread.

    Flow: Copy captures and clears clipboard. Cmd+V triggers typing (nothing pastes).
    """

    POLL_INTERVAL = 0.5  # seconds between clipboard checks

    def __init__(
        self,
        on_clipboard_change: Callable[[ClipboardContent], None],
        start_delay: float = 3.0,
    ):
        self._on_change = on_clipboard_change
        self.start_delay = start_delay
        self._enabled = False
        self._clipboard_lock = threading.RLock()
        self._suspensions = 0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_change_count: int = 0
        # Staged content: captured on copy, triggered on Cmd+V
        self._staged_content: Optional[ClipboardContent] = None
        self._staged_lock = threading.Lock()
        # Immediate mode: call on_change right away (for table fill mode)
        self._immediate_mode = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        logger.info("Clipboard monitor %s", "enabled" if value else "disabled")

    @contextmanager
    def suspended(self):
        """Serialize internal pasteboard transactions without changing user ON/OFF."""
        with self._clipboard_lock:
            self._suspensions += 1
            try:
                yield
            finally:
                self._suspensions -= 1

    def acknowledge_change(self, change_count: int) -> None:
        """Ignore a pasteboard revision written by an internal transaction."""
        with self._clipboard_lock:
            self._last_change_count = change_count

    def start(self) -> None:
        """Start the clipboard monitoring background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Clipboard monitor already running")
            return

        self._stop_event.clear()
        # Capture the current clipboard state so we don't trigger on existing content
        self._last_change_count = self._get_change_count()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="ClipboardMonitor")
        self._thread.start()
        logger.info("Clipboard monitor started")

    def stop(self) -> None:
        """Stop the clipboard monitoring thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Clipboard monitor stopped")

    def _monitor_loop(self) -> None:
        """Main loop that polls the clipboard for changes."""
        logger.debug("Clipboard monitor loop started")
        while not self._stop_event.is_set():
            try:
                with self._clipboard_lock:
                    if self._enabled and not self._suspensions:
                        current_count = self._get_change_count()
                        if current_count != self._last_change_count:
                            self._last_change_count = current_count
                            content = self._read_clipboard()
                            if content and content.text.strip():
                                logger.info("Clipboard captured: %s", content)
                                if self._immediate_mode:
                                    # Table fill mode: record and clear clipboard
                                    # so accidental Cmd+V won't paste (version history).
                                    self._clear_clipboard()
                                    self._last_change_count = self._get_change_count()
                                    try:
                                        self._on_change(content)
                                    except Exception:
                                        logger.exception("Error in clipboard change callback")
                                else:
                                    # Normal mode: stage and wait for Cmd+V
                                    with self._staged_lock:
                                        self._staged_content = content
                                    self._clear_clipboard()
                                    self._last_change_count = self._get_change_count()
                                    logger.info("Text staged — press Cmd+V to start typing")

            except Exception:
                logger.exception("Error in clipboard monitor loop")

            self._stop_event.wait(timeout=self.POLL_INTERVAL)

        logger.debug("Clipboard monitor loop exited")

    @staticmethod
    def _get_change_count() -> int:
        """Get the pasteboard change count (increments each time clipboard changes)."""
        if NSPasteboard is not None:
            pb = NSPasteboard.generalPasteboard()
            return pb.changeCount()
        # Fallback: no change tracking available
        return 0

    @staticmethod
    def _read_clipboard() -> Optional[ClipboardContent]:
        """Read the current clipboard content, extracting HTML if available."""
        if NSPasteboard is None:
            return None

        pb = NSPasteboard.generalPasteboard()

        # Try to get plain text
        plain_text = pb.stringForType_(NSPasteboardTypeString)
        if not plain_text:
            return None

        # Try to get HTML
        html_data = pb.stringForType_(NSPasteboardTypeHTML)

        return ClipboardContent(text=str(plain_text), html=str(html_data) if html_data else None)

    def trigger_paste(self) -> None:
        """Called when user presses Cmd+V — start typing the staged content."""
        if not self._enabled or self._suspensions:
            return
        with self._staged_lock:
            content = self._staged_content
            self._staged_content = None
        if content:
            logger.info("Cmd+V triggered — starting typing for: %s", content)
            try:
                self._on_change(content)
            except Exception:
                logger.exception("Error in clipboard change callback")
        else:
            logger.debug("Cmd+V pressed but no staged content")

    @staticmethod
    def _clear_clipboard() -> None:
        """Clear the clipboard so accidental Cmd+V won't paste duplicate text."""
        if NSPasteboard is None:
            return
        try:
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            logger.debug("Clipboard cleared after capture")
        except Exception:
            logger.exception("Failed to clear clipboard")
