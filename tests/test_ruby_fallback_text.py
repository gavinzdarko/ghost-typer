import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


def test_ruby_fallback_parentheses_are_hidden_but_annotation_is_kept():
    assert text('<ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby>') == '漢かん'


@pytest.mark.parametrize('style', ['', 'display:bogus', 'display:revert', 'display:revert-layer'])
def test_default_hidden_rp_never_adds_text_or_separators(style):
    assert text(f'before<rp style="{style}"><div>SECRET</div></rp>after') == 'beforeafter'


@pytest.mark.parametrize('style', [
    'display:inline', 'display:contents', 'display:initial', 'display:unset',
    'display:inherit', 'display:none;display:inline',
    'display:inline!important;display:none',
])
def test_rp_inline_css_can_restore_visible_fallback_text(style):
    assert text(f'<span>before<rp style="{style}">(shown)</rp>after</span>') == 'before(shown)after'


def test_rp_explicit_block_override_has_normal_boundaries():
    assert text('before<rp style="display:block">shown</rp>after') == 'before\nshown\n\nafter'


def test_rp_display_none_beats_visible_descendants():
    assert text('<rp style="display:none"><b style="display:inline">hidden</b></rp>shown') == 'shown'


def test_rp_hidden_inside_pre_does_not_remove_visible_whitespace():
    assert text('<pre>  before<rp>(hidden)</rp>after\n  end</pre>') == '  beforeafter\n  end'
