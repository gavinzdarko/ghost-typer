"""AI speed changes must survive conversion and remain bounded."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai_planner import AIPlanner
from src.models import Pause, Rewrite, Settings, TextSegment, TypeText


def convert(actions, text="easy hard"):
    planner = AIPlanner(enabled=False)
    return planner._convert_ai_plan({"segments": [{"text": text, "actions": actions}]},
                                    [TextSegment(text)])


def test_speed_changes_apply_to_subsequent_text_without_substituting_a_pause():
    plan = convert([
        {"type": "speed_change", "multiplier": 1.5},
        {"type": "type", "text": "easy "},
        {"type": "speed_change", "multiplier": .5},
        {"type": "type", "text": "hard"},
    ])
    assert [(action.text, action.speed_multiplier) for action in plan.actions
            if isinstance(action, TypeText)] == [("easy ", 1.5), ("hard", .5)]
    assert not any(isinstance(action, Pause) for action in plan.actions)
    assert AIPlanner._render_actions(plan.actions) == "easy hard"
    assert plan.estimated_duration_seconds == pytest.approx((5 / 1.5 + 4 / .5) / 5)


def test_speed_persists_across_segments_and_newlines_but_resets_for_new_plan():
    planner = AIPlanner(enabled=False)
    plan = planner._convert_ai_plan({"segments": [
        {"text": "a\n", "actions": [{"type": "speed_change", "multiplier": 1.3},
                                    {"type": "type", "text": "a\n"}]},
        {"text": "b", "actions": [{"type": "type", "text": "b"}]},
    ]}, [TextSegment("a\nb")])
    assert [a.speed_multiplier for a in plan.actions if isinstance(a, TypeText)] == [1.3, 1.3]
    reset = planner._convert_ai_plan({"segments": [{"text": "x", "actions": [
        {"type": "type", "text": "x"}]}]}, [TextSegment("x")])
    assert reset.actions[0].speed_multiplier == 1


def test_rewrite_draft_and_replacement_use_current_text_speed():
    plan = convert([{"type": "speed_change", "multiplier": .7},
                    {"type": "rewrite", "first_attempt": "old", "final_version": "new"}], "new")
    draft = next(a for a in plan.actions if isinstance(a, TypeText))
    rewrite = next(a for a in plan.actions if isinstance(a, Rewrite))
    assert draft.speed_multiplier == .7
    assert rewrite.new_actions[0].speed_multiplier == .7
    assert AIPlanner._render_actions(plan.actions) == "new"


@pytest.mark.parametrize("value,expected", [(100, 1.5), (.001, .5)])
def test_finite_positive_speed_requests_are_bounded(value, expected):
    plan = convert([{"type": "speed_change", "multiplier": value},
                    {"type": "type", "text": "easy hard"}])
    assert plan.actions[0].speed_multiplier == expected


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, None, "fast"])
def test_invalid_speed_uses_local_fallback_without_another_paid_request(value):
    planner = AIPlanner(Settings(error_rate=0, grammar_error_rate=0,
                                  punctuation_error_rate=0), enabled=False)
    planner._enabled = True
    planner._client = Mock()
    planner._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=json.dumps({"segments": [
            {"text": "easy hard", "actions": [{"type": "speed_change", "multiplier": value},
                                              {"type": "type", "text": "easy hard"}]}]}))])
    plan = planner.plan([TextSegment("easy hard")])
    assert not plan.metadata.get("ai_generated")
    planner._client.messages.create.assert_called_once()


def test_disabled_edits_keep_speed_when_converted_to_plain_text():
    planner = AIPlanner(Settings(error_rate=0, rewrite_max_probability=0), enabled=False)
    plan = planner._convert_ai_plan({"segments": [{"text": "the new", "actions": [
        {"type": "speed_change", "multiplier": .7},
        {"type": "mistake", "wrong": "teh ", "correct": "the "},
        {"type": "rewrite", "first_attempt": "old", "final_version": "new"},
    ]}]}, [TextSegment("the new")])
    assert [(a.text, a.speed_multiplier) for a in plan.actions] == [("the ", .7), ("new", .7)]
