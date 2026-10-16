"""Offline policy covers nested paid clients, regardless of environment keys."""
from unittest.mock import Mock, patch

from src.ai_planner import AIPlanner, AIProfileGenerator, AIRewriter
from src.human_errors import HumanErrors
from src.typing_planner import TypingPlanner


def test_opt_out_never_constructs_clients_with_environment_key():
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'fake-environment-key'}), patch('anthropic.Anthropic') as client:
        planner = AIPlanner(enabled=False)
        clients = [planner, planner._fallback_planner._human_errors,
                   AIProfileGenerator(enabled=False), AIRewriter(enabled=False), HumanErrors(enabled=False),
                   TypingPlanner(ai_enabled=False)._human_errors]
        assert all(not item.is_enabled for item in clients)
        assert HumanErrors(enabled=False).process_text('unchanged') == ('unchanged', [])
        client.assert_not_called()


def test_explicit_key_reaches_human_errors_and_empty_key_suppresses_environment():
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'environment'}), patch('anthropic.Anthropic', return_value=Mock()) as client:
        planner = TypingPlanner(api_key='configured-key')
        assert planner._human_errors.is_enabled
        client.assert_called_once_with(api_key='configured-key')
        client.reset_mock()
        assert not TypingPlanner(api_key='')._human_errors.is_enabled
        assert not AIPlanner(api_key='').is_enabled
        assert not AIRewriter(api_key='').is_enabled
        assert not AIProfileGenerator(api_key='').is_enabled
        client.assert_not_called()
