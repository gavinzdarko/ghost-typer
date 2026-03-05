#!/usr/bin/env python3
"""
Ghost Typer — entry point.
Starts the menu bar app and all background services.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

# Ensure the project root is on the path so ghost_typer.src imports work
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = Path.home() / ".ghost-typer"
LOG_FILE = LOG_DIR / "ghost-typer.log"


def setup_logging() -> None:
    """Configure logging to both file and stderr."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler — verbose
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(fh)

    # Console handler — info+
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(ch)


LOCK_FILE = LOG_DIR / "ghost-typer.pid"


def _check_single_instance() -> None:
    """Ensure only one instance of Ghost Typer runs at a time."""
    import fcntl

    # Open (or create) the lock file — keep it open for the lifetime of the process
    global _lock_fh  # noqa: PLW0603
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _lock_fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
        _lock_fh.truncate()
    except OSError:
        print("Ghost Typer is already running. Exiting.", file=sys.stderr)
        sys.exit(1)


_lock_fh = None


def main() -> None:
    setup_logging()
    logger = logging.getLogger("ghost_typer")

    _check_single_instance()
    logger.info("Ghost Typer starting up")

    # Import after path setup
    from src.orchestrator import Orchestrator
    from src.menu_bar_app import GhostTyperApp

    orchestrator = Orchestrator()
    orchestrator.start()

    app = GhostTyperApp(orchestrator)

    # Graceful shutdown: use a flag + timer instead of calling
    # rumps.quit_application() from a signal handler (not async-signal-safe).
    _shutdown_requested = threading.Event()

    def handle_signal(signum: int, frame: object) -> None:
        _shutdown_requested.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    import rumps

    def _check_shutdown(_timer: object) -> None:
        if _shutdown_requested.is_set():
            logger.info("Shutdown signal received, quitting")
            app._quit(None)  # use app's own teardown (stops hotkeys, overlay, etc.)

    shutdown_timer = rumps.Timer(_check_shutdown, 0.5)
    shutdown_timer.start()

    logger.info("Starting menu bar app")
    app.run()


if __name__ == "__main__":
    main()
