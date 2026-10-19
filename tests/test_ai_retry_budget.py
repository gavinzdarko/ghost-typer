from unittest.mock import Mock, patch
from src.ai_planner import AIPlanner, AIProfileGenerator, AIRewriter
from src.human_errors import HumanErrors


def test_every_paid_client_disables_hidden_sdk_retries():
    # Planner call budgets must correspond to actual HTTP attempts. A failed
    # optional enhancement falls back locally instead of multiplying requests.
    with patch('anthropic.Anthropic', return_value=Mock()) as client:
        clients = [AIPlanner(api_key='test'), AIProfileGenerator(api_key='test'),
                   AIRewriter(api_key='test'), HumanErrors(api_key='test')]
        assert all(c.is_enabled for c in clients)
        assert client.call_count == 4  # AIPlanner fallback is entirely local.
        assert all(call.kwargs == {'api_key': 'test', 'max_retries': 0}
                   for call in client.call_args_list)
