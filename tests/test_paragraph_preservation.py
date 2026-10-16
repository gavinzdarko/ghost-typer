from src.models import PressKey, Settings, TypeText
from src.text_parser import TextParser
from src.typing_planner import TypingPlanner


def rendered(actions):
    return ''.join(a.text if isinstance(a, TypeText) else '\n' if isinstance(a, PressKey) and a.key == 'enter' else '' for a in actions)


def test_parsed_paragraph_breaks_survive_planning():
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0, false_alarm_rate=0, rewrite_max_probability=0, rewrite_base_probability=0))
    for text in ['One.\n\nTwo.', 'One.\n\n\nTwo.', 'One.\nTwo.']:
        segments = TextParser().parse(text)
        assert rendered(planner.plan(segments).actions) == ''.join(s.text for s in segments)


def test_direct_text_preserves_all_paragraph_newlines():
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0, false_alarm_rate=0, rewrite_max_probability=0, rewrite_base_probability=0))
    assert rendered(planner.plan_plain_text('One.\n\n\nTwo.').actions) == 'One.\n\n\nTwo.'


def test_parser_preserves_exact_plain_whitespace():
    for text in ['One.\n\n\nTwo.', '\nLeading\n', '  indented\n\n  next  ', '\n\n', '   ']:
        segments = TextParser().parse(text)
        assert ''.join(s.text for s in segments) == text
        planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0, false_alarm_rate=0, rewrite_max_probability=0, rewrite_base_probability=0))
        assert rendered(planner.plan(segments).actions) == text
