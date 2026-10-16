import pytest
from src.models import Settings, PressKey, TypeText
from src.text_parser import TextParser
from src.typing_planner import TypingPlanner


@pytest.mark.parametrize('text', ['one\r\ntwo', 'one\rtwo', 'one\r\n\r\ntwo\rtail\nlast'])
def test_each_logical_newline_produces_one_enter(text):
    expected = text.replace('\r\n', '\n').replace('\r', '\n')
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, rewrite_base_probability=0,
        rewrite_max_probability=0, proofread_probability=0, revisit_probability=0))
    for plan in [planner.plan(TextParser().parse(text)), planner.plan_plain_text(text)]:
        # Both CR and LF map to Enter in pynput, so no literal CR may remain.
        actual = ''.join(a.text if isinstance(a, TypeText) else '\n'
                         if isinstance(a, PressKey) and a.key == 'enter' else '' for a in plan.actions)
        assert actual == expected
        assert '\r' not in actual
