from unittest.mock import Mock, call

import pytest

from src.models import MakeMistake, Rewrite, Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_engine import TypingEngine
from src.typing_planner import TypingPlanner


@pytest.mark.parametrize('typo', ['drop', 'double', 'unchanged'])
def test_simple_planning_always_advances_after_an_unsuitable_typo(typo):
    text = 'abc XYZ'
    planner = TypingPlanner(Settings(error_rate=1), ai_enabled=False)
    # The budget fails deterministically if planning retries one character
    # without consuming input; no hanging background thread is needed.
    planner._rng.random = Mock(side_effect=[0.0] * (4 * len(text)))
    planner.engine.generate_typo = Mock(side_effect=lambda char: {
        'drop': '', 'double': char * 2, 'unchanged': char,
    }[typo])
    plan = planner.plan([TextSegment(text)], simple=True)
    state = PlannedText().apply(plan.actions)
    assert state.valid and state.text == text
    assert planner.engine.generate_typo.call_count <= len(text)
    assert planner._char_position == len(text)


@pytest.mark.parametrize('minimum,maximum', [(0, 0), (4, 0), (4, 2), (0, 6)])
def test_correction_notice_delay_respects_zero_or_reversed_limits(minimum, maximum):
    engine = TypingEngine(Settings(correction_delay_chars_min=minimum,
                                   correction_delay_chars_max=maximum))
    engine.profile.mistakes.immediate_notice_rate = 0
    for _ in range(30):
        delay = engine.chars_before_noticing_mistake()
        assert 0 <= delay <= maximum


@pytest.mark.parametrize('text', ['abc cafe\u0301 end', 'abc family 👪 end',
                                  'abc family 👨‍👩‍👧 end'])
def test_unicode_chunks_skip_forced_transient_typos_and_false_alarms(text):
    planner = TypingPlanner(Settings(error_rate=1, grammar_error_rate=0,
                                     punctuation_error_rate=0, false_alarm_rate=1,
                                     rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    planner._pick_mistake_positions = Mock(return_value={0})
    planner.engine.generate_typo = Mock(return_value='z')
    planner.engine.should_false_alarm = Mock(return_value=True)
    plan = planner.plan([TextSegment(text)])
    assert PlannedText().apply(plan.actions).text == text
    assert not any(isinstance(action, (Rewrite, MakeMistake)) for action in plan.actions)
    planner._pick_mistake_positions.assert_not_called()
    planner.engine.should_false_alarm.assert_not_called()


def test_simple_unicode_typing_only_corrects_immediate_ascii_characters():
    planner = TypingPlanner(Settings(error_rate=1), ai_enabled=False)
    planner.engine.generate_typo = Mock(side_effect=lambda char: char.swapcase())
    plan = planner.plan([TextSegment('É ß a')], simple=True)
    assert PlannedText().apply(plan.actions).text == 'É ß a'
    assert planner.engine.generate_typo.call_args_list == [call('a')]
    rewrites = [action for action in plan.actions if isinstance(action, Rewrite)]
    assert len(rewrites) == 1
    assert rewrites[0].new_actions == [TypeText(text='a')]


def test_ascii_chunks_retain_false_alarm_corrections():
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
                                     punctuation_error_rate=0, false_alarm_rate=1,
                                     rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    planner.engine.should_false_alarm = lambda: True
    actions = planner.plan([TextSegment('ordinary ASCII text')]).actions
    assert any(isinstance(action, Rewrite) for action in actions)
    assert PlannedText().apply(actions).text == 'ordinary ASCII text'
