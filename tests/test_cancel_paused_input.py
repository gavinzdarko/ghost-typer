"""Cancellation must stop paused input before releasing the pause gate."""
import threading
from unittest.mock import Mock, patch

import pytest

from src.keystroke_simulator import KeystrokeSimulator
from src.orchestrator import Orchestrator, OrchestratorState


@pytest.mark.parametrize('blocking', [False, True])
@pytest.mark.parametrize('operation', ['character', 'key', 'hotkey'])
def test_cancel_does_not_release_pending_paused_input(blocking, operation):
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    sim.pause()
    waiting = threading.Event()
    original_check = sim._check_state

    def check_state():
        waiting.set()
        return original_check()

    sim._check_state = check_state
    actions = {'character': lambda: sim.type_char('x'),
               'key': lambda: sim.press_key('backspace'),
               'hotkey': lambda: sim.hotkey('cmd', 'a')}
    worker = threading.Thread(target=actions[operation])
    target = Orchestrator.__new__(Orchestrator)
    target._session_lock = threading.RLock()
    target._state_lock = threading.Lock()
    target._state = OrchestratorState.PAUSED
    target._state_revision = 0
    target.on_state_change = None
    target._cancel_event = threading.Event()
    target._simulator = sim
    target._typing_thread = worker
    target.notification_service = Mock()
    original_resume = sim.resume

    def resume_and_schedule_worker():
        original_resume()
        # Force the worker to finish before cancellation's next control call.
        # This models scheduling at resume without relying on a sleep race.
        worker.join(2)
        assert not worker.is_alive()

    sim.resume = resume_and_schedule_worker
    worker.start()
    try:
        assert waiting.wait(2)
        sim._controller.press.assert_not_called()
        target.cancel(blocking=blocking)
        assert target._cancel_event.is_set()
        assert not sim.is_active
        sim._controller.press.assert_not_called()
        sim._controller.release.assert_not_called()
        target.notification_service.notify_cancelled.assert_called_once_with()
    finally:
        sim.stop()
        original_resume()
        worker.join(2)
