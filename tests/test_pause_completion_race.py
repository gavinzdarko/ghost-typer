import threading
from unittest.mock import Mock
from orchestrator_support import Orchestrator
from src.orchestrator import OrchestratorState


def app(state):
    instance = Orchestrator.__new__(Orchestrator)
    instance._state = state
    instance._state_lock = threading.Lock()
    instance._session_lock = threading.RLock()
    instance.on_state_change = Mock()
    instance.notification_service = Mock()
    instance._simulator = Mock()
    return instance


def test_completion_during_pause_cannot_leave_idle_session_paused():
    instance = app(OrchestratorState.TYPING)
    instance._simulator.pause.side_effect = lambda: setattr(instance, 'state', OrchestratorState.IDLE)
    instance.pause()
    assert instance.state == OrchestratorState.IDLE
    instance.notification_service.notify_paused.assert_not_called()
    instance._simulator.resume.assert_called_once()


def test_completion_during_resume_cannot_leave_idle_session_typing():
    instance = app(OrchestratorState.PAUSED)
    instance._simulator.resume.side_effect = lambda: setattr(instance, 'state', OrchestratorState.IDLE)
    instance.resume()
    assert instance.state == OrchestratorState.IDLE
    instance.notification_service.notify_resumed.assert_not_called()


def test_normal_pause_resume_and_missing_simulator():
    instance = app(OrchestratorState.TYPING)
    instance.pause()
    assert instance.state == OrchestratorState.PAUSED
    instance.resume()
    assert instance.state == OrchestratorState.TYPING
    instance._simulator = None
    instance.pause()
    assert instance.state == OrchestratorState.TYPING
