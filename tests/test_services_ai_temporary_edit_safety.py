"""AI edits must be safe under native field and grapheme deletion semantics."""
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from src.ai_planner import AIPlanner
from src.models import TextSegment, TypeText, TypingPlan
from orchestrator_support import Orchestrator


def data(action, source="A"):
    return {"segments": [{"text": source, "actions": [action]}]}


@pytest.mark.parametrize("temporary", ["x\t", "x\n", "x\r", "x\b", "x\x1b", "x\x7f",
                                       "e\u0301", "é", "👩\u200d💻"])
@pytest.mark.parametrize("kind", ["mistake", "rewrite"])
def test_unsafe_temporary_edits_fall_back_before_any_execution(temporary, kind):
    action = ({"type": kind, "wrong": temporary, "correct": "A"} if kind == "mistake"
              else {"type": kind, "first_attempt": temporary, "final_version": "A"})
    planner = AIPlanner(enabled=False)
    planner._enabled = True
    planner._client = Mock()
    planner._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=json.dumps(data(action)))])
    fallback = TypingPlan(actions=[TypeText(text="A")])
    planner._fallback_planner = Mock()
    planner._fallback_planner.plan.return_value = fallback
    plan = planner.plan([TextSegment("A")])
    assert plan is fallback
    simulator = execute_with_mock(plan)
    assert simulator.type_char.call_args_list == [call("A")]
    simulator.press_key.assert_not_called()


@pytest.mark.parametrize("kind", ["mistake", "rewrite"])
def test_unicode_replacement_does_not_enter_a_repeatable_edit(kind):
    action = ({"type": kind, "wrong": "x", "correct": "e\u0301"} if kind == "mistake"
              else {"type": kind, "first_attempt": "x", "final_version": "e\u0301"})
    with pytest.raises(ValueError, match="printable ASCII"):
        AIPlanner(enabled=False)._convert_ai_plan(data(action, "e\u0301"), [TextSegment("e\u0301")])


def execute_with_mock(plan):
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = Event()
    target._record_typed_character = Mock()
    engine = Mock()
    engine.should_peek_pause.return_value = False
    engine.delay_for_keystroke.return_value = .01
    simulator = Mock(is_active=True)
    target._execute_plan(plan, engine, simulator)
    return simulator


def test_direct_unicode_source_typing_remains_supported():
    source = "你好 e\u0301 👩\u200d💻"
    plan = AIPlanner(enabled=False)._convert_ai_plan(
        data({"type": "type", "text": source}, source), [TextSegment(source)])
    simulator = execute_with_mock(plan)
    assert simulator.type_char.call_args_list == [call(char) for char in source]
    simulator.press_key.assert_not_called()


def test_ordinary_ascii_temporary_edits_still_validate():
    source = "the result"
    plan = AIPlanner(enabled=False)._convert_ai_plan({"segments": [{"text": source, "actions": [
        {"type": "mistake", "wrong": "teh", "correct": "the"},
        {"type": "type", "text": " "},
        {"type": "rewrite", "first_attempt": "thing", "final_version": "result"}]}]},
        [TextSegment(source)])
    assert AIPlanner._render_actions(plan.actions) == source
