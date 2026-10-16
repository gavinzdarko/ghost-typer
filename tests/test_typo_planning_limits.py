from unittest.mock import Mock

import pytest

from src.models import Settings, TextSegment
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
