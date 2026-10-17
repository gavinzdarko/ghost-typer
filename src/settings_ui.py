"""
Settings UI window for Ghost Typer using tkinter.
Provides sliders and inputs for all configurable options, with save/load to ~/.ghost-typer/settings.json.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import tempfile
from pathlib import Path
from typing import Callable, Optional

from .models import Settings

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    # The rumps menu uses persistence without opening the optional Tk window.
    # Homebrew Python can omit Tk; this must not prevent the app from starting.
    tk = None
    messagebox = ttk = None

logger = logging.getLogger(__name__)

SETTINGS_DIR = Path.home() / ".ghost-typer"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

# Defaults matching the Settings dataclass from models.py (engine settings)
# plus app-level settings (start_delay, webhook_url, sound_enabled)
DEFAULTS = {
    # Engine settings (must match Settings dataclass in models.py)
    "wpm": 60,
    "error_rate": 0.12,
    "pause_frequency": 0.15,
    "pause_duration_min": 0.3,
    "pause_duration_max": 4.0,
    "fatigue_enabled": True,
    "burst_typing_enabled": True,
    "rewrite_max_probability": 0.85,
    # App-level settings (not in Settings dataclass, handled by orchestrator)
    "start_delay": 3.0,
    "webhook_url": "",
    "sound_enabled": True,
    # AI settings
    "ai_enabled": True,
    "verify_after_typing": False,
    "anthropic_api_key": "",
    # Human error settings
    "grammar_error_rate": 0.15,
    "punctuation_error_rate": 0.20,
}


def load_settings_dict() -> dict:
    """Load settings from disk, falling back to defaults."""
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                settings.update(saved)
        except Exception:
            logger.exception("Failed to load settings file, using defaults")
    # The menu and API-key resolver consume this dictionary before constructing
    # an engine. Normalize here too so malformed persisted values cannot crash
    # the menu or accidentally enable a feature through string truthiness.
    settings.update(Settings.from_dict(settings).to_dict())
    for key in ("ai_enabled", "sound_enabled", "verify_after_typing"):
        if not isinstance(settings[key], bool):
            settings[key] = DEFAULTS[key]
    for key in ("anthropic_api_key", "webhook_url"):
        if not isinstance(settings[key], str):
            settings[key] = DEFAULTS[key]
    delay = settings["start_delay"]
    if (not isinstance(delay, (int, float)) or isinstance(delay, bool)
            or not 0 <= delay <= 3600 or not math.isfinite(delay)):
        settings["start_delay"] = DEFAULTS["start_delay"]
    return settings


def get_api_key() -> str:
    """Get the Anthropic API key: settings first, then .env, then env var.

    Priority:
    1. ~/.ghost-typer/settings.json  (anthropic_api_key field)
    2. ANTHROPIC_API_KEY environment variable (includes .env via python-dotenv)
    """
    settings = load_settings_dict()
    key = settings.get("anthropic_api_key", "").strip()
    if key:
        return key
    return os.environ.get("ANTHROPIC_API_KEY", "")


def save_settings_dict(settings: dict) -> None:
    """Persist settings dict to disk."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    # Serialize first: invalid values must not truncate a working configuration.
    payload = json.dumps(settings, indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=SETTINGS_DIR, delete=False) as f:
            temporary = Path(f.name)
            # NamedTemporaryFile is owner-only, including API keys in settings.
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, SETTINGS_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    logger.info("Settings saved to %s", SETTINGS_FILE)


class SettingsWindow:
    """A tkinter-based settings window for Ghost Typer."""

    def __init__(self, on_save: Optional[Callable[[dict], None]] = None):
        """
        Args:
            on_save: Optional callback invoked with the new settings dict when the user saves.
        """
        self._on_save = on_save
        self._window: Optional[tk.Tk] = None
        self._vars: dict[str, tk.Variable] = {}
        self._thread: Optional[threading.Thread] = None

    def show(self) -> None:
        """Open the settings window in a separate thread so it doesn't block rumps."""
        if tk is None:
            raise RuntimeError("The standalone settings window requires Python with Tk support")
        if self._thread and self._thread.is_alive():
            logger.info("Settings window already open")
            return
        self._thread = threading.Thread(target=self._build_and_run, daemon=True, name="SettingsUI")
        self._thread.start()

    def _build_and_run(self) -> None:
        """Build the tkinter window and enter its mainloop."""
        settings = load_settings_dict()

        root = tk.Tk()
        root.title("Ghost Typer Settings")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        self._window = root

        # Main frame with padding
        main = ttk.Frame(root, padding=20)
        main.pack(fill="both", expand=True)

        row = 0

        # --- Typing Speed ---
        ttk.Label(main, text="Typing Speed", font=("Helvetica", 14, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        row += 1

        row = self._add_slider(main, row, "WPM", "wpm", 10, 120, settings["wpm"], resolution=1)
        row = self._add_slider(main, row, "Error Rate", "error_rate", 0.0, 0.15, settings["error_rate"], resolution=0.005)

        # --- Pauses ---
        ttk.Separator(main, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Label(main, text="Pauses & Rhythm", font=("Helvetica", 14, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        row += 1

        row = self._add_slider(main, row, "Pause Frequency", "pause_frequency", 0.0, 0.5, settings["pause_frequency"], resolution=0.01)
        row = self._add_slider(main, row, "Pause Min (sec)", "pause_duration_min", 0.1, 10.0, settings["pause_duration_min"], resolution=0.1)
        row = self._add_slider(main, row, "Pause Max (sec)", "pause_duration_max", 0.5, 20.0, settings["pause_duration_max"], resolution=0.5)

        # --- Behavior ---
        ttk.Separator(main, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Label(main, text="Behavior", font=("Helvetica", 14, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        row += 1

        row = self._add_checkbox(main, row, "Fatigue Simulation", "fatigue_enabled", settings["fatigue_enabled"])
        row = self._add_checkbox(main, row, "Burst Typing", "burst_typing_enabled", settings["burst_typing_enabled"])
        row = self._add_slider(main, row, "Rewrite Probability", "rewrite_max_probability", 0.0, 1.0, settings["rewrite_max_probability"], resolution=0.01)

        # --- AI ---
        ttk.Separator(main, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Label(main, text="AI (Claude)", font=("Helvetica", 14, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        row += 1
        row = self._add_checkbox(main, row, "AI-Powered Typing Plans", "ai_enabled", settings.get("ai_enabled", True))
        row = self._add_checkbox(main, row, "Verify After Typing (OCR)", "verify_after_typing", settings.get("verify_after_typing", False))

        # API Key field
        ttk.Label(main, text="API Key:").grid(row=row, column=0, sticky="w", pady=2)
        api_key_var = tk.StringVar(value=settings.get("anthropic_api_key", ""))
        self._vars["anthropic_api_key"] = api_key_var
        api_key_entry = ttk.Entry(main, textvariable=api_key_var, width=40, show="*")
        api_key_entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(5, 0))
        row += 1

        # --- General ---
        ttk.Separator(main, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Label(main, text="General", font=("Helvetica", 14, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        row += 1

        row = self._add_slider(main, row, "Start Delay (sec)", "start_delay", 0.0, 15.0, settings["start_delay"], resolution=0.5)
        row = self._add_checkbox(main, row, "Sound Effects", "sound_enabled", settings["sound_enabled"])

        # --- Webhook ---
        ttk.Label(main, text="Webhook URL (ntfy/Pushover):").grid(row=row, column=0, sticky="w")
        webhook_var = tk.StringVar(value=settings.get("webhook_url", ""))
        self._vars["webhook_url"] = webhook_var
        webhook_entry = ttk.Entry(main, textvariable=webhook_var, width=40)
        webhook_entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(5, 0))
        row += 1

        # --- Buttons ---
        ttk.Separator(main, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="ew")

        ttk.Button(btn_frame, text="Reset to Defaults", command=self._reset_defaults).pack(side="left")
        ttk.Button(btn_frame, text="Cancel", command=root.destroy).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right")

        root.mainloop()
        self._window = None

    def _add_slider(
        self, parent: ttk.Frame, row: int, label: str, key: str,
        from_: float, to: float, value: float, resolution: float,
    ) -> int:
        """Add a labeled slider row. Returns the next row number."""
        ttk.Label(parent, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)

        var = tk.DoubleVar(value=value)
        self._vars[key] = var

        # Value label
        val_label = ttk.Label(parent, text=f"{value:.3g}", width=8)
        val_label.grid(row=row, column=2, sticky="e")

        def on_change(val: str) -> None:
            v = float(val)
            val_label.config(text=f"{v:.3g}")

        slider = ttk.Scale(parent, from_=from_, to=to, variable=var, orient="horizontal", length=250, command=on_change)
        slider.grid(row=row, column=1, sticky="ew", padx=5)

        return row + 1

    def _add_checkbox(self, parent: ttk.Frame, row: int, label: str, key: str, value: bool) -> int:
        """Add a labeled checkbox row. Returns the next row number."""
        var = tk.BooleanVar(value=value)
        self._vars[key] = var
        cb = ttk.Checkbutton(parent, text=label, variable=var)
        cb.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        return row + 1

    def _gather_settings(self) -> dict:
        """Collect current widget values into a settings dict."""
        # Controls expose only part of the configuration. Keep advanced and
        # future settings, including values changed since the window opened.
        settings = load_settings_dict()
        for key, var in self._vars.items():
            val = var.get()
            # Round floating-point slider values to avoid noise
            if isinstance(val, float):
                if key in ("wpm",):
                    val = int(round(val))
                else:
                    val = round(val, 4)
            settings[key] = val
        return settings

    def _save(self) -> None:
        """Save current settings to disk and notify the callback."""
        settings = self._gather_settings()
        try:
            save_settings_dict(settings)
            if self._on_save:
                self._on_save(settings)
            if self._window:
                self._window.destroy()
        except Exception:
            logger.exception("Failed to save settings")
            messagebox.showerror("Error", "Failed to save settings.")

    def _reset_defaults(self) -> None:
        """Reset all controls to default values."""
        for key, default in DEFAULTS.items():
            var = self._vars.get(key)
            if var is not None:
                var.set(default)
        logger.info("Settings reset to defaults")
