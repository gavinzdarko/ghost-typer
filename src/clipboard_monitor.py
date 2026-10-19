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
    from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeHTML, NSPasteboardTypeString
except ImportError:
    NSPasteboard = None
    NSPasteboardItem = None
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
        on_clipboard_change: Callable[[ClipboardContent], bool | None],
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
        self._saved_clipboard_items = None
        self._owned_empty_revision: int | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._clipboard_lock:
            self._enabled = value
            if not value:
                try:
                    self._restore_staged_clipboard()
                except Exception:
                    # Turning OFF must still reach the orchestrator's cancel
                    # path even if the OS rejects clipboard restoration.
                    logger.exception("Failed to restore staged clipboard content")
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
        self.enabled = False
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
                            self._capture_change(current_count)

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

    def _capture_change(self, expected_revision: int | None = None) -> None:
        """Capture one stable revision while holding the transaction lock."""
        if expected_revision is None:
            expected_revision = self._get_change_count()
        content = self._read_clipboard()
        if self._get_change_count() != expected_revision:
            return
        if not content or not content.text.strip():
            # A later image/empty copy supersedes any older staged text.
            self._saved_clipboard_items = None
            self._owned_empty_revision = None
            with self._staged_lock:
                self._staged_content = None
            return
        logger.info("Clipboard captured: %s, %d characters", "HTML" if content.is_html else "plain text", len(content.text))
        if self._immediate_mode:
            try:
                accepted = self._on_change(content) is not False
            except Exception:
                logger.exception("Error in clipboard change callback")
                return
            # Queue ownership must transfer successfully before consuming a copy.
            # The revision check still protects a newer copy made by the user.
            if accepted:
                cleared_revision = self._clear_clipboard(expected_revision)
                if cleared_revision is not None:
                    self._last_change_count = cleared_revision
        else:
            # Keep every representation until this staged paste is accepted.
            pb = NSPasteboard.generalPasteboard()
            saved_items = []
            for item in pb.pasteboardItems() or []:
                saved = NSPasteboardItem.alloc().init()
                for kind in item.types():
                    data = item.dataForType_(kind)
                    if data is None or not saved.setData_forType_(data, kind):
                        raise RuntimeError("Could not preserve clipboard content")
                saved_items.append(saved)
            cleared_revision = self._clear_clipboard(expected_revision)
            if cleared_revision is None:
                return
            self._owned_empty_revision = cleared_revision
            self._last_change_count = cleared_revision
            self._saved_clipboard_items = saved_items
            with self._staged_lock:
                self._staged_content = content
            logger.info("Text staged — press Cmd+V to start typing")

    def _restore_staged_clipboard(self) -> None:
        """Return an unused staged copy on OFF/quit if we still own the clipboard."""
        if NSPasteboard is not None and self._owned_empty_revision is not None:
            pb = NSPasteboard.generalPasteboard()
            if pb.changeCount() == self._owned_empty_revision:
                pb.clearContents()
                if self._saved_clipboard_items and not pb.writeObjects_(self._saved_clipboard_items):
                    raise RuntimeError("Could not restore staged clipboard content")
                self._last_change_count = pb.changeCount()
        self._saved_clipboard_items = None
        self._owned_empty_revision = None
        with self._staged_lock:
            self._staged_content = None

    def trigger_paste(self) -> None:
        """Called when user presses Cmd+V — start typing the staged content."""
        with self._clipboard_lock:
            if not self._enabled or self._suspensions:
                return
            # Cmd+V can arrive before the next polling interval after a new
            # copy. Only the empty revision we wrote belongs to this stage;
            # the destination may already be pasting the newer clipboard.
            if (self._owned_empty_revision is not None
                    and self._get_change_count() != self._owned_empty_revision):
                self._saved_clipboard_items = None
                self._owned_empty_revision = None
                with self._staged_lock:
                    self._staged_content = None
                return
            with self._staged_lock:
                content = self._staged_content
                self._staged_content = None
            if content:
                logger.info("Cmd+V triggered — starting typing for %d characters", len(content.text))
                accepted = False
                try:
                    accepted = self._on_change(content) is not False
                except Exception:
                    logger.exception("Error in clipboard change callback")
                finally:
                    if accepted:
                        self._saved_clipboard_items = None
                        self._owned_empty_revision = None
                    else:
                        with self._staged_lock:
                            if self._staged_content is None:
                                self._staged_content = content
            else:
                logger.debug("Cmd+V pressed but no staged content")

    @staticmethod
    def _clear_clipboard(expected_revision: int) -> int | None:
        """Clear only the revision read by this capture, returning our revision."""
        if NSPasteboard is None:
            return None
        pb = NSPasteboard.generalPasteboard()
        if pb.changeCount() != expected_revision:
            return None
        # clearContents returns the revision it wrote. Reading changeCount
        # afterward could accidentally claim ownership of a newer user's copy.
        revision = pb.clearContents()
        logger.debug("Clipboard cleared after capture")
        return int(revision) if revision is not None else pb.changeCount()
