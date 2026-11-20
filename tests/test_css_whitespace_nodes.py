"""Inline element boundaries must not destroy CSS-preserved source whitespace."""
import html

import pytest

from src.text_parser import TextParser


def rendered(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('mode', ['pre', 'pre-wrap', 'break-spaces', 'preserve wrap'])
@pytest.mark.parametrize('whitespace', ['\t', '   ', '\n\n', ' \t\n  \n\t '])
def test_preserved_whitespace_only_descendants_keep_exact_source(mode, whitespace):
    assert rendered(f'<div style="white-space:{mode}">A<span>{whitespace}</span>B</div>') == f'A{whitespace}B'


@pytest.mark.parametrize('mode', ['normal', 'nowrap', 'initial', 'collapse wrap'])
def test_normal_whitespace_only_descendants_still_collapse(mode):
    assert rendered(f'<div style="white-space:{mode}">A<span> \t\n\n </span>B</div>') == 'A B'


def test_css_whitespace_preservation_inherits_through_nested_inline_tags():
    assert rendered('<span style="white-space:pre-wrap">A<i><b>\t\n\n   </b></i>B</span>') == 'A\t\n\n   B'


def test_normal_override_collapses_only_its_own_descendants():
    source = '<div style="white-space:pre-wrap">A<i>\t</i><span style="white-space:normal">B<b> \t\n </b>C</span><i>  </i>D</div>'
    assert rendered(source) == 'A\tB C  D'


def test_pre_line_keeps_blank_lines_and_collapses_spaces_across_inline_nodes():
    assert rendered('<div style="white-space:pre-line">A<span> \t\n\n  </span>B</div>') == 'A\n\nB'


def test_literal_pre_newline_rule_and_nested_whitespace_still_apply():
    assert rendered('<pre>\nA<span>\t\n\n </span>B</pre>') == 'A\t\n\n B'


def test_markup_indentation_remains_invisible_around_block_elements():
    assert rendered('\t\n<div>A</div>\n\n <div>B</div>\t\n') == 'A\n\nB'


@pytest.mark.parametrize('mode', ['normal', 'pre-wrap', 'pre-line', 'break-spaces'])
def test_inline_wrapping_does_not_change_css_whitespace_output(mode):
    source = 'A\t\n\n B  C\n\t😀 & <last>'
    bare = f'<div style="white-space:{mode}">{html.escape(source)}</div>'
    wrapped = f'<div style="white-space:{mode}">' + ''.join(
        '<span>' + html.escape(character) + '</span>' for character in source) + '</div>'
    assert rendered(wrapped) == rendered(bare)
