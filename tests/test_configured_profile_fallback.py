from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator
from src.models import TypingProfile


def app():
    profile = TypingProfile.defaults()
    profile.persona_description = 'Calibrated personal profile'
    profile.keystroke.finger_pinky_multiplier = 1.7
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}):
        return Orchestrator(profile=profile)


def test_offline_sessions_preserve_the_explicit_profile_without_sharing_mutations():
    target = app()
    profile, behavior = target._generate_session_behaviors('hello')
    assert profile.persona_description == 'Calibrated personal profile'
    assert profile.keystroke.finger_pinky_multiplier == 1.7
    assert behavior == {}
    profile.keystroke.finger_pinky_multiplier = 3
    again, _ = target._generate_session_behaviors('hello again')
    assert again.keystroke.finger_pinky_multiplier == 1.7


def test_cancelled_or_busy_ai_generation_uses_the_configured_baseline():
    target = app()
    target.ai_profile_generator = Mock(is_enabled=True)
    target._cancel_event.set()
    assert target._generate_session_behaviors('hello')[0].persona_description == 'Calibrated personal profile'
    target._cancel_event.clear()
    target._profile_futures = {Mock(done=lambda: False)}
    assert target._generate_session_behaviors('hello')[0].keystroke.finger_pinky_multiplier == 1.7
