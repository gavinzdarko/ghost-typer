from unittest.mock import Mock, patch

import pytest

from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.models import Rewrite, TypingProfile


def custom_profile():
    profile = TypingProfile.defaults()
    profile.mistakes.type_weights = {name: int(name == 'drop') for name in profile.mistakes.type_weights}
    return profile


@pytest.mark.parametrize('refresh', [False, True])
def test_constructor_and_settings_refresh_preserve_configured_planner_profile(refresh):
    profile = custom_profile()
    settings = {'ai_enabled': False, 'start_delay': 0}
    with patch('src.orchestrator.load_settings_dict', return_value=settings):
        app = Orchestrator(profile=profile)
    if refresh:
        app._apply_settings(settings)
    assert app.fallback_planner.profile == profile
    assert app.fallback_planner.engine.profile == profile


@pytest.mark.parametrize('after_ai_session,refresh', [(False, False), (True, False), (True, True)])
def test_table_plan_and_runtime_share_baseline_profile(after_ai_session, refresh):
    profile = custom_profile()
    settings = {'ai_enabled': False, 'start_delay': 0, 'error_rate': 1,
                'fatigue_enabled': False}
    with patch('src.orchestrator.load_settings_dict', return_value=settings):
        app = Orchestrator(profile=profile)
    if after_ai_session:
        app._profile = TypingProfile.defaults()
        app.fallback_planner.profile = app._profile
    if refresh:
        app._apply_settings(settings)
    app.notification_service = Mock()
    app._cell_has_content = Mock(return_value=False)
    app._notify_table_queue_change = Mock()
    app.fallback_planner.seed(5)
    executed = []
    app._execute_plan = lambda plan, engine, simulator: executed.append((plan, engine.profile))
    with patch('src.orchestrator.KeystrokeSimulator', return_value=Mock(is_active=True)):
        app._table_fill_pipeline([ClipboardContent('abcdefghijklmnopqrstuvwxyz')], skip_columns=0)
    assert len(executed) == 1
    plan, runtime_profile = executed[0]
    assert runtime_profile == profile == app.fallback_planner.profile
    # Simple plans deliberately skip dropped-letter mistakes. Stock-profile
    # adjacent mistakes would instead emit many temporary Rewrite corrections.
    assert not any(isinstance(action, Rewrite) for action in plan.actions)
    assert app._baseline_profile == profile
