from unittest.mock import Mock

from src.models import IntRange, Pause, Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0,
        rewrite_base_probability=0, rewrite_max_probability=0,
        pause_frequency=0), ai_enabled=False)
    p.engine.paragraph_pause_duration = Mock(return_value=7)
    return p


def test_paragraph_break_has_one_pause_after_its_newlines():
    p = planner()
    text = "First paragraph.\n\nSecond paragraph."
    plan = p.plan([TextSegment(text)])
    assert p.engine.paragraph_pause_duration.call_count == 2
    boundary_pauses = [i for i, a in enumerate(plan.actions) if isinstance(a, Pause) and a.duration == 7]
    assert len(boundary_pauses) == 2
    assert PlannedText().apply(plan.actions[:boundary_pauses[0]]).text == "First paragraph.\n\n"
    assert PlannedText().apply(plan.actions).text == text


def test_separator_chunks_do_not_count_as_additional_sentences():
    p = planner()
    p.profile.pauses.thought_pause_sentences_interval = IntRange(2, 2)
    plan = p.plan([TextSegment("One.\n\nTwo.\n\nThree.")])
    thought_pauses = [a for a in plan.actions if isinstance(a, Pause)
                      and a.description == "Pausing to collect thoughts"]
    assert len(thought_pauses) == 1


def test_explicit_separator_segments_keep_one_pause_per_paragraph():
    p = planner()
    plan = p.plan([TextSegment("First paragraph."), TextSegment("\n\n"), TextSegment("Second paragraph.")])
    assert p.engine.paragraph_pause_duration.call_count == 2
    assert PlannedText().apply(plan.actions).text == "First paragraph.\n\nSecond paragraph."
