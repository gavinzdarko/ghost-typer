import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(s.text for s in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('display', ['inline', 'inline-block', 'inline-flex', 'inline-grid',
                                   'inline-table', 'contents', 'initial', 'unset', 'inline flow'])
def test_inline_paragraphs_do_not_insert_enter_keys(display):
    assert text(f'<p style="display:{display}">A</p><p style="display:{display}">B</p>') == 'AB'


def test_inline_headings_and_pre_keep_content_without_outer_breaks():
    assert text('Before<h2 style="display:inline">Title</h2>After') == 'BeforeTitleAfter'
    assert text('Before<pre style="display:inline">a  b\nc</pre>After') == 'Beforea  b\ncAfter'


def test_inline_override_keeps_descendants_block_boundaries():
    assert text('Before<div style="display:contents"><p>Inside</p></div>After') == 'Before\nInside\n\nAfter'


def test_display_precedence_and_inheritance_preserve_the_selected_layout():
    assert text('A<p style="display:inline!important;display:block">B</p>C') == 'ABC'
    assert text('A<p style="display:inline;display:block">B</p>C') == 'A\nB\n\nC'
    assert text('<span><p style="display:inherit">A</p>B</span>') == 'AB'
    assert text('<div style="display:inline"><p style="display:inherit">A</p>B</div>') == 'AB'
    assert text('<div><p style="display:inherit">A</p>B</div>') == 'A\n\nB'
    assert text('<span style="display:revert"><p style="display:inherit">A</p>B</span>') == 'AB'


@pytest.mark.parametrize('display', ['revert', 'revert-layer', 'block'])
def test_block_defaults_remain_for_block_display_and_reverts(display):
    assert text(f'Before<p style="display:{display}">Middle</p>After') == 'Before\nMiddle\n\nAfter'
