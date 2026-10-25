import pytest

from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


@pytest.mark.parametrize("mode", ["normal", "nowrap", "initial"])
def test_pre_inline_mode_can_restore_normal_whitespace(mode):
    assert text(f'<pre style="white-space:{mode}">a  b\n c\td</pre>') == "a b c d"


def test_pre_descendants_can_override_whitespace_without_losing_outer_spacing():
    source = '<pre>  a<span style="white-space:normal">  b\n c</span>  d\n e</pre>'
    assert text(source) == "  a b c  d\n e"


def test_pre_descendants_can_restore_preformatted_spacing():
    source = '<pre style="white-space:normal">a  <span style="white-space:pre-wrap"> b  c\n d</span>  e</pre>'
    assert text(source) == "a  b  c\n d e"


def test_pre_normal_still_preserves_explicit_breaks_and_visible_descendants():
    source = '<pre style="white-space:normal">a  b<br><br><span hidden>x</span> c</pre>'
    assert text(source) == "a b\n\nc"


def test_pre_default_keeps_inline_code_and_break_spacing():
    assert text('<pre>  a<b>  b</b><br>  c\t d</pre>') == "  a  b\n  c\t d"


@pytest.mark.parametrize("source", [
    '<pre>a{breaks}</pre><p>b</p>',
    '<p>a</p><pre>{breaks}b</pre>',
    '<pre>a{breaks}</pre><pre>b</pre>',
])
def test_pre_br_preserves_the_same_content_as_literal_newlines_at_block_edges(source):
    assert text(source.format(breaks="<br><br>")) == text(source.format(breaks="\n\n")) == "a\n\n\n\nb"


def test_pre_br_and_literal_newline_produce_the_same_planner_paragraph():
    from unittest.mock import Mock
    from src.models import Pause, Settings
    from src.planned_text import PlannedText
    from src.typing_planner import TypingPlanner

    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    planner.engine.paragraph_pause_duration = Mock(return_value=7)
    segments = TextParser().parse('<pre>a<br>b</pre>', is_html=True)
    assert len(segments) == 1
    assert segments == TextParser().parse('<pre>a\nb</pre>', is_html=True)
    plan = planner.plan(segments)
    assert PlannedText().apply(plan.actions).text == "a\nb"
    assert sum(isinstance(action, Pause) and action.duration == 7 for action in plan.actions) == 2
