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
