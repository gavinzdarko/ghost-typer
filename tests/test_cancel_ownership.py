import threading
from unittest.mock import Mock, patch
from orchestrator_support import Orchestrator
from src.orchestrator import OrchestratorState


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}), patch('src.settings_ui.get_api_key', return_value=''):
        result = Orchestrator()
    result.notification_service = Mock()
    return result


def test_timed_out_cancel_retains_worker_and_blocks_shared_event_reuse():
    target = app()
    worker = Mock(ident=42)
    worker.is_alive.return_value = True
    target._typing_thread = worker
    target.state = OrchestratorState.TYPING
    target.cancel()
    worker.join.assert_called_once_with(timeout=5.0)
    assert target._typing_thread is worker
    assert target.state == OrchestratorState.TYPING
    assert target._cancel_event.is_set()
    assert not target._launch_pipeline(Mock(), (), 'new')
    assert target._cancel_event.is_set()


def test_verification_can_cancel_and_relaunch_only_after_worker_exits():
    target = app()
    worker = Mock(ident=42)
    worker.is_alive.return_value = True
    target._typing_thread = worker
    target.state = OrchestratorState.VERIFYING
    target.cancel(blocking=False)
    assert target._cancel_event.is_set()
    assert target.state == OrchestratorState.VERIFYING
    worker.is_alive.return_value = False
    target.cancel()
    assert target.state == OrchestratorState.IDLE
    assert target._typing_thread is None


def test_live_worker_blocks_launch_even_during_idle_finalization_window():
    target = app()
    worker = Mock()
    worker.is_alive.return_value = True
    target._typing_thread = worker
    assert target.state == OrchestratorState.IDLE
    assert not target._launch_pipeline(Mock(), (), 'new')
