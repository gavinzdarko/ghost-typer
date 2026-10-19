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
