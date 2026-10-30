import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('display', ['inline', 'contents', 'inline-block', 'initial', 'unset'])
def test_specialized_nodes_without_block_boxes_do_not_invent_separators(display):
    table = (f'before<table style="display:{display}"><tr style="display:{display}">'
             f'<td style="display:{display}">one</td><th style="display:{display}">two</th>'
             '</tr></table>after')
    definitions = (f'before<dl style="display:{display}"><dt style="display:{display}">one</dt>'
                   f'<dd style="display:{display}">two</dd></dl>after')
    assert text(table) == 'beforeonetwoafter'
    assert text(definitions) == 'beforeonetwoafter'


def test_contents_containers_keep_descendant_table_and_definition_boundaries():
    assert text('before<table style="display:contents"><tr><td>one</td><td>two</td></tr></table>after') == 'before\none two\nafter'
    assert text('before<dl style="display:contents"><dt>one</dt><dd>two</dd></dl>after') == 'before\none\ntwo\nafter'


def test_specialized_display_uses_priority_inheritance_and_valid_declarations():
    assert text('<span>before<dl style="display:inherit"><dt style="display:inherit">one</dt>'
                '<dd style="display:inline!important;display:block">two</dd></dl>after</span>') == 'beforeonetwoafter'
    assert text('before<table style="display:contents"><tr style="display:inherit">'
                '<td style="display:inherit">one</td><td style="display:inline;display:bogus!important">two</td>'
                '</tr></table>after') == 'beforeonetwoafter'


def test_default_table_and_definition_layout_is_preserved():
    assert text('before<table><tr><td>one</td><th>two</th></tr></table>after') == 'before\none two\nafter'
    assert text('before<dl><dt>one</dt><dd>two</dd></dl>after') == 'before\none\ntwo\nafter'
