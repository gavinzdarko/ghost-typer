import pytest

from src.models import MakeMistake, Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    target = TypingPlanner(Settings(error_rate=1, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    target.engine.generate_typo = lambda _: ''
    target.engine.is_fast_loop_correction = lambda: False
    target.engine.chars_before_noticing_mistake = lambda: 2
    target.profile.mistakes.unnoticed_rate = 1
    return target


def test_dropped_letter_can_be_noticed_after_following_letters_and_restored():
    actions, consumed, unnoticed = planner()._build_mistake('abcd', 0)
    assert consumed == 3 and unnoticed is None
    assert isinstance(actions[0], MakeMistake)
    assert actions[0].wrong_text == 'bc'
    assert actions[0].correct_text == 'abc'
    assert PlannedText().apply(actions).text == 'abc'


@pytest.mark.parametrize('fast', [False, True])
def test_drops_preserve_the_full_source_even_with_unnoticed_rate_one(fast):
    target = planner()
    target.engine.is_fast_loop_correction = lambda: fast
    source = 'Dropped letters still get restored.'
    state = PlannedText().apply(target.plan([TextSegment(source)]).actions)
    assert state.valid and state.text == source


def test_drop_correction_cannot_cross_a_focus_changing_control():
    actions, consumed, _ = planner()._build_mistake('a\tend', 0)
    assert consumed == 1
    assert actions[0].wrong_text == ''
    assert actions[0].correct_text == 'a'
