import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('display', ['inline', 'block', 'contents', 'flex',
                                   'initial', 'unset', 'inherit', 'block flow'])
def test_valid_display_overrides_the_ordinary_hidden_attribute(display):
    assert 'visible' in text(f'<div hidden style="display:{display}">visible</div>')


def test_inline_hidden_override_preserves_adjacency_and_descendant_visibility():
    assert text('<p>A<span hidden style="display:inline">visible</span>B</p>') == 'AvisibleB'
    assert text('<span hidden="false" style="display:inline">visible</span>') == 'visible'
    assert text('<span hidden style="display:inline">A<b hidden>secret</b>B</span>') == 'AB'
    assert text('<span hidden style="display:inline;visibility:hidden">secret</span>') == ''


@pytest.mark.parametrize('style', ['', 'display:none', 'display:revert',
                                  'display:revert-layer', 'display:bogus',
                                  'display:inline block',
                                  'display:none!important;display:inline'])
def test_hidden_defaults_and_valid_cascade_keep_nonrendered_text_out(style):
    assert text(f'A<span hidden style="{style}">secret</span>B') == 'AB'


def test_display_cascade_discards_invalid_rules_before_selecting_override():
    assert text('<span hidden style="display:inline;display:bogus!important">visible</span>') == 'visible'
    assert text('<span hidden style="display:none;DISPLAY:/**/INLINE ! important">visible</span>') == 'visible'


def test_descendant_display_cannot_escape_a_hidden_parent():
    assert text('A<span hidden><b style="display:inline">secret</b></span>B') == 'AB'


def test_until_found_uses_content_visibility_rather_than_display_hiding():
    assert text('A<div hidden="until-found" style="display:block">secret</div>B') == 'AB'


def test_display_override_can_reveal_a_hidden_closed_dialog():
    assert text('<dialog hidden style="display:block">visible</dialog>') == 'visible'
