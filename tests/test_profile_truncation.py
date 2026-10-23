"""A response that hit the output budget is never treated as complete."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.ai_planner import AIProfileGenerator
from src.models import TypingProfile


def generator(data, stop_reason):
    target = AIProfileGenerator(enabled=False)
    target._enabled = True
    target._client = Mock()
    target._client.messages.create.return_value = SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(text=json.dumps(data))])
    return target


def test_token_limited_profile_uses_defaults_even_with_decodable_payload():
    target = generator({'persona_description': 'incomplete result'}, 'max_tokens')
    assert target.generate_profile('source text') == TypingProfile.defaults()
    target._client.messages.create.assert_called_once()


def test_token_limited_behaviors_are_discarded_without_retry():
    target = generator({'thought_boundaries': [0]}, 'max_tokens')
    assert target.generate_behavioral_content('source text') == {}
    target._client.messages.create.assert_called_once()


def test_completed_profiles_are_still_accepted():
    target = generator({'persona_description': 'complete result'}, 'end_turn')
    assert target.generate_profile('source text').persona_description == 'complete result'
