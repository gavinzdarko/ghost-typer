import pytest

from src.models import MakeMistake, Rewrite, Settings, TextSegment
from src.planned_text import replace_known_span
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, rewrite_base_probability=0, rewrite_max_probability=0),
        ai_enabled=False)
    p.engine.generate_typo = lambda _: "z"
    p.profile.mistakes.unnoticed_rate = 0
    p.engine.is_fast_loop_correction = lambda: False
    p.engine.chars_before_noticing_mistake = lambda: 6
    return p


@pytest.mark.parametrize("control", ["\t", "\r", "\n", "\b", "\x1b", "\x7f"])
def test_delayed_correction_stops_before_focus_or_navigation_control(control):
    actions, consumed, _ = planner()._build_mistake("ab" + control + "tail", 0)
    assert consumed == 2
    mistake = next(action for action in actions if isinstance(action, MakeMistake))
    assert mistake.wrong_text == "zb"
    assert mistake.correct_text == "ab"


def test_false_alarm_cannot_backspace_a_tab():
    p = planner()
    p.engine.should_false_alarm = lambda: True
    p.engine.false_alarm_chars = lambda: 2
    plan = p.plan([TextSegment("abc\t")])
    assert not any(isinstance(action, Rewrite) for action in plan.actions)
    assert p._char_position == len("abc\t")


def test_relative_navigation_rejects_text_with_a_tab_focus_boundary():
    text = "earlier phrase\tother cell tail"
    assert replace_known_span(text, "earlier", "revised") == []
    assert planner()._build_proofread([("a", "b", 1)], len(text), known_text=text) == []


def test_relative_navigation_still_supports_ordinary_paragraphs():
    assert replace_known_span("earlier phrase\nother paragraph", "earlier", "revised")
