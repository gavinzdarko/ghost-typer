from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest

from src.ai_planner import AIPlanner
from src.models import TextSegment


def test_split_words_and_newlines_are_preserved_without_guessed_spaces():
    planner = AIPlanner(enabled=False)
    data = {"segments": [{"text": "inside\n", "actions": [
        {"type": "type", "text": "in"}, {"type": "pause"},
        {"type": "type", "text": "side\n"}]}]}
    plan = planner._convert_ai_plan(data, [TextSegment("inside\n")])
    assert planner._render_actions(plan.actions) == "inside\n"


@pytest.mark.parametrize("actual", ["Hello world", "Hello.  world", "", "malicious replacement"])
def test_changed_ai_text_uses_fallback_before_execution(actual):
    planner = AIPlanner(enabled=False)
    planner._enabled = True
    planner._client = Mock()
    planner._fallback_planner = Mock()
    planner._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=json.dumps({
            "segments": [{"text": actual, "actions": [{"type": "type", "text": actual}]}]
        }))])
    source = [TextSegment("Hello. world")]
    assert planner.plan(source) is planner._fallback_planner.plan.return_value
    planner._fallback_planner.plan.assert_called_once_with(source)


def test_validation_replays_rewrites_instead_of_concatenating_temporary_text():
    planner = AIPlanner(enabled=False)
    plan = planner._convert_ai_plan({"segments": [{"text": "the result", "actions": [
        {"type": "mistake", "wrong": "teh", "correct": "the"},
        {"type": "type", "text": " "},
        {"type": "rewrite", "first_attempt": "thing", "final_version": "result"}]}]},
        [TextSegment("the result")])
    assert planner._render_actions(plan.actions) == "the result"
