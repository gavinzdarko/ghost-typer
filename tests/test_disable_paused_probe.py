import threading
from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator
from src.orchestrator import OrchestratorState


def test_turning_off_releases_a_paused_probe_before_waiting_for_clipboard_lock():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}):
        target = Orchestrator()
    target.notification_service = Mock()
    target._simulator = Mock()
    target.state = OrchestratorState.PAUSED
    held = threading.Event()
    stopped = threading.Event()
    release = threading.Event()
    target._simulator.stop.side_effect = stopped.set
    def paused_probe():
        with target.clipboard_monitor.suspended():
            held.set()
            # Model a paused simulator inside a table clipboard transaction.
            stopped.wait(2)
            release.set()
    worker = threading.Thread(target=paused_probe)
    target._typing_thread = worker
    worker.start()
    try:
        assert held.wait(1)
        target.disable(blocking=False)
        assert stopped.is_set()
        assert release.is_set()
        assert not target.is_enabled
        assert target._cancel_event.is_set()
    finally:
        stopped.set()
        worker.join(2)


def test_copy_callback_already_holding_clipboard_lock_cannot_launch_after_off():
    from src.clipboard_monitor import ClipboardContent
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}):
        target = Orchestrator()
    target.notification_service = Mock()
    target.enable()
    held = threading.Event()
    release = threading.Event()
    accepted = []
    def capture():
        with target.clipboard_monitor.suspended():
            held.set()
            release.wait(2)
            accepted.append(target._on_clipboard_change(ClipboardContent('new paste')))
    capture_worker = threading.Thread(target=capture)
    capture_worker.start()
    original_cancel = target.cancel
    def cancel(*args, **kwargs):
        original_cancel(*args, **kwargs)
        release.set()
    target.cancel = cancel
    fake_worker = Mock()
    fake_worker.is_alive.return_value = True
    try:
        assert held.wait(1)
        with patch('src.orchestrator.threading.Thread', return_value=fake_worker):
            target.disable(blocking=False)
        capture_worker.join(1)
        assert accepted == [False]
        fake_worker.start.assert_not_called()
        assert target.state == OrchestratorState.IDLE
        assert not target.is_enabled
        target.enable()
        with patch('src.orchestrator.threading.Thread', return_value=fake_worker):
            assert target._on_clipboard_change(ClipboardContent('after enable'))
        fake_worker.start.assert_called_once()
    finally:
        release.set()
        capture_worker.join(2)
