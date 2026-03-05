"""
macOS native notifications and optional webhook push notifications.
"""

from __future__ import annotations

import logging
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

    def update_settings(self, webhook_url: Optional[str] = None, sound_enabled: bool = True) -> None:
        """Update notification settings."""
        self.webhook_url = webhook_url
        self.sound_enabled = sound_enabled

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
        """Send a macOS native notification via osascript."""
        try:
            sound_part = ' sound name "Funk"' if self.sound_enabled else ""
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

        def _do_send() -> None:
            try:
                url = self.webhook_url
                if not url:
                    return

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
                logger.info("Webhook notification sent to %s", url)
            except Exception:
                logger.exception("Failed to send webhook notification")

        thread = threading.Thread(target=_do_send, daemon=True)
        thread.start()

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
