from types import SimpleNamespace
from unittest.mock import Mock
from src.human_errors import HumanErrors
from src.models import Settings, TextSegment
from src.typing_planner import TypingPlanner


def enabled_errors():
    errors = HumanErrors(enabled=False)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text='{}')])
    return errors


def test_many_paragraphs_and_failures_share_a_bounded_paste_budget():
    planner = TypingPlanner(Settings(error_rate=0), ai_enabled=False)
    errors = enabled_errors()
    errors._client.messages.create.side_effect = RuntimeError('offline')
    planner._human_errors = errors
    segments = [TextSegment('A complete paragraph with enough text for thinking. ')] * 40
    planner.plan(segments)
    assert errors._client.messages.create.call_count == errors.MAX_REQUESTS_PER_PLAN
    planner.plan(segments)
    assert errors._client.messages.create.call_count == 2 * errors.MAX_REQUESTS_PER_PLAN


def test_large_inputs_and_output_tokens_are_bounded():
    errors = enabled_errors()
    text = 'x' * (errors.MAX_INPUT_CHARS + 1)
    assert errors.process_text(text) == (text, [])
    errors._client.messages.create.assert_not_called()
    errors.process_text('hello ' * 1000)
    call = errors._client.messages.create.call_args.kwargs
    assert call['max_tokens'] <= errors.MAX_OUTPUT_TOKENS
    errors.find_thought_boundaries(text)
    assert len(errors._client.messages.create.call_args.kwargs['messages'][0]['content']) <= errors.MAX_INPUT_CHARS
