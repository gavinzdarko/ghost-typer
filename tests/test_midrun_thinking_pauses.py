from unittest.mock import Mock

from src.models import Pause, Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    return TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0,
        rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)


def test_word_boundaries_receive_thinking_pauses_without_typos_or_rewrites():
    p = planner()
    p.engine.should_thinking_pause = Mock(return_value=True)
    p.engine.thinking_pause_duration = Mock(return_value=.75)
    text = "Some ordinary words in one sentence."
    plan = p.plan([TextSegment(text)])
    assert p.engine.should_thinking_pause.call_count == text.count(" ")
    assert p.engine.thinking_pause_duration.call_count == text.count(" ")
    assert sum(isinstance(a, Pause) and a.duration == .75 for a in plan.actions) == text.count(" ")
    assert PlannedText().apply(plan.actions).text == text


def test_disabled_thinking_pauses_preserve_text_and_emit_no_midrun_pause():
    p = planner()
    p.engine.should_thinking_pause = Mock(return_value=False)
    p.engine.thinking_pause_duration = Mock()
    text = "Some ordinary words in one sentence."
    plan = p.plan([TextSegment(text)])
    p.engine.thinking_pause_duration.assert_not_called()
    assert PlannedText().apply(plan.actions).text == text
