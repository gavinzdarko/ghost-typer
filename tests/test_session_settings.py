from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator
from src.orchestrator import OrchestratorState


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}):
        return Orchestrator()


def test_settings_cannot_swap_a_live_planner_or_mutate_queued_configuration():
    target = app()
    old_planner = target.fallback_planner
    old_settings = target._settings
    target.state = OrchestratorState.PLANNING
    candidate = {'ai_enabled': False, 'wpm': 101, 'error_rate': .01}
    target.update_settings(candidate)
    candidate['wpm'] = 12
    assert target.fallback_planner is old_planner
    assert target._settings is old_settings
    assert target._pending_settings['wpm'] == 101
    target.state = OrchestratorState.IDLE
    worker = Mock()
    worker.is_alive.return_value = False
    with patch('src.orchestrator.threading.Thread', return_value=worker):
        assert target._launch_pipeline(Mock(), (), 'NextSession')
    assert target._settings.wpm == 101
    assert target.fallback_planner is not old_planner
    assert target._pending_settings is None


def test_idle_finalization_window_and_paused_session_keep_existing_components():
    target = app()
    target._typing_thread = Mock()
    target._typing_thread.is_alive.return_value = True
    old_planner = target.fallback_planner
    for state in (OrchestratorState.IDLE, OrchestratorState.PAUSED):
        target.state = state
        target.update_settings({'ai_enabled': False, 'wpm': 90})
        assert target.fallback_planner is old_planner
    target._typing_thread.is_alive.return_value = False
    target.state = OrchestratorState.IDLE
    assert target._pending_settings['wpm'] == 90


def test_latest_idle_save_supersedes_a_deferred_save():
    target = app()
    target.state = OrchestratorState.TYPING
    target.update_settings({'ai_enabled': False, 'wpm': 90})
    target.state = OrchestratorState.IDLE
    target.update_settings({'ai_enabled': False, 'wpm': 75})
    assert target._settings.wpm == 75
    assert getattr(target, '_pending_settings', None) is None
