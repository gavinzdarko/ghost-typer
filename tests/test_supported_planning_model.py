import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.ai_planner import AIPlanner
from src.models import TextSegment


def test_supported_model_produces_a_validated_plan_without_extra_requests():
    planner = AIPlanner(enabled=False)
    planner._enabled = True
    planner._client = Mock()
    def provider(**request):
        # The provider retired Sonnet 4; requests to that ID fail instead of
        # exercising the paid planner. Sonnet 4.6 accepts the same Messages API.
        assert request['model'] == 'claude-sonnet-4-6'
        assert request['max_tokens'] == 512
        return SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(text=json.dumps({
            'segments': [{'text': 'hello', 'actions': [{'type': 'type', 'text': 'hello'}]}]
        }))])
    planner._client.messages.create.side_effect = provider
    planner._fallback_planner = Mock()
    plan = planner.plan([TextSegment('hello')])
    assert plan.metadata['ai_generated'] is True
    assert planner._render_actions(plan.actions) == 'hello'
    planner._client.messages.create.assert_called_once()
    planner._fallback_planner.plan.assert_not_called()
