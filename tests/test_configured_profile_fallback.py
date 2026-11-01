from unittest.mock import Mock, patch
from types import SimpleNamespace
import json

import pytest

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


@pytest.mark.parametrize('failure', ['network', 'invalid_json', 'truncated', 'empty', 'non_object'])
@pytest.mark.parametrize('rebuild', [False, True])
def test_real_generator_failures_preserve_the_personal_profile(failure, rebuild):
    target = app()
    if rebuild:
        target._apply_settings({'ai_enabled': False})
    generator = target.ai_profile_generator
    generator._enabled = True
    generator._client = Mock()
    if failure == 'network':
        generator._client.messages.create.side_effect = RuntimeError('API unavailable')
    else:
        payload = {'invalid_json': '{', 'truncated': '{"persona_description":"incomplete"}',
                   'empty': '', 'non_object': '[]'}[failure]
        generator._client.messages.create.return_value = SimpleNamespace(
            stop_reason='max_tokens' if failure == 'truncated' else 'end_turn',
            content=[] if failure == 'empty' else [SimpleNamespace(text=payload)])
    # Keep behavior generation independent, and exercise the real profile API handler.
    generator.generate_behavioral_content = Mock(return_value={'word_speed_map': []})
    try:
        profile, behavior = target._generate_session_behaviors('hello')
        assert profile.persona_description == 'Calibrated personal profile'
        assert profile.keystroke.finger_pinky_multiplier == 1.7
        assert behavior == {'word_speed_map': []}
        profile.keystroke.finger_pinky_multiplier = 3
        again, _ = target._generate_session_behaviors('next paste')
        assert again.keystroke.finger_pinky_multiplier == 1.7
        assert generator._client.messages.create.call_count == 2  # One call per session, no retry.
    finally:
        target._profile_executor.shutdown(wait=True)


@pytest.mark.parametrize('payload', [
    {}, {'unknown': 123}, {'keystroke': {}},
    {'keystroke': {'finger_pinky_multiplier': 'invalid'}},
    {'peek': {'pause_duration': {'unknown': 2}}},
    {'mistakes': {'type_weights': {'unknown': 5}}},
    {'keystroke': {'delay_clamp_min': .5, 'delay_clamp_max': .1}},
])
def test_unusable_profile_objects_preserve_an_independent_personal_baseline(payload):
    target = app()
    generator = target.ai_profile_generator
    generator._enabled = True
    generator._client = Mock()
    generator._client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(text=json.dumps(payload))])
    profile = generator.generate_profile('hello')
    assert profile.persona_description == 'Calibrated personal profile'
    assert profile.keystroke.finger_pinky_multiplier == 1.7
    profile.keystroke.finger_pinky_multiplier = 3
    assert generator.generate_profile('again').keystroke.finger_pinky_multiplier == 1.7


@pytest.mark.parametrize('payload', [
    {'persona_description': 'New persona'},
    {'keystroke': {'finger_pinky_multiplier': 1.18}},
    {'unknown': True, 'keystroke': {'finger_pinky_multiplier': 'invalid'},
     'energy_level': .8},
])
def test_valid_sparse_profile_objects_keep_the_existing_stock_default_contract(payload):
    target = app()
    generator = target.ai_profile_generator
    generator._enabled = True
    generator._client = Mock()
    generator._client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(text=json.dumps(payload))])
    expected = TypingProfile.from_dict(payload)
    profile = generator.generate_profile('hello')
    assert profile == expected
    assert profile.keystroke.finger_pinky_multiplier == 1.18
    profile.keystroke.finger_pinky_multiplier = 3
    assert generator.generate_profile('again') == expected
