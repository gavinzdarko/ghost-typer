"""
macOS native notifications and optional webhook push notifications.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

APP_NAME = "Ghost Typer"


class NotificationService:
    """Sends macOS native notifications and optional webhook push notifications."""

    def __init__(self, webhook_url: Optional[str] = None, sound_enabled: bool = True):
        self.webhook_url = webhook_url
        self.sound_enabled = sound_enabled
        self._pending = queue.Queue(maxsize=32)
        self._worker_lock = threading.Lock()
        self._worker = None

    def _enqueue(self, operation) -> None:
        """Bound notification work and keep subprocess/network waits off UI threads."""
        try:
            self._pending.put_nowait(operation)
        except queue.Full:
            logger.warning("Notification queue full; dropping notification")
            return
        with self._worker_lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True, name="Notifications")
                self._worker.start()

    def _drain(self) -> None:
        while True:
            operation = self._pending.get()
            try:
                operation()
            except Exception:
                logger.exception("Notification delivery failed")
            finally:
                self._pending.task_done()

    def update_settings(self, webhook_url: Optional[str] = None, sound_enabled: bool = True) -> None:
        """Update notification settings."""
        self.webhook_url = webhook_url
        self.sound_enabled = sound_enabled

    def notify_planning(self) -> None:
        """Notify that AI planning has started."""
        self._send_native(
            title=f"{APP_NAME} - Planning",
            message="Analyzing text and generating typing profile...",
        )

    def notify_start(self, word_count: int) -> None:
        """Notify that typing has started."""
        message = f"Starting to type {word_count} words..."
        self._send_native(title=f"{APP_NAME} - Started", message=message)
        self._send_webhook(title="Typing Started", message=message)

    def notify_complete(self, word_count: int, elapsed_seconds: float) -> None:
        """Notify that typing is complete."""
        minutes = elapsed_seconds / 60.0
        if minutes >= 1.0:
            time_str = f"{minutes:.1f} minutes"
        else:
            time_str = f"{elapsed_seconds:.0f} seconds"

        message = f"Finished typing {word_count} words in {time_str}"
        self._send_native(title=f"{APP_NAME} - Complete", message=message)
        self._send_webhook(title="Typing Complete", message=message)

    def notify_error(self, error: str) -> None:
        """Notify about an error."""
        message = f"Error: {error}"
        self._send_native(title=f"{APP_NAME} - Error", message=message)
        self._send_webhook(title="Typing Error", message=message)

    def notify_cancelled(self) -> None:
        """Notify that typing was cancelled."""
        message = "Typing was cancelled by user"
        self._send_native(title=f"{APP_NAME} - Cancelled", message=message)

    def notify_paused(self) -> None:
        """Notify that typing is paused."""
        self._send_native(title=f"{APP_NAME}", message="Typing paused")

    def notify_resumed(self) -> None:
        """Notify that typing has resumed."""
        self._send_native(title=f"{APP_NAME}", message="Typing resumed")

    def _send_native(self, title: str, message: str) -> None:
        """Queue a macOS notification without blocking typing or hotkey handling."""
        sound_enabled = self.sound_enabled
        self._enqueue(lambda: self._deliver_native(title, message, sound_enabled))

    def _deliver_native(self, title: str, message: str, sound_enabled: bool) -> None:
        try:
            sound_part = ' sound name "Funk"' if sound_enabled else ""
            script = (
                f'display notification "{self._escape_applescript(message)}" '
                f'with title "{self._escape_applescript(title)}"'
                f"{sound_part}"
            )
            subprocess.run(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            logger.info("Native notification sent: %s - %s", title, message)
        except Exception:
            logger.exception("Failed to send native notification")

    def _send_webhook(self, title: str, message: str) -> None:
        """Send a push notification via webhook URL (ntfy, Pushover, etc.) in a background thread."""
        if not self.webhook_url:
            return

        url = self.webhook_url

        def _do_send() -> None:
            try:

                # Auto-detect service type from URL
                if "ntfy" in url or url.startswith("https://ntfy."):
                    # ntfy.sh style
                    requests.post(
                        url,
                        data=message,
                        headers={"Title": title, "Priority": "default"},
                        timeout=10,
                    )
                elif "pushover" in url:
                    # Pushover style — expects token and user in the URL params or as a full endpoint
                    requests.post(
                        url,
                        json={"title": title, "message": message},
                        timeout=10,
                    )
                else:
                    # Generic webhook: POST JSON
                    requests.post(
                        url,
                        json={"title": title, "message": message, "app": APP_NAME},
                        timeout=10,
                    )
                logger.info("Webhook notification sent")
            except Exception as exc:
                # Request exceptions can embed the full destination URL,
                # including webhook tokens, credentials, and query secrets.
                logger.warning("Failed to send webhook notification (%s)", type(exc).__name__)

        self._enqueue(_do_send)

    @staticmethod
    def _escape_applescript(text: str) -> str:
        """Escape special characters for AppleScript strings."""
        return (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("\t", " ")
        )
